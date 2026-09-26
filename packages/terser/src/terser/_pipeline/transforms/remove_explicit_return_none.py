from __future__ import annotations

from terser.ast import ast, is_constant_node
from ._suite import SuiteTransformer


class RemoveExplicitReturnNone(SuiteTransformer):
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.remove_explicit_return_none

    def visit_Return(self, node):
        assert isinstance(node, ast.Return)

        # Transform `return None` -> `return`

        if is_constant_node(node.value, ast.NameConstant) and node.value.value is None:
            node.value = None

        return node

    def visit_FunctionDef(self, node):
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))

        node.body = [self.visit(a) for a in node.body]

        # Remove an explicit valueless `return` from the end of a function
        if len(node.body) > 0 and isinstance(node.body[-1], ast.Return) and node.body[-1].value is None:
            node.body.pop()

        # Replace empty suites with `0` expression statements
        if len(node.body) == 0:
            node.body = [self.add_child(ast.Expr(value=ast.Num(0)), parent=node)]

        return node
