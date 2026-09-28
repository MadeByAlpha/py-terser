from __future__ import annotations

import os
import sys
import warnings
from threading import Lock, RLock
from typing import TYPE_CHECKING, final, override

from rich.console import Console
from rich.progress import BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from tqdm.rich import FractionColumn, RateColumn, tqdm_rich
from tqdm.std import TqdmExperimentalWarning
from tqdm.std import tqdm as tqdm_std

from ._reporter import Reporter, Stage

if __debug__ and TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from rich.progress import ProgressColumn


def _description() -> TextColumn:
    # a prefix or a stage name is no rich markup
    return TextColumn("{task.description}", style="progress.description", markup=False)


def _percentage() -> TextColumn:
    return TextColumn("{task.percentage:>3.0f}%", style="progress.percentage")


def _counted() -> tuple[ProgressColumn | str, ...]:
    """`tqdm.rich`'s own columns."""
    return (
        _description(), _percentage(), BarColumn(bar_width=None), FractionColumn(),
        "[", TimeElapsedColumn(), "<", TimeRemainingColumn(), ",", RateColumn(unit="it"), "]",
    )


def _uncounted() -> tuple[ProgressColumn | str, ...]:
    """A stage without a total has nothing to count, only a duration."""
    return _description(), "[", TimeElapsedColumn(), "]"


@final
class _RichBar(tqdm_rich):
    """
    A `tqdm.rich` bar drawn only when it's redrawn, and in full: rich doesn't redraw it on its own
    (which would clash with the line of items below it), and `tqdm.rich` would leave out a change of
    `total`.
    """

    @override
    def display(self, *_, **__) -> None:
        if not hasattr(self, "_task_id"):
            return
        self._prog.update(self._task_id, completed=self.n, total=self.total, description=self.desc)
        self._prog.refresh()

    def set_columns(self, columns: tuple[ProgressColumn | str, ...], /) -> None:
        """Draw the bar with `columns` from its next redraw on."""
        self._prog.columns = columns


@final
class TqdmReporter(Reporter):
    """
    On a terminal, `tqdm.rich` bars: the whole run's progress on top (every planned stage weighing
    the same), and the current stage's below it. Below them, the items the stage is working on
    (see `Stage.item()`), if any.

    Elsewhere (e.g. a log), a bar can't be redrawn in place, so each stage only writes its final
    line (plus one every 10s while it runs) with `tqdm.std`, and the whole run's progress is not
    shown.
    """

    def __init__(self, prefix: str = "", /, *, file: TextIO | None = None):
        """
        :param prefix: Put before every bar, e.g. to tell which tool the bars belong to
        :param file: Where to draw the bars, stderr by default
        """

        self.__prefix = prefix
        self.__file = file or sys.stderr

        # tqdm skips drawing on a terminal that reports no size (e.g. a pty nobody sized), taking
        # every line to be off-screen
        self.__shape: tuple[int, int] | None = None
        try:
            if 0 in os.get_terminal_size(self.__file.fileno()):
                self.__shape = 80, 24
        except (AttributeError, ValueError, OSError):
            pass

        # shared by the bars, so that each next one is drawn along with the others. None where rich
        # can't redraw (not a terminal, or a dumb one)
        self.__console: Console | None = None
        isatty = getattr(self.__file, "isatty", None)
        if isatty and isatty():
            width, height = self.__shape or (None, None)
            console = Console(file=self.__file, width=width, height=height)
            if console.is_interactive:
                self.__console = console

        # every bar and line on a terminal is drawn under it: drawing one moves the cursor over the others
        self.__lock = RLock()
        self.__overall: _RichBar | None = None
        self.__items: _Items | None = None  # of the current stage
        self.__started = 0  # stages started so far

    def __std(self, **kwargs) -> tqdm_std:
        return tqdm_std(
            file=self.__file,
            ncols=self.__shape and self.__shape[0],
            nrows=self.__shape and self.__shape[1],
            dynamic_ncols=self.__shape is None,
            **kwargs,
        )

    def __rich(self, columns: tuple[ProgressColumn | str, ...], /, **kwargs) -> _RichBar:
        # warns of being experimental on every bar
        with warnings.catch_warnings(action="ignore", category=TqdmExperimentalWarning):
            return _RichBar(
                file=self.__file,
                progress=columns,
                options={
                    "console": self.__console,
                    "auto_refresh": False,
                    # that would take the line of items too, and print it above the bars
                    "redirect_stdout": False,
                    "redirect_stderr": False,
                },
                # redraw on time only: tqdm otherwise learns to skip updates as small as the run's bar's,
                # and redraws from its monitor thread, out of `self.__lock`
                mininterval=0.1, miniters=0,
                **kwargs,
            )

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        if self.__console is None:
            bar = self.__std(
                desc=self.__prefix + name,
                total=total,
                leave=True,
                # every redraw is a new line in a log: draw far less often, and not at all for a
                # stage done before the first redraw (it still gets its final line when closed)
                mininterval=10.,
                delay=10.,
                # a stage without a total has nothing to count, only a duration
                bar_format=None if total is not None else "{desc} [{elapsed}]",
            )
            return _TqdmStage(name, total, bar, Lock(), None, None)

        with self.__lock:
            self.__started += 1
            base = self.__started - 1
            self.__draw_overall(base)

            bar = self.__rich(
                _counted() if total is not None else _uncounted(),
                desc=self.__prefix + name, total=total, leave=False,
            )
            # the bars take their final height before the line of items is drawn below them
            bar.refresh()

            self.__items = _Items(self.__prefix, lambda **kwargs: self.__std(position=1, leave=False, **kwargs))
            return _TqdmStage(
                name, total, bar, self.__lock, lambda fraction: self.__progress(base + fraction), self.__items,
            )

    def __draw_overall(self, done: float, /) -> None:
        """Show that stage `self.__started` began, with `done` stages' worth of work done."""

        if self.planned is None:
            stages = None
            columns = (_description(), "stage " + str(self.__started), "[", TimeElapsedColumn(), "]")
        else:
            stages = max(self.planned, self.__started)
            columns = (
                _description(), _percentage(), BarColumn(bar_width=None), f"{self.__started}/{stages}",
                "[", TimeElapsedColumn(), "]",
            )

        if self.__overall is None:
            self.__overall = self.__rich(columns, desc=self.__prefix, total=stages, leave=True)

        overall = self.__overall
        overall.set_columns(columns)
        overall.total, overall.n = stages, done
        overall.refresh()

    def __progress(self, done: float, /) -> None:
        # under `self.__lock`, by the stage
        if self.__overall is not None:
            self.__overall.update(done - self.__overall.n)

    @override
    def warn(self, message: str, category: type[Warning] = UserWarning, /) -> None:
        line = f"{self.__prefix}warning: {message}"
        with self.__lock:
            if self.__console is None:
                tqdm_std.write(line, file=self.__file)
                return

            # above the bars, which rich draws again below it, and the line of items below them
            items = self.__items
            if items is not None:
                items.clear()
            self.__console.print(line, markup=False, highlight=False, emoji=False, soft_wrap=True)
            if items is not None:
                items.redraw()

    @override
    def close(self) -> None:
        with self.__lock:
            if self.__overall is not None:
                self.__overall.close()
                self.__overall = None


