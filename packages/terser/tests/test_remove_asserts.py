import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveAsserts


@pytest.mark.parametrize("source,expected", [
    ("assert x\nprint(1)", "print(1)"),
    ("def f(x):\n    assert x, 'message'\n    return x", "def f(x):\n    return x"),
    ("def f(x):\n    assert x", "def f(x):\n    0"),
])
def test_remove_asserts(source, expected):
    assert_code(apply_transform(source, RemoveAsserts, only("remove_asserts")), expected)
