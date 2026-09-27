import re

import pytest
from helpers import minify_project, read_tree, write_tree

import terser
from terser import TransformConfig
from terser._pipeline.mangler.util import preserved_names

SOURCE = """\
def Field(default=None, *, alias=None, **extra):
    def inner(*args, **kwargs):
        local_value = [item_value for item_value in args]
        return local_value, kwargs
    return inner(default, alias, **extra)


class Model:
    def method(self, *values, **options):
        some_local = values
        return some_local, options, (gen_value for gen_value in values), lambda *lambda_args: lambda_args
"""

# every local name of SOURCE that can be renamed
NAMES = {"extra", "args", "kwargs", "local_value", "item_value", "values", "options", "some_local", "gen_value",
         "lambda_args"}


def kept(preserve_locals=(), **kwargs) -> set[str]:
    """The local names of SOURCE that minifying it leaves as they are."""

    return _names(terser.minify(SOURCE, TransformConfig(), "m.py", preserve_locals=list(preserve_locals), **kwargs))


def _names(minified: str) -> set[str]:
    return NAMES & set(re.findall(r"\w+", minified))


def test_everything_renamed_by_default():
    assert kept() == set()


@pytest.mark.parametrize(("spec", "expected"), [
    # parameter kinds
    ("*", {"args", "values", "lambda_args"}),
    ("**", {"extra", "kwargs", "options"}),
    ("**extra", {"extra"}),
    ("*values", {"values"}),
    ("**values", set()),  # not a `**` parameter
    # plain names are kept wherever they're bound
    ("local_value", {"local_value"}),
    # scoped to functions and classes, by qualname
    ("Field::**", {"extra"}),
    ("Field.<locals>.inner::*", {"args"}),
    ("Field.<locals>.*::**", {"kwargs"}),
    ("Model.method::**", {"options"}),
    ("Model.*::some_local", {"some_local"}),
    ("Model::some_local", set()),  # bound in the method, not the class body
    ("Model.method.<locals>.<lambda>::*", {"lambda_args"}),
    ("Model.method.<locals>.<genexpr>::gen_value", {"gen_value"}),
    # a list comprehension belongs to the function it's in
    ("Field.<locals>.inner::item_value", {"item_value"}),
])
def test_rules(spec, expected):
    assert kept([spec]) == expected


def test_rename_star_args():
    assert kept(rename_star_args=False) == {"extra", "args", "kwargs", "values", "options", "lambda_args"}


@pytest.mark.parametrize("spec", ["Field::", "::"])
def test_rule_naming_nothing(spec):
    with pytest.raises(ValueError, match="names nothing"):
        kept([spec])


def test_preserved_names_with_qualname():
    preserved = {"pkg.*::Field": ["**"], "pkg.mod": ["a"], "other::Field": ["b"]}
    assert preserved_names("pkg.mod", preserved) == {"Field::**", "a"}


@pytest.mark.parametrize(("options", "expected"), [
    ({"preserve_locals": {"pkg.mod::Field": ["**"]}}, {"extra"}),
    ({"preserve_locals": {"other::Field": ["**"]}}, set()),
    ({"rename_star_args": False}, {"extra", "args", "kwargs", "values", "options", "lambda_args"}),
])
def test_project(tmp_path, options, expected):
    root = write_tree(tmp_path / "src", {"pkg/__init__.py": "", "pkg/mod.py": SOURCE})
    out = tmp_path / "out"
    minify_project(root, out, **options)

    assert _names(read_tree(out)["pkg/mod.py"]) == expected
