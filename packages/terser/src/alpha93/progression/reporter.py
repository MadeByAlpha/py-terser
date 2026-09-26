from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum
from typing import TYPE_CHECKING

from .abc import Reporter
from .tasks import AsyncIterableTaskGroup, IterableTaskGroup

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable


class BaseReporter(Reporter, ABC):
    class Status(IntEnum):
        CONFIGURING = 0
        IN_PROGRESS = 1

    @abstractmethod
    def _task_provider(self, message: str, /):
        ...

    @abstractmethod
    def prepare(self, message: str):
        ...

    @abstractmethod
    def init(self, /, **kwargs):
        ...

    @abstractmethod
    def close(self):
        ...

    def __enter__(self):
        return self

    def __exit__(self, *__, **_):
        self.close()

    def iter(self, iterable: Iterable, message: str):
        return IterableTaskGroup(self._task_provider(message), iterable)

    def aiter(self, iterable: AsyncIterable, message: str):
        return AsyncIterableTaskGroup(self._task_provider(message), iterable)
