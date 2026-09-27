import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import ConvertEarlyExits


@pytest.mark.parametrize("source,expected", [
    ("def f(x):\n    if x:\n        return 1\n    return 2", "def f(x):\n    return 1 if x else 2"),
    ("def f(x):\n    if x:\n        return\n    return 2", "def f(x):\n    return None if x else 2"),
    ("def f(x):\n    a()\n    if x:\n        return 1\n    return 2", "def f(x):\n    a()\n    return 1 if x else 2"),
    # only when the `return` comes right after
    ("def f(x):\n    if x:\n        return 1\n    a()\n    return 2", "def f(x):\n    if x:\n        return 1\n    a()\n    return 2"),
    ("def f(x):\n    if x:\n        return 1\n    else:\n        a()\n    return 2", "def f(x):\n    if x:\n        return 1\n    else:\n        a()\n    return 2"),
    ("def f(x):\n    if x:\n        a()\n        return 1\n    return 2", "def f(x):\n    if x:\n        a()\n        return 1\n    return 2"),
])
def test_convert_early_exits(source, expected):
    assert_code(apply_transform(source, ConvertEarlyExits, only("convert_early_exits")), expected)
