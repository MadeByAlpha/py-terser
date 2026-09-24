import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemovePass


@pytest.mark.parametrize("source,expected", [
    ("pass", ""),
    ("def f():\n    pass", "def f():\n    0"),
    ("def f():\n    pass\n    return 1", "def f():\n    return 1"),
    ("class A:\n    pass", "class A:\n    0"),
    ("while x:\n    pass\nelse:\n    pass", "while x:\n    0\nelse:\n    0"),
    pytest.param(
        "try:\n    pass\nexcept E:\n    pass", "try:\n    0\nexcept E:\n    0",
        marks=pytest.mark.xfail(strict=True, reason="SuiteTransformer doesn't visit except handler bodies"),
    ),
])
def test_remove_pass(source, expected):
    assert_code(apply_transform(source, RemovePass, only("convert_pass")), expected)
