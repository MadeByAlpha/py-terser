from typing import override

from terser.ast import ast, is_constant_node
from terser.config import RemoveDocstringOptions, TransformConfig
from terser.utils.hints import is_hinted
from ._suite import SuiteTransformer, TransformerFlag


class RemoveDocstrings(SuiteTransformer):
    """
    Remove docstrings, preserving module docstrings unless `also_modules` is
    set, and preserving anything decorated with `@terser_hints.preserve_docstring`
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    def __init__(self, ctx, /):
        super().__init__(ctx)
        self._options = RemoveDocstringOptions() if isinstance(self._config.remove_docstrings, bool) else self._config.remove_docstrings

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_docstrings is not False

    def _has_docstring(self, body) -> bool:
        return bool(body) and isinstance(body[0], ast.Expr) and is_constant_node(body[0].value, ast.Str)

    def _preserved(self, decorator_list) -> bool:
        return is_hinted(decorator_list, "preserve_docstring", self._config)

    def _strip_docstring(self, node):
        node.body = node.body[1:]
        if not node.body:
            node.body = [self.add_child(ast.Expr(ast.Num(0)), parent=node)]

    @override
    def visit_Module(self, node: ast.Module):
        node.body = self.suite(node.body, parent=node)

        if self._options.also_modules and self._has_docstring(node.body):
            node.body = node.body[1:]

        return node

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node: ast.ClassDef = super().visit_ClassDef(node)

        if self._has_docstring(node.body) and not self._preserved(node.decorator_list):
            self._strip_docstring(node)

        return node

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node: ast.FunctionDef = super().visit_FunctionDef(node)

        if self._has_docstring(node.body) and not self._preserved(node.decorator_list):
            self._strip_docstring(node)

        return node
