"""
Edits to a module after its names are resolved and bound, keeping the bindings in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from terser.ast.ref._node import NodeRef
from ..parser._scope import ScopeResolver
from .binder._bind import bind as bind_names
from .resolver import resolve_subtree
from .util import scope_ref_global

if TYPE_CHECKING:
    from terser.ast.ref import ContainsScope


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
