from __future__ import annotations

import sys
import time
from threading import Lock
from typing import TYPE_CHECKING, final, override

from ._reporter import Reporter, Stage

if TYPE_CHECKING:
    from typing import TextIO


@final
class LogReporter(Reporter):
    """
    Reports stages as plain lines, for where no progress bar can be drawn.

    By default only the name of each stage is written as it starts. With `verbose`, a stage also
    reports its size, its progress at every tenth of it, and how it ended and how long it took.
    """

    def __init__(self, prefix: str = "", /, *, file: TextIO | None = None, verbose: bool = False):
        """
        :param prefix: Put before every line, e.g. to tell which tool the lines belong to
        :param file: Where to write the lines, stderr by default
        """

        self.__prefix = prefix
        self.__file = file or sys.stderr
        self.__verbose = verbose
        self.__lock = Lock()

    def _write(self, line: str, /) -> None:
        with self.__lock:
            self.__file.write(self.__prefix + line + "\n")
            self.__file.flush()

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        if not self.__verbose:
            self._write(name)
            return _QuietStage(name, total)

        self._write(f"{name}: started" + (f" ({total} total)" if total is not None else ""))
        return _VerboseStage(self, name, total)


@final
class _QuietStage(Stage):
    @override
    def advance(self, n: int = 1, /) -> None:
        pass

    @override
    def _close(self, completed: bool, /) -> None:
        pass


@final
class _VerboseStage(Stage):
    def __init__(self, reporter: LogReporter, name: str, total: int | None, /):
        super().__init__(name, total)
        self.__reporter = reporter
        self.__lock = Lock()
        self.__done = 0
        self.__tenths = 0  # the last tenth of `total` reported
        self.__start = time.monotonic()

    def __elapsed(self) -> str:
        return f"{time.monotonic() - self.__start:.1f}s"

    @override
    def advance(self, n: int = 1, /) -> None:
        with self.__lock:
            self.__done += n
            if not self.total:
                return

            tenths = min(self.__done * 10 // self.total, 10)
            # the last tenth is reported by the stage's final line
            if tenths == self.__tenths or tenths == 10:
                return
            self.__tenths = tenths

            done, total = self.__done, self.total
            line = f"{self.name}: {done}/{total} ({done * 100 // total}%) [{self.__elapsed()}]"
        self.__reporter._write(line)

    @override
    def _close(self, completed: bool, /) -> None:
        with self.__lock:
            done, counted = self.__done, self.total is not None
            if completed:
                # a stage may finish early (e.g. once transforms stop changing anything): what was
                # done is all there was to do
                line = f"{self.name}: done{f' {done}/{done}' if counted else ''} in {self.__elapsed()}"
            else:
                line = f"{self.name}: failed{f' at {done}/{self.total}' if counted else ''} after {self.__elapsed()}"
        self.__reporter._write(line)
