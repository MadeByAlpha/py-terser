from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag


def _is_bare_generic(base: ast.expr) -> bool:
    return isinstance(base, (ast.Name, ast.Attribute)) and qualified_name(base) == "typing.Generic"


class RemoveGenerics(SuiteTransformer):
    """
    Remove bare (non-parametrized) `Generic` base classes.

    `Generic[T]` is left alone - the subscript form has real runtime behavior
    (`__class_getitem__`) that a bare `Generic` base doesn't add.
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
        return node
