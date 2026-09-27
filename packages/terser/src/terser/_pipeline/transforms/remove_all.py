from fnmatch import fnmatch
from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer, TransformerFlag


def _is_dunder_all_assign(node) -> bool:
    return (
        isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == '__all__'
    )


def _removal_allowed(module_path: str, config: TransformConfig) -> bool:
    if config.remove_dunder_all:
        return True

    return any(fnmatch(module_path, pattern) for pattern in config.remove_dunder_all_modules)


class RemoveAll(SuiteTransformer):
    """
    Remove the top-level `__all__` assignment, for modules allowed by `config.remove_dunder_all`
    / `config.remove_dunder_all_modules`
    """
    FLAGS = TransformerFlag.INFLUENCES_MANGLING

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_dunder_all or bool(config.remove_dunder_all_modules)

    @override
    def visit_Module(self, node: ast.Module):
        if not _removal_allowed(str(ref(node).spec), self._config):
            return node

        assigns = [stmt for stmt in node.body if _is_dunder_all_assign(stmt)]
        if not assigns:
            return node

        # Removing the assignment would break other uses of __all__ (e.g.
        # `__all__.append(...)`), so keep it if referenced anywhere else.
        referenced_elsewhere = any(
            isinstance(name, ast.Name) and name.id == '__all__' and isinstance(name.ctx, ast.Load)
            for stmt in node.body if stmt not in assigns
            for name in ast.walk(stmt)
        )
        if referenced_elsewhere:
            return node

        node.body = [stmt for stmt in node.body if stmt not in assigns]
        return node
