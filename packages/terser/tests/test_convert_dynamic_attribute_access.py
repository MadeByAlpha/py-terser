import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import ConvertDynamicAttributeAccess


@pytest.mark.parametrize("source,expected", [
    ("a = getattr(o, 'name')", "a = o.name"),
    ("setattr(o, 'name', 1)", "o.name = 1"),
    ("a = getattr(f(), '__dunder__')", "a = f().__dunder__"),
    # a default, a name that's no identifier, or isn't known
    ("a = getattr(o, 'name', None)", "a = getattr(o, 'name', None)"),
    ("a = getattr(o, 'not valid')", "a = getattr(o, 'not valid')"),
    ("a = getattr(o, 'class')", "a = getattr(o, 'class')"),
    ("a = getattr(o, n)", "a = getattr(o, n)"),
    # `setattr()`'s value is used
    ("a = setattr(o, 'name', 1)", "a = setattr(o, 'name', 1)"),
    # `self.__x` is mangled in a class, the string isn't
    ("class A:\n    def f(self):\n        return getattr(self, '__x')", "class A:\n    def f(self):\n        return getattr(self, '__x')"),
    # not the builtins
    ("def getattr(o, n): pass\na = getattr(o, 'name')", "def getattr(o, n): pass\na = getattr(o, 'name')"),
])
def test_convert_dynamic_attribute_access(source, expected):
    config = only("convert_dynamic_attribute_access")
    assert_code(apply_transform(source, ConvertDynamicAttributeAccess, config), expected)
