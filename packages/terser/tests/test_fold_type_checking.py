import anyio
import pytest

from helpers import apply_transform, assert_code, minify_src, only, read_tree, write_tree
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


def _preserved(source: str, **kwargs) -> str:
    config = only("fold_type_checking", "remove_dead_code")
    return minify_src(source, config, hoist_literals=False, rename_locals=False, **kwargs)


@pytest.mark.parametrize("source,options,expected", [
    # still folded, but the preserved name stays bound
    (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import os\nprint(1)",
        {"preserve_globals": ["TYPE_CHECKING"]},
        "from typing import TYPE_CHECKING\nprint(1)",
    ),
    (
        "from typing import TYPE_CHECKING as TC\nif TC:\n    import os\nprint(1)",
        {"preserve_globals": ["TC"]},
        "from typing import TYPE_CHECKING as TC\nprint(1)",
    ),
    (
        "import typing\nif typing.TYPE_CHECKING:\n    import os\nprint(1)",
        {"preserve_globals": ["typing"]},
        "import typing\nprint(1)",
    ),
    # local names are preserved by `preserve_locals`, in the scopes it names
    (
        (
            "def f():\n    from typing import TYPE_CHECKING\n    return TYPE_CHECKING\n"
            "def g():\n    from typing import TYPE_CHECKING\n    return TYPE_CHECKING"
        ),
        {"preserve_locals": ["f::TYPE_CHECKING"]},
        "def f():\n    from typing import TYPE_CHECKING\n    return False\ndef g():\n    return False",
    ),
    # a global isn't a local, nor the other way around
    (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import os\nprint(1)",
        {"preserve_locals": ["TYPE_CHECKING"]},
        "print(1)",
    ),
    (
        "def f():\n    from typing import TYPE_CHECKING\n    return TYPE_CHECKING",
        {"preserve_globals": ["TYPE_CHECKING"]},
        "def f():\n    return False",
    ),
])
def test_preserved_import_is_kept(source, options, expected):
    assert_code(_preserved(source, **options), expected)


# like `anyio`: a function deletes the module's `TYPE_CHECKING` from its globals
LAZY_IMPORTER = """\
from typing import TYPE_CHECKING
import sys

def install():
    del sys._getframe(1).f_globals['TYPE_CHECKING']
    return False

if TYPE_CHECKING or not install():
    from os import path
"""


def test_preserved_import_is_looked_up_by_name():
    minified = minify_src(LAZY_IMPORTER, TransformConfig(), preserve_globals=["TYPE_CHECKING"])
    namespace = {}
    exec(minified, namespace)  # noqa: S102 - running the output is the test
    assert "TYPE_CHECKING" not in namespace and "path" in namespace

    with pytest.raises(KeyError, match="TYPE_CHECKING"):
        exec(minify_src(LAZY_IMPORTER, TransformConfig()), {})  # noqa: S102


@pytest.mark.parametrize(("pattern", "kept"), [("pkg.mod", True), ("other", False)])
def test_preserved_import_is_kept_in_project(tmp_path, pattern, kept):
    root = write_tree(tmp_path / "src", {"pkg/__init__.py": "", "pkg/mod.py": LAZY_IMPORTER})
    out = tmp_path / "out"
    anyio.run(lambda: minify_project(
        TransformConfig(), {str(root)}, output=anyio.Path(out), preserve_globals={pattern: ["TYPE_CHECKING"]},
    ))

    assert ("import TYPE_CHECKING" in read_tree(out)["pkg/mod.py"]) is kept
