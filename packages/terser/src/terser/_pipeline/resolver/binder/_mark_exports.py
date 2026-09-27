from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from ..binding import ImportBinding

if __debug__ and __import__("typing").TYPE_CHECKING:
    from ast import Module


def _is_intentional_reexport(binding) -> bool:
    """
    Without an explicit `__all__`, a locally-defined name is implicitly part of the module's
    public interface - but a plain import isn't: `from typing import override` used only for
    a decorator isn't "re-exporting `override`" by convention (matching ruff/pyflakes F401),
    only the explicit `import x as x` / `from y import x as x` idiom is.
    """
    if not isinstance(binding, ImportBinding):
        return True

    node = binding.node
    return isinstance(node, ast.alias) and node.asname == node.name


def mark_exports(module: Module) -> None:
    """
    Flag the module-level bindings that make up `module_ref`'s public interface - importable via
    `from module_ref import name` or `from module_ref import *`, regardless of whether the
    project actually imports them.

    Only needs `module_ref`'s own AST/bindings. Safe to run independently per module, immediately
    after `binder.bind`.
    """

    module_ref = ref(module)
    if module_ref.all is not None:
        exported_names: set[str] = module_ref.all
    else:
        exported_names = {
            name for binding in module_ref.bindings
            if (name := binding.name) and not name.startswith('__') and _is_intentional_reexport(binding)
        }

    for binding in module_ref.bindings:
        if binding.name in exported_names:
            binding.mark_exported()
