from functools import partial

import anyio
import pytest

from helpers import read_tree, run_py, write_tree
from terser import TransformConfig, minify_project

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
    anyio.run(partial(
        minify_project,
        config or TransformConfig(),
        {str(p) for p in paths},
        output=anyio.Path(output) if output else None,
        **kwargs,
    ))


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


@pytest.mark.xfail(strict=True, reason="a package directory given directly names its __init__ '__init__'")
def test_multiple_paths(app, tmp_path):
    out = tmp_path / "out"
    minify(app / "main.py", app / "shop", output=out)
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


def test_multiple_paths_require_output(app):
    with pytest.raises(ValueError):
        minify(app / "main.py", app / "shop")


@pytest.mark.xfail(strict=True, reason="a package directory given directly names its __init__ '__init__'")
def test_package_directory(app, tmp_path):
    out = tmp_path / "out"
    minify(app / "shop", output=out / "shop")

    tree = read_tree(out)
    assert set(tree) == {path for path in APP if path.startswith("shop/")}
    # the package keeps its name, so the unminified main.py still finds it
    (out / "main.py").write_text(APP["main.py"])
    assert run_py("main.py", cwd=out).stdout == EXPECTED_OUTPUT


@pytest.mark.xfail(strict=True, reason="a package directory given directly names its __init__ '__init__'")
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
