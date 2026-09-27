from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from .resolver.binding import ImportBinding

if TYPE_CHECKING:
    from terser.ast import ModuleRef


def __shadowed(package: ModuleRef, name: str, submodule: ModuleRef) -> bool:
    """
    If the package binds `name` itself, to something else than its submodule of that name:
    importing the submodule sets the package's attribute, but a binding in the package's own
    namespace takes it over (`from .version import version` leaves `pkg.version` a string).
    """

    return any(
        binding.name == name and not (
            # the submodule itself (`from . import sub`), not a name in it
            isinstance(binding, ImportBinding) and binding.target is submodule and binding.target_name is None
        )
        for binding in package.bindings
    )


def submodule_hops(node: ast.expr, target: ModuleRef, project: dict[str, ModuleRef]):
    """
    (Attribute node, submodule dotted path) pairs for every submodule hop in an attribute chain
    reading off an imported package (`x.a.b.c`), hopping submodule by submodule until a hop
    resolves to an actual name instead of a further submodule (or the chain can't be resolved any
    further within the project). Shared by `tree_shake` (to mark the hopped-through submodules
    reachable) and `mangler._modules` (to rename them if hopped-through).
    """

    hops = []
    current = target
    chain_node: ast.AST = node
    attr_node = ref(chain_node).parent

    while isinstance(attr_node, ast.Attribute) and attr_node.value is chain_node:
        submodule_path = f"{current.spec}.{attr_node.attr}"
        submodule = project.get(submodule_path)
        if submodule is None or __shadowed(current, attr_node.attr, submodule):
            break

        hops.append((attr_node, submodule_path))
        current = submodule
        chain_node = attr_node
        attr_node = ref(chain_node).parent

    return hops


def import_bindings(module_ref: ModuleRef) -> list[ImportBinding]:
    """
    Every import binding of a module, in any of its namespaces: those of its import statements
    (at any depth - an import inside a function is a dependency all the same), and the names
    its wildcard imports provide.
    """

    bindings = list(module_ref.import_targets)
    seen = set(bindings)
    bindings.extend(
        binding for binding in module_ref.bindings
        if isinstance(binding, ImportBinding) and binding not in seen
    )
    return bindings


def dependencies(module_ref: ModuleRef, project: dict[str, ModuleRef]) -> set[str]:
    """
    Every module `module_ref` depends on: each resolved import target, plus every submodule
    reached by hopping through an attribute chain off a root-package import (`import x.y.z`
    without `as` only binds `x` - `y`/`z` are only visible as attribute hops at usage sites).
    """

    deps: set[str] = set()

    for binding in import_bindings(module_ref):
        if binding.target is None:
            continue

        deps.add(str(binding.target.spec))

        if binding.target_name is not None:
            # resolved to a plain name in the target module, not a submodule - no further hops
            continue

        for node in binding.references:
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue

            for _, submodule_path in submodule_hops(node, binding.target, project):
                deps.add(submodule_path)

    for found in module_ref.dynamic_imports:
        for target in (found.target, found.returns, *found.submodules.values()):
            if target is not None:
                deps.add(str(target.spec))

        if found.returns is not None:
            for root in found.roots:
                for _, submodule_path in submodule_hops(root, found.returns, project):
                    deps.add(submodule_path)

    return deps
