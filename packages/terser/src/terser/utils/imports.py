from terser.ast import ast, ref
from .._pipeline.resolver.binding import ImportBinding


def qualified_name(node: ast.expr, /) -> str | None:
    """
    Resolve a `Name` or dotted `Attribute` expression to the dotted path of the
    import it refers to (e.g. `cast` after `from typing import cast` or
    `typing.cast` both resolve to `"typing.cast"`), using the already-computed
    name bindings. Returns None if the root name isn't an import, or its
    binding has no name.
    """

    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    attrs.reverse()

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
    # the (possibly aliased) local name. With no attrs, this is a bare `Name`
    # from a `from x import y` binding, where binding.name is the local
    # (possibly aliased) symbol name.
    tail = ".".join(attrs) if attrs else binding.name
    return f"{source_module}.{tail}"
