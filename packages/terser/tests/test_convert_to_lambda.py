import pytest

from helpers import apply_transform, assert_code, minify_src, only, run_py
from terser import TransformConfig
from terser._pipeline.transforms import ConvertToLambda


@pytest.mark.parametrize("source,expected", [
    ("def f(x):\n    return x + 1", "f = lambda x: x + 1"),
    ("def f(x=1, *a, k, **kw):\n    return x", "f = lambda x=1, *a, k, **kw: x"),
    ("class A:\n    def f(self):\n        return self", "class A:\n    f = lambda self: self"),
    # a lambda has no statements, decorators, annotations or `async`
    ("def f(x):\n    x", "def f(x):\n    x"),
    ("def f():\n    y = 1\n    return y", "def f():\n    y = 1\n    return y"),
    ("@d\ndef f(x):\n    return x", "@d\ndef f(x):\n    return x"),
    ("def f(x: int):\n    return x", "def f(x: int):\n    return x"),
    ("def f(x) -> int:\n    return x", "def f(x) -> int:\n    return x"),
    ("async def f():\n    return 1", "async def f():\n    return 1"),
    ("def f():\n    return", "def f():\n    return"),
])
def test_convert_to_lambda(source, expected):
    assert_code(apply_transform(source, ConvertToLambda, only("convert_to_lambda")), expected)


def test_parameters_are_mangled():
    source = "def f(*args, **kwargs):\n    return args, kwargs\nprint(f(1, a=2))\n"
    minified = minify_src(source, TransformConfig())
    assert "lambda" in minified
    assert "args" not in minified
    assert run_py("-c", minified).stdout == "((1,), {'a': 2})\n"


def test_keyword_parameters_are_kept():
    source = "def f(value):\n    return value * 2\nprint(f(value=2))\n"
    minified = minify_src(source, TransformConfig())
    assert run_py("-c", minified).stdout == "4\n"


def test_preserved_locals_keep_the_function():
    # `module::qualname` patterns match the function's `__qualname__`, which a lambda's isn't
    source = "def Field(**extra):\n    return extra\nprint(Field(a=1))\n"
    minified = minify_src(source, TransformConfig(), "sig.py", preserve_locals=["Field::**"])
    assert "def Field(**extra)" in minified
