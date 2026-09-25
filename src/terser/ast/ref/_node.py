from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from terser.ast.ast import AST as Node, iter_child_nodes

if TYPE_CHECKING:
    from ast import AST
    from typing import Final

    from terser._pipeline.resolver.binding import Binding
    from ._scoped import ContainsScope


_FIELD = "__AST_NodeRef__ref__"


class NodeRef[T: AST]:
    _KLASSES: ClassVar[dict[type[AST], type[NodeRef]]] = {}

    namespace: ContainsScope
    parent: AST

    __ast: Final[T]
    _binding: Binding

    @classmethod
    def new(cls, node: AST, parent: AST):
        if cls_ := NodeRef._KLASSES.get(type(node)):
            return cls_(node, parent)

        return cls(node, parent)

    def __init__(self, node: T, parent: AST):
        setattr(node, _FIELD, self)

        self.__ast = node
        if parent:  # INTENDED: for ModuleRef
            self.parent = parent

    @property
    def ast(self):
        return self.__ast

    @property
    def binding(self):
        return self._binding

    def _resolve_all(self):
        for node in iter_child_nodes(self.__ast):
            NodeRef.new(node, self.__ast)._resolve_all()

    @override
    def __repr__(self):
        r = {i: f"{j.__class__.__name__}(...)" if isinstance(j, Node) else repr(j) for i, j in self.__dict__.items()}
        return f"{self.__class__.__name__}({', '.join([f"{k}={v}" for k, v in r.items()])})"


ref = lambda node: getattr(node, _FIELD)
