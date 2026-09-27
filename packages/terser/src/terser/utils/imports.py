from terser.ast import ast
from terser.ast.ref import ref_or_none
from .._pipeline.dynamic_imports import returned_module
from .._pipeline.resolver.binding import ImportBinding


def _assigned_once(binding) -> ast.expr | None:
    """The value of the only assignment binding a name (`x = value`), if it has no other store"""

    stores = [node for node in binding.references if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load))]
    if len(stores) != 1 or not isinstance(target := stores[0], ast.Name):
        return None

    if (target_ref := ref_or_none(target)) is None:
        return None

    stmt = target_ref.parent
    if not isinstance(stmt, ast.Assign) or stmt.targets != [target]:
        return None
    return stmt.value


def _dynamic_root(node: ast.expr) -> ast.Call | None:
    """The call at the root of `node` (`__import__("a")` of `__import__("a").b.c`), if any"""

    while isinstance(node, ast.Attribute):
        node = node.value
    return node if isinstance(node, ast.Call) else None


def qualified_name(node: ast.expr, /) -> str | None:
    """
    Resolve a `Name` or dotted `Attribute` expression to the dotted path of the
    import it refers to (e.g. `cast` after `from typing import cast` or
    `typing.cast` both resolve to `"typing.cast"`), using the already-computed
    name bindings. Also follows dynamic imports of literals (see
    `terser._pipeline.dynamic_imports`), called inline
    (`__import__("typing").TYPE_CHECKING`) or assigned to a name once
    (`t = __import__("typing")`, then `t.cast`).

    Returns None if the root name isn't an import (or dynamic-import call), or its
    binding has no name.
    """

    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    attrs.reverse()

    def qualify(root: str | None) -> str | None:
        if not root:
            return None
        return f"{root}.{'.'.join(attrs)}" if attrs else root

    if isinstance(node, ast.Call):
        if ref_or_none(node) is None or ref_or_none(node.func) is None:
            return None
        return qualify(returned_module(node))

    if not isinstance(node, ast.Name) or (node_ref := ref_or_none(node)) is None:
        return None

    # some mangler-synthesized nodes are never fully registered with a binding (e.g. an aliasing
    # assignment for a keyword-callable renamed parameter) - treat those as unresolvable
    binding = getattr(node_ref, 'binding', None)
    if binding is None or not binding.name:
        return None

    if not isinstance(binding, ImportBinding):
        # `t = __import__("typing")` or `cast = __import__("typing").cast`, assigned once
        value = _assigned_once(binding)
        if value is None or _dynamic_root(value) is None:
            return None
        return qualify(qualified_name(value))

    source_module = binding.source_module
    if not source_module:
        return None

    alias = binding.node
    if isinstance(alias, ast.alias) and (alias_ref := ref_or_none(alias)) is not None and isinstance(alias_ref.parent, ast.Import):
        # `import x [as y]` binds the module itself (e.g. `typing.cast`): its identity comes from
        # source_module, not the (possibly aliased) local name - but `import a.b` binds `a`, the
        # top package, not `a.b`
        return qualify(source_module if alias.asname else source_module.split('.')[0])

    # a bare `Name` - use `remote_name` (the name as written in the source module) when the
    # binding has one (e.g. `override` for `from typing import override as ov`), since `.name`
    # may be a local alias or a later-mangled name that means nothing in the source module
    return f"{source_module}.{binding.remote_name or binding.name}"
