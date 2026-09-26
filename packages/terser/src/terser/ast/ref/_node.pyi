import ast
from abc import ABC
from ast import AST
from typing import overload, ClassVar

from terser._pipeline.resolver.binding import Binding
from ._module import ModuleRef
from ._scoped import ScopedNode


type Invokable = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
type Comprehension = ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp
type ContainsScope = ast.Module | ast.ClassDef | Invokable | Comprehension


class NodeRef[T: AST](ABC):
    _KLASSES: ClassVar[dict[type[ast.AST], type[NodeRef]]]

    __slots__ = ("__ast", "_binding", "parent", "namespace")

    @property
    def ast(self) -> T: ...

    @property
    def binding(self) -> Binding: ...

    namespace: ContainsScope
    parent: AST

    @classmethod
    def new(cls, node: T, parent: AST) -> NodeRef[T]: ...

    def __init__(self, node: T, parent: AST) -> None: ...
    def _resolve_all(self) -> None: ...


@overload
def ref(node: ast.Module) -> ModuleRef: ...
@overload
def ref[T: ContainsScope](node: T) -> ScopedNode[T]: ...
@overload
def ref[T: AST](node: T) -> NodeRef[T]: ...
