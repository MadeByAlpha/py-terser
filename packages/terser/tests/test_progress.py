import io
import threading
from functools import partial

import anyio
import pytest
from helpers import write_tree

from alpha93.progression import NullReporter, Reporter, Stage, TqdmReporter
from terser import TransformConfig, minify_project

PROJECT = {
    "pkg/__init__.py": "from pkg.util import twice\n",
    "pkg/util.py": "def twice(some_value):\n    doubled_value = some_value * 2\n    return doubled_value\n",
    "main.py": "from pkg import twice\nprint(twice(21))\n",
}


class RecordingReporter(Reporter):
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


def test_project_reports_every_stage(tmp_path):
    root = write_tree(tmp_path / "src", PROJECT)
    reporter = RecordingReporter()
    anyio.run(partial(minify_project, TransformConfig(), {str(root)}, reporter, anyio.Path(tmp_path / "out")))

    assert [stage.name for stage in reporter.stages] == [
        "Resolving paths",
        "Compiling modules",
        "Linking",
        "Tree-shaking",
        "Mangling modules",
        "Applying transforms",
        "Mangling globals",
        "Applying transforms after mangling",
        "Writing output",
    ]
    assert all(stage.completed for stage in reporter.stages)

    counted = {stage.name: stage for stage in reporter.stages if stage.total is not None}
    for name in ("Compiling modules", "Linking", "Applying transforms after mangling", "Writing output"):
        assert counted[name].done == counted[name].total == len(PROJECT)

    # stops once a pass changes nothing, well before `passes` passes
    transforms = counted["Applying transforms"]
    assert 0 < transforms.done < transforms.total


def test_project_does_not_close_reporter(tmp_path):
    class Closing(RecordingReporter):
        closed = False

        def close(self):
            self.closed = True

    root = write_tree(tmp_path / "src", PROJECT)
    reporter = Closing()
    anyio.run(partial(minify_project, TransformConfig(), {str(root)}, reporter, anyio.Path(tmp_path / "out")))
    assert not reporter.closed


def test_null_reporter():
    with NullReporter() as reporter, reporter.stage("stage", 3) as stage:
        assert list(stage.iter("abc")) == ["a", "b", "c"]


def test_tqdm_stages_are_kept():
    out = io.StringIO()
    with TqdmReporter("tool: ", file=out) as reporter:
        with reporter.stage("Counting", 3) as stage:
            for _ in stage.iter(range(3)):
                pass
        with reporter.stage("Waiting"):
            pass

    # not a terminal: a stage done quickly only leaves its final line
    lines = [line for line in out.getvalue().replace("\r", "\n").splitlines() if line]
    assert len(lines) == 2
    assert lines[0].startswith("tool: Counting: 100%") and "3/3" in lines[0]
    assert lines[1].startswith("tool: Waiting [")


def test_tqdm_draws_at_once_on_terminal():
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    out = Terminal()
    with TqdmReporter(file=out) as reporter, reporter.stage("Counting", 3):
        assert "Counting:   0%" in out.getvalue()


def test_tqdm_stage_finished_early_is_complete():
    out = io.StringIO()
    with TqdmReporter(file=out) as reporter, reporter.stage("Passes", 10) as stage:
        for i in stage.iter(range(10)):
            if i == 3:
                break

    last = out.getvalue().replace("\r", "\n").splitlines()[-1]
    assert "100%" in last and "3/3" in last


def test_tqdm_failed_stage_stays_where_it_stopped():
    out = io.StringIO()
    with pytest.raises(ValueError), TqdmReporter(file=out) as reporter, reporter.stage("Failing", 4) as stage:
        stage.advance()
        raise ValueError

    last = out.getvalue().replace("\r", "\n").splitlines()[-1]
    assert "1/4" in last


def test_tqdm_advance_is_thread_safe():
    out = io.StringIO()
    with TqdmReporter(file=out) as reporter, reporter.stage("Threads", 8000) as stage:
        threads = [threading.Thread(target=lambda: [stage.advance() for _ in range(1000)]) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert "8000/8000" in out.getvalue().replace("\r", "\n").splitlines()[-1]


def test_tqdm_draws_on_unsized_terminal():
    pty = pytest.importorskip("pty")
    import os
    import select

    master, slave = pty.openpty()  # a fresh pty reports 0 columns and 0 rows
    try:
        with (
            open(slave, "w", closefd=False) as out,
            TqdmReporter(file=out) as reporter,
            reporter.stage("Counting", 3) as stage,
        ):
            stage.advance(3)

        drawn = b""
        while select.select([master], [], [], 0.1)[0]:
            drawn += os.read(master, 65536)
    finally:
        os.close(master)
        os.close(slave)

    assert "Counting: 100%" in drawn.decode()
