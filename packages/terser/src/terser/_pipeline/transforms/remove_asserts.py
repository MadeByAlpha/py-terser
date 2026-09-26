from __future__ import annotations

import terser.ast.ast as ast

from terser._pipeline.transforms._suite import SuiteTransformer


class RemoveAsserts(SuiteTransformer):
    """
    Remove assert statements

    If a statement is syntactically necessary, use an empty expression instead
    """
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.optimize == 2 or config.remove_asserts

    def suite(self, node_list, parent):
        without_assert = [self.visit(a) for a in filter(lambda n: not isinstance(n, ast.Assert), node_list)]

        if len(without_assert) == 0:
            if isinstance(parent, ast.Module):
                return []
            else:
                return [self.add_child(ast.Expr(value=ast.Num(0)), parent=parent)]

        return without_assert
