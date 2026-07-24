from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from ._suite import SuiteTransformer, TransformerFlag


def _is_dunder_all_assign(node) -> bool:
    return (
        isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == '__all__'
    )


class RemoveAll(SuiteTransformer):
    """
    Remove the top-level `__all__` assignment
    """
    FLAGS = TransformerFlag.INFLUENCES_MANGLING

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_dunder_all

    @override
    def visit_Module(self, node: ast.Module):
        node.body = [stmt for stmt in node.body if not _is_dunder_all_assign(stmt)]
        return node
