import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveObject


@pytest.mark.parametrize("source,expected", [
    ("class A(object): pass", "class A: pass"),
    ("class A(object, B): pass", "class A(B): pass"),
    ("class A(B): pass", "class A(B): pass"),
    ("class A(object, metaclass=M): pass", "class A(metaclass=M): pass"),
])
def test_remove_object_base(source, expected):
    assert_code(apply_transform(source, RemoveObject, only("remove_explicit_base")), expected)
