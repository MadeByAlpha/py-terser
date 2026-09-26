from collections.abc import Callable
from typing import Never

def preserve_docstring[T: type | Callable](obj: T, /) -> T:
    """
    Marker decorator: tells terser to keep this class/function's docstring
    even when docstring removal is otherwise enabled. Detected statically,
    a no-op at runtime.
    """

def preserve_annotations[T: type | Callable](obj: T, /) -> T:
    """
    Marker decorator: tells terser to keep this function/class's type annotations
    even when annotation removal is otherwise enabled. Detected statically,
    a no-op at runtime.
    """

def inline[T: Callable](obj: T, /) -> T:
    ...

def not_none[T](value: T | None, /) -> T:
    ...

def constant[T](func: Callable[[], T], /) -> T:
    """
    Marker decorator: tells terser this function is only ever called once, to
    compute a constant - immediately call it and rebind its name to the result,
    the same as the `@lambda _: _()` idiom. Detected statically; at runtime this
    just calls `fn` once and returns its result.
    """

def unreachable() -> Never:
    ...

__all__ = (
    "constant",
    "inline",
    "not_none",
    "preserve_annotations",
    "preserve_docstring",
    "unreachable",
)
