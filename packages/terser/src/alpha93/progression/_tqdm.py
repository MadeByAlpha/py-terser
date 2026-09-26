from __future__ import annotations

import os
import sys
from threading import Lock
from typing import TYPE_CHECKING, final, override

from tqdm import tqdm

from ._reporter import Reporter, Stage

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO


@final
class TqdmReporter(Reporter):
    """
    On a terminal, two bars: the whole run's progress on top (every planned stage weighing the
    same), and the current stage's below it.

    Elsewhere (e.g. a log), a bar can't be redrawn in place, so each stage only writes its final
    line (plus one every 10s while it runs), and the whole run's progress is not shown.
    """

    def __init__(self, prefix: str = "", /, *, file: TextIO | None = None):
        """
        :param prefix: Put before every bar, e.g. to tell which tool the bars belong to
        :param file: Where to draw the bars, stderr by default
        """

        self.__prefix = prefix
        self.__file = file or sys.stderr

        isatty = getattr(self.__file, "isatty", None)
        self.__interactive = bool(isatty and isatty())

        # tqdm skips drawing on a terminal that reports no size (e.g. a pty nobody sized), taking
        # every line to be off-screen
        self.__shape: tuple[int, int] | None = None
        try:
            if 0 in os.get_terminal_size(self.__file.fileno()):
                self.__shape = 80, 24
        except (AttributeError, ValueError, OSError):
            pass

        self.__lock = Lock()
        self.__overall: tqdm | None = None
        self.__started = 0  # stages started so far

    def __bar(self, **kwargs) -> tqdm:
        return tqdm(
            file=self.__file,
            ncols=self.__shape and self.__shape[0],
            nrows=self.__shape and self.__shape[1],
            dynamic_ncols=self.__shape is None,
            **kwargs,
        )

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        # a stage without a total has nothing to count, only a duration
        bar_format = None if total is not None else "{desc} [{elapsed}]"

        if not self.__interactive:
            bar = self.__bar(
                desc=self.__prefix + name,
                total=total,
                leave=True,
                # every redraw is a new line in a log: draw far less often, and not at all for a
                # stage done before the first redraw (it still gets its final line when closed)
                mininterval=10.,
                delay=10.,
                bar_format=bar_format,
            )
            return _TqdmStage(name, total, bar, None)

        with self.__lock:
            self.__started += 1
            base = self.__started - 1
            self.__draw_overall(base)

        bar = self.__bar(
            desc=self.__prefix + name,
            total=total,
            position=1,
            leave=False,
            mininterval=0.1,
            bar_format=bar_format,
        )
        return _TqdmStage(name, total, bar, lambda fraction: self.__progress(base + fraction))

    def __draw_overall(self, done: float, /) -> None:
        """Show that stage `self.__started` began, with `done` stages' worth of work done."""

        if self.planned is None:
            stages = None
            bar_format = "{desc}stage " + str(self.__started) + " [{elapsed}]"
        else:
            stages = max(self.planned, self.__started)
            bar_format = "{desc}{percentage:3.0f}%|{bar}| " + f"{self.__started}/{stages}" + " [{elapsed}]"

        if self.__overall is None:
            self.__overall = self.__bar(
                desc=self.__prefix, total=stages, position=0, leave=True, bar_format=bar_format,
                # redraw on time only: tqdm otherwise learns to skip updates as small as this bar's
                mininterval=0.1, miniters=0,
            )

        overall = self.__overall
        overall.total, overall.bar_format, overall.n = stages, bar_format, done
        overall.refresh()

    def __progress(self, done: float, /) -> None:
        with self.__lock:
            if self.__overall is not None:
                self.__overall.update(done - self.__overall.n)

    @override
    def close(self) -> None:
        with self.__lock:
            if self.__overall is not None:
                self.__overall.close()
                self.__overall = None


@final
class _TqdmStage(Stage):
    def __init__(self, name: str, total: int | None, bar: tqdm, progress: Callable[[float], None] | None, /):
        """:param progress: Receives the fraction of the stage done, if the run's progress is shown"""

        super().__init__(name, total)
        self.__bar = bar
        self.__progress = progress
        self.__lock = Lock()

    @override
    def advance(self, n: int = 1, /) -> None:
        with self.__lock:
            bar = self.__bar
            bar.update(n)
            if self.__progress is not None and bar.total:
                self.__progress(min(bar.n / bar.total, 1.))

    @override
    def _close(self, completed: bool, /) -> None:
        with self.__lock:
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
