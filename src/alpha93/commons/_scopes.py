from __future__ import annotations

if __debug__ and __import__("typing").TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from .types import Coroutine

constant = lambda _: _()

def dynamics(source, /):
    locals_ = {}
    exec(source, None, locals_)
    return locals_

@constant
def enumerate():
    import builtins

    __aenum = dynamics("async def _(a,b):\n\tasync for a in a:\n\t\tyield b,a\n\t\tb+=1")["_"]

    def __func(iterable, /, start = 0):
        if hasattr(iterable, "__aiter__"):
            return __aenum(iterable, start)
        return builtins.enumerate(iterable, start)
    return __func

def throw(cls, /, *args, caused_by = None, **kwargs):
    try:
        if caused_by: raise cls(*args) from caused_by
        raise cls(*args)
    except cls as exc:
        for k, v in kwargs.items(): setattr(exc, k, v)
        return exc

def catch(*types: type, coro: bool | None = None):
    if coro is None or coro:
        def acall[**P](fn: Coroutine[P, Any], /):
            async def __func(*args: P.args, **kwargs: P.kwargs):
                try: return await fn(*args, **kwargs), None
                except types as e: return None, e
            return __func
    if coro is None or not coro:
        def call[**P](fn: Callable[P, Any], /):
            def __func(*args: P.args, **kwargs: P.kwargs):
                try: return fn(*args, **kwargs), None
                except types as e: return None, e
            return __func

    if coro is not None:
        # noinspection PyUnboundLocalVariable
        return acall if coro else call

    import inspect

    def __determine[**P](fn: Callable[P, Any] | Coroutine[P, Any], /):
        return acall(fn) \
            if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn) or inspect.isawaitable(fn) \
            else call(fn)
    return __determine
