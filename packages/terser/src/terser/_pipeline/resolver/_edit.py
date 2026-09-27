"""
Edits to a module after its names are resolved and bound, keeping the bindings in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, is_scoped, ref
from terser.ast.ref import ref_or_none
from terser.ast.ref._node import NodeRef
from ..parser._scope import ScopeResolver
from .binder._bind import bind as bind_names
from .binder._resolve_imports import alias_target
from .binding import BuiltinBinding, ImportBinding, UnresolvedBinding
from .resolver import resolve_subtree
from .util import scope_ref_global

if __debug__ and __import__("typing").TYPE_CHECKING:
    from terser.ast.ref import ContainsScope, ScopedNode
    from .binding import Binding


def attach(child: ast.AST, parent: ast.AST, namespace: ContainsScope):
    """
    Resolve and bind the names of `child`, a new subtree placed under `parent` in `namespace`, the
    way the rest of the module already is.
    """

    NodeRef.new(child, parent)._resolve_all()
    ScopeResolver.child(child, namespace=namespace)

    # Names have already been resolved/bound for the rest of the module by this point,
    # so newly added nodes need the same treatment done incrementally instead of a full re-resolve.
    resolve_subtree(child, scope_ref_global(namespace))
    bind_names(child)

    return child


_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _evaluated_here(node: ast.AST):
    """
    The nodes of `node` evaluated in its own scope: of a nested function or class, only what its
    definition evaluates (decorators, defaults, annotations, bases), not its body.
    """

    yield node

    if isinstance(node, _DEFINITIONS):
        fields = ('decorator_list', 'args', 'returns', 'bases', 'keywords')
        children = [
            child for field in fields
            for value in [getattr(node, field, None)]
            for child in (value if isinstance(value, list) else [value])
            if isinstance(child, ast.AST)
        ]
    else:
        children = ast.iter_child_nodes(node)

    for child in children:
        yield from _evaluated_here(child)


def _is_load(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)


def _binding_of(node: ast.AST) -> Binding | None:
    return getattr(ref_or_none(node), '_binding', None)


def removable(nodes: list[ast.AST]) -> bool:
    """
    If code that never runs (`nodes`, the branch of an `if False:`) can be removed without
    changing what the code around it does. Code that never runs still takes part in compiling
    its function:

    - a `yield` makes it a generator (`if False: yield`);
    - `global`/`nonlocal` decide the scope of a name for the whole function;
    - binding a name makes it local to the function, so the other references of a name bound
      nowhere else would look it up elsewhere.
    """

    if any(
        isinstance(node, (ast.Yield, ast.YieldFrom, ast.Global, ast.Nonlocal))
        for root in nodes for node in _evaluated_here(root)
    ):
        return False

    removed = {id(node) for root in nodes for node in ast.walk(root)}
    for root in nodes:
        for node in ast.walk(root):
            if _is_load(node) or (binding := _binding_of(node)) is None:
                continue

            namespace = ref(node).namespace
            if isinstance(namespace, (ast.Module, ast.ClassDef)) or binding.name in ref(namespace).globals:
                continue  # looked up by name at run time, bound or not

            remaining = [other for other in binding.references if id(other) not in removed]
            if remaining and all(_is_load(other) for other in remaining):
                return False

    return True


def _namespace_of(binding: Binding, node: ast.AST) -> ScopedNode | None:
    namespace = ref(node).namespace
    while True:
        namespace_ref = ref(namespace)
        if any(other is binding for other in namespace_ref.bindings):
            return namespace_ref
        if isinstance(namespace, ast.Module):
            return None
        namespace = namespace_ref.namespace


def _under(node: ast.AST, scopes: set[int]) -> bool:
    """If `node` is in one of the namespaces `scopes`, as far as NodeRefs tell"""

    while (node_ref := ref_or_none(node)) is not None and not isinstance(node, ast.Module):
        node = node_ref.namespace
        if id(node) in scopes:
            return True
    return False


def forget(nodes: list[ast.AST]) -> None:
    """
    Forget the references `nodes` make, once they are taken out of the module: a name nothing
    binds any more is bound again where it's still used (in an enclosing namespace, as a builtin,
    or unresolved), and an import removed is no longer one the module makes.
    """

    if not nodes:
        return

    # nodes made after the module was parsed may have no NodeRef, nor bindings
    known = next((node for root in nodes for node in ast.walk(root) if ref_or_none(node) is not None), None)
    if known is None:
        return
    module_ref = scope_ref_global(known)
    removed = {id(node) for root in nodes for node in ast.walk(root)}
    touched: dict[int, tuple[Binding, ast.AST]] = {}

    for root in nodes:
        for node in ast.walk(root):
            if (binding := _binding_of(node)) is not None:
                touched.setdefault(id(binding), (binding, node))
            if isinstance(node, ast.alias):
                module_ref.import_aliases.pop(node, None)
            elif isinstance(node, ast.ImportFrom):
                module_ref.wildcard_targets.pop(node, None)

    module_ref.dynamic_imports = [found for found in module_ref.dynamic_imports if id(found.call) not in removed]

    # references a transform took out of a function or class without forgetting them (e.g. of the
    # annotations it removed) still lead to it, for as long as they are known
    if scopes := {id(node) for root in nodes for node in ast.walk(root) if is_scoped(node)}:
        for namespace in ast.walk(module_ref.ast):
            if not is_scoped(namespace) or id(namespace) in scopes:
                continue
            for binding in ref(namespace).bindings:
                for other in binding.references:
                    if id(other) not in removed and _under(other, scopes):
                        removed.add(id(other))
                        touched.setdefault(id(binding), (binding, other))

    for binding, node in touched.values():
        references = binding.references
        references[:] = [other for other in references if id(other) not in removed]

        if isinstance(binding, ImportBinding) and binding in module_ref.import_targets:
            if aliases := [other for other in references if isinstance(other, ast.alias)]:
                if id(binding.node) in removed:
                    binding.node = aliases[0]
                    linked = alias_target(module_ref, aliases[0])
                    module_ref.import_targets[binding] = linked.unresolved
                    binding.target, binding.target_name = linked.target, linked.target_name
                continue

            del module_ref.import_targets[binding]

        if isinstance(binding, (BuiltinBinding, UnresolvedBinding)):
            if not references and (namespace_ref := _namespace_of(binding, node)) is not None:
                namespace_ref.bindings.remove(binding)
            continue

        if not all(_is_load(other) for other in references):
            continue  # still bound

        if (namespace_ref := _namespace_of(binding, node)) is not None:
            namespace_ref.bindings.remove(binding)
        for other in references:
            # bound again by `bind_names`, to what the name is now
            bind_names(other)
