from __future__ import annotations

from typing import TYPE_CHECKING

from ._all import resolve_all as __resolve__all__
from ._mark_exports import mark_exports as __mark_exports
from ._resolve_imports import UnresolvedModuleRef, resolve_imports as __resolve_imports
from ._bind import bind as __bind

if TYPE_CHECKING:
    from ast import Module


def bind(module: Module):
    __resolve__all__(module)
    __mark_exports(module)
    __resolve_imports(module)
    __bind(module)


__all__ = ("UnresolvedModuleRef", "bind",)
