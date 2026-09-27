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


def attributes(**overrides):
    return only(remove_annotations=RemoveAnnotationOptions(remove_attribute_annotations=True), **overrides)


@pytest.mark.parametrize("source", [
    # pydantic builds its fields from the annotations, and `computed_field` reads the return type
    "from pydantic import BaseModel, computed_field\nclass A(BaseModel):\n    b: int = 2\n    c: str\n"
    "    @computed_field\n    @property\n    def d(self) -> int:\n        return self.b",
    "import pydantic\nclass A(pydantic.BaseModel):\n    b: int",
    "from pydantic import RootModel\nclass A(RootModel[list[int]]):\n    root: list[int]",
    # through a base class of the same module
    "from pydantic import BaseModel\nclass Base(BaseModel):\n    pass\nclass A(Base):\n    b: int",
    "from typing import TypedDict\nclass Base(TypedDict):\n    a: int\nclass A(Base, total=False):\n    b: int",
    # through a metaclass
    "from pydantic._internal._model_construction import ModelMetaclass\nclass A(metaclass=ModelMetaclass):\n    b: int",
    "import attrs\n@attrs.define\nclass A:\n    b: int",
    # a base class reading its subclasses' annotations, like anyio's `TypedAttributeSet`
    "class Base:\n    def __init_subclass__(cls):\n        assert getattr(cls, '__annotations__', {})\nclass A(Base):\n    b: int = 0",
    "import typing\nclass Meta(type):\n    def __new__(mcs, *args):\n        cls = super().__new__(mcs, *args)\n        typing.get_type_hints(cls)\n        return cls\nclass A(metaclass=Meta):\n    b: int = 0",
])
def test_annotation_readers_are_kept(source):
    assert_code(apply_transform(source, RemoveAnnotations, attributes()), source)


def test_other_classes_lose_annotations():
    source = "from pydantic import BaseModel\nclass Base(BaseModel):\n    pass\nclass A:\n    b: int = 2\n    def f(self, x: int) -> int:\n        return x"
    expected = "from pydantic import BaseModel\nclass Base(BaseModel):\n    pass\nclass A:\n    b = 2\n    def f(self, x):\n        return x"
    assert_code(apply_transform(source, RemoveAnnotations, attributes()), expected)


def test_preserve_annotations_hint_covers_methods():
    source = (
        "from terser_hints import preserve_annotations\n@preserve_annotations\nclass A:\n    b: int = 2\n"
        "    def f(self, x: int) -> int:\n        return x"
    )
    assert_code(apply_transform(source, RemoveAnnotations, attributes()), source)


@pytest.mark.parametrize("patterns,expected", [
    (["test_module"], "class A:\n    b: int = 2\nclass B:\n    c: int = 3\ndef f(x: int) -> int:\n    return x"),
    (["test_*::A"], "class A:\n    b: int = 2\nclass B:\n    c = 3\ndef f(x):\n    return x"),
    (["*::f"], "class A:\n    b = 2\nclass B:\n    c = 3\ndef f(x: int) -> int:\n    return x"),
    (["other"], "class A:\n    b = 2\nclass B:\n    c = 3\ndef f(x):\n    return x"),
])
def test_preserve_annotations_patterns(patterns, expected):
    source = "class A:\n    b: int = 2\nclass B:\n    c: int = 3\ndef f(x: int) -> int:\n    return x"
    assert_code(apply_transform(source, RemoveAnnotations, attributes(preserve_annotations=patterns)), expected)
