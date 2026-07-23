from typing import TYPE_CHECKING

from ._module_graph import dependencies

if TYPE_CHECKING:
    from terser.ast import ModuleRef


def _ancestors(dotted: str):
    while '.' in dotted:
        dotted = dotted.rsplit('.', 1)[0]
        yield dotted


def shake(project: dict[str, ModuleRef], entry: set[str]) -> dict[str, ModuleRef]:
    """
    Drop every module in `project` that isn't reachable from `entry`.

    Must run after `linker.link`, so every `ImportBinding.target` is resolved. A module is
    reachable if it's an entry point, an ancestor package of a reachable module (Python has to
    import the whole package chain to reach a submodule), or imported by a reachable module.

    If `entry` is empty, tree-shaking is a no-op - without a caller-provided entry point there's
    no basis to tell a genuinely dead module from a library's public surface.

    :param project: Every module in the project, keyed by dotted module path
    :param entry: Dotted paths of the project's entry modules
    :return: The subset of `project` reachable from `entry`
    """

    if not entry:
        return project

    reachable: set[str] = set()
    queue = [dotted for dotted in entry if dotted in project]

    while queue:
        dotted = queue.pop()
        if dotted in reachable:
            continue
        reachable.add(dotted)

        queue.extend(ancestor for ancestor in _ancestors(dotted) if ancestor not in reachable)
        queue.extend(dep for dep in dependencies(project[dotted], project) if dep not in reachable)

    return {dotted: module_ref for dotted, module_ref in project.items() if dotted in reachable}
