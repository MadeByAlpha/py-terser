from __future__ import annotations

import os
import sys
from threading import Lock
from typing import TYPE_CHECKING, final, override

from tqdm import tqdm

from ._reporter import Reporter, Stage

if TYPE_CHECKING:
    from typing import TextIO


@final
class TqdmReporter(Reporter):
    """
    One tqdm bar per stage, kept on screen once done, so the output reads as a log of the stages
    and how long each took.
    """

    def __init__(self, prefix: str = "", /, *, file: TextIO | None = None):
        """
        :param prefix: Put before every stage's name, e.g. to tell which tool the bars belong to
        :param file: Where to draw the bars, stderr by default
        """

        self.__prefix = prefix
        self.__file = file or sys.stderr

        # redrawing a bar in place only works on a terminal; elsewhere every redraw is a new line
        # in a log, so draw far less often, and not at all for a stage done before the first redraw
        # (it still gets its final line when closed)
        isatty = getattr(self.__file, "isatty", None)
        self.__interval = 0. if isatty and isatty() else 10.

        # tqdm skips drawing on a terminal that reports no size (e.g. a pty nobody sized), taking
        # every line to be off-screen
        self.__shape: tuple[int, int] | None = None
        try:
            if 0 in os.get_terminal_size(self.__file.fileno()):
                self.__shape = 80, 24
        except (AttributeError, ValueError, OSError):
            pass

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        bar = tqdm(
            desc=self.__prefix + name,
            total=total,
            file=self.__file,
            leave=True,
            ncols=self.__shape and self.__shape[0],
            nrows=self.__shape and self.__shape[1],
            dynamic_ncols=self.__shape is None,
            mininterval=self.__interval or 0.1,
            delay=self.__interval,
            # a stage without a total has nothing to count, only a duration
            bar_format=None if total is not None else "{desc} [{elapsed}]",
        )
        return _TqdmStage(name, total, bar)


@final
class _TqdmStage(Stage):
    def __init__(self, name: str, total: int | None, bar: tqdm, /):
        super().__init__(name, total)
        self.__bar = bar
        self.__lock = Lock()

    @override
    def advance(self, n: int = 1, /) -> None:
        with self.__lock:
            self.__bar.update(n)

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
