import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDebug


@pytest.mark.parametrize("source,expected", [
    ("if __debug__:\n    print(1)\nprint(2)", "print(2)"),
    ("if __debug__ is True:\n    print(1)\nprint(2)", "print(2)"),
    ("def f():\n    if __debug__:\n        print(1)\n    return 2", "def f():\n    return 2"),
    ("def f():\n    if __debug__:\n        print(1)", "def f():\n    0"),
    ("if not __debug__:\n    print(1)", "if not __debug__:\n    print(1)"),
])
def test_remove_debug(source, expected):
    assert_code(apply_transform(source, RemoveDebug, only("remove_debug")), expected)
