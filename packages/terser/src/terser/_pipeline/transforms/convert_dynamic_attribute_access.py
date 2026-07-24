import keyword
from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from ..resolver.binding import BuiltinBinding
from ._suite import SuiteTransformer, TransformerFlag


def _valid_attr_name(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None

    name = node.value
    return name if name.isidentifier() and not keyword.iskeyword(name) else None


def _is_unshadowed_builtin(node: ast.expr, name: str) -> bool:
    if not isinstance(node, ast.Name):
        return False

    try:
        binding = ref(node).binding
    except AttributeError:
        # some mangler-synthesized nodes are never fully registered with a binding
        return False

    return isinstance(binding, BuiltinBinding) and binding.name == name and not binding.is_redefined()


class ConvertDynamicAttributeAccess(SuiteTransformer):
    """
    Convert `getattr(obj, "name")` to `obj.name`, and a bare
    `setattr(obj, "name", value)` statement to `obj.name = value`
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_dynamic_attribute_access

    @override
    def visit_Call(self, node: ast.Call):
        node: ast.Call = self.generic_visit(node)

        if node.keywords or len(node.args) != 2 or not _is_unshadowed_builtin(node.func, 'getattr'):
            return node

        attr = _valid_attr_name(node.args[1])
        if attr is None:
            return node

        new_node = ast.Attribute(value=node.args[0], attr=attr, ctx=ast.Load())
        return self.add_child(new_node, parent=ref(node).parent)

    @override
    def visit_Expr(self, node: ast.Expr):
        node.value = self.visit(node.value)
        value = node.value

        if (
            isinstance(value, ast.Call) and not value.keywords and len(value.args) == 3
            and _is_unshadowed_builtin(value.func, 'setattr')
        ):
            attr = _valid_attr_name(value.args[1])
            if attr is not None:
                new_node = ast.Assign(targets=[ast.Attribute(value=value.args[0], attr=attr, ctx=ast.Store())], value=value.args[2])
                return self.add_child(new_node, parent=ref(node).parent)

        return node
