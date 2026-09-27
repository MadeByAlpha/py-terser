from __future__ import annotations

from typing import TYPE_CHECKING, override

from terser.ast import ast
from terser.ast.ref import ref_or_none
from ..resolver import forget, removable
from ._suite import SuiteTransformer, TransformerFlag

if __debug__ and TYPE_CHECKING:
    from ...config import TransformConfig


def static_truth(node: ast.expr) -> tuple[bool | None, bool]:
    """
    What an expression is known to be before it runs.

    :return: Whether it's truthy (None if not known), and if evaluating it has no effect
    """

    if isinstance(node, ast.Constant):
        return bool(node.value), True

    if isinstance(node, ast.Name) and node.id == '__debug__':
        # can't be assigned, so reading it can't fail
        return None, True

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        truth, pure = static_truth(node.operand)
        return (None if truth is None else not truth), pure

    if isinstance(node, ast.BoolOp):
        # `and` is falsy once any operand is, `or` truthy once any operand is: what comes after
        # the first such operand never runs
        deciding = not isinstance(node.op, ast.And)
        pure, known = True, True
        for value in node.values:
            truth, value_pure = static_truth(value)
            pure = pure and value_pure
            if truth is deciding:
                return deciding, pure
            known = known and truth is not None
        return (not deciding if known else None), pure

    return None, False


class RemoveDeadCode(SuiteTransformer):
    """
    Remove the branches of `if` and `while` statements whose condition is known, and never
    true (or always true, for the `else` of an `if`).

    A branch is kept when removing it would change how its function compiles (see `removable`).
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_dead_code

    def __live(self, node: ast.stmt) -> list[ast.stmt] | None:
        """The statements to replace `node` with, when a part of it never runs"""

        if not isinstance(node, (ast.If, ast.While)):
            return None

        truth, pure = static_truth(node.test)
        if truth is None or not pure:
            return None

        if isinstance(node, ast.While):
            if truth:
                return None  # a loop left by `break`, if ever
            live, dead = node.orelse, node.body
        else:
            live, dead = (node.body, node.orelse) if truth else (node.orelse, node.body)

        if not removable(dead):
            return None

        forget([node.test, *dead])
        return live

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            node = self.visit(node)
            if (live := self.__live(node)) is None:
                result.append(node)
                continue

            # visited already, with the rest of `node`
            for statement in live:
                if (statement_ref := ref_or_none(statement)) is not None:
                    statement_ref.parent = parent
            result.extend(live)

        if not result and not isinstance(parent, ast.Module):
            return [self.add_child(ast.Expr(value=ast.Constant(value=0)), parent=parent)]
        return result
