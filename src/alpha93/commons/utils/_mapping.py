from __future__ import annotations

from abc import ABC

if __debug__ and __import__("typing").TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
    from typing import Any, Final


class _BaseAccessor(ABC):
    __field: Final[Mapping]
    __children: Final[MutableMapping[str, _BaseAccessor]]

    @classmethod
    def new(cls, obj, /):
        return MutableMappingAccessor(obj) if hasattr(obj, "__setitem__") else MappingAccessor(obj)

    def __init__(self, obj, /):
        self.__field = obj
        self.__children = {}

    @property
    def _actual(self):
        return self.__field

    @property
    def _children(self):
        return self.__children

class MappingAccessor(_BaseAccessor):
    def __init__(self, obj, /):
        super().__init__(obj)

    def get(self, key, default = None, /):
        return self._actual.get(key, default)

    def __getitem__(self, key, /):
        return self._actual[key]

    def __getattr__(self, key, /):
        value: Any | None = None
        if child := self._children.get(key):
            value = self.get(key)
            if value and value == _BaseAccessor._actual.__get__(value, _BaseAccessor):
                return child
            del self._children[key]
        if not value:
            value = self[key]

        if hasattr(value, "__getitem__"):
            value: Mapping
            child = self._children[key] = _BaseAccessor.new(value)
            return child

        return value

class MutableMappingAccessor(MappingAccessor):
    def __init__(self, obj, /):
        super().__init__(obj)

    def __setitem__(self, key, value, /):
        mutable = self._actual
        mutable: MutableMapping
        mutable[key] = value

    def __delitem__(self, key, /):
        mutable = self._actual
        mutable: MutableMapping
        del mutable[key]

    def __setattr__(self, key, value, /):
        mutable = self._actual
        mutable: MutableMapping
        mutable[key] = value

        if hasattr(value, "__getitem__"):
            self._children[key] = _BaseAccessor.new(value)
            return
        elif value in self._children:
            del self._children[value]

accessor = _BaseAccessor.new
