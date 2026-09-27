from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ._suite import SuiteTransformer, TransformerFlag


def _binding_of(node):
    try:
        return ref(node).binding
    except AttributeError:
        return None


def _is_load(node) -> bool:
    return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)


class RemoveDummyAssignments(SuiteTransformer):
    """
    Remove self-assignments like `x = x`, of a name bound elsewhere too, outside a class body
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_dummy_assignments

    @override
    def suite(self, node_list, parent):
        result = [self.visit(node) for node in node_list if not self._is_dummy(node)]

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result

    def _is_dummy(self, node) -> bool:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            return False

        target, value = node.targets[0], node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Name):
            return False

        target_binding = _binding_of(target)
        # some mangler-synthesized nodes are never fully registered with a NodeRef/binding
        # (e.g. an aliasing assignment for a keyword-callable renamed parameter) - if we
        # can't resolve both sides, we can't prove this is a genuine dummy assignment
        if target_binding is None or target_binding is not _binding_of(value):
            return False

        if isinstance(ref(target).namespace, ast.ClassDef):
            # `print = print` in a class body makes a class attribute of what it reads
            return False

        # the name must be bound elsewhere too: `print = print` alone makes a module global of a
        # builtin, and `x = x` alone in a function raises `UnboundLocalError`
        return any(other is not target and not _is_load(other) for other in target_binding.references)
