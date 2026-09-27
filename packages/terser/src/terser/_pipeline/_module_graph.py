from __future__ import annotations

from terser.ast import ast, ref
from .resolver.binder import alias_target
from .resolver.binding import ImportBinding

if __debug__ and __import__("typing").TYPE_CHECKING:
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


def submodule_hops(node: ast.expr, target: ModuleRef, project: dict[str, ModuleRef], renamed: dict[ast.Attribute, str] | None = None):
    """
    (Attribute node, submodule dotted path) pairs for every submodule hop in an attribute chain
    reading off an imported package (`x.a.b.c`), hopping submodule by submodule until a hop
    resolves to an actual name instead of a further submodule (or the chain can't be resolved any
    further within the project). Shared by `tree_shake` (to mark the hopped-through submodules
    reachable), `mangler._modules` (to rename them if hopped-through) and `mangler._globals` (to
    find the name the chain ends at).

    `mangler._modules` keeps every hop it renames in `ModuleRef.submodule_hops`, by the submodule's
    old dotted path: given as `renamed`, the chain is still followed once the hops are renamed.
    """

    renamed = renamed or {}
    hops = []
    current = target
    chain_node: ast.AST = node
    attr_node = ref(chain_node).parent

    while isinstance(attr_node, ast.Attribute) and attr_node.value is chain_node:
        if (submodule_path := renamed.get(attr_node)) is not None:
            # a hop renaming modules already found, and renamed: its `attr` is the new name
            submodule = project[submodule_path]
        else:
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


def imported_paths(module_ref: ModuleRef) -> set[str]:
    """Every dotted path the import statements of `module_ref` may import, in the project or not"""

    paths = set()
    for binding in module_ref.import_targets:
        for alias in binding.aliases:
            unresolved = alias_target(module_ref, alias).unresolved
            paths.update(p for p in (unresolved.path, unresolved.submodule_path) if p is not None)
    for found in module_ref.dynamic_imports:
        if found.path is not None:
            paths.add(found.path)
    return paths


def dependencies(module_ref: ModuleRef, project: dict[str, ModuleRef]) -> set[str]:
    """
    Every module `module_ref` depends on: each resolved import target, plus every submodule
    reached by hopping through an attribute chain off a root-package import (`import x.y.z`
    without `as` only binds `x` - `y`/`z` are only visible as attribute hops at usage sites).
    """

    deps: set[str] = set()

    # every statement importing a name, where more than one does (`try: from ._speedups import f`
    # / `except ImportError: from ._native import f`)
    for binding in module_ref.import_targets:
        for alias in binding.aliases:
            if (target := alias_target(module_ref, alias).target) is not None:
                deps.add(str(target.spec))

    # `from x import *` imports x, whether a name it provides is used or not
    for unresolved in module_ref.wildcard_targets.values():
        if unresolved.path is not None and unresolved.path in project:
            deps.add(unresolved.path)

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
