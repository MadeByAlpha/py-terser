from __future__ import annotations

from terser.ast import ast, is_constant_node
from ._suite import SuiteTransformer


def _reads_doc(module: ast.Module) -> tuple[bool, bool]:
    """
    Whether `module` reads its own `__doc__`, and whether it reads any other docstring
    (`x.__doc__`, or `__doc__` inside a class).
    """

    name = other = False
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and node.id == '__doc__':
            name = True
        elif isinstance(node, ast.Attribute) and node.attr == '__doc__':
            other = True
        elif isinstance(node, ast.ClassDef) and any(
            isinstance(n, ast.Name) and n.id == '__doc__' for n in ast.walk(node)
        ):
            # inside a class body, `__doc__` is the class's own docstring
            other = True
    return name, other


class RemoveLiteralStatements(SuiteTransformer):
    """
    Remove literal expressions from the code

    This includes docstrings. This only looks at syntax (it runs before names are bound): the
    module docstring is kept when `__doc__` is read anywhere in the module, and nothing is removed
    when any `x.__doc__` is read, since that could be any function's or class's docstring.
    """
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.remove_literal_statements

    def visit_Module(self, node):
        reads_module_doc, reads_other_doc = _reads_doc(node)
        if reads_other_doc:
            return node

        if reads_module_doc and node.body and self.is_literal_statement(node.body[0]):
            node.body = [node.body[0], *self.suite(node.body[1:], parent=node)]
            return node

        node.body = self.suite(node.body, parent=node)
        return node

    def is_literal_statement(self, node):
        if not isinstance(node, ast.Expr):
            return False

        return is_constant_node(node.value, (ast.Num, ast.Str, ast.NameConstant, ast.Bytes))

    def suite(self, node_list, parent):
        without_literals = [self.visit(n) for n in node_list if not self.is_literal_statement(n)]

        if len(without_literals) == 0:
            if isinstance(parent, ast.Module):
                return []
            else:
                return [self.add_child(ast.Expr(value=ast.Num(0)), parent=parent)]

        return without_literals
