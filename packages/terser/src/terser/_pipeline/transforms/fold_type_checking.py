from __future__ import annotations

from typing import TYPE_CHECKING, override

from terser.ast import ast, ref
from terser.ast.ref import ref_or_none
from terser.utils.imports import qualified_name
from ..resolver import forget
from ..resolver.binding import ImportBinding
from ._suite import SuiteTransformer, TransformerFlag

if __debug__ and TYPE_CHECKING:
    from ...config import TransformConfig

_TYPING = frozenset({'typing', 'typing_extensions'})
_NAMES = frozenset({f'{module}.TYPE_CHECKING' for module in _TYPING})


def _binding(node: ast.AST):
    return getattr(ref_or_none(node), '_binding', None)


def _imports(binding: object, imported: str, statement: type[ast.Import | ast.ImportFrom]) -> bool:
    """If every statement binding `binding` imports `imported` from `typing`/`typing_extensions`."""

    if not isinstance(binding, ImportBinding) or binding.source_module not in _TYPING:
        return False

    return all(
        isinstance(other, ast.alias) and other.name == imported and isinstance(ref(other).parent, statement)
        and (statement is ast.Import or (ref(other).parent.module in _TYPING and ref(other).parent.level == 0))
        for other in binding.references
        if not (isinstance(other, ast.Name) and isinstance(other.ctx, ast.Load))
    )


def _dynamic(node: ast.expr) -> bool:
    """If `node` is a dynamic import (`__import__(...)`), or a name not bound by an import statement"""

    return isinstance(node, ast.Call) or (isinstance(node, ast.Name) and not isinstance(_binding(node), ImportBinding))


class _RemoveImports(SuiteTransformer):
    """Remove the aliases of `bindings` from their import statements."""

    def __init__(self, ctx, bindings: list[ImportBinding], /):
        super().__init__(ctx)
        self.__aliases = {id(alias) for binding in bindings for alias in binding.aliases}

    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return True

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            if isinstance(node, (ast.Import, ast.ImportFrom)) and (
                removed := [alias for alias in node.names if id(alias) in self.__aliases]
            ):
                forget(removed)
                node.names = [alias for alias in node.names if id(alias) not in self.__aliases]
                if not node.names:
                    continue
            result.append(self.visit(node))

        if not result and not isinstance(parent, ast.Module):
            return [self.add_child(ast.Expr(value=ast.Constant(value=0)), parent=parent)]
        return result


class FoldTypeChecking(SuiteTransformer):
    """
    Replace `typing.TYPE_CHECKING` (or `typing_extensions`') with `False`, its value at run time,
    for the code only type checkers see to be removed as dead code. `from typing import
    TYPE_CHECKING` and `import typing` left unused are removed too, as importing either does
    nothing else.

    Modules marked `preserve_type_checking` are left as they are.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.fold_type_checking

    @override
    def visit_Module(self, node: ast.Module):
        if ref(node).preserve_type_checking:
            return node

        node = super().visit_Module(node)

        # imports left unused, now or once the code only type checkers see is removed as dead code
        unused = [
            binding for binding in ref(node).import_targets
            if not any(isinstance(other, ast.Name) and isinstance(other.ctx, ast.Load) for other in binding.references)
            and (_imports(binding, 'TYPE_CHECKING', ast.ImportFrom) or _imports(binding, binding.source_module or '', ast.Import))
        ]
        return _RemoveImports(self._cache or self._config, unused)(node) if unused else node

    def __fold(self, node: ast.expr) -> ast.expr:
        node_ref = ref(node)
        forget([node])
        return self.add_child(ast.Constant(value=False), parent=node_ref.parent, namespace=node_ref.namespace)

    @override
    def visit_Name(self, node: ast.Name):
        # `from typing import TYPE_CHECKING [as name]`
        if isinstance(node.ctx, ast.Load) and _imports(_binding(node), 'TYPE_CHECKING', ast.ImportFrom):
            return self.__fold(node)
        # `name = __import__("typing").TYPE_CHECKING`, assigned once
        if isinstance(node.ctx, ast.Load) and not isinstance(_binding(node), ImportBinding) and qualified_name(node) in _NAMES:
            return self.__fold(node)
        return node

    @override
    def visit_Attribute(self, node: ast.Attribute):
        # `import typing [as name]`, then `typing.TYPE_CHECKING`
        if (
            node.attr == 'TYPE_CHECKING' and isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name)
            and isinstance(binding := _binding(node.value), ImportBinding)
            and _imports(binding, binding.source_module or '', ast.Import)
        ):
            return self.__fold(node)
        # `__import__("typing").TYPE_CHECKING`, or through a name assigned such a call once
        if node.attr == 'TYPE_CHECKING' and isinstance(node.ctx, ast.Load) and _dynamic(node.value) and qualified_name(node) in _NAMES:
            return self.__fold(node)
        return self.generic_visit(node)


def is_type_checking(node: ast.expr) -> bool:
    """If `node` reads `typing.TYPE_CHECKING` (or `typing_extensions`'), by any of the ways `FoldTypeChecking` folds"""

    if isinstance(node, ast.Name):
        binding = _binding(node)
        return _imports(binding, 'TYPE_CHECKING', ast.ImportFrom) or qualified_name(node) in _NAMES
    if isinstance(node, ast.Attribute) and node.attr == 'TYPE_CHECKING':
        return qualified_name(node) in _NAMES
    return False


def keep_type_checking(module: ast.Module) -> None:
    """
    Keep the names a module marked `preserve_type_checking` reads `TYPE_CHECKING` by: the code
    reading it back (anyio's lazy importer) looks for `TYPE_CHECKING` (or `typing.TYPE_CHECKING`)
    in the source, and deletes it from the module's globals by name.
    """

    for node in ast.walk(module):
        if not is_type_checking(node):
            continue
        name = node if isinstance(node, ast.Name) else node.value
        if isinstance(name, ast.Name) and (binding := _binding(name)) is not None:
            binding.disallow_rename()
            binding.mark_preserved()
