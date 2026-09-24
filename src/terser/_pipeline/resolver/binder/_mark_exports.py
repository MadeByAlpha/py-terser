from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ref

if TYPE_CHECKING:
    from ast import Module


def mark_exports(module: Module) -> None:
    """
    Flag the module-level bindings that make up `module_ref`'s public interface - importable via
    `from module_ref import name` or `from module_ref import *`, regardless of whether the
    project actually imports them.

    Only needs `module_ref`'s own AST/bindings. Safe to run independently per module, immediately
    after `binder.bind`.
    """

    module_ref = ref(module)
    exported_names: set[str] = module_ref.all or {
        name for binding in module_ref.bindings if (name := binding.name) and not name.startswith('__')
    }

    for binding in module_ref.bindings:
        if binding.name in exported_names:
            binding.mark_exported()
