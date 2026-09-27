import anyio
import pytest

from helpers import LAZY_PACKAGE, apply_transform, assert_code, minify_src, only, run_py, write_tree
from terser import TransformConfig, minify_project
from terser._pipeline.transforms import FoldTypeChecking


@pytest.mark.parametrize("source,expected", [
    ("from typing import TYPE_CHECKING\nprint(TYPE_CHECKING)", "print(False)"),
    ("from typing_extensions import TYPE_CHECKING as TC\nprint(TC)", "print(False)"),
    ("import typing\nprint(typing.TYPE_CHECKING)", "print(False)"),
    ("import typing as t\nprint(t.TYPE_CHECKING, t.cast)", "import typing as t\nprint(False, t.cast)"),
    # the import stays while something else uses it
    ("from typing import TYPE_CHECKING, cast\nprint(TYPE_CHECKING, cast)", "from typing import cast\nprint(False, cast)"),
    ("def f():\n    from typing import TYPE_CHECKING\n    return TYPE_CHECKING", "def f():\n    return False"),
    # not `typing`'s
    ("TYPE_CHECKING = True\nprint(TYPE_CHECKING)", "TYPE_CHECKING = True\nprint(TYPE_CHECKING)"),
    ("from .typing import TYPE_CHECKING\nprint(TYPE_CHECKING)", "from .typing import TYPE_CHECKING\nprint(TYPE_CHECKING)"),
    ("from compat import TYPE_CHECKING\nprint(TYPE_CHECKING)", "from compat import TYPE_CHECKING\nprint(TYPE_CHECKING)"),
    (
        "from typing import TYPE_CHECKING\nTYPE_CHECKING = True\nprint(TYPE_CHECKING)",
        "from typing import TYPE_CHECKING\nTYPE_CHECKING = True\nprint(TYPE_CHECKING)",
    ),
    ("import typing\ntyping.TYPE_CHECKING = True", "import typing\ntyping.TYPE_CHECKING = True"),
])
def test_fold_type_checking(source, expected):
    assert_code(apply_transform(source, FoldTypeChecking, only("fold_type_checking")), expected)


@pytest.mark.parametrize("optimize", [-1, 1])
def test_type_checking_blocks_are_removed(optimize):
    source = """\
from typing import TYPE_CHECKING
if __debug__ and TYPE_CHECKING:
    from os import path
if TYPE_CHECKING:
    import sys
else:
    x = 1
if False:
    y = 2
print(x)
"""
    assert_code(minify_src(source, TransformConfig(optimize=optimize)), "x = 1\nprint(x)")


def test_type_checking_left_as_is():
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sys\nprint(1)\n"
    assert "TYPE_CHECKING" in minify_src(source, TransformConfig(fold_type_checking=False))


@pytest.mark.parametrize("rename_globals", [False, True])
def test_classes_only_type_checkers_see(rename_globals):
    # removing annotations leaves their references known, under the class removed afterwards
    source = """\
import typing
if typing.TYPE_CHECKING:
    from typing import Protocol

    class HasKeys(Protocol):
        def keys(self) -> typing.Iterator[str]: ...
        def __getitem__(self, key: str) -> str: ...
def f(x):
    return str(x)
print(f(1))
"""
    minified = minify_src(source, TransformConfig(), rename_globals=rename_globals)
    assert "Protocol" not in minified and "typing" not in minified


def test_preserve_type_checking():
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING or f():\n    import os\nprint(1)"
    assert_code(minify_src(source, only("fold_type_checking", "remove_dead_code", "fold_constants")), "if f():\n    import os\nprint(1)")
    assert_code(
        minify_src(source, only("fold_type_checking", "remove_dead_code", "fold_constants"), preserve_type_checking=True),
        source,
    )


@pytest.mark.parametrize(("patterns", "expected"), [
    ({"pkg"}, "True"),
    ({"p*"}, "True"),
    ({"pkg._lazy"}, "KeyError: 'TYPE_CHECKING'"),
    (set(), "KeyError: 'TYPE_CHECKING'"),
])
def test_preserve_type_checking_in_project(tmp_path, patterns, expected):
    root = write_tree(tmp_path / "src", LAZY_PACKAGE)
    out = tmp_path / "out"
    anyio.run(lambda: minify_project(
        TransformConfig(), {str(root)}, output=anyio.Path(out), preserve_type_checking=patterns,
    ))

    result = run_py("-c", "import pkg; print(pkg.LAZY)", env={"PYTHONPATH": str(out)}, check=False)
    assert expected in result.stdout + result.stderr
