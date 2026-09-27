import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDummyAssignments


@pytest.mark.parametrize("source,expected", [
    ("x = 1\nx = x", "x = 1"),
    ("import os\nos = os", "import os"),
    ("def f():\n    y = 1\n    y = y\n    return y", "def f():\n    y = 1\n    return y"),
    ("def f(a):\n    a = a", "def f(a):\n    0"),
    # bound nowhere else: a module global made of a builtin, or an `UnboundLocalError`
    ("print = print", "print = print"),
    ("def f():\n    y = y", "def f():\n    y = y"),
    # a class attribute
    ("class A:\n    print = print", "class A:\n    print = print"),
    ("x = 1\nclass A:\n    x = x", "x = 1\nclass A:\n    x = x"),
    # not the same binding
    ("x = 1\ndef f():\n    global y\n    y = x", "x = 1\ndef f():\n    global y\n    y = x"),
    ("x = y = 1\nx = y", "x = y = 1\nx = y"),
])
def test_remove_dummy_assignments(source, expected):
    assert_code(apply_transform(source, RemoveDummyAssignments, only("remove_dummy_assignments")), expected)
