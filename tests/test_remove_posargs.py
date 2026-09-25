import pytest

from helpers import apply_transform, assert_code, minify_src, only
from terser._pipeline.transforms import ConvertPosargs


@pytest.mark.parametrize("source,expected", [
    ("def f(a, /, b): pass", "def f(a, b): pass"),
    ("def f(a, b=1, /, c=2, *, d): pass", "def f(a, b=1, c=2, *, d): pass"),
    ("async def f(a, /): pass", "async def f(a): pass"),
    ("f = lambda a, /: a", "f = lambda a: a"),
    ("class A:\n    def m(self, a, /): pass", "class A:\n    def m(self, a): pass"),
    ("def f(a, /, *args): pass", "def f(a, *args): pass"),
    # f(1, a=2) passes `a` in `kw`, which would clash with a normal argument
    ("def f(a, /, **kw): pass", "def f(a, /, **kw): pass"),
    ("def f(a, b): pass", "def f(a, b): pass"),
])
def test_convert_posargs(source, expected):
    assert_code(apply_transform(source, ConvertPosargs, only("convert_posargs")), expected)


def test_converted_after_renaming():
    # positional-only arguments are renamed first (callers can't use their names), then converted
    source = "def f(long_argument_name, /):\n    return long_argument_name * 2\nprint(f(21))\n"
    assert minify_src(source, only("convert_posargs"), rename_locals=True) == "def f(A):return A*2\nprint(f(21))"


def test_disabled():
    source = "def f(long_argument_name, /):\n    return long_argument_name * 2\n"
    assert "/" in minify_src(source, only(), rename_locals=True)
