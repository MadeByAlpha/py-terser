# ruff: noqa: F405

import ast as __ast
import builtins as __builtins
import typing as __typing
from ast import *   # noqa: F403
from sys import version_info as __python


# We only support Python 3.10 and above
assert __python >= (3, 10)


# noinspection protected-member
class Constant(__ast.Constant):
    n: __ast._ConstantValue
    s: __ast._ConstantValue

    def __init__(
        self,
        value: __ast._ConstantValue,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes]
    ) -> None: ...

# noinspection protected-member
class Str(Constant):
    s: str

    # noinspection init-new-signature,bad-argument-type
    def __init__(
        self,
        s: str,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes],
    ) -> None: ...

# noinspection protected-member
class Bytes(Constant):
    s: bytes

    # noinspection init-new-signature,bad-argument-type
    def __init__(
        self,
        s: str,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes],
    ) -> None: ...

# noinspection protected-member
class Num(Constant):
    n: int | float | complex

    # noinspection init-new-signature,bad-argument-type
    def __init__(
        self,
        n: int | float | complex,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes],
    ) -> None: ...

# noinspection protected-member
class NameConstant(Constant):
    # noinspection bad-argument-type
    def __init__(
        self,
        value: __ast._ConstantValue,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes]
    ) -> None: ...

# noinspection protected-member
class Ellipsis(Constant):
    # noinspection bad-argument-type
    def __init__(
        self,
        value: __ast._ConstantValue,
        kind: str | None = None,
        **kwargs: __typing.Unpack[__ast._Attributes]
    ) -> None: ...

if __python < (3, 11):
    # noinspection protected-member
    class TryStar(stmt):
        __match_args__ = ("body", "handlers", "orelse", "finalbody")
        body: list[stmt]
        handlers: list[ExceptHandler]
        orelse: list[stmt]
        finalbody: list[stmt]

        def __init__(
            self,
            body: list[stmt] = ...,
            handlers: list[ExceptHandler] = ...,
            orelse: list[stmt] = ...,
            finalbody: list[stmt] = ...,
            **kwargs: __typing.Unpack[__ast._Attributes],
        ) -> None: ...

        def __replace__(
            self,
            *,
            body: list[stmt] = ...,
            handlers: list[ExceptHandler] = ...,
            orelse: list[stmt] = ...,
            finalbody: list[stmt] = ...,
            **kwargs: __typing.Unpack[__ast._Attributes],
        ) -> __typing.Self: ...

if __python < (3, 12):
    # noinspection pep8-naming
    class type_param(__ast.AST):
        lineno: int
        col_offset: int
        end_lineno: int
        end_col_offset: int

        def __init__(self, **kwargs: __typing.Unpack[__ast.Attributes[int]]) -> None: ...

        def __replace__(self, **kwargs: __typing.Unpack[__ast.Attributes[int]]) -> __typing.Self: ...

    class TypeVar(type_param):
        __match_args__ = ("name", "bound", "default_value")
        name: str
        bound: expr | None
        default_value: expr | None

        def __init__(
            self, name: str, bound: expr | None = None, default_value: expr | None = None, **kwargs: __typing.Unpack[__ast.Attributes[int]]
        ) -> None: ...

        def __replace__(
            self,
            *,
            name: str = ...,
            bound: expr | None = ...,
            default_value: expr | None = ...,
            **kwargs: __typing.Unpack[__ast.Attributes[int]],
        ) -> __typing.Self: ...

    class ParamSpec(type_param):
        __match_args__ = ("name", "default_value")
        name: str
        default_value: expr | None

        def __init__(self, name: str, default_value: expr | None = None, **kwargs: __typing.Unpack[__ast.Attributes[int]]) -> None: ...

        def __replace__(
            self, *, name: str = ..., default_value: expr | None = ..., **kwargs: __typing.Unpack[__ast.Attributes[int]]
        ) -> __typing.Self: ...

    class TypeVarTuple(type_param):
        __match_args__ = ("name", "default_value")
        name: str
        default_value: expr | None

        def __init__(self, name: str, default_value: expr | None = None, **kwargs: __typing.Unpack[__ast.Attributes[int]]) -> None: ...

        def __replace__(
            self, *, name: str = ..., default_value: expr | None = ..., **kwargs: __typing.Unpack[__ast.Attributes[int]]
        ) -> __typing.Self: ...

if __python < (3, 14):
    # noinspection protected-member
    class TemplateStr(expr):
        __match_args__ = ("values",)
        values: list[expr]

        def __init__(self,
            values: list[expr] = ...,
            **kwargs: __typing.Unpack[__ast._Attributes]
        ) -> None: ...

        def __replace__(
            self,
            *,
            values: list[expr] = ...,
            **kwargs: __typing.Unpack[__ast._Attributes]
        ) -> __typing.Self: ...

    # noinspection protected-member
    class Interpolation(expr):
        __match_args__ = ("value", "str", "conversion", "format_spec")
        value: expr
        str: __builtins.str
        conversion: int
        format_spec: expr | None = None

        def __init__(
            self,
            value: expr = ...,
            str: __builtins.str = ...,
            conversion: int = ...,
            format_spec: expr | None = ...,
            **kwargs: __typing.Unpack[__ast._Attributes],
        ) -> None: ...

        def __replace__(
            self,
            *,
            value: expr = ...,
            str: __builtins.str = ...,
            conversion: int = ...,
            format_spec: expr | None = ...,
            **kwargs: __typing.Unpack[__ast._Attributes],
        ) -> __typing.Self: ...

class Exec(__ast.AST):
    pass
