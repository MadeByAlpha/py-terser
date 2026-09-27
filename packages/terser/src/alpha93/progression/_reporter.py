from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final, override

if __debug__ and TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from types import TracebackType
    from typing import Self


class Task:
    def __init__(self, stage: Stage, name: str, /):
        self.stage = stage
        self.name = name

    def __enter__(self):
        self.stage._begin(self.name)
        return self

    def __exit__(self, exc_ty: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None):
        self.stage._end(self.name)
        self.stage.advance()

        if exc:
            import traceback

            traceback.print_exception(exc_ty, exc, tb)
            raise RuntimeError(f"{self.stage.name} failed while processing {self.name}") from exc


class Stage(ABC):
    def __init__(self, name: str, total: int | None, /):
        self.name = name
        self.total = total

    @abstractmethod
    def advance(self, n: int = 1, /) -> None:
        """Mark `n` more units of work as done. Thread-safe."""

    @abstractmethod
    def _close(self, completed: bool, /) -> None:
        ...

    def _begin(self, item: str, /) -> None:
        """`item` is being worked on from now. Thread-safe."""

    def _end(self, item: str, /) -> None:
        """`item` is no longer being worked on. Thread-safe."""

    def iter[T](self, iterable: Iterable[T], /) -> Iterator[T]:
        """Yield from `iterable`, counting an item as done once the loop body moves past it."""

        for item in iterable:
            yield item
            self.advance()

    @final
    def item(self, name: str, /) -> Task:
        """
        Work on one unit of the stage (e.g. a file) in the block: shown by name while in it, where
        the reporter shows what is being worked on, and counted as done once the block is left
        normally. Thread-safe, so units may be worked on concurrently.
        """
        return Task(self, name)

    @final
    def __enter__(self) -> Self:
        return self

    @final
    def __exit__(self, exc_ty: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self._close(exc_ty is None)
        if exc:
            import traceback

            traceback.print_exception(exc_ty, exc, tb)
            raise RuntimeError(f"{self.name} failed") from exc


class Reporter(ABC):
    _planned: int | None = None

    @final
    @property
    def planned(self) -> int | None:
        """How many stages the run was planned to have, if known."""
        return self._planned

    @final
    def plan(self, stages: int, /) -> None:
        """
        Declare how many stages the run has, for showing its overall progress.

        Only the first call counts: a caller running a pipeline as part of a bigger run plans the
        whole run before the pipeline plans its own part.
        """

        if self._planned is None:
            self._planned = stages

    @abstractmethod
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        """
        Start the next stage.

        :param total: Units of work in the stage, or None for a stage done in one go
        """

    def close(self) -> None:
        pass

    def warn(self, message: str, category: type[Warning] = UserWarning, /) -> None:
        """Tell about something that went wrong, but not enough to stop. A Python warning by default."""

        warnings.warn(message, category, stacklevel=2)

    @final
    def __enter__(self) -> Self:
        return self

    @final
    def __exit__(self, *_) -> None:
        self.close()


@final
class NullReporter(Reporter):
    """Reports nothing."""

    @override
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        return _NullStage(name, total)


@final
class _NullStage(Stage):
    @override
    def advance(self, n: int = 1, /) -> None:
        pass

    @override
    def _close(self, completed: bool, /) -> None:
        pass
