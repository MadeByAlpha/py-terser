
import pytest

from helpers import minify_project, read_tree, run_py, write_tree
from terser.config import RemoveAnnotationOptions, TransformConfig

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


def test_entry_in_package_keeps_package_names(tmp_path):
    # `python -m app.main` (or `uvicorn app.main:app`) finds the entry by its whole dotted path
    root = write_tree(tmp_path / "src", {
        "app/__init__.py": "",
        "app/main.py": "from app.util import greet\nprint(greet())\n",
        "app/util.py": "def greet():\n    return 'hi'\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"app.main"}, rename_modules=True, rename_globals=True)

    tree = read_tree(out)
    assert "app/main.py" in tree
    assert "app/util.py" not in tree
    assert run_py("-m", "app.main", cwd=out).stdout == "hi\n"


def test_entry_tree_shaking_through_namespace_package(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "from ns.lib import VALUE\nprint(VALUE)\n",
        "ns/lib/__init__.py": "from .data import VALUE\n",
        "ns/lib/data.py": "VALUE = 3\n",
        "ns/other.py": "UNUSED = 4\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"})

    assert set(read_tree(out)) == {"main.py", "ns/lib/__init__.py", "ns/lib/data.py"}
    assert run_py("main.py", cwd=out).stdout == "3\n"


def test_annotation_readers_across_modules(tmp_path):
    # `Item` is a pydantic model through a base class of another module: its fields are annotations
    root = write_tree(tmp_path / "src", {
        "main.py": "from models.item import Item\nprint(Item(name='a', price='3'))\n",
        "models/__init__.py": "from .base import Base\n",
        "models/base.py": "from pydantic import BaseModel\nclass Base(BaseModel):\n    pass\n",
        "models/item.py": "from models import Base\nclass Item(Base):\n    name: str\n    price: int\n",
    })
    out = tmp_path / "out"
    config = TransformConfig(remove_annotations=RemoveAnnotationOptions(remove_attribute_annotations=True))
    minify(root, output=out, config=config, entry={"main"}, rename_globals=True, rename_modules=True)
    assert run_py("main.py", cwd=out).stdout == "name='a' price=3\n"


LAZY = {
    "main.py": "import lazy\nprint(lazy.greeting, lazy.farewell)\n",
    "lazy/__init__.py": """\
from typing import TYPE_CHECKING

from ._importer import install

if TYPE_CHECKING or not install():
    from ._impl import greeting as greeting
    from ._impl import farewell as farewell
    ALIASES = {"hello": "greeting", "hi": "greeting", "bye": "farewell", "later": "farewell"}
""",
    # like anyio's: reads the imports `TYPE_CHECKING` guards back from the source
    "lazy/_importer.py": """\
import ast
import inspect
import sys
from importlib import import_module


def install():
    module_globals = sys._getframe(1).f_globals
    module = sys.modules[module_globals["__name__"]]
    lazy = {}
    for node in ast.parse(inspect.getsource(module)).body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp) and getattr(node.test.values[0], "id", None) == "TYPE_CHECKING":
            for stmt in node.body:
                if isinstance(stmt, ast.ImportFrom):
                    for alias in stmt.names:
                        lazy[alias.asname or alias.name] = ("." * stmt.level + stmt.module, alias.name)
                else:
                    if not all(isinstance(key, ast.Constant) for key in (*stmt.value.keys, *stmt.value.values)):
                        raise TypeError("not a literal")
    del module_globals["TYPE_CHECKING"]

    def __getattr__(name):
        module_name, attr = lazy[name]
        return getattr(import_module(module_name, module_globals["__name__"]), attr)

    module_globals["__getattr__"] = __getattr__
    return True
""",
    "lazy/_impl.py": "greeting = 'hello'\nfarewell = 'bye'\n",
}


@pytest.mark.parametrize("options", [{}, {"rename_globals": True, "rename_modules": True}])
def test_preserve_type_checking_for_a_lazy_importer(tmp_path, options):
    root = write_tree(tmp_path / "src", LAZY)
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"}, preserve_type_checking={"lazy"}, **options)
    assert run_py("main.py", cwd=out).stdout == "hello bye\n"


def test_package_global_and_submodule_names_stay_apart(tmp_path):
    # importing `pkg.sub` sets `pkg.sub`: a global of `pkg` renamed to the same name would be replaced
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nimport pkg.sub\nprint(pkg.VALUE, pkg.sub.X)\n",
        "pkg/__init__.py": "VALUE = 'v'\n",
        "pkg/sub.py": "X = 1\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"}, rename_globals=True, rename_modules=True)
    assert run_py("main.py", cwd=out).stdout == "v 1\n"


