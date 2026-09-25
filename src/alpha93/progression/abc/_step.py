from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
    from types import TracebackType


class StepContext(ABC):
    @abstractmethod
    def __enter__(self) -> None:
        ...

    @abstractmethod
    def __next__(self) -> None:
        ...

    @final
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb_type: TracebackType | None
    ) -> None:
        self._exit(exc, exc_type, tb_type)

    @abstractmethod
    def _exit[E: BaseException, T: TracebackType](
        self, exc: E | None, exc_type: type[E] | None, tb_type: T | None, /
    ) -> None:
        ...


class Step(ABC):
    def __init__(self, ctx: StepContext, /):
        self.__ctx = ctx

    @final
    @property
    def _ctx(self) -> StepContext:
        return self.__ctx

class BaseStep(Step):
    def __enter__(self):
        self._ctx.__enter__()
        next(self._ctx)

    def __exit__(self, *args, **kwargs):
        self._ctx.__exit__(*args, **kwargs)

class IterableStep[T](Step):
    def __init__(self, ctx: StepContext, iterable: Iterable[T]):
        super().__init__(ctx)
        self.__iterable = iterable

    def __iter__(self) -> Iterator[T]:
        with self._ctx:
            for i in self.__iterable:
                next(self._ctx)
                yield i

class AsyncIterableStep[T](Step):
    def __init__(self, ctx: StepContext, iterable: AsyncIterable[T]):
        super().__init__(ctx)
        self.__iterable = iterable

    async def __aiter__(self) -> AsyncIterator[T]:
        with self._ctx:
            async for i in self.__iterable:
                next(self._ctx)
                yield i
