from __future__ import annotations

from collections.abc import Awaitable, Sequence


type AwaitableOr[T] = T | Awaitable[T]
type SequenceOr[T] = T | Sequence[T]


class typed[T]:
    @staticmethod
    def getattr(self, name: str, default = ...) -> T:
        return getattr(self, name) if default is ... else getattr(self, name, default)
