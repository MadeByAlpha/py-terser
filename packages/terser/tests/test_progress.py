import io
import re
import sys
import threading
import time

import pytest
from helpers import RecordingReporter, minify_project, write_tree

from alpha93.progression import (
    LogReporter,
    NullReporter,
    TqdmReporter,
    auto_reporter,
    in_ci,
)
from terser.project import ProjectMinifier

PROJECT = {
    "pkg/__init__.py": "from pkg.util import twice\n",
    "pkg/util.py": "def twice(some_value):\n    doubled_value = some_value * 2\n    return doubled_value\n",
    "main.py": "from pkg import twice\nprint(twice(21))\n",
}


def test_project_reports_every_stage(tmp_path):
    root = write_tree(tmp_path / "src", PROJECT)
    reporter = RecordingReporter()
    minify_project(root, tmp_path / "out", reporter)

    assert reporter.planned == ProjectMinifier.STAGES == len(reporter.stages)
    assert [stage.name for stage in reporter.stages] == [
        "Compiling modules",
        "Linking",
        "Applying transforms",
        "Mangling globals",
        "Mangling modules",
        "Finalizing",
        "Writing output",
    ]
    assert all(stage.completed for stage in reporter.stages)

    counted = {stage.name: stage for stage in reporter.stages if stage.total is not None}
    for name in ("Compiling modules", "Linking", "Finalizing", "Writing output"):
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
    minify_project(root, tmp_path / "out", reporter)
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


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def terminal(monkeypatch):
    # rich draws nothing until the end on a terminal it takes for a dumb one
    monkeypatch.setenv("TERM", "xterm")
    return Terminal()


def _lines(out):
    """Every line drawn, without escape sequences (e.g. colors, or the cursor moving to redraw)."""
    return re.split(r"[\r\n]", re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.getvalue()))


def _drawn(out, pattern):
    return any(re.match(pattern, line) for line in _lines(out))


def test_stage_item_counts_even_when_failed():
    stage = RecordingReporter().stage("Items", 2)
    with stage.item("a"):
        pass
    with pytest.raises(RuntimeError, match="^Items failed while processing b$") as info, stage.item("b"):
        raise ValueError
    assert isinstance(info.value.__cause__, ValueError)
    assert stage.done == 2


def test_tqdm_draws_at_once_on_terminal(terminal):
    with TqdmReporter(file=terminal) as reporter, reporter.stage("Counting", 3):
        assert _drawn(terminal, r"Counting +0% .* 0/3 ")


def test_tqdm_terminal_shows_items(terminal):
    with TqdmReporter("tool: ", file=terminal) as reporter, reporter.stage("Compiling", 3) as stage:
        with stage.item("pkg.a"), stage.item("pkg.b"):
            assert _drawn(terminal, r"tool: 2 in progress: pkg\.a, pkg\.b *$")
        with stage.item("pkg.c"):
            assert _drawn(terminal, r"tool: 1 in progress: pkg\.c *$")
        # counted once done
        assert stage._TqdmStage__bar.n == 3

    # not left behind
    assert "in progress" not in terminal.getvalue().rsplit("\n", 1)[-1]


def test_tqdm_terminal_warns_above_bars(terminal):
    with (
        TqdmReporter("tool: ", file=terminal) as reporter,
        reporter.stage("Compiling", 2) as stage,
        stage.item("pkg.a"),
    ):
        reporter.warn("something odd")
        assert _drawn(terminal, r"tool: warning: something odd$")
        # the bars and the line of items, drawn again below it
        after = terminal.getvalue().rsplit("something odd", 1)[1]
        assert "Compiling" in after and "1 in progress: pkg.a" in after


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
    with pytest.raises(RuntimeError), TqdmReporter(file=out) as reporter, reporter.stage("Failing", 4) as stage:
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

    assert "Counting" in drawn.decode()


@pytest.fixture
def no_tqdm(monkeypatch):
    monkeypatch.setitem(sys.modules, "tqdm", None)  # makes `import tqdm` raise ImportError


