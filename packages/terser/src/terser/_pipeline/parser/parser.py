from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import DummySpec, ModuleRef, ast
from ._scope import ScopeResolver

if __debug__ and __import__("typing").TYPE_CHECKING:
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


def _wrap_format_specs(node: ast.AST) -> None:
    """
    With `optimize > 0`, CPython's AST optimizer folds `'%-25s' % (x,)` into an f-string whose
    `format_spec` is a bare `Constant`, whereas the parser always wraps it in a `JoinedStr`.
    The f-string printer (and `compare_ast` against the reparsed output) expects the parser's
    shape, so wrap it the same way.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.FormattedValue) and isinstance(n.format_spec, ast.Constant):
            n.format_spec = ast.copy_location(ast.JoinedStr([n.format_spec]), n.format_spec)


def parse(source: str, spec: ModuleSpec | str, mode: str = "exec", **kwargs):
    if isinstance(spec, str):
        path = spec
        spec = DummySpec(spec)
    else:
        path = spec.path

    module: Any = ast.parse(source, path, mode, **kwargs)
    if kwargs.get("optimize", -1) > 0:
        _wrap_format_specs(module)
    _unshare_singletons(module)
    ModuleRef(module, spec)
    ScopeResolver.module(module)
    return module
