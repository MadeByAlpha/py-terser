from __future__ import annotations

from terser.ast import ast, ref

from ._suite import SuiteTransformer
from ...config import TransformConfig


class CombineImports(SuiteTransformer):
    """
    Combine multiple import statements where possible

    This doesn't change the order of imports

    """
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.combine_imports

    def suite(self, node_list, parent):
        a = list(self._combine_import(node_list, parent))
        b = list(self._combine_import_from(a, parent))

        return [self.visit(n) for n in b]

    def _combine_import(self, node_list, parent):

        pending = []

        def flush():
            if len(pending) > 1:
                alias = [a for stmt in pending for a in stmt.names]
                yield self.add_child(ast.Import(names=alias), parent=parent, namespace=None)
            elif pending:
                # nothing to combine - yield the original statement unchanged, rather than
                # needlessly reconstructing (and re-binding) an identical Import node
                yield pending[0]

        for statement in node_list:
            if isinstance(statement, ast.Import):
                pending.append(statement)
            else:
                yield from flush()
                pending = []

                yield statement

        yield from flush()

    def _combine_import_from(self, node_list, parent):

        pending: list[ast.ImportFrom] = []

        def combine(statement):
            if not isinstance(statement, ast.ImportFrom):
                return False

            if len(statement.names) == 1 and statement.names[0].name == '*':
                return False

            if not pending:
                return True

            return statement.module == pending[0].module and statement.level == pending[0].level

        def flush():
            if len(pending) > 1:
                alias = [a for stmt in pending for a in stmt.names]
                yield self.add_child(
                    ast.ImportFrom(module=pending[0].module, names=alias, level=pending[0].level), parent=parent, namespace=ref(pending[0]).namespace
                )
            elif pending:
                # nothing to combine - yield the original statement unchanged, rather than
                # needlessly reconstructing (and re-binding) an identical ImportFrom node
                yield pending[0]

        for statement in node_list:
            if combine(statement):
                pending.append(statement)
            else:
                yield from flush()
                pending = []

                yield statement

        yield from flush()
