from __future__ import annotations

import re
from pathlib import Path

from ._module_graph import dependencies, imported_paths

if __debug__ and __import__("typing").TYPE_CHECKING:
    from collections.abc import Mapping

    from terser.ast import ModuleRef

_DOTTED = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def __ancestors(dotted: str):
    while '.' in dotted:
        dotted = dotted.rsplit('.', 1)[0]
        yield dotted


def binary_dependencies(path: str, project: Mapping[str, object]) -> set[str]:
    """
    The modules of `project` a native extension may import: what it imports is out of sight, but
    its module names are in the binary, as the strings it hands `PyImport_ImportModule()`
    (`numpy._core._exceptions`, in numpy's `_multiarray_umath`).
    """

    data = Path(path).read_bytes()
    return {name for match in _DOTTED.finditer(data) if (name := match.group().decode()) in project}


def shake(project: dict[str, ModuleRef], entry: set[str], binaries: Mapping[str, str] | None = None) -> dict[str, ModuleRef]:
    """
    Drop every module in `project` that isn't reachable from `entry`.

    Must run after `linker.link`, so every `ImportBinding.target` is resolved. A module is
    reachable if it's an entry point, an ancestor package of a reachable module (Python has to
    import the whole package chain to reach a submodule), or imported by a reachable module.

    If `entry` is empty, tree-shaking is a no-op - without a caller-provided entry point there's
    no basis to tell a genuinely dead module from a library's public surface.

    A native extension (of `binaries`) a reachable module imports makes the modules it names
    reachable too (see `binary_dependencies`).

    :param project: Every module in the project, keyed by dotted module path
    :param entry: Dotted paths of the project's entry modules
    :param binaries: The project's native extensions, their files by dotted module path
    :return: The subset of `project` reachable from `entry`
    """

    if not entry:
        return project

    reachable: set[str] = set()
    queue = [dotted for dotted in entry if dotted in project]

    binaries = binaries or {}
    loaded: set[str] = set()

    while queue:
        dotted = queue.pop()
        if dotted in reachable:
            continue
        reachable.add(dotted)

        # a namespace package (no `__init__.py`) is no module of the project
        queue.extend(ancestor for ancestor in __ancestors(dotted) if ancestor in project and ancestor not in reachable)
        queue.extend(dep for dep in dependencies(project[dotted], project) if dep not in reachable)

        for binary in imported_paths(project[dotted]) & binaries.keys() - loaded:
            loaded.add(binary)
            queue.extend(dep for dep in binary_dependencies(binaries[binary], project) if dep not in reachable)

    return {dotted: module_ref for dotted, module_ref in project.items() if dotted in reachable}
