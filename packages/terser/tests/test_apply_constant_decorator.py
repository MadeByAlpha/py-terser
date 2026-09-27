import pytest

from helpers import apply_transform, assert_code, minify_src, only, run_py
from terser import TransformConfig
from terser._pipeline.transforms import ApplyConstantDecorator


@pytest.mark.parametrize("source,expected", [
    ("@lambda _: _()\ndef x():\n    return 1", "def x():\n    return 1\nx = x()"),
    ("import terser_hints\n@terser_hints.constant\ndef x():\n    return 1", "import terser_hints\ndef x():\n    return 1\nx = x()"),
    ("from terser_hints import constant\n@constant\ndef x():\n    return 1", "from terser_hints import constant\ndef x():\n    return 1\nx = x()"),
    # only the outermost decorator applies last
    ("@lambda _: _()\n@d\ndef x():\n    return 1", "@d\ndef x():\n    return 1\nx = x()"),
    ("@d\n@lambda _: _()\ndef x():\n    return 1", "@d\n@lambda _: _()\ndef x():\n    return 1"),
    ("@lambda _: _(1)\ndef x(a):\n    return a", "@lambda _: _(1)\ndef x(a):\n    return a"),
])
def test_apply_constant_decorator(source, expected):
    assert_code(apply_transform(source, ApplyConstantDecorator, only("unfold_iife_lambdas")), expected)


def test_behaves_the_same():
    source = "@lambda _: _()\ndef table():\n    return {i: i * i for i in range(4)}\nprint(table[3])\n"
    assert run_py("-c", minify_src(source, TransformConfig())).stdout == "9\n"
