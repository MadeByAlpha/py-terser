from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from ._suite import SuiteTransformer

_TypeAlias = getattr(ast, "TypeAlias", ())


class RemoveTypeStatements(SuiteTransformer):
    """
    Remove `type X = ...` alias statements
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_type_statements and bool(_TypeAlias)

    @override
    def suite(self, node_list, parent):
        result = [self.visit(node) for node in node_list if not isinstance(node, _TypeAlias)]

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
