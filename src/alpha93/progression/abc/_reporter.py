from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ._step import AsyncIterableStep, BaseStep, IterableStep

if TYPE_CHECKING:
    from typing import Any


class Reporter(ABC):
    def __call__(self, message: str, iterable = None):
        if iterable is None:
            return self._base_step(message)

        iterable: Any
        return self._iter_step(message, iterable) if hasattr(iterable, '__iter__') \
            else self._aiter_step(message, iterable)

    @abstractmethod
    def _step_context(self, message: str, /):
        ...

    def _base_step(self, message: str):
        return BaseStep(self._step_context(message))

    def _iter_step(self, message: str, iterable):
        return IterableStep(self._step_context(message), iterable)

    def _aiter_step(self, message: str, iterable):
        return AsyncIterableStep(self._step_context(message), iterable)
