from __future__ import annotations

import fnmatch

from terser.ast import ast, ref
from terser.ast.ref._node import NodeRef
from .._module_graph import import_bindings, submodule_hops
from ..resolver import attach
from ..resolver.binder import alias_target
from .name_generator import name_filter

if __debug__ and __import__("typing").TYPE_CHECKING:
    from terser.ast import ModuleRef

    from ..dynamic_imports import DynamicImport


def __rename_dotted(dotted: str, new_dotted: dict[str, str]) -> str:
    """Rename every renamed segment of a dotted path, walking cumulative old prefixes."""

    parts = dotted.split('.')
    prefix = parts[0]
    result = [new_dotted.get(prefix, prefix)]

    for part in parts[1:]:
        prefix = f"{prefix}.{part}"
        renamed = new_dotted.get(prefix)
        result.append(renamed.rsplit('.', 1)[-1] if renamed is not None else part)

    return '.'.join(result)


def __rename_import_alias(alias: ast.alias, new_dotted: dict[str, str]):
    """Rename a plain `import x[.y[.z]] [as w]` alias's source text."""

    old_text = alias.name
    new_text = __rename_dotted(old_text, new_dotted)
    if new_text == old_text:
        return

    old_root, new_root = old_text.split('.')[0], new_text.split('.')[0]
    alias.name = new_text

    if alias.asname is not None or new_root == old_root:
        return

    if '.' not in new_text:
        # `import a` binds the module itself, so `as` keeps the name it's bound to
        alias.asname = old_root
        return

    # `import a.b.c` (no `as`) binds the root segment (`a`) - `as` would bind the leaf instead, and
    # the bare `import A.B.C` binds the new root `A`, a name nothing else in the namespace knows of
    # (to be taken by another binding, before or after it). `a = __import__('A.B.C')` imports the
    # same and binds `a` to the same root, binding no other name.
    __import_root(alias, old_root, new_text)


def __import_root(alias: ast.alias, name: str, dotted: str):
    """Replace `alias` of its `import` statement with `name = __import__(dotted)`."""

    stmt = ref(alias).parent
    parent = ref(stmt).parent
    namespace = ref(stmt).namespace
    body = next(value for _, value in ast.iter_fields(parent) if isinstance(value, list) and stmt in value)

    # `import a, b.c, d` imports in order: `import a` / `b = __import__('B.C')` / `import d`
    index = stmt.names.index(alias)
    before, after = stmt.names[:index], stmt.names[index + 1:]

    assign = ast.Assign(
        targets=[ast.Name(id=name, ctx=ast.Store())],
        value=ast.Call(func=ast.Name(id='__import__', ctx=ast.Load()), args=[ast.Constant(value=dotted)], keywords=[]),
    )
    replacement: list[ast.stmt] = [assign]

    if after:
        rest = ast.Import(names=after)
        NodeRef.new(rest, parent)
        ref(rest).namespace = namespace
        for other in after:
            ref(other).parent = rest
        replacement.append(rest)

    position = body.index(stmt)
    if before:
        stmt.names = before
        body[position + 1:position + 1] = replacement
    else:
        body[position:position + 1] = replacement

    attach(assign, parent, namespace)


def __rename_from_module(stmt: ast.ImportFrom, resolved_path: str | None, new_dotted: dict[str, str]):
    """Rename the `x` part of `from x import y`, following relative dots as-is."""

    if stmt.module is None or resolved_path is None:
        return

    new_path = new_dotted.get(resolved_path)
    if new_path is None:
        return

    count = stmt.module.count('.') + 1
    stmt.module = '.'.join(new_path.split('.')[-count:])


def __rename_submodule_alias(alias: ast.alias, submodule_path: str, new_dotted: dict[str, str]):
    """Rename the `y` part of `from x import y` when `y` is itself a submodule of `x`."""

    new_path = new_dotted.get(submodule_path)
    if new_path is None:
        return

    new_leaf = new_path.rsplit('.', 1)[-1]
    if new_leaf == alias.name:
        return

    if alias.asname is None:
        alias.asname = alias.name

    alias.name = new_leaf


