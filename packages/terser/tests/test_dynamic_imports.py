import builtins
import io
import re
import warnings
from functools import partial

import anyio
import pytest
from helpers import read_tree, run_py, write_tree

from alpha93.progression import LogReporter, TqdmReporter
from terser import TransformConfig, minify_project
from terser._minify import minify as minify_module
from terser._pipeline.dynamic_imports import Callee
from terser.ast import ref
from terser.exceptions import DynamicImportWarning

PACKAGE = {"pkg/__init__.py": "", **{f"pkg/{name}.py": f'X = "{name}"\n' for name in ("alpha", "beta", "gamma", "delta")}}

LITERALS = """\
import importlib
from importlib import import_module as load

a = __import__("pkg.alpha")                              # returns `pkg`
b = importlib.import_module("pkg.beta")                  # returns `pkg.beta`
c = load(".gamma", "pkg")                                # relative, with a literal package
d = __import__("pkg.delta", fromlist=["X"])              # returns `pkg.delta`
print(a.alpha.X, b.X, c.X, d.X, __import__("pkg", fromlist=["beta"]).beta.X)
"""

EXPECTED = "alpha beta gamma delta beta\n"


def minify(root, out, **options):
    anyio.run(partial(minify_project, TransformConfig(), {str(root)}, None, anyio.Path(out), **options))
    return read_tree(out)


@pytest.mark.parametrize("options", [
    {},
    {"rename_modules": True, "preserve_modules": {"main"}},
    {"entry": {"main"}},
    {"rename_modules": True, "entry": {"main"}},
    {"rename_globals": True},
    {"rename_globals": True, "entry": {"main"}},
])
def test_literals(tmp_path, options):
    root = write_tree(tmp_path / "src", {"main.py": LITERALS, **PACKAGE})
    assert run_py("main.py", cwd=root).stdout == EXPECTED

    out = tmp_path / "out"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DynamicImportWarning)
        tree = minify(root, out, **options)

    assert run_py("main.py", cwd=out).stdout == EXPECTED
    if options.get("rename_modules"):
        assert "pkg" not in tree["main.py"]
    if options.get("rename_globals"):
        # `X` was renamed, and every attribute access through what the calls return followed
        assert "X=" not in "".join(tree[f"pkg/{name}.py"] for name in ("alpha", "beta", "gamma", "delta"))


def test_entry_keeps_what_literals_import(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": 'import importlib\nprint(importlib.import_module("pkg.beta").X)\n', **PACKAGE,
    })
    tree = minify(root, tmp_path / "out", entry={"main"})
    assert set(tree) == {"main.py", "pkg/__init__.py", "pkg/beta.py"}


def test_relative_to_own_package(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nprint(pkg.run())\n",
        "pkg/__init__.py": (
            "import importlib\n\n\n"
            "def run():\n"
            "    first = importlib.import_module('.beta', __package__)\n"
            "    second = __import__('gamma', globals(), None, ['X'], 1)\n"
            "    return first.X + second.X\n"
        ),
        **{k: v for k, v in PACKAGE.items() if k != "pkg/__init__.py"},
    })
    tree = minify(root, tmp_path / "out", rename_modules=True, preserve_modules={"main", "pkg"}, entry={"main"})
    assert set(tree) == {"main.py", "pkg/__init__.py", "pkg/A.py", "pkg/B.py"}
    assert run_py("main.py", cwd=tmp_path / "out").stdout == "betagamma\n"


def test_literals_are_not_hoisted(tmp_path):
    # hoisting a literal repeated this often in a function would take it out of the calls
    source = "import importlib\n\n\ndef run():\n" + "".join(
        f'    print(importlib.import_module("pkg.alpha").X, "pkg.alpha", {i})\n' for i in range(6)
    ) + "\n\nrun()\n"
    root = write_tree(tmp_path / "src", {"main.py": source, **PACKAGE})
    tree = minify(root, tmp_path / "out", rename_modules=True, preserve_modules={"main"})

    assert len(re.findall(r"import_module\('A\.[A-Z]'\)", tree["main.py"])) == 6
    assert "='pkg.alpha'" in tree["main.py"]  # the other literals were hoisted
    assert run_py("main.py", cwd=tmp_path / "out").stdout.count("alpha pkg.alpha") == 6


