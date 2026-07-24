from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag

_REMOVABLE_NAMES = ("typing.override", "typing_extensions.override", "typing.final", "typing_extensions.final")


def _strip(decorator_list: list[ast.expr]) -> list[ast.expr]:
    return [d for d in decorator_list if qualified_name(d) not in _REMOVABLE_NAMES]


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
