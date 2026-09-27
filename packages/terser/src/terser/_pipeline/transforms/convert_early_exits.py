from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from ._suite import SuiteTransformer


class ConvertEarlyExits(SuiteTransformer):
    """
    Merge `if cond: return a` immediately followed by `return b` into
    `return a if cond else b`
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_early_exits

    @override
    def suite(self, node_list, parent):
        result = []
        i = 0
        while i < len(node_list):
            node = node_list[i]
            next_node = node_list[i + 1] if i + 1 < len(node_list) else None

            if (
                isinstance(node, ast.If) and not node.orelse
                and len(node.body) == 1 and isinstance(node.body[0], ast.Return)
                and isinstance(next_node, ast.Return)
            ):
                a = node.body[0].value or ast.Constant(value=None)
                b = next_node.value or ast.Constant(value=None)
                merged = ast.Return(value=ast.IfExp(test=node.test, body=a, orelse=b))
                result.append(self.add_child(merged, parent=parent))
                i += 2
                continue

            result.append(self.visit(node))
            i += 1

        return result