@pytest.mark.parametrize(("value", "expected"), [
    (None, False), ("", False), ("0", False), ("false", False), ("False", False), ("no", False),
    ("true", True), ("1", True), ("yes", True),
])
def test_in_ci(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", value)
    assert in_ci() is expected


def test_auto_reporter_uses_tqdm():
    assert isinstance(auto_reporter(file=io.StringIO()), TqdmReporter)


def test_auto_reporter_without_tqdm_in_ci(no_tqdm, monkeypatch):
    monkeypatch.setenv("CI", "true")
    out, warnings = io.StringIO(), []
    with auto_reporter("tool: ", file=out, warn=warnings.append) as reporter, reporter.stage("Counting", 2) as stage:
        stage.advance(2)

    assert isinstance(reporter, LogReporter)
    assert warnings == []
    lines = out.getvalue().splitlines()
    assert lines[0] == "tool: Counting: started (2 total)"
    assert lines[-1].startswith("tool: Counting: done 2/2 in ")


def test_auto_reporter_without_tqdm_outside_ci(no_tqdm, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    out, warnings = io.StringIO(), []
    with auto_reporter("tool: ", file=out, warn=warnings.append) as reporter:
        with reporter.stage("Counting", 3) as stage:
            stage.advance(3)
        with reporter.stage("Waiting"):
            pass

    assert warnings == ["tqdm or rich is not installed, so only the stages are shown, not their progress"]
    assert out.getvalue() == "tool: Counting\ntool: Waiting\n"


def test_auto_reporter_without_rich(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setitem(sys.modules, "rich", None)
    monkeypatch.setitem(sys.modules, "tqdm.rich", None)
    warnings = []
    assert isinstance(auto_reporter(file=io.StringIO(), warn=warnings.append), LogReporter)
    assert warnings == ["tqdm or rich is not installed, so only the stages are shown, not their progress"]


def test_auto_reporter_warns_on_file_by_default(no_tqdm, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    out = io.StringIO()
    auto_reporter("tool: ", file=out)
    assert out.getvalue() == "tool: warning: tqdm or rich is not installed, so only the stages are shown, not their progress\n"


def _verbose_lines(run):
    out = io.StringIO()
    reporter = LogReporter("tool: ", file=out, verbose=True)
    try:
        run(reporter)
    except RuntimeError:
        pass
    # durations vary: keep the lines up to them
    return [line.rsplit(" [", 1)[0].rsplit(" in ", 1)[0].rsplit(" after ", 1)[0] for line in out.getvalue().splitlines()]


def test_log_reporter_verbose_reports_every_tenth():
    def run(reporter):
        with reporter.stage("Counting", 20) as stage:
            for _ in stage.iter(range(20)):
                pass

    assert _verbose_lines(run) == [
        "tool: Counting: started (20 total)",
        *(f"tool: Counting: {n}/20 ({n * 5}%)" for n in range(2, 20, 2)),
        "tool: Counting: done 20/20",
    ]


def test_log_reporter_verbose_stage_without_total():
    def run(reporter):
        with reporter.stage("Waiting"):
            pass

    assert _verbose_lines(run) == ["tool: Waiting: started", "tool: Waiting: done"]


def test_log_reporter_verbose_stage_finished_early():
    def run(reporter):
        with reporter.stage("Passes", 10) as stage:
            for i in stage.iter(range(10)):
                if i == 3:
                    break

    assert _verbose_lines(run)[-1] == "tool: Passes: done 3/3"


def test_log_reporter_verbose_failed_stage():
    def run(reporter):
        with reporter.stage("Failing", 4) as stage:
            stage.advance()
            raise ValueError

    assert _verbose_lines(run)[-1] == "tool: Failing: failed at 1/4"


def test_log_reporter_verbose_is_thread_safe():
    out = io.StringIO()
    with LogReporter(file=out, verbose=True) as reporter, reporter.stage("Threads", 8000) as stage:
        threads = [threading.Thread(target=lambda: [stage.advance() for _ in range(1000)]) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    lines = out.getvalue().splitlines()
    assert len(lines) == 1 + 9 + 1  # started, every tenth but the last, done
    assert lines[-1].startswith("Threads: done 8000/8000 in ")


def test_plan_first_call_counts():
    reporter = NullReporter()
    assert reporter.planned is None
    reporter.plan(11)
    reporter.plan(9)  # a pipeline planning its part of a bigger run
    assert reporter.planned == 11


def _last(out):
    return [line for line in _lines(out) if line.strip()][-1]


def test_tqdm_terminal_shows_run_and_stage(terminal):
    with TqdmReporter("tool: ", file=terminal) as reporter:
        reporter.plan(2)
        with reporter.stage("Counting", 4) as stage:
            time.sleep(0.15)  # past the bars' redraw interval
            stage.advance(2)
            # the run's bar: half of the first of two stages
            assert _drawn(terminal, r"tool: +25% .* 1/2 \[")
            assert _drawn(terminal, r"tool: Counting +50% .* 2/4 ")
            stage.advance(2)
        with reporter.stage("Waiting"):
            assert _drawn(terminal, r"tool: +50% .* 2/2 \[")

    assert re.match(r"tool: +100% .* 2/2 \[", _last(terminal))


def test_tqdm_terminal_failed_run_stays_where_it_stopped(terminal):
    with pytest.raises(RuntimeError), TqdmReporter(file=terminal) as reporter:
        reporter.plan(4)
        with reporter.stage("Done"):
            pass
        with reporter.stage("Failing", 2):
            raise ValueError

    assert re.match(r" *25% .* 2/4 \[", _last(terminal))


def test_tqdm_terminal_unplanned_run_counts_stages(terminal):
    with TqdmReporter(file=terminal) as reporter:
        for name in ("One", "Two"):
            with reporter.stage(name):
                pass

    assert _drawn(terminal, r" *stage 2 \[")
    assert "%" not in "".join(line for line in _lines(terminal) if "stage" in line)


def test_tqdm_terminal_more_stages_than_planned(terminal):
    with TqdmReporter(file=terminal) as reporter:
        reporter.plan(1)
        for name in ("One", "Two"):
            with reporter.stage(name):
                pass

    assert re.match(r" *100% .* 2/2 \[", _last(terminal))


@pytest.mark.parametrize("workers", [1, 3])
def test_workers_bound_threads(tmp_path, monkeypatch, workers):
    root = write_tree(tmp_path / "src", {f"pkg/mod{i}.py": f"def f{i}(value):\n    return value + {i}\n" for i in range(24)}
                      | {"pkg/__init__.py": ""})
    started = []
    real_start = threading.Thread.start

    def start(self):
        started.append(self)
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", start)
    minify_project(root, tmp_path / "out", workers=workers)
    assert 1 <= len(started) <= workers
