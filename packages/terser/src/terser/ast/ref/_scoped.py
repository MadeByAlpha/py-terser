from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ast
from ._node import NodeRef

if TYPE_CHECKING:
    from typing import Final, TypeGuard

    # noinspection protected-member
    from terser._pipeline.resolver.binding import Binding
    from ._node import ContainsScope


SCOPED_T: Final[tuple[type[ContainsScope], ...]] = (
    ast.FunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.Module,
    ast.GeneratorExp,
    ast.SetComp,
    ast.DictComp,
    ast.ListComp,
    ast.AsyncFunctionDef,
)

class ScopedNode[T: ContainsScope](NodeRef[T]):
    bindings: list[Binding]
    globals: set[str]
    nonlocals: set[str]
    assigned_names: set[str]
    """Names reserved in this namespace during mangling - set lazily, see mangler.renamer.add_assigned"""

    def __init__(self, node: T, parent: ast.AST):
        super().__init__(node, parent)
        self.bindings = []
        self.globals = set()
        self.nonlocals = set()

for k in SCOPED_T:
    NodeRef._KLASSES[k] = ScopedNode

def is_scoped(node: ast.AST) -> TypeGuard[ContainsScope]:
    return isinstance(node, SCOPED_T)
