import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import ConvertTypingExtensions


@pytest.mark.parametrize("source,expected", [
    ("from typing_extensions import Protocol, TypedDict", "from typing import Protocol, TypedDict"),
    ("from typing_extensions import Protocol as P", "from typing import Protocol as P"),
    # only when every name is stable in `typing`
    ("from typing_extensions import Protocol, Foo", "from typing_extensions import Protocol, Foo"),
    ("import typing_extensions", "import typing_extensions"),
    ("from typing_extensions import *", "from typing_extensions import *"),
])
def test_convert_typing_extensions(source, expected):
    assert_code(apply_transform(source, ConvertTypingExtensions, only("convert_typing_extensions")), expected)
