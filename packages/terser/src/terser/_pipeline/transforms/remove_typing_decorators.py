from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag

_REMOVABLE_NAMES = ("typing.override", "typing_extensions.override", "typing.final", "typing_extensions.final")


def _unreference(decorator: ast.expr):
    # Drop the binding reference this decorator was holding (the root `Name` of a bare
    # `override` or a dotted `typing.override`), so unused-import cleanup can see it's
    # actually unused now that the decorator using it is gone.
    node = decorator
    while isinstance(node, ast.Attribute):
        node = node.value

    if isinstance(node, ast.Name):
        try:
            ref(node).binding.remove_reference(node)
        except AttributeError:
            pass


def _strip(decorator_list: list[ast.expr]) -> list[ast.expr]:
    kept = []
    for d in decorator_list:
        if qualified_name(d) in _REMOVABLE_NAMES:
            _unreference(d)
        else:
            kept.append(d)

    return kept


class RemoveTypingDecorators(SuiteTransformer):
    """
    Remove `@typing.override`/`@typing.final` decorators
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_typing_decorators

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node: ast.ClassDef = super().visit_ClassDef(node)
        node.decorator_list = _strip(node.decorator_list)
        return node

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node: ast.FunctionDef = super().visit_FunctionDef(node)
        node.decorator_list = _strip(node.decorator_list)
        return node
