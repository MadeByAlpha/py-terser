import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveLiteralStatements

pytestmark = pytest.mark.xfail(strict=True, reason="visit_Module reads `bindings` from the AST node instead of its ref")


@pytest.mark.parametrize("source,expected", [
    ('"""module doc"""\nx = 1', "x = 1"),
    ('def f():\n    """doc"""\n    return 1', "def f():\n    return 1"),
    ('def f():\n    """doc"""', "def f():\n    0"),
    ('class A:\n    """doc"""\n    x = 1', "class A:\n    x = 1"),
    ("x = 1\n'stray'\n1234\nNone", "x = 1"),
])
def test_remove_literal_statements(source, expected):
    config = only("remove_literal_statements")
    assert_code(apply_transform(source, RemoveLiteralStatements, config), expected)


@pytest.mark.parametrize("source", [
    '"""module doc"""\nprint(__doc__)',
    '"""module doc"""\ndef f():\n    return __doc__',
])
def test_module_docstring_kept_when_used(source):
    config = only("remove_literal_statements")
    assert_code(apply_transform(source, RemoveLiteralStatements, config), source)
