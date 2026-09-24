from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final

from .reporter import Reporter

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
    from types import TracebackType


class TaskProvider(ABC):
    @abstractmethod
    def __enter__(self) -> None:
        ...

    @final
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb_type: TracebackType | None
    ) -> None:
        self._exit(exc, exc_type, tb_type)

    @final
    def __next__(self) -> Task:
        return self._task()

    @abstractmethod
    def _task(self) -> Task:
        ...

    @abstractmethod
    def _exit[E: BaseException, T: TracebackType](
        self, exc: E | None, exc_type: type[E] | None, tb_type: T | None, /
    ) -> None:
        ...


class TaskGroup(ABC):
    # noinspection property-definition
    _ctx = property(lambda self: self.__ctx)

    def __init__(self, provider: TaskProvider):
        self.__ctx = provider


class IterableTaskGroup[T](TaskGroup):
    def __init__(self, provider: TaskProvider, iterable: Iterable[T]):
        super().__init__(provider)
        self.__iterable = iterable

    def __iter__(self) -> Iterator[tuple[Task, T]]:
        with self._ctx:
            for i in self.__iterable:
                yield next(self._ctx), i


class AsyncIterableTaskGroup[T](TaskGroup):
    def __init__(self, provider: TaskProvider, iterable: AsyncIterable[T]):
        super().__init__(provider)
        self.__iterable = iterable

    async def __aiter__(self) -> AsyncIterator[tuple[Task, T]]:
        with self._ctx:
            async for i in self.__iterable:
                yield next(self._ctx), i


class Task(Reporter, ABC):
    @abstractmethod
    def done(self, /) -> None:
        ...
