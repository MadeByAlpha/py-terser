from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag

_OVERLOAD_NAMES = ("typing.overload", "typing_extensions.overload")


def _is_overload(node) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False

    return any(qualified_name(d) in _OVERLOAD_NAMES for d in node.decorator_list)


class RemoveOverloads(SuiteTransformer):
    """
    Remove `@typing.overload`-decorated stub definitions - only the final,
    undecorated implementation remains
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_overloads or config.remove_typing_decorators

    @override
    def suite(self, node_list, parent):
        result = [self.visit(node) for node in node_list if not _is_overload(node)]

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
