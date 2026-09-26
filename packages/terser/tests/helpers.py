import ast
import dataclasses
import os
import subprocess
import sys
import threading
from pathlib import Path

import terser
from alpha93.progression import Reporter, Stage
from terser._minify import unparse
from terser._pipeline import parser, resolver
from terser.ast import CompareError, compare_ast
from terser.ast.ref._module._spec import SingleFileModuleSpec
from terser.config import TransformConfig
from terser.exceptions import UnbeneficialMinificationError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# TransformConfig fields that toggle a transform (everything that isn't a tuning knob)
_TOGGLES = frozenset(
    f.name for f in dataclasses.fields(TransformConfig)
    if f.name not in {"passes", "optimize", "contracts"}
)


def only(*enabled: str, **overrides) -> TransformConfig:
    """A config with every transform disabled except `enabled`."""

    unknown = set(enabled) - _TOGGLES
    assert not unknown, f"unknown transform option(s): {unknown}"

    values = {name: name in enabled for name in _TOGGLES}
    values.update(overrides)
    return TransformConfig(**values)


def apply_transform(source: str, transform: type, config: TransformConfig | None = None) -> ast.Module:
    """
    Run a single transform on `source` the way `_minify.minify` does: pre-transforms (FLAGS == 0)
    before name resolution, the others after it.
    """

    config = config or TransformConfig()
    module = parser.parse(source, SingleFileModuleSpec(Path("test_module.py")))

    if transform.FLAGS == 0:
        module = transform(config)(module)

    resolver.resolve(module)
    resolver.bind(module)

    if transform.FLAGS != 0:
        module = transform(config)(module)

    return module


def assert_code(actual: str | ast.AST, expected: str):
    """Assert that `actual` (source or AST) parses into the same AST as `expected`."""

    actual_ast = ast.parse(actual) if isinstance(actual, str) else actual
    try:
        compare_ast(ast.parse(expected), actual_ast)
    except CompareError:
        printed = actual if isinstance(actual, str) else unparse("<test>", None, actual_ast)
        print("Actual code:\n" + printed, file=sys.stderr)
        raise


def minify_src(source: str, config: TransformConfig | None = None, path: str = "test_module.py", /, **kwargs) -> str:
    """`terser.minify`, returning the source unchanged when minifying doesn't make it smaller."""

    try:
        return terser.minify(source, config or TransformConfig(), path, **kwargs)
    except UnbeneficialMinificationError:
        return source


def run_py(*args: str | os.PathLike, cwd: str | os.PathLike | None = None, stdin: str | None = None,
           env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run the current interpreter in a subprocess."""

    result = subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
        check=False,  # checked below, with the output in the message
    )
    if check and result.returncode:
        raise AssertionError(
            f"exit code {result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return result


def run_terser(*args: str | os.PathLike, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run the `terser` CLI (`python -m terser`) in a subprocess."""

    return run_py("-m", "terser", *args, **kwargs)


def write_tree(root: Path, files: dict[str, str]) -> Path:
    """Write `{relative path: source}` under `root`."""

    for relpath, source in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def read_tree(root: Path) -> dict[str, str]:
    """`{relative posix path: source}` of every file under `root`."""

    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


class RecordingReporter(Reporter):
    """Records every stage it is given, and how far each got."""

    def __init__(self):
        self.stages = []

    def stage(self, name, total=None, /):
        stage = RecordingStage(name, total)
        self.stages.append(stage)
        return stage


class RecordingStage(Stage):
    def __init__(self, name, total):
        super().__init__(name, total)
        self.done = 0
        self.completed = None
        self.__lock = threading.Lock()

    def advance(self, n=1, /):
        with self.__lock:
            self.done += n

    def _close(self, completed, /):
        self.completed = completed
