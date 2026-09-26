from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from ..resolver.binding import ImportBinding
from ._locals import NameAssigner, add_assigned
from .util import preserved_names

if TYPE_CHECKING:
    from terser.ast import ModuleRef


def _disallow(project: dict[str, ModuleRef], rename_globals: bool, preserved: dict[str, list[str]]):
    for module_path, module_ref in project.items():
        preserve = preserved_names(module_path, preserved)

        for binding in module_ref.bindings:
            if not rename_globals or binding.name in preserve:
                binding.disallow_rename()


def _from_import_links(project: dict[str, ModuleRef]):
    """
    (alias node, origin binding) pairs for `from x import y [as z]`, where `y` is a name bound
    in `x` (rather than a submodule of `x`) - once `y` is renamed, the alias's imported name
    must follow, independently of whatever local name `z`/`y` mangles to in the importer.
    """

    links = []

    for module_ref in project.values():
        for binding in module_ref.import_targets:
            if not isinstance(binding, ImportBinding) or binding.target is None or binding.target_name is None:
                continue

            if not isinstance(binding.node, ast.alias):
                # `from x import *` upgraded bindings have no single alias node to update -
                # not tracked here, see the module docstring.
                continue

            origin = next((b for b in binding.target.bindings if b.name == binding.target_name), None)
            if origin is not None:
                links.append((binding.node, origin))

    return links


def _walk_attribute_chain(node: ast.Name, target: ModuleRef, project: dict[str, ModuleRef]):
    """
    Walk an Attribute chain reading off an imported module (`x.a.b.c`), following submodules
    hop by hop until a hop resolves to an actual name instead of a further submodule (or the
    chain can't be resolved any further within the project).

    :param node: The `ast.Name` node the import binding is referenced by
    :param target: The module the import binding resolves to
    :param project: Every module in the project, keyed by dotted module path
    :return: The `(Attribute node, origin binding)` pair for the resolved name, or None
    """

    current = target
    attr_node = ref(node).parent

    while isinstance(attr_node, ast.Attribute) and attr_node.value is node:
        attr = attr_node.attr
        submodule = project.get(f"{current.spec}.{attr}")

        if submodule is not None:
            current = submodule
            node = attr_node
            attr_node = ref(node).parent
            continue

        origin = next((b for b in current.bindings if b.name == attr), None)
        return (attr_node, origin) if origin is not None else None

    return None


def _attribute_links(project: dict[str, ModuleRef]):
    """
    (Attribute node, origin binding) pairs for `import x.y` followed by `x.y.name` access, or
    `from x import y` followed by `y.name` access where `y` is itself a submodule - once
    `name` is renamed in the resolved module, every such attribute access must follow.
    """

    links = []

    for module_ref in project.values():
        for binding in module_ref.bindings:
            if not isinstance(binding, ImportBinding) or binding.target is None or binding.target_name is not None:
                continue

            for node in binding.references:
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                    continue

                link = _walk_attribute_chain(node, binding.target, project)
                if link is not None:
                    links.append(link)

    return links


def mangle_globals(project: dict[str, ModuleRef], rename_globals: bool = False, preserved: dict[str, list[str]] | None = None):
    """
    Mangle module-level (global) bindings across a whole project

    Must run after every module in the project has been through :func:`resolver.bind` and
    `linker.link`, so `ImportBinding.target`/`target_name` are resolved. Safe to run on a
    single-module project too (a plain `{str(module_ref.spec): module_ref}` dict).

    Each module keeps its own separate top-level namespace (Python doesn't merge globals across
    files), so names are still assigned per-module - the project-wide part is only in following
    every known cross-module reference (`from x import y`, and `import x.y; x.y.name` attribute
    access) so a rename doesn't break importers elsewhere in the project. References from outside
    the project (e.g. a consumer of this package) can't be tracked, so exported names should stay
    preserved unless the caller knows the project is self-contained.

    :param project: Every module in the project, keyed by dotted module path
    :param bool rename_globals: If module-level names may be renamed
    :param preserved: Names to leave unchanged, keyed by a glob pattern matched against each
        module's dotted path (e.g. ``{"foo.bar": ["baz"], "*": ["qux"]}``)
    """

    preserved = preserved or {}
    _disallow(project, rename_globals, preserved)

    if not rename_globals:
        return

    from_import_links = _from_import_links(project)
    attribute_links = _attribute_links(project)

    for module_ref in project.values():
        add_assigned(module_ref.ast)

    assigner = NameAssigner()
    pairs = [
        (module_ref.ast, binding)
        for module_ref in project.values()
        for binding in module_ref.bindings
    ]
    pairs.sort(key=lambda pair: pair[1].new_mention_count(), reverse=True)

    for namespace, binding in pairs:
        assigner.assign(namespace, binding)

    for alias_node, origin in from_import_links:
        alias_node.name = origin.name
        if alias_node.asname == alias_node.name:
            alias_node.asname = None

    for attribute_node, origin in attribute_links:
        attribute_node.attr = origin.name
