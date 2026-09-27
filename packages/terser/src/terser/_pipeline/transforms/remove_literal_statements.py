from __future__ import annotations

from terser.ast import ast, is_constant_node
from terser.utils.hints import is_hinted
from ._suite import SuiteTransformer, TransformerFlag


class RemoveLiteralStatements(SuiteTransformer):
    """
    Remove literal expressions from the code

    Docstrings are left to `RemoveDocstrings`, which knows the `@terser_hints.preserve_docstring`
    hint and when a docstring may be read. Under that hint, a class keeps its attribute docstrings
    too (a string right after an assignment in its body), which e.g. pydantic reads back from the
    source with `use_attribute_docstrings`.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

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

    def _is_attribute_docstring(self, node_list, index, parent):
        return (
            isinstance(parent, ast.ClassDef) and index > 0
            and isinstance(node_list[index - 1], (ast.Assign, ast.AnnAssign))
            and isinstance(node_list[index], ast.Expr) and is_constant_node(node_list[index].value, ast.Str)
            and is_hinted(parent.decorator_list, "preserve_docstring", self._config)
        )

    def suite(self, node_list, parent):
        without_literals = [
            self.visit(n) for i, n in enumerate(node_list)
            if self._is_docstring_position(node_list, i, parent) or not self.is_literal_statement(n)
            or self._is_attribute_docstring(node_list, i, parent)
        ]

        if len(without_literals) == 0:
            if isinstance(parent, ast.Module):
                return []
            else:
                return [self.add_child(ast.Expr(value=ast.Num(0)), parent=parent)]

        return without_literals
