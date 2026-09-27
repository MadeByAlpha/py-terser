from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._classes import subclassed
from ._suite import SuiteTransformer, TransformerFlag

_PROTOCOL_NAMES = ("typing.Protocol", "typing_extensions.Protocol")
_RUNTIME_CHECKABLE_NAMES = ("typing.runtime_checkable", "typing_extensions.runtime_checkable")


class RemoveTypingClasses(SuiteTransformer):
    """
    Remove bare `Protocol` base classes, unless the class is decorated with
    `@typing.runtime_checkable` (removing `Protocol` there would break `isinstance`), or another
    class derives from it: a protocol can only derive from protocols. Needs the module linked, to
    tell subclasses in the other modules of the project.
    """
    FLAGS = TransformerFlag.REQUIRES_MODULE_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_typing_classes

    @override
    def visit_Module(self, node: ast.Module):
        # unless the project was linked and marked (see `mark_classes`), as far as this module tells
        self._subclassed = subclassed(ref(node))
        return super().visit_Module(node)

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node: ast.ClassDef = super().visit_ClassDef(node)

        if any(qualified_name(d) in _RUNTIME_CHECKABLE_NAMES for d in node.decorator_list):
            return node

        if getattr(ref(node), 'subclassed', False) or id(node) in self._subclassed:
            return node

        node.bases = [b for b in node.bases if qualified_name(b) not in _PROTOCOL_NAMES]
        return node
