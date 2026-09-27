import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDocstrings, RemoveLiteralStatements
from terser.config import RemoveDocstringOptions


def apply(source, config):
    """`RemoveLiteralStatements` leaves docstrings to `RemoveDocstrings`, which runs after it"""

    module = apply_transform(source, RemoveLiteralStatements, config)
    return RemoveDocstrings(config)(module)


def with_docstrings():
    return only("remove_literal_statements", "remove_docstrings", remove_docstrings=RemoveDocstringOptions(also_modules=True))


@pytest.mark.parametrize("source,expected", [
    ('"""module doc"""\nx = 1', "x = 1"),
    ('def f():\n    """doc"""\n    return 1', "def f():\n    return 1"),
    ('def f():\n    """doc"""', "def f():\n    0"),
    ('class A:\n    """doc"""\n    x = 1', "class A:\n    x = 1"),
    ("x = 1\n'stray'\n1234\nNone", "x = 1"),
])
def test_remove_literal_statements(source, expected):
    assert_code(apply(source, with_docstrings()), expected)


@pytest.mark.parametrize("source", [
    '"""module doc"""\nx = 1',
    'def f():\n    """doc"""\n    return 1',
    'class A:\n    """doc"""\n    x = 1',
])
def test_docstrings_left_to_remove_docstrings(source):
    config = only("remove_literal_statements")
    assert_code(apply_transform(source, RemoveLiteralStatements, config), source)


@pytest.mark.parametrize("source,expected", [
    ('"""module doc"""\nprint(__doc__)', '"""module doc"""\nprint(__doc__)'),
    ('"""module doc"""\ndef f():\n    """doc"""\n    return __doc__', '"""module doc"""\ndef f():\n    return __doc__'),
    ('"""module doc"""\n"stray"\nprint(__doc__)', '"""module doc"""\nprint(__doc__)'),
    ('class A:\n    """doc"""\n    x = __doc__', 'class A:\n    """doc"""\n    x = __doc__'),
    # any object's docstring might be read, so everything is kept
    ('"""module doc"""\ndef f():\n    """doc"""\nprint(f.__doc__)', '"""module doc"""\ndef f():\n    """doc"""\nprint(f.__doc__)'),
])
def test_docstrings_kept_when_used(source, expected):
    assert_code(apply(source, with_docstrings()), expected)