@pytest.mark.parametrize("shadowing", [
    "def __import__(name, *args):\n    return name\n",
    "class importlib:\n    import_module = staticmethod(lambda name: name)\n",
])
def test_shadowed_callees_are_left_alone(tmp_path, shadowing):
    source = shadowing + 'print(__import__("pkg.alpha") if "def" in """' + shadowing + '""" else importlib.import_module("pkg.alpha"))\n'
    root = write_tree(tmp_path / "src", {"main.py": source, **PACKAGE})
    tree = minify(root, tmp_path / "out", rename_modules=True, preserve_modules={"main"})
    assert "'pkg.alpha'" in tree["main.py"]
    assert run_py("main.py", cwd=tmp_path / "out").stdout == "pkg.alpha\n"


@pytest.mark.skipif(not hasattr(builtins, "__lazy_import__"), reason="`__lazy_import__()` is new in 3.15")
def test_lazy_import_is_followed():
    # module level only: that's where `__lazy_import__()` works
    source = (
        'a = __lazy_import__("pkg.alpha")\n'
        'b = __lazy_import__("pkg.delta", globals(), None, ("X",), 0)\n'
        'c = __lazy_import__(a.name)\n'
    )
    module, _ = minify_module(source, "pkg.main", TransformConfig(), rename=False, hoist_literals=False)

    a, b, c = ref(module).dynamic_imports
    assert (a.callee, a.path, a.returned) == (Callee.DUNDER_LAZY_IMPORT, "pkg.alpha", "pkg")
    assert (b.callee, b.path, b.returned) == (Callee.DUNDER_LAZY_IMPORT, "pkg.delta", "pkg.delta")
    assert (c.callee, c.name) == (Callee.DUNDER_LAZY_IMPORT, None)


NOT_LITERALS = """\
import importlib


def load(name):
    return importlib.import_module(name)


for package in ("pkg.alpha",):
    __import__(package)
"""


@pytest.mark.parametrize("options", [{"rename_modules": True}, {"rename_globals": True}, {"entry": {"main"}}])
def test_not_literals_warn(tmp_path, options):
    root = write_tree(tmp_path / "src", {"main.py": NOT_LITERALS, **PACKAGE})
    with pytest.warns(DynamicImportWarning) as record:
        minify(root, tmp_path / "out", **options)

    messages = [str(warning.message) for warning in record]
    assert len(messages) == 2
    assert messages[0].startswith("main, line 5: `importlib.import_module()` is given a module name that is not a literal")
    assert messages[1].startswith("main, line 9: `__import__()` is given a module name that is not a literal")


def test_not_literals_are_fine_otherwise(tmp_path):
    root = write_tree(tmp_path / "src", {"main.py": NOT_LITERALS, **PACKAGE})
    with warnings.catch_warnings():
        warnings.simplefilter("error", DynamicImportWarning)
        minify(root, tmp_path / "out")


@pytest.mark.parametrize("reporter", [LogReporter, TqdmReporter])
def test_reporters_write_warnings(reporter):
    out = io.StringIO()
    reporter("tool: ", file=out).warn("something", DynamicImportWarning)
    assert "tool: warning: something\n" in out.getvalue()


def test_rename_modules_and_globals_attribute_chain(tmp_path):
    root = write_tree(tmp_path / "src", {"main.py": "import pkg.alpha\nprint(pkg.alpha.X)\n", **PACKAGE})
    minify(root, tmp_path / "out", rename_modules=True, rename_globals=True, preserve_modules={"main"})
    assert run_py("main.py", cwd=tmp_path / "out").stdout == "alpha\n"


def test_rename_modules_and_globals_new_names(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": 'import pkg.alpha\nprint(pkg.__name__ is not None)\nprint(len("x"))\n', **PACKAGE,
    })
    minify(root, tmp_path / "out", rename_modules=True, rename_globals=True, preserve_modules={"main"})
    assert run_py("main.py", cwd=tmp_path / "out").stdout == "True\n1\n"
