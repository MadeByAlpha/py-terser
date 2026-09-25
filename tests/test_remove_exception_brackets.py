import pytest

from helpers import (
    apply_transform,
    assert_code,
    minify_src,
    only,
    read_tree,
    run_py,
    write_tree,
)
from terser._pipeline.transforms import RemoveExceptionBrackets


@pytest.mark.parametrize("source,expected", [
    ("raise ValueError()", "raise ValueError"),
    ("raise ValueError() from TypeError()", "raise ValueError from TypeError"),
    ("def f():\n    raise KeyError()", "def f():\n    raise KeyError"),
    ("raise FileNotFoundError()", "raise FileNotFoundError"),
    ("raise ExceptionGroup()", "raise ExceptionGroup"),
    # left alone
    ("raise ValueError('message')", "raise ValueError('message')"),
    ("raise ValueError(code=1)", "raise ValueError(code=1)"),
    ("x = ValueError()", "x = ValueError()"),
    ("class MyError(Exception): pass\nraise MyError()", "class MyError(Exception): pass\nraise MyError()"),
    ("ValueError = TypeError\nraise ValueError()", "ValueError = TypeError\nraise ValueError()"),
    ("class A:\n    ValueError = ValueError\nraise ValueError()", "class A:\n    ValueError = ValueError\nraise ValueError()"),
    ("def f(ValueError):\n    raise ValueError()", "def f(ValueError):\n    raise ValueError()"),
    ("print = exec\nraise ValueError()", "print = exec\nraise ValueError()"),
])
def test_remove_exception_brackets(source, expected):
    config = only("remove_empty_exc_brackets")
    assert_code(apply_transform(source, RemoveExceptionBrackets, config), expected)


def test_minify():
    source = "def check(value):\n    if not value:\n        raise ValueError()\n    return value\n"
    assert "raise ValueError\n" in minify_src(source, only("remove_empty_exc_brackets")) + "\n"


def test_external_wildcard_import():
    # `os` could provide any name, so ValueError may not be the builtin
    source = "from os import *\ndef check(value):\n    raise ValueError()\n"
    assert "ValueError()" in minify_src(source, only("remove_empty_exc_brackets"))


def test_project_wildcard_import(tmp_path):
    root = write_tree(tmp_path / "app", {
        # not an exception class: `raise ValueError` would raise TypeError instead of KeyError
        "errors.py": "def ValueError():\n    return KeyError('from a factory')\n",
        "main.py": (
            "from errors import *\n"
            "try:\n"
            "    raise ValueError()\n"
            "except Exception as error:\n"
            "    print(type(error).__name__, error)\n"
        ),
    })
    expected = run_py("main.py", cwd=root).stdout

    from test_project import minify

    out = tmp_path / "out"
    minify(root, output=out, config=only("remove_empty_exc_brackets"))
    assert "ValueError()" in read_tree(out)["main.py"]
    assert run_py("main.py", cwd=out).stdout == expected
