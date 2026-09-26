from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Iterable
from typing import overload

from ._step import AsyncIterableStep, BaseStep, IterableStep, Step, StepContext

class Reporter(ABC):
    @overload
    def __call__[T](self, message: str, iterable: None = None) -> BaseStep:
        ...
    @overload
    def __call__[T](self, message: str, iterable: Iterable[T]) -> IterableStep[T]:
        ...
    @overload
    def __call__[T](self, message: str, iterable: AsyncIterable[T]) -> AsyncIterableStep[T]:
        ...
    @overload
    def __call__[T](self, message: str, iterable: Iterable[T] | AsyncIterable[T] | None) -> Step:
        ...

    @abstractmethod
    def _step_context(self, message: str, /) -> StepContext:
        ...

    def _base_step(self, message: str) -> BaseStep:
        ...

    def _iter_step[T](self, message: str, iterable: Iterable[T]) -> IterableStep[T]:
        ...

    def _aiter_step[T](self, message: str, iterable: AsyncIterable[T]) -> AsyncIterableStep[T]:
        ...
