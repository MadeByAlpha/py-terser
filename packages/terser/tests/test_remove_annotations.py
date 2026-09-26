import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveAnnotations
from terser.config import RemoveAnnotationOptions


@pytest.mark.parametrize("source,expected", [
    ("def f(a: int, *b: str, c: int = 1, **d: str) -> None: pass",
     "def f(a, *b, c=1, **d): pass"),
    ("def f(a: int, /, b: int) -> int: return a", "def f(a, /, b): return a"),
    ("async def f(a: int) -> int: return a", "async def f(a): return a"),
    ("x: int = 1", "x = 1"),
    # a bare annotation defines nothing at runtime, but it must stay a valid statement
    ("x: int", "x: 0"),
    # class attribute annotations are kept by default, since dataclasses and friends read them
    ("class A:\n    b: int = 2\n    c: str", "class A:\n    b: int = 2\n    c: str"),
    ("def f():\n    x: int = 1\n    return x", "def f():\n    x = 1\n    return x"),
])
def test_remove_annotations(source, expected):
    assert_code(apply_transform(source, RemoveAnnotations, only("remove_annotations")), expected)


def test_remove_attribute_annotations():
    config = only(remove_annotations=RemoveAnnotationOptions(remove_attribute_annotations=True))
    actual = apply_transform("class A:\n    b: int = 2", RemoveAnnotations, config)
    assert_code(actual, "class A:\n    b = 2")


def test_keep_return_annotations():
    config = only(remove_annotations=RemoveAnnotationOptions(remove_return_annotations=False))
    actual = apply_transform("def f(a: int) -> int: return a", RemoveAnnotations, config)
    assert_code(actual, "def f(a) -> int: return a")


def test_dataclass_fields_are_kept():
    source = "from dataclasses import dataclass\n@dataclass\nclass A:\n    b: int\n    c: str = ''"
    config = only(remove_annotations=RemoveAnnotationOptions(remove_attribute_annotations=True))
    assert_code(apply_transform(source, RemoveAnnotations, config), source)
