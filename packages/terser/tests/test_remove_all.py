import pytest

from helpers import apply_transform, assert_code, only
from terser import TransformConfig
from terser._pipeline.transforms import RemoveAll


@pytest.mark.parametrize("source,expected", [
    ("__all__ = ['x']\nx = 1", "x = 1"),
    ("__all__ = ('x',)\nx = 1", "x = 1"),
    # still used
    ("__all__ = ['x']\n__all__.append('y')\nx = y = 1", "__all__ = ['x']\n__all__.append('y')\nx = y = 1"),
    ("__all__ = ['x']\nprint(__all__)", "__all__ = ['x']\nprint(__all__)"),
])
def test_remove_all(source, expected):
    assert_code(apply_transform(source, RemoveAll, only("remove_dunder_all")), expected)


@pytest.mark.parametrize("patterns,expected", [
    (["test_*"], "x = 1"),
    (["other"], "__all__ = ['x']\nx = 1"),
])
def test_remove_dunder_all_modules(patterns, expected):
    # `apply_transform` names the module `test_module`
    config = only(remove_dunder_all_modules=patterns)
    assert RemoveAll.is_enabled(config)
    assert_code(apply_transform("__all__ = ['x']\nx = 1", RemoveAll, config), expected)


def test_off_by_default():
    assert not RemoveAll.is_enabled(TransformConfig())
