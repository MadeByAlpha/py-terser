from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer, TransformerFlag


class RemoveDeadBlocks(SuiteTransformer):
    """
    Collapse `if` statements whose test is a literal constant bool:
    `if True: body` -> `body`, `if False: body` (else: `orelse`) -> `orelse`

    Registered directly after `FoldConstants` (same FLAGS stage), which is
    what folds comparisons/`__debug__`/`typing.TYPE_CHECKING` down to a literal
    bool test in the first place.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_debug or config.fold_constants

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool):
                branch = node.body if node.test.value else node.orelse
                for stmt in branch:
                    ref(stmt).parent = parent
                result.extend(self.suite(branch, parent))
                continue

            result.append(self.visit(node))

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
