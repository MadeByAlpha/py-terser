import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveTypeStatements


@pytest.mark.parametrize("source,expected", [
    ("type X = int\nx = 1", "x = 1"),
    ("type X[T] = list[T]", ""),
    ("def f():\n    type X = int", "def f():\n    0"),
])
def test_remove_type_statements(source, expected):
    assert_code(apply_transform(source, RemoveTypeStatements, only("remove_type_statements")), expected)


def test_off_by_default():
    from terser import TransformConfig

    assert not RemoveTypeStatements.is_enabled(TransformConfig())
