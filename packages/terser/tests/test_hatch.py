import base64
import csv
import hashlib
import io
import sys
import zipfile

import pytest
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


def _build_rollup(tmp_path):
    project = write_tree(tmp_path / "demo", {"pyproject.toml": ROLLUP_PYPROJECT, **ROLLUP_SOURCES})
    run_py("-m", "hatchling", "build", "-t", "wheel", "-d", "dist", cwd=project)
    dist = project / "dist"
    path = next(dist.glob("*.whl"))

    hook = TerserBuildHook(str(project), {}, None, None, str(dist), "rollup")
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
