from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer


class ConvertToInline(SuiteTransformer):
    """
    Convert `if cond: func(x)` to `cond and func(x)`, and
    `if fizz: foo()` / `else: bar()` to `foo() if fizz else bar()`
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_to_inline

    @override
    def visit_If(self, node: ast.If):
        node: ast.If = self.generic_visit(node)

        if len(node.body) != 1 or not isinstance(node.body[0], ast.Expr):
            return node

        a = node.body[0].value

        if not node.orelse:
            new_node = ast.Expr(value=ast.BoolOp(op=ast.And(), values=[node.test, a]))
            return self.add_child(new_node, parent=ref(node).parent)

        if len(node.orelse) != 1 or not isinstance(node.orelse[0], ast.Expr):
            return node

        b = node.orelse[0].value
        new_node = ast.Expr(value=ast.IfExp(test=node.test, body=a, orelse=b))
        return self.add_child(new_node, parent=ref(node).parent)
