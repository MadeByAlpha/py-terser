from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer


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
        ref(body).parent = ref(node).parent
        return body
