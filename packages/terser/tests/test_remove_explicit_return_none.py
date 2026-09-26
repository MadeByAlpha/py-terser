import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveExplicitReturnNone


@pytest.mark.parametrize("source,expected", [
    ("def f():\n    a = 1\n    return None", "def f():\n    a = 1"),
    ("def f(a):\n    if a:\n        return None\n    return a", "def f(a):\n    if a:\n        return\n    return a"),
    ("def f(a):\n    return a", "def f(a):\n    return a"),
    ("async def f():\n    await g()\n    return None", "async def f():\n    await g()"),
])
def test_remove_explicit_return_none(source, expected):
    config = only("remove_explicit_return_none")
    assert_code(apply_transform(source, RemoveExplicitReturnNone, config), expected)
