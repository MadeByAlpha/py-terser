"""
Print a representation of an AST

This prints a human readable representation of the nodes in the AST.
The goal is to make it easy to see what the AST looks like, and to
make it easy to compare two ASTs.

This is not intended to be a complete representation of the AST, some
fields or field names may be omitted for clarity. It should still be precise and unambiguous.

"""

from __future__ import annotations
from typing import TYPE_CHECKING

from . import ast

if TYPE_CHECKING:
    from typing import TypeIs


INDENT = '    '

# The field name that can be omitted for each node
# Either it's the only field or would otherwise be obvious
default_fields = {
    'Constant': 'value',
    'Num': 'n',
    'Str': 's',
    'Bytes': 's',
    'NameConstant': 'value',
    'FormattedValue': 'value',
    'JoinedStr': 'values',
    'List': 'elts',
    'Tuple': 'elts',
    'Set': 'elts',
    'Name': 'id',
    'Expr': 'value',
    'UnaryOp': 'op',
    'BinOp': 'op',
    'BoolOp': 'op',
    'Call': 'func',
    'Index': 'value',
    'ExtSlice': 'dims',
    'Assert': 'test',
    'Delete': 'targets',
    'Import': 'names',
    'If': 'test',
    'While': 'test',
    'Try': 'handlers',
    'TryExcept': 'handlers',
    'With': 'items',
    'withitem': 'context_expr',
    'FunctionDef': 'name',
    'arg': 'arg',
    'Return': 'value',
    'Yield': 'value',
    'YieldFrom': 'value',
    'Global': 'names',
    'Nonlocal': 'names',
    'ClassDef': 'name',
    'AsyncFunctionDef': 'name',
    'Await': 'value',
    'AsyncWith': 'items',
    'Raise': 'exc',
    'Subscript': 'value',
    'Attribute': 'value',
    'AugAssign': 'op',
}


def is_constant_node[T: ast.AST](node: ast.AST, types: type[T] | tuple[type[T], ...]) -> TypeIs[T]:
    """
    Is a node one of the specified node types

    A node type may be an actual ast class or a tuple of many.

    If types includes a specific Constant type (Str, Bytes, Num etc),
    returns true for Constant nodes of the correct type.

    :type node: ast.AST
    :param types:
    :rtype: bool

    """

    if not isinstance(types, tuple):
        types: tuple[type[T]] = (types,)

    for node_type in types:
        assert not isinstance(node_type, str)

    if isinstance(node, types):
        return True

    if isinstance(node, ast.Constant):
        if type(node.value) in [type(None), type(True), type(False)]:
            return ast.NameConstant in types
        elif isinstance(node.value, (int, float, complex)):
            return ast.Num in types
        elif isinstance(node.value, str):
            return ast.Str in types
        elif isinstance(node.value, bytes):
            return ast.Bytes in types
        elif node.value == Ellipsis:
            return ast.Ellipsis in types
        else:
            raise RuntimeError('Unknown Constant value %r' % type(node.value))

    return False


def is_literal(node, field):
    if hasattr(ast, 'Constant') and isinstance(node, ast.Constant) and field == 'value':
        return True

    if is_constant_node(node, ast.Num) and field == 'n':
        return True

    if is_constant_node(node, ast.Str) and field == 's':
        return True

    if is_constant_node(node, ast.Bytes) and field == 's':
        return True

    if is_constant_node(node, ast.NameConstant) and field == 'value':
        return True

    return False


def print_ast(node):
    if not isinstance(node, ast.AST):
        return repr(node)

    s = ''

    node_name = node.__class__.__name__
    s += node_name
    s += '('

    first = True
    for field, value in ast.iter_fields(node):
        if not value and not is_literal(node, field):
            # Don't bother printing fields that are empty, except for literals
            continue

        if field == 'ctx':
            # Don't print the ctx, it's always apparent from context
            continue

        if first:
            first = False
        else:
            s += ', '

        if default_fields.get(node_name) != field:
            s += field + '='

        if isinstance(value, ast.AST):
            s += print_ast(value)
        elif isinstance(value, list):
            s += '['
            first_list = True
            for item in value:
                if first_list:
                    first_list = False
                else:
                    s += ','

                for line in print_ast(item).splitlines():
                    s += '\n' + INDENT + line
            s += '\n]'
        else:
            s += repr(value)

    s += ')'
    return s
