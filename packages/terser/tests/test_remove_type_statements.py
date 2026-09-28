import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveTypeStatements


def remove(source):
    return apply_transform(source, RemoveTypeStatements, only("remove_type_statements"), link=True)


@pytest.mark.parametrize("source,expected", [
    # `__all__` leaves them out of the module's public interface
    ("__all__ = []\ntype X = int\nx = 1", "__all__ = []\nx = 1"),
    ("__all__ = []\ntype X[T] = list[T]", "__all__ = []"),
    ("def f():\n    type X = int", "def f():\n    0"),
])
def test_remove_type_statements(source, expected):
    assert_code(remove(source), expected)


@pytest.mark.parametrize("source", [
    # read by a name left in the module: an annotation kept for code reading it at run time, say
    "__all__ = []\ntype X = int\nclass A:\n    b: X",
    "def f():\n    type X = int\n    return X",
    # part of the module's public interface: other modules may import it
    "type X = int",
    "__all__ = ['X']\ntype X = int",
])
def test_type_statements_kept(source):
    assert_code(remove(source), source)


def test_type_statements_kept_until_linked():
    source = "__all__ = []\ntype X = int"
    assert_code(apply_transform(source, RemoveTypeStatements, only("remove_type_statements")), source)


def test_off_by_default():
    from terser import TransformConfig

    assert not RemoveTypeStatements.is_enabled(TransformConfig())
