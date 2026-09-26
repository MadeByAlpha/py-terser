from typing import TYPE_CHECKING

from ._scoped import SCOPED_T, ScopedNode, is_scoped
from ._node import ref
from ._module import DummySpec, ModuleSpec, ModuleRef, _spec as spec


if TYPE_CHECKING:
    from ._node import Comprehension, Invokable, ContainsScope


__all__ = (
    "SCOPED_T",
    "DummySpec",
    "ModuleSpec",
    "ModuleRef",
    "ScopedNode",
    "spec",
    "is_scoped",
    "ref",

    "Comprehension",
    "Invokable",
    "ContainsScope",
)
