from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final, override

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from types import TracebackType
    from typing import Self


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

    def iter[T](self, iterable: Iterable[T], /) -> Iterator[T]:
        """Yield from `iterable`, counting an item as done once the loop body moves past it."""

        for item in iterable:
            yield item
            self.advance()

    @final
    def __enter__(self) -> Self:
        return self

    @final
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._close(exc_type is None)


class Reporter(ABC):
    @abstractmethod
    def stage(self, name: str, total: int | None = None, /) -> Stage:
        """
        Start the next stage.

        :param total: Units of work in the stage, or None for a stage done in one go
        """

    def close(self) -> None:
        pass

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
