"""`RemoveOverloads`, `RemoveTypingDecorators`, `RemoveGenerics` and `RemoveTypingClasses`"""

import pytest

from helpers import apply_transform, assert_code, only
from terser import TransformConfig
from terser._pipeline.transforms import RemoveGenerics, RemoveOverloads, RemoveTypingClasses, RemoveTypingDecorators


@pytest.mark.parametrize("source,expected", [
    (
        "from typing import overload\n@overload\ndef f(x: int) -> int: ...\n@overload\ndef f(x: str) -> str: ...\ndef f(x):\n    return x",
        "from typing import overload\ndef f(x):\n    return x",
    ),
    (
        "import typing\nclass A:\n    @typing.overload\n    def f(self): ...\n    def f(self):\n        pass",
        "import typing\nclass A:\n    def f(self):\n        pass",
    ),
    ("def overload(f):\n    return f\n@overload\ndef f(): ...", "def overload(f):\n    return f\n@overload\ndef f(): ..."),
])
def test_remove_overloads(source, expected):
    assert_code(apply_transform(source, RemoveOverloads, only("remove_overloads")), expected)


def test_remove_overloads_with_typing_decorators():
    assert RemoveOverloads.is_enabled(only("remove_typing_decorators"))


@pytest.mark.parametrize("source,expected", [
    (
        "from typing import override, final\nclass A:\n    @override\n    def f(self): pass\n@final\nclass B: pass",
        "from typing import override, final\nclass A:\n    def f(self): pass\nclass B: pass",
    ),
    ("from typing_extensions import override as o\n@o\n@d\ndef f(): pass", "from typing_extensions import override as o\n@d\ndef f(): pass"),
    ("@override\ndef f(): pass", "@override\ndef f(): pass"),
])
def test_remove_typing_decorators(source, expected):
    assert_code(apply_transform(source, RemoveTypingDecorators, only("remove_typing_decorators")), expected)


@pytest.mark.parametrize("source,expected", [
    ("from typing import Generic\nclass A(Generic):\n    pass", "from typing import Generic\nclass A:\n    pass"),
    ("import typing\nclass A(B, typing.Generic):\n    pass", "import typing\nclass A(B):\n    pass"),
    # `Generic[T]` has `__class_getitem__`
    ("from typing import Generic\nclass A(Generic[T]):\n    pass", "from typing import Generic\nclass A(Generic[T]):\n    pass"),
    # unused type params of a class defined in a function
    ("def f():\n    class A[T]:\n        pass\n    return A", "def f():\n    class A:\n        pass\n    return A"),
    ("def f():\n    class A[T]:\n        x: T\n    return A", "def f():\n    class A[T]:\n        x: T\n    return A"),
    ("def f():\n    class A[T](list[T]):\n        pass\n    return A", "def f():\n    class A[T](list[T]):\n        pass\n    return A"),
    ("def f():\n    class A[T]:\n        pass\n    return A[int]", "def f():\n    class A[T]:\n        pass\n    return A[int]"),
    # another module may subscript it
    ("class A[T]:\n    pass", "class A[T]:\n    pass"),
])
def test_remove_generics(source, expected):
    assert_code(apply_transform(source, RemoveGenerics, only("remove_generics")), expected)


@pytest.mark.parametrize("source,expected", [
    ("from typing import Protocol\nclass A(Protocol):\n    pass", "from typing import Protocol\nclass A:\n    pass"),
    (
        "from typing import Protocol, runtime_checkable\n@runtime_checkable\nclass A(Protocol):\n    pass",
        "from typing import Protocol, runtime_checkable\n@runtime_checkable\nclass A(Protocol):\n    pass",
    ),
    ("from typing import Protocol\nclass A(Protocol[T]):\n    pass", "from typing import Protocol\nclass A(Protocol[T]):\n    pass"),
])
def test_remove_typing_classes(source, expected):
    assert_code(apply_transform(source, RemoveTypingClasses, only("remove_typing_classes")), expected)


def test_remove_typing_classes_off_by_default():
    assert not RemoveTypingClasses.is_enabled(TransformConfig())
