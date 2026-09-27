import pytest

from helpers import apply_transform, assert_code, minify_src, only, run_py
from terser import TransformConfig
from terser._pipeline.transforms import ConvertTypingConstructors


def convert(source):
    return apply_transform(source, ConvertTypingConstructors, only("convert_typing_constructors"))


@pytest.mark.parametrize("source,expected", [
    (
        "from typing import NamedTuple\nclass P(NamedTuple):\n    x: int\n    y: int = 0",
        "import collections\nfrom typing import NamedTuple\nP = collections.namedtuple('P', ('x', 'y'), defaults=(0,))",
    ),
    (
        "import collections\nfrom typing import NamedTuple\nclass P(NamedTuple):\n    x: int",
        "import collections\nfrom typing import NamedTuple\nP = collections.namedtuple('P', ('x',))",
    ),
    # methods, or anything but fields, are kept
    (
        "from typing import NamedTuple\nclass P(NamedTuple):\n    x: int\n    def f(self):\n        return self.x",
        "from typing import NamedTuple\nclass P(NamedTuple):\n    x: int\n    def f(self):\n        return self.x",
    ),
])
def test_named_tuple(source, expected):
    assert_code(convert(source), expected)


def test_typed_dict():
    source = "from typing import TypedDict\ndef f():\n    class D(TypedDict):\n        x: int\n    return D(x=1)"
    assert_code(convert(source), "from typing import TypedDict\ndef f():\n    return dict(x=1)")


@pytest.mark.parametrize("source", [
    # a call that isn't pure keywords
    "from typing import TypedDict\ndef f():\n    class D(TypedDict):\n        x: int\n    return D({'x': 1})",
    # used as anything but a call
    "from typing import TypedDict\ndef f():\n    class D(TypedDict):\n        x: int\n    return D",
    # another module may use it
    "from typing import TypedDict\nclass D(TypedDict):\n    x: int\nd = D(x=1)",
])
def test_typed_dict_kept(source):
    assert_code(convert(source), source)


def test_named_tuple_behaves_the_same():
    source = (
        "from typing import NamedTuple\n"
        "class P(NamedTuple):\n    x: int\n    y: int = 2\n"
        "p = P(1)\nprint(p, p.x + p.y, p._replace(y=3))\n"
    )
    expected = run_py("-c", source).stdout
    assert run_py("-c", minify_src(source, TransformConfig())).stdout == expected
