import zipfile

import pytest

from helpers import run_py, write_tree

PYPROJECT = """\
[build-system]
requires = ["hatchling", "py-terser"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "0.0.1"

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.hatch.build.targets.wheel.hooks.terser]
rename_globals = true
preserve_globals = { "*" = ["add_numbers"] }

[tool.hatch.build.targets.wheel.hooks.terser.config]
passes = 3
contracts = []

[tool.hatch.build.targets.wheel.hooks.terser.config.remove_annotations]
remove_return_annotations = false
"""

SOURCES = {
    "src/demo/__init__.py": "from demo.math import add_numbers\n\n__all__ = ['add_numbers']\n",
    "src/demo/math.py": (
        "def add_numbers(first_number: int, second_number: int) -> int:\n"
        "    result_value = first_number + second_number\n"
        "    return result_value\n"
    ),
}


@pytest.fixture
def wheel(tmp_path):
    project = write_tree(tmp_path / "demo", {"pyproject.toml": PYPROJECT, **SOURCES})
    result = run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=project)
    dist = project / "dist"
    return result, dist, next(dist.glob("*.whl"))


def test_wheel_sources_are_minified(wheel):
    _, _, path = wheel
    with zipfile.ZipFile(path) as whl:
        sources = {name: whl.read(name).decode() for name in whl.namelist() if name.endswith(".py")}

    assert set(sources) == {"demo/__init__.py", "demo/math.py"}
    for name, source in sources.items():
        assert len(source) < len(SOURCES["src/" + name])
    assert "result_value" not in sources["demo/math.py"]
    assert "def add_numbers(first_number,second_number)->" in sources["demo/math.py"]


def test_wheel_works(wheel, tmp_path):
    _, _, path = wheel
    code = "from demo import add_numbers; print(add_numbers(40, 2))"
    assert run_py("-c", code, env={"PYTHONPATH": str(path)}).stdout == "42\n"


def test_no_warnings(wheel):
    result, _, _ = wheel
    assert "Warning" not in result.stderr


def test_output_directory_is_clean(wheel):
    _, dist, path = wheel
    assert list(dist.iterdir()) == [path]