def __rename_dynamic_import(found: DynamicImport, new_dotted: dict[str, str]):
    """Rewrite the literals of an `__import__()`/`importlib.import_module()` call naming renamed modules."""

    if found.name is None or found.target is None:
        return

    new_path = __rename_dotted(found.path, new_dotted)
    if found.dots:
        # a relative name keeps its dots, and names as many trailing segments as it did
        tail = found.name.value.lstrip('.')
        count = tail.count('.') + 1 if tail else 0
        new_tail = '.'.join(new_path.split('.')[-count:]) if count else ''
        found.name.value = '.' * (found.dots if found.callee != '__import__' else 0) + new_tail

        if found.package is not None:
            found.package.value = __rename_dotted(found.package.value, new_dotted)
    else:
        found.name.value = new_path

    for entry, submodule in found.submodules.items():
        entry.value = new_dotted.get(str(submodule.spec), str(submodule.spec)).rsplit('.', 1)[-1]


def __rename_hops(
    module_ref: ModuleRef, node: ast.expr, target: ModuleRef, project: dict[str, ModuleRef], new_dotted: dict[str, str],
):
    """Rename the submodule hops of an attribute chain reading off `target` (`x.a.b.name`)."""

    for attr_node, submodule_path in submodule_hops(node, target, project):
        # for `submodule_hops` to follow the chain later on, by the old path
        module_ref.submodule_hops[attr_node] = submodule_path
        attr_node.attr = new_dotted[submodule_path].rsplit('.', 1)[-1]


def mangle_modules(
    project: dict[str, ModuleRef],
    rename_modules: bool,
    preserved: set[str] | None = None,
    entry: set[str] | None = None,
) -> dict[str, str]:
    """
    Mangle module/package leaf names (file and directory basenames) across the whole project.

    Only the last dotted segment of each module's path is renamed - the directory hierarchy stays
    the same - and every import statement/attribute access in the project that refers to a renamed
    module is rewritten so behavior is preserved. Must run after `linker.link`, so every
    `ImportBinding.target` is resolved.

    Physically moving the renamed files is the caller's responsibility.

    :param project: Every module in the project, keyed by dotted module path
    :param rename_modules: If module/package names may be renamed
    :param preserved: Dotted-path glob patterns for modules that must keep their name
    :param entry: Dotted paths of entry modules - always preserved, since their filename may be
        invoked externally (e.g. as a script)
    :return: Every module's dotted path, old -> new (identity if not renamed)
    """

    identity = {dotted: dotted for dotted in project}
    if not rename_modules:
        return identity

    preserved = preserved or set()
    entry = entry or set()

    groups: dict[str, list[str]] = {}
    for dotted in project:
        parent, _, _ = dotted.rpartition('.')
        groups.setdefault(parent, []).append(dotted)

    new_leaf: dict[str, str] = {}
    for members in groups.values():
        used = set()
        renamable = []

        for dotted in members:
            if dotted in entry or any(fnmatch.fnmatch(dotted, pattern) for pattern in preserved):
                used.add(dotted.rsplit('.', 1)[-1])
            else:
                renamable.append(dotted)

        generator = name_filter()
        for dotted in renamable:
            name = next(n for n in generator if n not in used)
            new_leaf[dotted] = name
            used.add(name)

    new_dotted: dict[str, str] = {}
    for dotted in sorted(project, key=lambda d: d.count('.')):
        parent, _, leaf = dotted.rpartition('.')
        leaf = new_leaf.get(dotted, leaf)
        new_parent = new_dotted.get(parent, parent)
        new_dotted[dotted] = f"{new_parent}.{leaf}" if new_parent else leaf

    for module_ref in project.values():
        for binding in module_ref.import_targets:
            for alias in binding.aliases:
                linked = alias_target(module_ref, alias)
                unresolved = linked.unresolved
                stmt = ref(alias).parent

                if isinstance(stmt, ast.ImportFrom):
                    __rename_from_module(stmt, unresolved.path, new_dotted)

                    if (
                        unresolved.submodule_path is not None
                        and linked.target is not None
                        and str(linked.target.spec) == unresolved.submodule_path
                    ):
                        __rename_submodule_alias(alias, unresolved.submodule_path, new_dotted)
                else:
                    assert isinstance(stmt, ast.Import)
                    __rename_import_alias(alias, new_dotted)

        for stmt, unresolved in module_ref.wildcard_targets.items():
            __rename_from_module(stmt, unresolved.path, new_dotted)

        for binding in import_bindings(module_ref):
            if binding.target is None or binding.target_name is not None:
                continue

            for node in binding.references:
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                    continue

                __rename_hops(module_ref, node, binding.target, project, new_dotted)

        for found in module_ref.dynamic_imports:
            __rename_dynamic_import(found, new_dotted)

            if found.returns is not None:
                for root in found.roots:
                    __rename_hops(module_ref, root, found.returns, project, new_dotted)

    return new_dotted
