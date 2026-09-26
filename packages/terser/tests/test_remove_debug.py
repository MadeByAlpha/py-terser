import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDebug


@pytest.mark.parametrize("source,expected", [
    ("if __debug__:\n    print(1)\nprint(2)", "print(2)"),
    ("if __debug__ is True:\n    print(1)\nprint(2)", "print(2)"),
    ("def f():\n    if __debug__:\n        print(1)\n    return 2", "def f():\n    return 2"),
    ("def f():\n    if __debug__:\n        print(1)", "def f():\n    0"),
    ("if not __debug__:\n    print(1)", "if not __debug__:\n    print(1)"),
    ("if __debug__:\n    a()\nelse:\n    b()\nc()", "b()\nc()"),
    ("if __debug__:\n    a()\nelif x:\n    b()\nelse:\n    c()", "if x:\n    b()\nelse:\n    c()"),
    ("def f():\n    if __debug__:\n        a()\n    else:\n        return 1", "def f():\n    return 1"),
    ("if __debug__:\n    a()\nelse:\n    if __debug__:\n        b()\n    else:\n        c()", "c()"),
])
def test_remove_debug(source, expected):
    assert_code(apply_transform(source, RemoveDebug, only("remove_debug")), expected)
