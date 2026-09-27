from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ..resolver.binding import ImportBinding
from ._suite import SuiteTransformer, TransformerFlag


class CleanupLocalImports(SuiteTransformer):
    """
    Remove unused local (function/class-scope) imports, and unused
    module-level imports too if `config.respect_all` (and not exported)
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    _module: ast.Module

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.cleanup_local_imports

    @override
    def visit_Module(self, node: ast.Module):
        self._module = node
        node.body = self.suite(node.body, parent=node)
        return node

    def _clean_alias_list(self, stmt, in_module_scope: bool):
        kept = []
        for alias in stmt.names:
            if alias.name == '*':
                return stmt.names  # wildcard imports are left alone entirely

            binding = ref(alias).binding
            if not isinstance(binding, ImportBinding):
                kept.append(alias)
                continue

            if in_module_scope and (not self._config.respect_all or binding.exported):
                kept.append(alias)
                continue

            if len(binding.references) > 1:
                kept.append(alias)

        return kept

    @override
    def suite(self, node_list, parent):
        result = []
        for stmt in node_list:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                kept = self._clean_alias_list(stmt, in_module_scope=ref(stmt).namespace is self._module)
                if not kept:
                    continue
                stmt.names = kept

            result.append(self.visit(stmt))

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
