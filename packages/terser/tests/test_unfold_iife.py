import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import UnfoldIIFE


@pytest.mark.parametrize("source,expected", [
    ("x = (lambda: 1)()", "x = 1"),
    ("x = (lambda: [i for i in y])()", "x = [i for i in y]"),
    ("x = (lambda: (lambda: 1)())()", "x = 1"),
    # arguments are left
    ("x = (lambda a: a)(1)", "x = (lambda a: a)(1)"),
    ("x = (lambda *a: a)()", "x = (lambda *a: a)()"),
    ("x = (lambda: 1)(*y)", "x = (lambda: 1)(*y)"),
    # a generator, or a binding of the lambda's own scope
    ("x = (lambda: (yield))()", "x = (lambda: (yield))()"),
    ("def f():\n    return (lambda: (y := 1))()", "def f():\n    return (lambda: (y := 1))()"),
    ("x = (lambda: lambda: (yield))()", "x = lambda: (yield)"),
    # a lambda doesn't see the names of the class body it's in
    ("class A:\n    x = 1\n    y = (lambda: x)()", "class A:\n    x = 1\n    y = (lambda: x)()"),
])
def test_unfold_iife(source, expected):
    assert_code(apply_transform(source, UnfoldIIFE, only("unfold_iife_lambdas")), expected)
