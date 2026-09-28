from __future__ import annotations

from terser.ast import ast, ref
from terser.ast.ref import ref_or_none
from .._module_graph import import_bindings, submodule_hops
from ..resolver.binder import alias_target
from ..resolver.binding import ImportBinding
from ._locals import NameAssigner, add_assigned
from .util import preserved_names

if __debug__ and __import__("typing").TYPE_CHECKING:
    from terser.ast import ModuleRef


def _disallow(project: dict[str, ModuleRef], rename_globals: bool, preserved: dict[str, list[str]]):
    for module_path, module_ref in project.items():
        preserve = preserved_names(module_path, preserved)

        for binding in module_ref.bindings:
            if not rename_globals or binding.name in preserve:
                binding.disallow_rename()


def _from_import_links(project: dict[str, ModuleRef]):
    """
    (alias node, local binding, origin binding) triples for `from x import y [as z]`, where `y`
    is a name bound in `x` (rather than a submodule of `x`) - once `y` is renamed, the alias's
    imported name must follow, independently of whatever local name `z`/`y` mangles to in the
    importer.
    """

    links = []

    for module_ref in project.values():
        for binding in module_ref.import_targets:
            for alias in binding.aliases:
                linked = alias_target(module_ref, alias)
                if linked.target is None or linked.target_name is None:
                    continue

                origin = next((b for b in linked.target.bindings if b.name == linked.target_name), None)
                if origin is not None:
                    links.append((alias, binding, origin))

    # `from x import *` upgraded bindings have no single alias node to update - not tracked here
    return links


def _walk_attribute_chain(node: ast.expr, target: ModuleRef, module_ref: ModuleRef, project: dict[str, ModuleRef]):
    """
    Walk an Attribute chain reading off an imported module (`x.a.b.c`), following submodules
    hop by hop until a hop resolves to an actual name instead of a further submodule (or the
    chain can't be resolved any further within the project).

    :param node: The node evaluating to `target`: the `ast.Name` an import binding is referenced
        by, or a dynamic import's root
    :param target: The module the import binding resolves to
    :param module_ref: The module `node` is in
    :param project: Every module in the project, keyed by dotted module path
    :return: The `(Attribute node, origin binding)` pair for the resolved name, or None
    """

    current, last = target, node
    for last, submodule_path in submodule_hops(node, target, project, module_ref.submodule_hops):
        current = project[submodule_path]

    attr_node = ref(last).parent
    if not (isinstance(attr_node, ast.Attribute) and attr_node.value is last):
        return None

    origin = next((b for b in current.bindings if b.name == attr_node.attr), None)
    return (attr_node, origin) if origin is not None else None


def _attribute_links(project: dict[str, ModuleRef]):
    """
    (Attribute node, origin binding) pairs for `import x.y` followed by `x.y.name` access, or
    `from x import y` followed by `y.name` access where `y` is itself a submodule - once
    `name` is renamed in the resolved module, every such attribute access must follow.
    """

    links = []

    for module_ref in project.values():
        # imports inside functions too
        for binding in import_bindings(module_ref):
            if binding.target is None or binding.target_name is not None:
                continue

            for node in binding.references:
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                    continue

                link = _walk_attribute_chain(node, binding.target, module_ref, project)
                if link is not None:
                    links.append(link)

        # what `__import__()`/`__lazy_import__()`/`importlib.import_module()` returns
        for found in module_ref.dynamic_imports:
            if found.returns is None:
                continue

            for root in found.roots:
                link = _walk_attribute_chain(root, found.returns, module_ref, project)
                if link is not None:
                    links.append(link)

    return links


def mark_imported(project: dict[str, ModuleRef]) -> None:
    """
    Mark the module-level bindings other modules of the linked `project` import (`from x import
    y`) or read (`x.y`) as preserved: they must stay bound, even once nothing in their own module
    reads them (an import re-exported without `__all__`, say).
    """

    for _, _, origin in _from_import_links(project):
        origin.mark_preserved()
    for _, origin in _attribute_links(project):
        origin.mark_preserved()
    for origin in _named_attribute_links(project):
        origin.mark_preserved()


_NAMED_ATTRIBUTE_FUNCTIONS = frozenset({'getattr', 'hasattr', 'setattr', 'delattr'})


def _named_attribute_links(project: dict[str, ModuleRef]):
    """
    The bindings read off an imported module by name: `hasattr(module, "name")` (numpy's
    `_core/__init__.py` checking `multiarray` for `_multiarray_umath`), and `getattr()` and the like
    """

    for module_ref in project.values():
        for node in ast.walk(module_ref.ast):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _NAMED_ATTRIBUTE_FUNCTIONS
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Name)
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
            ):
                continue
            binding = getattr(ref_or_none(node.args[0]), 'binding', None)
            if not isinstance(binding, ImportBinding) or binding.target is None or binding.target_name is not None:
                continue  # not a module of the project
            name = node.args[1].value
            yield from (b for b in binding.target.bindings if b.name == name)


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

    # importing a submodule sets it as an attribute of its package, replacing a global of the same name
    for dotted in project:
        parent, _, leaf = dotted.rpartition('.')
        if parent in project:
            ref(project[parent].ast).assigned_names.add(leaf)

    assigner = NameAssigner()
    pairs = [
        (module_ref.ast, binding)
        for module_ref in project.values()
        for binding in module_ref.bindings
    ]
    pairs.sort(key=lambda pair: pair[1].new_mention_count(), reverse=True)

    for namespace, binding in pairs:
        assigner.assign(namespace, binding)

    for alias_node, local, origin in from_import_links:
        alias_node.name = origin.name
        alias_node.asname = local.name if local.name != alias_node.name else None

    for attribute_node, origin in attribute_links:
        attribute_node.attr = origin.name
