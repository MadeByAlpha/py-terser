from __future__ import annotations

import sys
import time
from threading import Lock
from typing import TYPE_CHECKING, final, override

from ._reporter import Reporter, Stage

if __debug__ and TYPE_CHECKING:
    from typing import TextIO


@final
class LogReporter(Reporter):
    """
    Reports stages as plain lines, for where no progress bar can be drawn (e.g. a CI log).

    By default only the name of each stage is written as it starts. With `progress`, a stage also
    reports its size, its progress every `every` units of work, and how it ended and how long it
    took. With `items`, each item of a stage (see `Stage.item()`) is reported as it starts, and as it
    ends along with how long it took, to tell which item a slow or stuck stage is spending its time
    on.

    Every line but the plain name of a stage starts with how far the stage is (`[done/total pct%]`),
    in a column of the same width for every stage (blank for a stage that counts nothing), so that
    the rest of the lines lines up.
    """

    def __init__(
        self,
        prefix: str = "",
        /,
        *,
        file: TextIO | None = None,
        progress: bool = False,
        items: bool = False,
        every: int = 100,
    ):
        """
        :param prefix: Put before every line, e.g. to tell which tool the lines belong to
        :param file: Where to write the lines, stderr by default
        """

        self.__prefix = prefix
        self.__file = file or sys.stderr
        self.__progress = progress
        self.__items = items
        self.__every = every
        self.__lock = Lock()

    def _write(self, line: str, /) -> None:
        with self.__lock:
            self.__file.write(self.__prefix + line + "\n")
            self.__file.flush()

    @override
    def warn(self, message: str, category: type[Warning] = UserWarning, /) -> None:
        self._write(f"warning: {message}")

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        if not self.__progress:
            self._write(name)
        else:
            self._write(f"{_count(0, total)} {name}: started")
        return _LogStage(self, name, total, self.__progress, self.__items, self.__every)


def _seconds(start: float, /) -> str:
    return f"{time.monotonic() - start:.1f}s"


# fits `[99999/99999 100%]`; a longer count only pushes its own line further
_COUNT_WIDTH = 18


def _count(done: int, total: int | None, /) -> str:
    """How far a stage is, as a column of the same width on every line (and blank without a total)."""

    if total is None:
        count = ""
    else:
        percent = done * 100 // total if total else 100
        count = f"[{done:>{len(str(total))}}/{total} {percent:>3}%]"
    return count.rjust(_COUNT_WIDTH)


@final
class _LogStage(Stage):
    def __init__(
        self, reporter: LogReporter, name: str, total: int | None, progress: bool, items: bool, every: int, /,
    ):
        super().__init__(name, total)
        self.__reporter = reporter
        self.__progress = progress
        self.__items = items
        self.__every = every
        self.__lock = Lock()
        self.__done = 0
        self.__start = time.monotonic()
        self.__started: dict[str, list[float]] = {}  # when each item being worked on began

    # every line is written under `self.__lock`, so that the counts go up line after line even when
    # items are worked on concurrently

    @override
    def advance(self, n: int = 1, /) -> None:
        # counted even without `progress`, for the lines of items
        with self.__lock:
            before, done = self.__done, self.__done + n
            self.__done = done
            # the end is reported by the stage's final line
            if not self.__progress or before // self.__every == done // self.__every or done == self.total:
                return
            self.__reporter._write(f"{_count(done, self.total)} {self.name} [{_seconds(self.__start)}]")

    @override
    def _begin(self, item: str, /) -> None:
        if not self.__items:
            return

        with self.__lock:
            self.__started.setdefault(item, []).append(time.monotonic())
            self.__reporter._write(f"{_count(self.__done, self.total)} {self.name}: {item}: started")

    @override
    def _end(self, item: str, completed: bool, /) -> None:
        if not self.__items:
            return

        with self.__lock:
            starts = self.__started[item]
            start = starts.pop()
            if not starts:
                del self.__started[item]

            # finer than a stage's: an item often takes a few milliseconds
            took = f"{time.monotonic() - start:.3f}s"
            outcome = f"done in {took}" if completed else f"failed after {took}"
            self.__reporter._write(f"{_count(self.__done, self.total)} {self.name}: {item}: {outcome}")

    @override
    def _close(self, completed: bool, /) -> None:
        if not self.__progress:
            return

        with self.__lock:
            done, total = self.__done, self.total
            if completed:
                # a stage may finish early (e.g. once transforms stop changing anything): what was
                # done is all there was to do
                line = f"{_count(done, None if total is None else done)} {self.name}: done in {_seconds(self.__start)}"
            else:
                line = f"{_count(done, total)} {self.name}: failed after {_seconds(self.__start)}"
            self.__reporter._write(line)
