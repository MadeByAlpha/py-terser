from __future__ import annotations

from terser.ast import ast, is_constant_node
from ._suite import SuiteTransformer


class RemoveLiteralStatements(SuiteTransformer):
    """
    Remove literal expressions from the code

    Docstrings are left to `RemoveDocstrings`, which knows the `@terser_hints.preserve_docstring`
    hint and when a docstring may be read.
    """
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.remove_literal_statements

    def is_literal_statement(self, node):
        if not isinstance(node, ast.Expr):
            return False

        return is_constant_node(node.value, (ast.Num, ast.Str, ast.NameConstant, ast.Bytes))

    def _is_docstring_position(self, node_list, index, parent):
        # leave docstrings alone here - RemoveDocstrings decides whether to remove them
        if index != 0 or not isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return False

        node = node_list[0]
        return isinstance(node, ast.Expr) and is_constant_node(node.value, ast.Str)

    def suite(self, node_list, parent):
        without_literals = [
            self.visit(n) for i, n in enumerate(node_list)
            if self._is_docstring_position(node_list, i, parent) or not self.is_literal_statement(n)
        ]

        if len(without_literals) == 0:
            if isinstance(parent, ast.Module):
                return []
            else:
                return [self.add_child(ast.Expr(value=ast.Num(0)), parent=parent)]

        return without_literals
