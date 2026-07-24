from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag

_PROTOCOL_NAMES = ("typing.Protocol", "typing_extensions.Protocol")
_RUNTIME_CHECKABLE_NAMES = ("typing.runtime_checkable", "typing_extensions.runtime_checkable")


class RemoveTypingClasses(SuiteTransformer):
    """
    Remove bare `Protocol` base classes, unless the class is decorated with
    `@typing.runtime_checkable` (removing `Protocol` there would break `isinstance`)
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_typing_classes

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node: ast.ClassDef = super().visit_ClassDef(node)

        if any(qualified_name(d) in _RUNTIME_CHECKABLE_NAMES for d in node.decorator_list):
            return node

        node.bases = [b for b in node.bases if qualified_name(b) not in _PROTOCOL_NAMES]
        return node
