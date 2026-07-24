from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer


class ConvertToLambda(SuiteTransformer):
    """
    Convert a single-expression function to a lambda assignment:
    `def foo(...): return expr` -> `foo = lambda ...: expr`
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_to_lambda

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node: ast.FunctionDef = self.generic_visit(node)

        if isinstance(node, ast.AsyncFunctionDef) or node.decorator_list or len(node.body) != 1:
            return node

        stmt = node.body[0]
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            # a bare `Expr` body isn't equivalent as a lambda: it always
            # implicitly returns None, but a lambda returns the expression's value
            return node

        body = stmt.value
        new_node = ast.Assign(targets=[ast.Name(id=node.name, ctx=ast.Store())], value=ast.Lambda(args=node.args, body=body))
        return self.add_child(new_node, parent=ref(node).parent)
