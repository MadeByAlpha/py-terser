import base64
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
from hatchling.metadata.core import ProjectMetadata
from hatchling.plugin.manager import PluginManager
from helpers import RecordingReporter, run_py, write_tree

from terser.hatch import TerserBuildHook

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


def test_progress_is_shown(wheel):
    result, _, _ = wheel
    assert "terser: Compiling modules: 100%" in result.stderr
    assert "terser: Writing output: 100%" in result.stderr


def test_output_directory_is_clean(wheel):
    _, dist, path = wheel
    assert list(dist.iterdir()) == [path]


# `rollup` (rollup-py) adds vendored packages from its own hook, which always runs after this one's
# `initialize()`; they are emulated here with `force-include`, and the hook is run on the built wheel
# the way that target runs it.
ROLLUP_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "0.0.1"

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.hatch.build.targets.wheel.force-include]
"vendor/helper" = "helper"

[tool.hatch.build.targets.wheel.shared-scripts]
"scripts/tool.py" = "tool.py"
"""

ROLLUP_SOURCES = {
    "src/demo/__init__.py": "from demo.math import add_numbers\n\n__all__ = ['add_numbers']\n",
    "src/demo/math.py": (
        "from helper import double_it\n\n\n"
        "def add_numbers(first_number, second_number):\n"
        "    result_value = double_it(first_number) + second_number\n"
        "    return result_value\n"
    ),
    "vendor/helper/__init__.py": (
        "def double_it(some_number):\n"
        "    doubled_number = some_number * 2\n"
        "    return doubled_number\n"
    ),
    "vendor/helper/data.txt": "keep   me\n",
    "scripts/tool.py": "some_script_variable = 1\n",
}


def _record_is_valid(whl: zipfile.ZipFile) -> bool:
    [record] = [name for name in whl.namelist() if name.endswith(".dist-info/RECORD")]
    rows = {row[0]: row[1:] for row in csv.reader(io.StringIO(whl.read(record).decode()))}
    if set(rows) != set(whl.namelist()):
        return False

    for name, (digest, size) in rows.items():
        if name == record:
            continue
        data = whl.read(name)
        expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if digest != f"sha256={expected}" or int(size) != len(data):
            return False
    return True


def _build_rollup(tmp_path, config=None):
    project = write_tree(tmp_path / "demo", {"pyproject.toml": ROLLUP_PYPROJECT, **ROLLUP_SOURCES})
    run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=project)
    dist = project / "dist"
    path = next(dist.glob("*.whl"))

    metadata = ProjectMetadata(str(project), PluginManager())
    hook = TerserBuildHook(str(project), config or {}, None, metadata, str(dist), "rollup")
    build_data = {}
    hook.initialize("standard", build_data)
    assert build_data == {}  # nothing to do before the vendored files exist
    hook.finalize("standard", build_data, str(path))
    return dist, path


@pytest.fixture
def rollup_wheel(tmp_path):
    return _build_rollup(tmp_path)


def test_rollup_vendored_sources_are_minified(rollup_wheel):
    _, path = rollup_wheel
    with zipfile.ZipFile(path) as whl:
        sources = {name: whl.read(name).decode() for name in whl.namelist() if name.endswith(".py")}

    assert "result_value" not in sources["demo/math.py"]
    assert "doubled_number" not in sources["helper/__init__.py"]
    assert len(sources["helper/__init__.py"]) < len(ROLLUP_SOURCES["vendor/helper/__init__.py"])


def test_rollup_other_files_are_untouched(rollup_wheel):
    _, path = rollup_wheel
    with zipfile.ZipFile(path) as whl:
        assert whl.read("helper/data.txt").decode() == ROLLUP_SOURCES["vendor/helper/data.txt"]
        [script] = [name for name in whl.namelist() if name.endswith(".data/scripts/tool.py")]
        assert whl.read(script).decode() == ROLLUP_SOURCES["scripts/tool.py"]


def test_rollup_record_is_valid(rollup_wheel):
    _, path = rollup_wheel
    with zipfile.ZipFile(path) as whl:
        assert whl.testzip() is None
        assert _record_is_valid(whl)
        assert whl.namelist()[-1].endswith(".dist-info/RECORD")


def test_rollup_wheel_works(rollup_wheel):
    _, path = rollup_wheel
    code = "from demo import add_numbers; print(add_numbers(20, 2))"
    assert run_py("-c", code, env={"PYTHONPATH": str(path)}).stdout == "42\n"


def test_rollup_output_directory_is_clean(rollup_wheel):
    dist, path = rollup_wheel
    assert list(dist.iterdir()) == [path]


def test_rollup_progress_is_shown(tmp_path, capsys):
    _build_rollup(tmp_path)
    stderr = capsys.readouterr().err
    for stage in ("Extracting wheel", "Compiling modules", "Writing output", "Rewriting wheel"):
        assert f"terser: {stage}: 100%" in stderr


def test_rollup_progress_is_quiet(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HATCH_QUIET", "1")
    _build_rollup(tmp_path)
    assert "terser:" not in capsys.readouterr().err


def test_rollup_progress_without_tqdm(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "tqdm", None)
    monkeypatch.delenv("CI", raising=False)
    _build_rollup(tmp_path)
    lines = capsys.readouterr().err.splitlines()

    [warning] = [line for line in lines if "tqdm is not installed" in line]
    assert "`[build-system].requires`" in warning
    stages = [line for line in lines if line.startswith("terser: ") and line != warning]
    assert stages[0] == "terser: Extracting wheel"
    assert "terser: Compiling modules" in stages
    assert stages[-1] == "terser: Rewriting wheel"


def test_rollup_progress_without_tqdm_in_ci(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "tqdm", None)
    monkeypatch.setenv("CI", "true")
    _build_rollup(tmp_path)
    stderr = capsys.readouterr().err

    assert "tqdm is not installed" not in stderr
    assert "terser: Compiling modules: started (3 total)" in stderr
    assert "terser: Rewriting wheel: done " in stderr


def test_rollup_plans_every_stage(tmp_path, monkeypatch):
    import terser.hatch

    reporter = RecordingReporter()
    monkeypatch.setattr(terser.hatch, "auto_reporter", lambda *args, **kwargs: reporter)
    _build_rollup(tmp_path)

    assert reporter.planned == len(reporter.stages) == 11
    assert reporter.stages[0].name == "Extracting wheel"
    assert reporter.stages[-1].name == "Rewriting wheel"


def _capture_workers(monkeypatch):
    import terser.hatch
    from terser.project import ProjectMinifier

    seen = []
    real_init = ProjectMinifier.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        # the limiter decides how many modules are compiled at once
        seen.append((kwargs.get("workers"), self._ProjectMinifier__limiter.total_tokens))

    monkeypatch.setattr(ProjectMinifier, "__init__", init)
    monkeypatch.setattr(terser.hatch, "auto_reporter", lambda *args, **kwargs: RecordingReporter())
    return seen


def test_workers_option(tmp_path, monkeypatch):
    seen = _capture_workers(monkeypatch)
    _build_rollup(tmp_path, {"workers": 2})
    assert seen == [(2, 2)]


def test_workers_default(tmp_path, monkeypatch):
    seen = _capture_workers(monkeypatch)
    _build_rollup(tmp_path)
    [(workers, tokens)] = seen
    assert workers is None and tokens >= 1


@pytest.mark.parametrize("workers", [0, -1, "2", True, 1.5])
def test_workers_must_be_positive_integer(tmp_path, monkeypatch, workers):
    _capture_workers(monkeypatch)
    with pytest.raises(ValueError, match="`workers` must be a positive integer"):
        _build_rollup(tmp_path, {"workers": workers})


def _with_workers(workers):
    table = "[tool.hatch.build.targets.wheel.hooks.terser]\n"
    assert PYPROJECT.count(table) == 1
    return PYPROJECT.replace(table, f"{table}workers = {workers}\n")


def test_wheel_workers_option(tmp_path):
    project = write_tree(tmp_path / "demo", {"pyproject.toml": _with_workers(1), **SOURCES})
    run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=project)
    assert next((project / "dist").glob("*.whl"))

    bad = write_tree(tmp_path / "bad", {"pyproject.toml": _with_workers(0), **SOURCES})
    result = run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=bad, check=False)
    assert result.returncode != 0
    assert "`workers` must be a positive integer, got 0" in result.stderr


MODULES_PYPROJECT = """\
[build-system]
requires = ["hatchling", "py-terser"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "0.0.1"

[project.scripts]
demo-cli = "demo.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.hatch.build.targets.wheel.hooks.terser]
"""

MODULES_SOURCES = {
    "src/demo/__init__.py": "from demo.math import add_numbers\n",
    "src/demo/math.py": (
        "from demo.sub import scale\n\n\n"
        "def add_numbers(first_number, second_number):\n"
        "    return scale(first_number) + second_number\n"
    ),
    "src/demo/sub/__init__.py": "def scale(some_number):\n    return some_number * 2\n",
    "src/demo/sub/data.txt": "some data\n",
    "src/demo/unused.py": "def never_called():\n    return 'unused'\n",
    "src/demo/cli.py": "def main():\n    print('cli')\n",
}


def _build_modules_wheel(tmp_path, options, check=True):
    project = write_tree(tmp_path / "demo", {"pyproject.toml": MODULES_PYPROJECT + options, **MODULES_SOURCES})
    result = run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=project, check=check)
    wheels = list((project / "dist").glob("*.whl"))
    return result, (wheels[0] if wheels else None)


def _package_files(path):
    with zipfile.ZipFile(path) as whl:
        assert _record_is_valid(whl)
        return {name for name in whl.namelist() if name.startswith("demo/")}


def _run_demo(path, code="from demo import add_numbers; print(add_numbers(20, 2))"):
    return run_py("-c", code, env={"PYTHONPATH": str(path)}).stdout


def test_wheel_rename_modules(tmp_path):
    _, path = _build_modules_wheel(tmp_path, 'rename_modules = true\npreserve_modules = ["demo"]\n')
    files = _package_files(path)

    assert "demo/__init__.py" in files
    assert not {"demo/math.py", "demo/sub/__init__.py", "demo/unused.py"} & files
    # the data file went along with its renamed package
    [data] = [name for name in files if name.endswith("/data.txt")]
    assert data != "demo/sub/data.txt"
    assert data.rpartition("/")[0] + "/__init__.py" in files
    assert _run_demo(path) == "42\n"


def test_wheel_rename_modules_keeps_entry_points(tmp_path):
    _, path = _build_modules_wheel(tmp_path, "rename_modules = true\n")
    files = _package_files(path)

    # `demo.cli:main` is a console script: it and its package keep their names
    assert {"demo/__init__.py", "demo/cli.py"} <= files
    assert "demo/math.py" not in files
    assert _run_demo(path, "from demo.cli import main; main()") == "cli\n"


@pytest.mark.parametrize("entry", ["demo", "src/demo/__init__.py"])
def test_wheel_entry_drops_unreachable_modules(tmp_path, entry):
    _, path = _build_modules_wheel(tmp_path, f'entry = ["{entry}"]\n')
    files = _package_files(path)

    assert "demo/unused.py" not in files
    # a console script is an entry point of its own
    assert {"demo/__init__.py", "demo/math.py", "demo/sub/__init__.py", "demo/sub/data.txt", "demo/cli.py"} <= files
    assert _run_demo(path) == "42\n"


def test_wheel_entry_must_be_in_the_build(tmp_path):
    result, _ = _build_modules_wheel(tmp_path, 'entry = ["demo.missing"]\n', check=False)
    assert result.returncode != 0
    assert "entry `demo.missing` is neither a module nor a module file of the build" in result.stderr


@pytest.mark.parametrize(("option", "value", "expected"), [
    ("rename_modules", '"yes"', "a boolean"),
    ("preserve_modules", '"demo"', "a list of strings"),
    ("entry", "[1]", "a list of strings"),
])
def test_wheel_module_options_are_checked(tmp_path, option, value, expected):
    result, _ = _build_modules_wheel(tmp_path, f"{option} = {value}\n", check=False)
    assert result.returncode != 0
    assert f"`{option}` must be {expected}" in result.stderr


@pytest.fixture
def extra_rollup_sources(monkeypatch):
    def add(files):
        monkeypatch.setattr(sys.modules[__name__], "ROLLUP_SOURCES", {**ROLLUP_SOURCES, **files})
    return add


# an extension module next to the source it was compiled from, the way mypyc builds ship them
FFI = {
    "vendor/helper/fast.py": "def fast_path(some_value):\n    result_value = some_value\n    return result_value\n",
    "vendor/helper/fast.cpython-314-x86_64-linux-gnu.so": "not really a binary\n",
}


def test_rollup_source_next_to_extension_is_minified(tmp_path, extra_rollup_sources, monkeypatch):
    extra_rollup_sources(FFI)

    # which of the two took the module's name would come down to the order the files are listed in
    minified_files = []
    real_minify = TerserBuildHook._minify

    def minify(self, roots, *args):
        minified_files.extend(p.name for root in roots for p in Path(root).rglob("*") if p.is_file())
        return real_minify(self, roots, *args)

    monkeypatch.setattr(TerserBuildHook, "_minify", minify)
    _, path = _build_rollup(tmp_path)
    assert "fast.py" in minified_files
    assert not [name for name in minified_files if name.endswith(".so")]

    with zipfile.ZipFile(path) as whl:
        assert _record_is_valid(whl)
        assert "result_value" not in whl.read("helper/fast.py").decode()
        assert whl.read("helper/fast.cpython-314-x86_64-linux-gnu.so").decode() == "not really a binary\n"


def test_rollup_rename_modules_and_entry(tmp_path, extra_rollup_sources):
    extra_rollup_sources({"vendor/helper/unused.py": "def never_called():\n    return 'unused'\n", **FFI})
    dist, path = _build_rollup(tmp_path, {"rename_modules": True, "entry": ["demo"]})

    with zipfile.ZipFile(path) as whl:
        assert _record_is_valid(whl)
        names = set(whl.namelist())

    assert "demo/__init__.py" in names  # an entry module keeps its name
    assert not {"demo/math.py", "helper/__init__.py", "helper/unused.py"} & names
    # files other than modules went along with the renamed package
    [data] = [name for name in names if name.endswith("/data.txt")]
    [binary] = [name for name in names if name.endswith(".so")]
    assert data.rpartition("/")[0] == binary.rpartition("/")[0] != "helper"
    assert len([name for name in names if name.endswith(".py") and ".data/" not in name]) == 3
    assert run_py("-c", "from demo import add_numbers; print(add_numbers(20, 2))",
                  env={"PYTHONPATH": str(path)}).stdout == "42\n"
    assert list(dist.iterdir()) == [path]
