
import pytest

from helpers import minify_project, read_tree, run_py, write_tree

APP = {
    "main.py": """\
from shop import checkout
from shop.models.item import Item


def main() -> None:
    items = [Item("apple", 3), Item("pear", 5)]
    print(checkout(items))


if __name__ == "__main__":
    main()
""",
    "shop/__init__.py": """\
from .cart import checkout

__all__ = ["checkout"]
""",
    "shop/cart.py": """\
from shop.models.item import Item

TAX_RATE = 10


def checkout(items: list[Item]) -> str:
    subtotal = sum(item.price for item in items)
    total = subtotal + subtotal * TAX_RATE // 100
    return f"{len(items)} items, total {total}"
""",
    "shop/models/__init__.py": "",
    "shop/models/item.py": """\
class Item(object):
    def __init__(self, name: str, price: int) -> None:
        self.name = name
        self.price = price
""",
    "shop/unused.py": """\
def never_called():
    return "unused"
""",
}

EXPECTED_OUTPUT = "2 items, total 8\n"


@pytest.fixture
def app(tmp_path):
    return write_tree(tmp_path / "app", APP)


def minify(*paths, output=None, config=None, **kwargs):
    minify_project(paths, output, None, config, **kwargs)


def total_size(tree: dict[str, str]) -> int:
    return sum(map(len, tree.values()))


def test_original_app_runs(app):
    assert run_py("main.py", cwd=app).stdout == EXPECTED_OUTPUT


def test_default(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out)

    tree = read_tree(out)
    assert set(tree) == set(APP)
    assert total_size(tree) < total_size(APP)
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT
    # globals are kept by default
    assert "def checkout(" in tree["shop/cart.py"]


def test_in_place(app):
    minify(app)
    tree = read_tree(app)
    assert set(tree) == set(APP)
    assert total_size(tree) < total_size(APP)
    assert run_py("main.py", cwd=app).stdout == EXPECTED_OUTPUT


def test_rename_globals(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, rename_globals=True)

    tree = read_tree(out)
    assert "checkout" not in tree["shop/cart.py"]
    assert "TAX_RATE" not in tree["shop/cart.py"]
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_preserve_globals(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, rename_globals=True, preserve_globals={"shop.*": ["TAX_RATE"]})

    tree = read_tree(out)
    assert "TAX_RATE" in tree["shop/cart.py"]
    assert "def checkout(" not in tree["shop/cart.py"]
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_preserve_locals(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, preserve_locals={"shop.cart": ["subtotal"]})
    assert "subtotal" in read_tree(out)["shop/cart.py"]


def test_entry_tree_shaking(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, entry={"main"})

    tree = read_tree(out)
    assert set(tree) == set(APP) - {"shop/unused.py"}
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_rename_modules(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, entry={"main"}, rename_modules=True, rename_globals=True)

    tree = read_tree(out)
    # the entry module keeps its name, everything else is renamed
    assert "main.py" in tree
    assert not any(path.startswith("shop") for path in tree)
    assert len(tree) == len(APP) - 1
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_preserve_modules(app, tmp_path):
    out = tmp_path / "out"
    minify(app, output=out, entry={"main"}, rename_modules=True, preserve_modules={"shop", "shop.models*"})

    tree = read_tree(out)
    assert "shop/__init__.py" in tree
    assert "shop/models/item.py" in tree
    assert "shop/cart.py" not in tree
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_multiple_paths(app, tmp_path):
    out = tmp_path / "out"
    minify(app / "main.py", app / "shop", output=out)
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_multiple_paths_require_output(app):
    with pytest.raises(ValueError):
        minify(app / "main.py", app / "shop")


def test_package_directory(app, tmp_path):
    out = tmp_path / "out"
    minify(app / "shop", output=out / "shop")

    tree = read_tree(out)
    assert set(tree) == {path for path in APP if path.startswith("shop/")}
    # the package keeps its name, so the unminified main.py still finds it
    (out / "main.py").write_text(APP["main.py"])
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_package_directory_rename_modules(app, tmp_path):
    out = tmp_path / "out"
    minify(app / "shop", output=out / "shop", rename_modules=True, rename_globals=True)

    tree = read_tree(out)
    # the package's own name stays, since its directory name is chosen by the caller
    assert "shop/__init__.py" in tree
    assert "shop/cart.py" not in tree
    assert any("shop." in source for source in tree.values())


def test_package_directory_in_place(app):
    minify(app / "shop")
    assert total_size(read_tree(app / "shop")) < total_size({k: v for k, v in APP.items() if k.startswith("shop/")})
    assert run_py("main.py", cwd=app).stdout == EXPECTED_OUTPUT


def test_pyw_files(tmp_path):
    root = write_tree(tmp_path / "gui", {
        "app.pyw": "from helper import value\nprint(value())\n",
        "helper.py": "def value():\n    result_value = 40 + 2\n    return result_value\n",
    })
    out = tmp_path / "out"
    minify(root, output=out)
    assert set(read_tree(out)) == {"app.pyw", "helper.py"}
    assert run_py("app.pyw", cwd=out).stdout == "42\n"


