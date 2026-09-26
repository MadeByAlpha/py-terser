from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from .resolver.binding import ImportBinding

if TYPE_CHECKING:
    from terser.ast import ModuleRef
    from .resolver.binder import UnresolvedModuleRef


def _link_alias(
    binding: ImportBinding,
    unresolved: UnresolvedModuleRef,
    project: dict[str, ModuleRef]
) -> None:
    package_target = project.get(unresolved.path) if unresolved.path is not None else None

    if unresolved.submodule_path is None:
        # plain `import x[.y]` - unambiguous, the binding always refers to the module itself
        binding.target = package_target
        return

    name = binding.node.name  # the imported attribute/submodule name
    if package_target is not None and any(binding.name == name for binding in package_target.bindings):
        binding.target = package_target
        binding.target_name = name
        return

    submodule_target = project.get(unresolved.submodule_path) if unresolved.submodule_path is not None else None
    if submodule_target is not None:
        binding.target = submodule_target
        return

    if package_target is not None:
        # x resolves within the project, but y is neither a binding nor a submodule of it,
        # e.g. provided dynamically through x's __getattr__ (PEP 562)
        binding.target = package_target
        binding.disallow_rename()

    # else: x itself is stdlib / third-party - leave binding.target as None


def _link_wildcard(
    module_ref: ModuleRef,
    stmt: ast.ImportFrom,
    unresolved: UnresolvedModuleRef,
    project: dict[str, ModuleRef]
) -> None:
    target = project.get(unresolved.path) if unresolved.path is not None else None

    if target is None:
        # Can't enumerate an external module's exports statically
        module_ref.tainted = True
        return

    exported = {binding.name for binding in target.bindings if binding._exported}

    for index, binding in enumerate(module_ref.bindings):
        if binding.name not in exported or not all(
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) for node in binding.references
        ):
            continue  # unused, or shadowed by a real local definition - the wildcard doesn't apply

        upgraded = ImportBinding(binding.name, stmt, module_ref)
        for node in binding.references:
            upgraded.add_reference(node)

        upgraded.target = target
        upgraded.target_name = binding.name  # exported implies target actually has this binding

        module_ref.bindings[index] = upgraded


def link(module: ast.Module, project: dict[str, ModuleRef]) -> None:
    """
    Resolve every import's target and expand wildcard imports, using the other modules in the
    project. Must run after every module in the project has run `resolve_imports`, `mark_exports`
    and `binder.resolve` (the latter so undefined-but-used names have their fallback binding, for
    `_link_wildcard` to upgrade).

    :param module: The module to link imports for
    :param project: Every module in the project, keyed by resolved module path
    """

    module_ref = ref(module)

    for binding, unresolved in module_ref.import_targets.items():
        _link_alias(binding, unresolved, project)

    for stmt, unresolved in module_ref.wildcard_targets.items():
        _link_wildcard(module_ref, stmt, unresolved, project)
