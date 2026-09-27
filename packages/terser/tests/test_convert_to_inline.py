import pytest

from helpers import apply_transform, assert_code, minify_src, only
from terser import TransformConfig
from terser._pipeline.transforms import ConvertToInline


@pytest.mark.parametrize("source,expected", [
    ("if x:\n    f()", "x and f()"),
    ("if x:\n    a()\nelse:\n    b()", "a() if x else b()"),
    ("def g():\n    if x:\n        f()", "def g():\n    x and f()"),
    # only single expression statements
    ("if x:\n    a = 1", "if x:\n    a = 1"),
    ("if x:\n    a()\n    b()", "if x:\n    a()\n    b()"),
    ("if x:\n    a()\nelse:\n    b = 1", "if x:\n    a()\nelse:\n    b = 1"),
    ("if x:\n    a()\nelif y:\n    b()", "a() if x else y and b()"),
])
def test_convert_to_inline(source, expected):
    assert_code(apply_transform(source, ConvertToInline, only("convert_to_inline")), expected)


def test_dead_code_is_removed_first():
    # not `False and print(1)`, which nothing removes
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    print(1)\nprint(2)\n"
    assert_code(minify_src(source, TransformConfig()), "print(2)")
