from typing import override

from terser.ast import ast, ref
from terser.ast.ref import ref_or_none
from terser.config import TransformConfig
from ..resolver import forget
from ._suite import SuiteTransformer, TransformerFlag

_TypeAlias = getattr(ast, "TypeAlias", ())


class RemoveTypeStatements(SuiteTransformer):
    """
    Remove `type X = ...` alias statements nothing reads: not a name left in the module (an
    annotation kept for code reading it at run time, say), nor, at module level, other modules (in
    project mode) or the module's public interface. Needs the module linked, to tell.
    """
    FLAGS = TransformerFlag.REQUIRES_MODULE_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_type_statements and bool(_TypeAlias)

    @override
    def visit_Module(self, node: ast.Module):
        self._module_ref = ref(node)
        return super().visit_Module(node)

    def _removable(self, node) -> bool:
        binding = getattr(ref_or_none(node.name), 'binding', None)
        if binding is None:
            return False
        if any(isinstance(other, ast.Name) and isinstance(other.ctx, ast.Load) for other in binding.references):
            return False
        if isinstance(ref(node).namespace, ast.Module) and (
            binding.exported or binding.preserved or not self._module_ref.linked
        ):
            return False  # other modules may import it
        return True

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            if isinstance(node, _TypeAlias) and self._removable(node):
                forget([node])
                continue
            result.append(self.visit(node))

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