@pytest.mark.parametrize("options", [{"rename_modules": True}, {"entry": {"main"}}])
def test_relative_submodule_import(tmp_path, options):
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nprint(pkg.VALUE)\n",
        "pkg/__init__.py": "from . import sub\nVALUE = sub.X\n",
        "pkg/sub.py": "X = 1\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, preserve_modules={"main"}, **options)
    assert run_py("main.py", cwd=out).stdout == "1\n"


def test_entry_keeps_function_level_imports(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "def f():\n    import dep\n    return dep.Y\nprint(f())\n",
        "dep.py": "Y = 2\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"})
    assert run_py("main.py", cwd=out).stdout == "2\n"


def test_package_name_shadowing_its_submodule(tmp_path):
    # `from .version import version` imports the submodule, then takes `pkg.version` over
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nprint(pkg.version)\n",
        "pkg/__init__.py": "from .version import version\n",
        "pkg/version.py": 'version = "1.0"\n',
    })
    out = tmp_path / "out"
    minify(root, output=out, rename_modules=True, preserve_modules={"main"})
    assert run_py("main.py", cwd=out).stdout == "1.0\n"


SEVERAL_IMPORTS = {
    "main.py": """\
import pkg.alpha
import pkg.beta
from pkg import alpha
from pkg import alpha
try:
    from pkg._speedups import value
except ImportError:
    from pkg._native import value
print(pkg.alpha.X, pkg.beta.X, alpha.X, value())
""",
    "pkg/__init__.py": "",
    "pkg/alpha.py": 'X = "a"\n',
    "pkg/beta.py": 'X = "b"\n',
    "pkg/_native.py": "def value():\n    return 1\n",
}


@pytest.mark.parametrize("options", [
    {"rename_modules": True, "preserve_modules": {"main"}},
    {"entry": {"main"}},
    {"rename_globals": True},
    {"rename_modules": True, "rename_globals": True, "entry": {"main"}},
])
def test_name_bound_by_several_imports(tmp_path, options):
    # every statement binding the name is followed, not only the first
    root = write_tree(tmp_path / "src", SEVERAL_IMPORTS)
    out = tmp_path / "out"
    minify(root, output=out, **options)
    assert run_py("main.py", cwd=out).stdout == "a b a 1\n"


@pytest.mark.parametrize("rename_globals", [False, True])
def test_renamed_root_package_binds_no_other_name(tmp_path, rename_globals):
    # `import pkg.alpha` can't become `import A.A`, which binds `A`
    root = write_tree(tmp_path / "src", {
        "main.py": "A = 5\nimport pkg.alpha\nprint(A, pkg.alpha.X, len('ab'))\n"
                   "def f():\n    B = 1\n    import pkg.alpha\n    return B, pkg.alpha.X\nprint(f())\n",
        "pkg/__init__.py": "",
        "pkg/alpha.py": 'X = "a"\n',
    })
    out = tmp_path / "out"
    minify(root, output=out, rename_modules=True, preserve_modules={"main"}, rename_globals=rename_globals)
    assert run_py("main.py", cwd=out).stdout == "5 a 2\n(1, 'a')\n"


def test_rename_globals_follows_function_level_imports(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "def f():\n    import pkg.alpha\n    return pkg.alpha.VALUE\nprint(f())\n",
        "pkg/__init__.py": "",
        "pkg/alpha.py": 'VALUE = "a"\n',
    })
    out = tmp_path / "out"
    minify(root, output=out, rename_globals=True)
    assert "VALUE=" not in read_tree(out)["pkg/alpha.py"]
    assert run_py("main.py", cwd=out).stdout == "a\n"


def test_type_checking_imports_are_not_dependencies(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from types_only import Alias\n"
                   "def f(x: 'Alias'):\n    return x\nprint(f(1))\n",
        "types_only.py": "Alias = int\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"}, rename_globals=True)
    assert set(read_tree(out)) == {"main.py"}
    assert run_py("main.py", cwd=out).stdout == "1\n"


def test_preserved_reexport_keeps_its_name(tmp_path):
    # `main.application` is renamed, `pkg.application` is preserved: `from .main import A as application`
    root = write_tree(tmp_path / "src", {
        "run.py": "from pkg import application\nprint(application())\n",
        "pkg/__init__.py": "from .main import application\n",
        "pkg/main.py": "def application():\n    return 'ok'\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, rename_globals=True, preserve_globals={"pkg": ["application"], "run": ["application"]})
    tree = read_tree(out)
    assert "def application" not in tree["pkg/main.py"]
    assert "as application" in tree["pkg/__init__.py"]
    assert run_py("run.py", cwd=out).stdout == "ok\n"


def test_keyword_parameter_alias(tmp_path):
    # a keyword-callable parameter keeps its name, and is aliased to a shorter one in the body
    source = (
        "def total(quantity, *, discount_percentage=0):\n"
        "    for _ in range(3):\n"
        "        quantity = quantity + discount_percentage + discount_percentage + discount_percentage\n"
        "    return quantity\n"
        "print(total(1, discount_percentage=2))\n"
    )
    root = write_tree(tmp_path / "src", {"main.py": source})
    expected = run_py("main.py", cwd=root).stdout
    out = tmp_path / "out"
    minify(root, output=out)
    minified = read_tree(out)["main.py"]
    assert "discount_percentage=0" in minified
    assert run_py("main.py", cwd=out).stdout == expected
