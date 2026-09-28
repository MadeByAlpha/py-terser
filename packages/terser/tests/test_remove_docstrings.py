import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDocstrings
from terser.config import RemoveDocstringOptions


def remove(source, **options):
    config = only("remove_docstrings", remove_docstrings=RemoveDocstringOptions(**options))
    return apply_transform(source, RemoveDocstrings, config)


@pytest.mark.parametrize("source,expected", [
    ('"""m"""\ndef f():\n    """d"""\n    return 1', '"""m"""\ndef f():\n    return 1'),
    ('class A:\n    """d"""\n    x = 1', "class A:\n    x = 1"),
    ('def f():\n    """d"""', "def f():\n    0"),
    ('async def f():\n    """d"""\n    return 1', "async def f():\n    return 1"),
    # only the first statement is a docstring
    ('def f():\n    x = 1\n    "not a docstring"', 'def f():\n    x = 1\n    "not a docstring"'),
    ('def f():\n    b"bytes"', 'def f():\n    b"bytes"'),
])
def test_remove_docstrings(source, expected):
    assert_code(remove(source), expected)


def test_also_modules():
    assert_code(remove('"""m"""\nx = 1', also_modules=True), "x = 1")


@pytest.mark.parametrize("source,expected", [
    ('"""m"""\nprint(__doc__)', '"""m"""\nprint(__doc__)'),
    ('"""m"""\ndef f():\n    """d"""\n    return __doc__', '"""m"""\ndef f():\n    return __doc__'),
    ('class A:\n    """d"""\n    x = __doc__', 'class A:\n    """d"""\n    x = __doc__'),
    ('def f():\n    """d"""\nprint(f.__doc__)', 'def f():\n    """d"""\nprint(f.__doc__)'),
])
def test_docstrings_kept_when_read(source, expected):
    assert_code(remove(source, also_modules=True), expected)


@pytest.mark.parametrize("source", [
    'import terser_hints\n@terser_hints.preserve_docstring\ndef f():\n    """d"""',
    'from terser_hints import preserve_docstring as keep\n@keep\nclass A:\n    """d"""',
])
def test_preserve_docstring_hint(source):
    assert_code(remove(source), source)


def test_hint_modules():
    source = 'from my.hints import preserve_docstring\n@preserve_docstring\ndef f():\n    """d"""'
    config = only("remove_docstrings", hint_modules=["my.hints"])
    assert_code(apply_transform(source, RemoveDocstrings, config), source)
    assert_code(remove(source), 'from my.hints import preserve_docstring\n@preserve_docstring\ndef f():\n    0')


def test_optimize_2_keeps_preserved_docstrings():
    from helpers import minify_src
    from terser import TransformConfig

    source = (
        '"""module"""\nfrom terser_hints import preserve_docstring\n'
        '@preserve_docstring\ndef f():\n    """kept"""\n    return f.__name__\n'
        'def g():\n    """removed"""\n    return 1\nprint(f(), g())\n'
    )
    minified = minify_src(source, TransformConfig(optimize=2), rename_locals=False)
    assert "kept" in minified
    assert "removed" not in minified and "module" not in minified


def test_optimize_2_removes_docstrings_read_too():
    # like `python -OO`: numpy tells `__doc__ is None` apart, not only some docstrings left
    from helpers import minify_src
    from terser import TransformConfig

    source = 'def f():\n    """doc"""\nif f.__doc__ is not None:\n    print(f.__doc__.upper())\nprint(1)\n'
    assert "doc" not in minify_src(source, TransformConfig(optimize=2), rename_locals=False).replace("__doc__", "")