@final
class _Items:
    """
    The line below the bars naming the items being worked on, in the order they began. A line of
    text, drawn by `tqdm.std` right below where rich leaves the cursor: rich only redraws its own
    lines, as long as the bars keep their height.
    """

    def __init__(self, prefix: str, line: Callable[..., tqdm_std], /):
        """:param line: Makes the line, given its text"""

        self.__prefix = prefix
        self.__line = line
        self.__names: list[str] = []
        self.__drawn: tqdm_std | None = None

    def __text(self) -> str:
        return f"{self.__prefix}{len(self.__names)} in progress: {', '.join(self.__names)}" if self.__names else ""

    def __draw(self) -> None:
        if self.__drawn is None:
            self.__drawn = self.__line(bar_format="{desc}", desc=self.__text())
        else:
            self.__drawn.set_description_str(self.__text())

    def begin(self, name: str, /) -> None:
        self.__names.append(name)
        self.__draw()

    def end(self, name: str, /) -> None:
        self.__names.remove(name)
        self.__draw()

    def clear(self) -> None:
        """Clear the line until it's redrawn."""
        if self.__drawn is not None:
            self.__drawn.clear()

    def redraw(self) -> None:
        if self.__drawn is not None:
            self.__drawn.refresh()

    def close(self) -> None:
        """Clear the line for good: before the bars above it change height."""

        if self.__drawn is not None:
            self.__drawn.close()
            self.__drawn = None


@final
class _TqdmStage(Stage):
    def __init__(
        self,
        name: str,
        total: int | None,
        bar: tqdm_std,
        lock: Lock | RLock,
        progress: Callable[[float], None] | None,
        items: _Items | None,
        /,
    ):
        """
        :param lock: Held while drawing, shared by every bar on a terminal
        :param progress: Receives the fraction of the stage done, if the run's progress is shown
        :param items: Shows the items being worked on, if shown
        """

        super().__init__(name, total)
        self.__bar = bar
        self.__lock = lock
        self.__progress = progress
        self.__items = items

    @override
    def advance(self, n: int = 1, /) -> None:
        with self.__lock:
            bar = self.__bar
            bar.update(n)
            if self.__progress is not None and bar.total:
                self.__progress(min(bar.n / bar.total, 1.))

    @override
    def _begin(self, item: str, /) -> None:
        if self.__items is not None:
            with self.__lock:
                self.__items.begin(item)

    @override
    def _end(self, item: str, completed: bool, /) -> None:
        if self.__items is not None:
            with self.__lock:
                self.__items.end(item)

    @override
    def _close(self, completed: bool, /) -> None:
        with self.__lock:
            if self.__items is not None:
                self.__items.close()

            bar = self.__bar
            # a stage may finish early (e.g. once transforms stop changing anything): what was done
            # is all there was to do
            if completed and bar.total is not None and bar.n != bar.total:
                bar.total = bar.n
            # always leave the stage's final line, even when it ended within the display delay
            bar.delay = 0
            bar.close()

            if completed and self.__progress is not None:
                self.__progress(1.)
