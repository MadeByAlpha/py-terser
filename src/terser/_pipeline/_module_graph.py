from typing import TYPE_CHECKING

from terser.ast import ast, ref
from .resolver.binding import ImportBinding

if TYPE_CHECKING:
    from terser.ast import ModuleRef


def submodule_hops(node: ast.Name, target: ModuleRef, project: dict[str, ModuleRef]):
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
        if submodule is None:
            break

        hops.append((attr_node, submodule_path))
        current = submodule
        chain_node = attr_node
        attr_node = ref(chain_node).parent

    return hops


def dependencies(module_ref: ModuleRef, project: dict[str, ModuleRef]) -> set[str]:
    """
    Every module `module_ref` depends on: each resolved import target, plus every submodule
    reached by hopping through an attribute chain off a root-package import (`import x.y.z`
    without `as` only binds `x` - `y`/`z` are only visible as attribute hops at usage sites).
    """

    deps: set[str] = set()

    for binding in module_ref.bindings:
        if not isinstance(binding, ImportBinding) or binding.target is None:
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

    return deps
