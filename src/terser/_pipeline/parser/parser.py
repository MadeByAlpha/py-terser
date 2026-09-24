from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import DummySpec, ModuleRef, ast
from ._scope import ScopeResolver

if TYPE_CHECKING:
    from typing import Any

    from terser.ast.ref import ModuleSpec


def _unshare_singletons(node: ast.AST) -> None:
    """
    CPython reuses a single instance for zero-field AST leaves (expr_context, operator,
    boolop, unaryop, cmpop) across the whole process. NodeRef metadata is attached via
    setattr directly on the node object, so sharing those instances across modules
    parsed concurrently on different threads makes them clobber each other's metadata.
    Give every occurrence its own instance before any NodeRef gets attached.
    """
    for parent in ast.walk(node):
        for field, value in ast.iter_fields(parent):
            if isinstance(value, ast.AST) and not value._fields:
                setattr(parent, field, type(value)())
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, ast.AST) and not item._fields:
                        value[i] = type(item)()


def parse(source: str, spec: ModuleSpec | str, mode: str = "exec", **kwargs):
    if isinstance(spec, str):
        path = spec
        spec = DummySpec(spec)
    else:
        path = spec.path

    module: Any = ast.parse(source, path, mode, **kwargs)
    _unshare_singletons(module)
    ModuleRef(module, spec)
    ScopeResolver.module(module)
    return module