def test_protocol_subclassed_in_another_module(tmp_path):
    root = write_tree(tmp_path / "src", {
        "main.py": "from handlers import Handler\nprint(Handler.__name__)\n",
        "base.py": "from typing import Protocol\nclass Base(Protocol):\n    def __call__(self): ...\n",
        "handlers.py": "from typing import Protocol, TypeVar\nfrom base import Base\nT = TypeVar('T')\nclass Handler(Base, Protocol[T]):\n    pass\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, config=TransformConfig(remove_typing_classes=True), entry={"main"})
    assert run_py("main.py", cwd=out).stdout == "Handler\n"


def test_entry_tree_shaking_keeps_wildcard_imports(tmp_path):
    # `httpx` re-exports `from ._api import *`, and `main` only reads what `pkg` re-exports
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nprint(pkg.get())\n",
        "pkg/__init__.py": "from ._api import *\nfrom ._other import *\n",
        "pkg/_api.py": "__all__ = ['get']\ndef get():\n    return 'got'\n",
        "pkg/_other.py": "import sys\nsys.modules['pkg'].SIDE = 1\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"})
    assert set(read_tree(out)) == {"main.py", "pkg/__init__.py", "pkg/_api.py", "pkg/_other.py"}
    assert run_py("main.py", cwd=out).stdout == "got\n"


def test_respect_all_keeps_what_other_modules_import(tmp_path):
    # without `__all__`, `Cython` re-exports `from .Shadow import __version__` for `cython.py`
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nfrom pkg import __version__\nprint(__version__, pkg.helper())\n",
        "pkg/__init__.py": "from .shadow import __version__\nfrom .shadow import helper\nimport os\n",
        "pkg/shadow.py": "__version__ = '3.3'\ndef helper():\n    return 'h'\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, config=TransformConfig(respect_all=True), entry={"main"})
    assert "os" not in read_tree(out)["pkg/__init__.py"]
    assert run_py("main.py", cwd=out).stdout == "3.3 h\n"


def test_entry_tree_shaking_follows_native_extensions(tmp_path):
    # numpy's `_multiarray_umath` imports `numpy._core._exceptions` from C: its name is in the binary
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\n",
        "pkg/__init__.py": "from . import _native\n",
        "pkg/_errors.py": "class Error(Exception):\n    pass\n",
        "pkg/_unused.py": "X = 1\n",
    })
    (root / "pkg" / "_native.cpython-314-x86_64-linux-gnu.so").write_bytes(b"\x7fELF\x00pkg._errors\x00PyInit__native\x00")
    out = tmp_path / "out"
    minify(root, output=out, entry={"main"})
    assert set(read_tree(out)) >= {"main.py", "pkg/__init__.py", "pkg/_errors.py"}
    assert "pkg/_unused.py" not in read_tree(out)


def test_typed_dict_imported_by_another_module(tmp_path):
    # `pydantic.networks` imports `MultiHostHost`, a TypedDict `pydantic_core` itself never uses
    root = write_tree(tmp_path / "src", {
        "main.py": "from core import Host\nprint(Host.__name__)\n",
        # not in `__all__`, like `MultiHostHost`
        "core.py": "from typing import TypedDict\n__all__ = ['Url']\nUrl = str\nclass Host(TypedDict):\n    name: str\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, config=TransformConfig(convert_typing_constructors=True), entry={"main"})
    assert run_py("main.py", cwd=out).stdout == "Host\n"


def test_respect_all_keeps_what_other_modules_read_by_name(tmp_path):
    # numpy's `_core/__init__.py` checks `hasattr(multiarray, "_multiarray_umath")`
    root = write_tree(tmp_path / "src", {
        "main.py": "import pkg\nprint(pkg.OK)\n",
        "pkg/__init__.py": "from . import multiarray\nOK = hasattr(multiarray, '_impl') and getattr(multiarray, 'helper')()\n",
        "pkg/multiarray.py": "__all__ = []\nfrom . import _impl\nfrom ._impl import helper\n",
        "pkg/_impl.py": "def helper():\n    return 'ok'\n",
    })
    out = tmp_path / "out"
    minify(root, output=out, config=TransformConfig(respect_all=True), entry={"main"})
    assert run_py("main.py", cwd=out).stdout == "ok\n"
