# ruff: noqa
# ty: ignore
"""
The is a backwards compatible shim for the ast module.

This is the best way to make the ast module work the same in both python 2 and 3.
This is essentially what the ast module was doing until 3.12, when it started throwing
deprecation warnings.
"""

# Ideally we don't import anything else
from ast import *


# noinspection unresolved-references,unused-local
if "TypeAlias" in globals():
    # Add n and s properties to Constant so it can stand in for Num, Str and Bytes
    Constant.n = property(lambda self: self.value, lambda self, value: setattr(self, 'value', value))
    Constant.s = property(lambda self: self.value, lambda self, value: setattr(self, 'value', value))


    # These classes are redefined from the ones in ast that complain about deprecation
    # They will continue to work once they are removed from ast

    class Str(Constant):
        # noinspection init-new-signature,bad-argument-type
        def __new__(cls, s, *args, **kwargs):
            return Constant(value=s, *args, **kwargs)


    class Bytes(Constant):
        # noinspection init-new-signature,bad-argument-type
        def __new__(cls, s, *args, **kwargs):
            return Constant(value=s, *args, **kwargs)


    class Num(Constant):
        # noinspection init-new-signature,bad-argument-type
        def __new__(cls, n, *args, **kwargs):
            return Constant(value=n, *args, **kwargs)


    class NameConstant(Constant):
        # noinspection bad-argument-type
        def __new__(cls, *args, **kwargs):
            return Constant(*args, **kwargs)


    # noinspection shadowing-builtins
    class Ellipsis(Constant):
        # noinspection bad-argument-type
        def __new__(cls, *args, **kwargs):
            return Constant(value=literal_eval('...'), *args, **kwargs)


# Create a dummy class for missing AST nodes
for _node_type in [
    'Exec',


    ### Python 3
    'AnnAssign',
    'AsyncFor',
    'AsyncFunctionDef',
    'AsyncWith',
    'Constant',
    'DictComp',
    'ListComp',
    'MatchAs',
    'MatchMapping',
    'MatchStar',
    'NamedExpr',
    'Nonlocal',
    'SetComp',
    'Starred',
    'YieldFrom',
    'arg',
    'withitem',


    ### Python 3.11
    'TryStar',


    ### Python 3.12
    'TypeVar',
    'ParamSpec',
    'TypeVarTuple',


    ### Python 3.14
    'TemplateStr',
    'Interpolation',
    # Deprecated
    'NameConstant',
    'Bytes',
]:
    if _node_type not in globals():
        globals()[_node_type] = type(_node_type, (AST,), {})
