import fnmatch
from typing import TYPE_CHECKING

from anyio import Path

from terser.ast import ast, ref
from terser.ast.ref import spec as _spec
from .._module_graph import submodule_hops
from ..resolver.binding import ImportBinding
from .name_generator import name_filter

if TYPE_CHECKING:
    from terser.ast import ModuleRef
    type ModuleSpec = _spec.ModuleSpec


def _insert_after(stmt: ast.AST, new_stmt: ast.AST):
    """Insert `new_stmt` right after `stmt` in whichever statement list contains it."""

    parent = ref(stmt).parent
    for _, value in ast.iter_fields(parent):
        if isinstance(value, list) and stmt in value:
            value.insert(value.index(stmt) + 1, new_stmt)
            return


def _rename_dotted(dotted: str, new_dotted: dict[str, str]) -> str:
    """Rename every renamed segment of a dotted path, walking cumulative old prefixes."""

    parts = dotted.split('.')
    prefix = parts[0]
    result = [new_dotted.get(prefix, prefix)]

    for part in parts[1:]:
        prefix = f"{prefix}.{part}"
        renamed = new_dotted.get(prefix)
        result.append(renamed.rsplit('.', 1)[-1] if renamed is not None else part)

    return '.'.join(result)


def _rename_import_alias(alias: ast.alias, new_dotted: dict[str, str]):
    """Rename a plain `import x[.y[.z]] [as w]` alias's source text."""

    old_text = alias.name
    new_text = _rename_dotted(old_text, new_dotted)
    if new_text == old_text:
        return

    old_root, new_root = old_text.split('.')[0], new_text.split('.')[0]
    alias.name = new_text

    if alias.asname is None and new_root != old_root:
        # `import a.b.c` (no `as`) binds the root segment (`a`) as the local name - adding
        # `as a` here would instead bind the *leaf* module (`as` always targets the leaf on a
        # dotted import), which is a different object. Keep the statement bare (so it still
        # binds the new root under its own name) and re-point the old local name at it instead.
        _insert_after(
            ref(alias).parent,
            ast.Assign(
                targets=[ast.Name(id=old_root, ctx=ast.Store())],
                value=ast.Name(id=new_root, ctx=ast.Load()),
            ),
        )


def _rename_from_module(stmt: ast.ImportFrom, resolved_path: str | None, new_dotted: dict[str, str]):
    """Rename the `x` part of `from x import y`, following relative dots as-is."""

    if stmt.module is None or resolved_path is None:
        return

    new_path = new_dotted.get(resolved_path)
    if new_path is None:
        return

    count = stmt.module.count('.') + 1
    stmt.module = '.'.join(new_path.split('.')[-count:])


def _rename_submodule_alias(alias: ast.alias, submodule_path: str, new_dotted: dict[str, str]):
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


def module_output_path(spec: ModuleSpec, new_dotted: dict[str, str]) -> Path:
    """The relative output path a module should be written to, reflecting its mangled name."""

    parts = new_dotted.get(str(spec), str(spec)).split('.')
    if isinstance(spec, _spec.PackageSpec):
        return Path(*parts, "__init__.py")
    return Path(*parts[:-1], parts[-1] + spec.path.suffix)


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

    Physically moving the renamed files is the caller's responsibility - see `module_output_path`.

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
        for binding, unresolved in module_ref.import_targets.items():
            node = binding.node
            stmt = ref(node).parent

            if isinstance(stmt, ast.ImportFrom):
                _rename_from_module(stmt, unresolved.path, new_dotted)

                if (
                    unresolved.submodule_path is not None
                    and binding.target is not None
                    and str(binding.target.spec) == unresolved.submodule_path
                ):
                    _rename_submodule_alias(node, unresolved.submodule_path, new_dotted)
            else:
                assert isinstance(stmt, ast.Import)
                _rename_import_alias(node, new_dotted)

        for stmt, unresolved in module_ref.wildcard_targets.items():
            _rename_from_module(stmt, unresolved.path, new_dotted)

        for binding in module_ref.bindings:
            if not isinstance(binding, ImportBinding) or binding.target is None or binding.target_name is not None:
                continue

            for node in binding.references:
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                    continue

                for attr_node, submodule_path in submodule_hops(node, binding.target, project):
                    new_path = new_dotted.get(submodule_path)
                    if new_path is not None:
                        attr_node.attr = new_path.rsplit('.', 1)[-1]

    return new_dotted
