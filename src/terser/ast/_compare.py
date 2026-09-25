from __future__ import annotations

from typing import TYPE_CHECKING

from . import ast

if TYPE_CHECKING:
    from typing import Any


class CompareError(RuntimeError):
    """
    Raised when an AST compares unequal.
    """

    def __init__(self, lnode, rnode, msg=None):
        self.lnode = lnode
        self.rnode = rnode
        self.msg = msg

    def __repr__(self):
        return 'NodeError(%r, %r)' % (self.lnode, self.rnode)

    def namespace(self, node):
        if hasattr(node, 'namespace'):
            if isinstance(node.specs, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                return self.namespace(node.specs) + '.' + node.specs.name
            elif isinstance(node.specs, ast.Module):
                return ''
            else:
                return repr(node.specs.__class__)

        return None

    def __str__(self):
        error = ''

        if self.msg:
            error += self.msg

        if namespace := self.namespace(self.lnode):
            error += ' in namespace ' + namespace

        if self.lnode and hasattr(self.lnode, 'lineno'):
            error += ' at source %i:%i' % (self.lnode.lineno, self.lnode.col_offset)

        return error


# noinspection string-conversion-without-dunder-method
def compare_ast(l_ast: Any, r_ast: Any, /):
    """
    Compare Python Abstract Syntax Trees

    >>> compare_ast(l_ast, r_ast)

    If the AST's are not identical, an exception will be raised.

    """

    if not isinstance(r_ast, type(l_ast)):
        raise CompareError(l_ast, r_ast, msg='Nodes do not match! %r != %r' % (l_ast, r_ast))
    assert isinstance(l_ast, ast.AST) and isinstance(r_ast, ast.AST)

    # noinspection shadowing-names
    def counter():
        i = 0
        while True:
            yield i
            i += 1

    for field in sorted(set(l_ast._fields + r_ast._fields)):

        if field == 'kind' and isinstance(l_ast, ast.Constant):
            continue

        if field == 'str' and hasattr(ast, 'Interpolation') and isinstance(l_ast, ast.Interpolation):
            continue

        l_field = getattr(l_ast, field, None)
        r_field = getattr(r_ast, field, None)

        if not isinstance(l_field, list):
            if isinstance(l_field, ast.AST) or isinstance(r_field, ast.AST):
                compare_ast(l_field, r_field)
            elif l_field != r_field:
                raise CompareError(
                    l_ast,
                    r_ast,
                    f"Fields do not match: {type(l_ast)}.{field}={l_field}, {type(r_ast)}.{field}={r_field}"
                )

            continue

        assert isinstance(r_field, list)

        if len(l_field) != len(r_field):
            raise CompareError(
                l_field,
                r_field,
                "List does not have the same number of elements:"
                f" len({type(l_ast)}.{field})={len(l_field)},"
                f" len({type(r_ast)}.{field})={len(r_field)}"
            )

        for i, left, right in zip(counter(), l_field, r_field):
            if isinstance(left, ast.AST) or isinstance(right, ast.AST):
                compare_ast(left, right)
            elif left != right:
                raise CompareError(
                    l_ast,
                    r_ast,
                    f"Fields do not match: {type(l_ast)}.{field}[{i}]={left}, {type(r_ast)}.{field}[{i}]={right}"
                )
