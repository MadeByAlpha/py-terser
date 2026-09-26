from __future__ import annotations

import builtins
from typing import TYPE_CHECKING

from terser.ast import ModuleRef, ast, ref
from ..binding import Binding, BuiltinBinding, UnresolvedBinding
from ..util import scope_ref_global, scope_ref_nonlocal
from ...parser._scope import ScopeResolver

if TYPE_CHECKING:
    from terser.ast.ref import ScopedNode


def __get_binding(name: str, namespace_ref: ScopedNode) -> Binding:
    if name in namespace_ref.globals and not isinstance(namespace_ref, ModuleRef):
        return __get_binding(name, scope_ref_global(namespace_ref.ast))
    elif name in namespace_ref.nonlocals and not isinstance(namespace_ref, ModuleRef):
        return __get_binding(name, scope_ref_nonlocal(namespace_ref.ast))

    for binding in namespace_ref.bindings:
        if binding.name == name:
            return binding

    if not isinstance(namespace_ref, ModuleRef):
        return __get_binding(name, scope_ref_nonlocal(namespace_ref.ast))

    else:
        # This is unresolved at global scope - is it a builtin?
        if name in dir(builtins):
            if name in ['exec', 'eval', 'locals', 'globals', 'vars']:
                namespace_ref.tainted = True

            binding = BuiltinBinding(name, namespace_ref.ast)
            namespace_ref.bindings.append(binding)
            return binding

        else:
            binding = UnresolvedBinding(name)
            namespace_ref.bindings.append(binding)
            return binding


def __attr_get_binding(name: str, namespace: ScopedNode) -> Binding:
    binding = __get_binding(name, namespace)

    if isinstance(namespace.ast, ast.ClassDef):
        # This name will become an attribute of a class, so it can't be renamed
        binding.disallow_rename()

    return binding


def bind(node: ast.AST):
    """
    Resolve unbound names to a NameBinding

    :param node: The node to resolve names in
    """
    namespace = ref(node).namespace
    namespace_ref = ref(namespace)

    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        __get_binding(node.id, namespace_ref).add_reference(node)
    elif isinstance(node, ast.Name) and node.id in namespace_ref.nonlocals:
        binding = __get_binding(node.id, namespace_ref)
        binding.add_reference(node)

        if isinstance(node.ctx, ast.Store) and isinstance(namespace, ast.ClassDef):
            binding.disallow_rename()

    elif isinstance(node, ast.ClassDef) and node.name in namespace_ref.nonlocals:
        binding = __attr_get_binding(node.name, namespace_ref)
        binding.add_reference(node)

    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in namespace_ref.nonlocals:
        binding = __attr_get_binding(node.name, namespace_ref)
        binding.add_reference(node)

    elif isinstance(node, ast.alias):

        if node.asname is not None:
            if node.asname in namespace_ref.nonlocals:
                binding = __attr_get_binding(node.asname, namespace_ref)
                binding.add_reference(node)

        else:
            # This binds the root module only for a dotted import
            root_module = node.name.split('.')[0]

            if root_module in namespace_ref.nonlocals:
                binding = __attr_get_binding(root_module, namespace_ref)
                binding.add_reference(node)

                if '.' in node.name:
                    binding.disallow_rename()

    elif isinstance(node, ast.ExceptHandler) and node.name is not None:
        if isinstance(node.name, str) and node.name in namespace_ref.nonlocals:
            __attr_get_binding(node.name, namespace_ref).add_reference(node)

    elif isinstance(node, ast.Nonlocal):
        for name in node.names:
            __attr_get_binding(name, namespace_ref).add_reference(node)
    elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name in namespace_ref.nonlocals:
        assert node.name
        __attr_get_binding(node.name, namespace_ref).add_reference(node)
    elif isinstance(node, ast.MatchMapping) and node.rest in namespace_ref.nonlocals:
        assert node.rest
        __attr_get_binding(node.rest, namespace_ref).add_reference(node)

    elif isinstance(node, ast.Exec):
        scope_ref_global(node).tainted = True

    for child in ast.iter_child_nodes(node):
        bind(child)
