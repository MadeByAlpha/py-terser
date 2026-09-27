from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag


def _is_bare_generic(base: ast.expr) -> bool:
    return isinstance(base, (ast.Name, ast.Attribute)) and qualified_name(base) == "typing.Generic"


def _is_subscripted_anywhere(binding) -> bool:
    return any(isinstance(r, ast.Name) and isinstance(ref(r).parent, ast.Subscript) for r in binding.references)


def _type_param_used(name: str, node: ast.ClassDef) -> bool:
    # Type params introduce a scope the bases, keywords and whole class body (annotations,
    # nested defs) can reference - dropping the declaration while it's still used elsewhere
    # would leave a dangling name. Only a genuinely dead type param (never referenced anywhere)
    # is safe to remove; err on the side of keeping it otherwise.
    roots = [*node.bases, *node.keywords, *node.body]
    return any(isinstance(n, ast.Name) and n.id == name for root in roots for n in ast.walk(root))


def _is_local(node: ast.ClassDef) -> bool:
    # A class reachable from outside its module (at module level, or an attribute of one) may be
    # subscripted there, which this per-module pass can't see - whether it's in `__all__` or not
    return isinstance(ref(node).namespace, (ast.FunctionDef, ast.AsyncFunctionDef))


class RemoveGenerics(SuiteTransformer):
    """
    Remove bare (non-parametrized) `Generic` base classes, and unused PEP 695
    `class Foo[T]:` type params.

    `Generic[T]` is left alone - the subscript form has real runtime behavior
    (`__class_getitem__`) that a bare `Generic` base doesn't add. Type params are only
    dropped for a class defined in a function and not subscripted anywhere -
    `Foo[int]` relies on `__class_getitem__`, which type params are what provide.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_generics

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node: ast.ClassDef = super().visit_ClassDef(node)
        node.bases = [b for b in node.bases if not _is_bare_generic(b)]

        if getattr(node, 'type_params', None):
            binding = ref(node).binding
            if (
                _is_local(node) and not _is_subscripted_anywhere(binding)
                and not any(_type_param_used(tp.name, node) for tp in node.type_params)
            ):
                node.type_params = []

        return node
