from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, override

from .ast import AST, NodeVisitor as __NodeVisitor, iter_fields

if TYPE_CHECKING:
    from ast import Constant
    from collections.abc import Callable


class NodeVisitor(ABC, __NodeVisitor):
    def __visitor(self, name: str) -> Callable[[AST], AST]:
        return getattr(self, f"visit_{name}", self.generic_visit)

    @override
    def visit(self, node: AST):
        """Visit a node."""
        return self.__visitor(node.__class__.__name__)(node)

    @override
    def generic_visit(self, node: AST):
        """Called if no explicit visitor function exists for a node."""
        for _field, value in iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, AST):
                        self.visit(item)
            elif isinstance(value, AST):
                self.visit(value)

    @override
    def visit_Constant(self, node: Constant):
        name: str
        if node.value in [None, True, False]:
            name = "NameConstant"
        elif isinstance(node.value, (int, float, complex)):
            name = "Num"
        elif isinstance(node.value, str):
            name = "Str"
        elif isinstance(node.value, bytes):
            name = "Bytes"
        elif node.value == Ellipsis:
            name = "Ellipsis"
        else:
            raise RuntimeError(f"Unknown Constant value type {type(node.value)}")

        return self.__visitor(name)(node)
