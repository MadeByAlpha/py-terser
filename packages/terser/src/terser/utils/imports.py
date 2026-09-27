from terser.ast import ast, ref
from .._pipeline.resolver.binding import ImportBinding
from .._pipeline.resolver.dynamic_import import match_dynamic_import_call


def qualified_name(node: ast.expr, /) -> str | None:
    """
    Resolve a `Name` or dotted `Attribute` expression to the dotted path of the
    import it refers to (e.g. `cast` after `from typing import cast` or
    `typing.cast` both resolve to `"typing.cast"`), using the already-computed
    name bindings. Also recognizes an inline dynamic-import call directly (e.g.
    `__import__("typing").TYPE_CHECKING`), with no binding involved.

    Returns None if the root name isn't an import (or dynamic-import call), or its
    binding has no name.
    """

    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    attrs.reverse()

    if (source_module := match_dynamic_import_call(node)) is not None:
        return f"{source_module}.{'.'.join(attrs)}" if attrs else source_module

    if not isinstance(node, ast.Name):
        return None

    # some mangler-synthesized nodes are never fully registered with a NodeRef/binding
    # (e.g. an aliasing assignment for a keyword-callable renamed parameter) - treat
    # those as unresolvable rather than crashing
    try:
        binding = ref(node).binding
    except AttributeError:
        return None

    if not isinstance(binding, ImportBinding) or not binding.name:
        return None

    source_module = binding.source_module
    if not source_module:
        return None

    # `attrs` non-empty means this was a dotted access off an `import x` binding
    # (e.g. `typing.cast`) - the module identity comes from source_module, not
    # the (possibly aliased) local name. With no attrs, this is a bare `Name` - use
    # `remote_name` (the name as written in the source module) when the binding has
    # one (e.g. `override` for `from typing import override as ov`), since `.name` may
    # be a local alias or a later-mangled name that means nothing in the source module.
    tail = ".".join(attrs) if attrs else (binding.remote_name or binding.name)
    return f"{source_module}.{tail}"
