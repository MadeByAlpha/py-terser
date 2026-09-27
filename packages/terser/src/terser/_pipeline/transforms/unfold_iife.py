from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer


def _evaluated_here(node: ast.AST):
    """The nodes of `node` evaluated in its own scope, not in a nested lambda's"""

    yield node
    if isinstance(node, ast.Lambda):
        return
    for child in ast.iter_child_nodes(node):
        yield from _evaluated_here(child)


class UnfoldIIFE(SuiteTransformer):
    """
    Inline immediately-invoked no-arg lambda calls: `(lambda: x)()` -> `x`
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.unfold_iife_lambdas

    @override
    def visit_Call(self, node: ast.Call):
        node: ast.Call = self.generic_visit(node)

        if node.args or node.keywords or not isinstance(node.func, ast.Lambda):
            return node

        args = node.func.args
        if args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg:
            return node

        body = node.func.body
        if isinstance(ref(node).namespace, ast.ClassDef):
            # a lambda doesn't see the names of the class body it's in, its body would
            return node
        if any(isinstance(child, (ast.Yield, ast.YieldFrom, ast.NamedExpr)) for child in _evaluated_here(body)):
            # a `yield` makes the lambda a generator, and `:=` binds in the lambda's own scope
            return node

        ref(body).parent = ref(node).parent
        return body
