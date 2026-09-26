from __future__ import annotations

from typing import override

from terser.ast import ast

from ._suite import SuiteTransformer, TransformerFlag


class ConvertPosargs(SuiteTransformer):
    """
    Convert positional-only arguments to normal arguments: `def f(a, /, b)` -> `def f(a, b)`

    Runs after mangling, which may rename positional-only arguments since callers can't pass them by
    keyword. Functions taking `**kwargs` are left alone: there, a keyword argument sharing a
    positional-only argument's name goes into `kwargs`, and would clash after the conversion.
    """
    FLAGS = TransformerFlag.INFLUENCES_MANGLING

    @override
    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.convert_posargs

    def visit_arguments(self, node: ast.arguments):
        node = self.generic_visit(node)

        if node.posonlyargs and node.kwarg is None:
            node.args = node.posonlyargs + node.args
            node.posonlyargs = []

        return node
