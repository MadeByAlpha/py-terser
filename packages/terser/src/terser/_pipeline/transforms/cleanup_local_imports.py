from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ..resolver import forget
from ..resolver.binding import ImportBinding
from ._suite import SuiteTransformer, TransformerFlag


def _has_annotations(module: ast.Module) -> bool:
    """If `module` has annotations left, other than the `0` `RemoveAnnotations` leaves in a bare `x: int`"""

    for node in ast.walk(module):
        if isinstance(node, ast.AnnAssign):
            annotations = [node.annotation]
        elif isinstance(node, ast.arg):
            annotations = [node.annotation]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [node.returns]
        else:
            continue
        if any(a is not None and not (isinstance(a, ast.Constant) and a.value == 0) for a in annotations):
            return True
    return False


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
        self._annotated = _has_annotations(node)
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

    def _clean_future(self, stmt: ast.ImportFrom):
        """
        A `__future__` import changes how the module compiles, whether its name is read or not:
        `annotations` keeps the annotations left in the module unevaluated (code reading them at run
        time, like pydantic's, would otherwise evaluate names only imported under `TYPE_CHECKING`),
        `barry_as_FLUFL` changes the grammar, and the others are how Python 3 always behaves.
        """

        if not self._config.respect_all:
            return stmt.names
        return [
            alias for alias in stmt.names
            if alias.name == 'barry_as_FLUFL' or alias.name == 'annotations' and self._annotated
        ]

    @override
    def suite(self, node_list, parent):
        result = []
        for stmt in node_list:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if isinstance(stmt, ast.ImportFrom) and stmt.module == '__future__':
                    kept = self._clean_future(stmt)
                else:
                    kept = self._clean_alias_list(stmt, in_module_scope=ref(stmt).namespace is self._module)
                # or the bindings keep the aliases as references, which e.g. `ConvertToLambda` then
                # moves with them into a lambda the aliases are not in
                forget([alias for alias in stmt.names if not any(alias is k for k in kept)])
                if not kept:
                    continue
                stmt.names = kept

            result.append(self.visit(stmt))

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
