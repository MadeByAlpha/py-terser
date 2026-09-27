"""
Imports made by calling `__import__()` or `importlib.import_module()`.

When every argument naming the module is a literal (a `LiteralString`), the call is as static as
an import statement: `find` resolves the module it imports, `link` ties it to the project, and
tree-shaking and module renaming follow it like any other import - the latter rewriting the
literals. The module a call returns is followed too, where it's used right away
(`__import__("a.b").b.name`) or kept in a name assigned once (`m = import_module("a"); m.name`).

A call whose module name is only known at run time is kept in `ModuleRef.dynamic_imports` as
well, unresolved, for the pipeline to warn about when it relies on knowing every import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, ref
from .resolver.binding import BuiltinBinding, ImportBinding

if TYPE_CHECKING:
    from terser.ast import ModuleRef


class DynamicImport:
    """
    One call to `__import__()` or `importlib.import_module()`.

    :ivar call: The call
    :ivar callee: `__import__` or `importlib.import_module`, for messages
    :ivar name: The literal naming the module - None when it's not one, and the import unresolved
    :ivar package: `import_module()`'s literal package, that a relative name is resolved against
    :ivar dots: How many levels up a relative name starts (`level` for `__import__()`, the leading
        dots otherwise)
    :ivar path: The dotted path of the module imported, None if unresolved
    :ivar fromlist: `__import__()`'s literal `fromlist` entries, that may be submodules to import too
    :ivar returned: The dotted path of the module the call evaluates to, None if unknown
    :ivar roots: Nodes evaluating to the returned module: the call, and the loads of a name it's
        assigned to once
    :ivar target: The module imported, once linked and if in the project
    :ivar submodules: The `fromlist` entries that are submodules of `target`, by entry literal
    """

    __slots__ = (
        'call', 'callee', 'name', 'package', 'dots', 'path', 'fromlist', 'returned', 'roots',
        'target', 'returns', 'submodules',
    )

    def __init__(self, call: ast.Call, callee: str):
        self.call = call
        self.callee = callee
        self.name: ast.Constant | None = None
        self.package: ast.Constant | None = None
        self.dots = 0
        self.path: str | None = None
        self.fromlist: list[ast.Constant] = []
        self.returned: str | None = None
        self.roots: list[ast.AST] = []

        self.target: ModuleRef | None = None
        self.returns: ModuleRef | None = None
        self.submodules: dict[ast.Constant, ModuleRef] = {}

    @property
    def literals(self) -> list[ast.Constant]:
        """The literals naming modules: pinned, so literal hoisting leaves them in the call."""

        return [node for node in (self.name, self.package, *self.fromlist) if node is not None]

    @property
    def location(self) -> str:
        return f"line {self.call.lineno}" if hasattr(self.call, 'lineno') else "somewhere"


def _string(node: ast.AST | None) -> ast.Constant | None:
    return node if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _argument(call: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(call.args) > position:
        return call.args[position]
    return next((kw.value for kw in call.keywords if kw.arg == keyword), None)


def _callee(call: ast.Call) -> str | None:
    """`__import__`/`importlib.import_module`, if that's what `call` calls."""

    func = call.func

    if isinstance(func, ast.Name):
        binding = ref(func).binding
        if isinstance(binding, BuiltinBinding) and binding.name == '__import__':
            return '__import__'
        # `from importlib import import_module [as y]`
        if (
            isinstance(binding, ImportBinding) and binding.source_module == 'importlib'
            and isinstance(binding.node, ast.alias) and isinstance(ref(binding.node).parent, ast.ImportFrom)
            and binding.node.name == 'import_module'
        ):
            return 'importlib.import_module'

    # `import importlib [as x]`, then `x.import_module(...)`
    if isinstance(func, ast.Attribute) and func.attr == 'import_module' and isinstance(func.value, ast.Name):
        binding = ref(func.value).binding
        if (
            isinstance(binding, ImportBinding) and binding.source_module == 'importlib'
            and isinstance(binding.node, ast.alias) and isinstance(ref(binding.node).parent, ast.Import)
            and binding.node.name == 'importlib'
        ):
            return 'importlib.import_module'

    return None


def _resolve(module_ref: ModuleRef, relative: str) -> str | None:
    try:
        return module_ref.spec.resolve(relative)
    except ImportError:
        return None


def _import_module(module_ref: ModuleRef, found: DynamicImport) -> None:
    call = found.call
    if (name := _string(_argument(call, 0, 'name'))) is None or call.args[2:]:
        return

    stripped = name.value.lstrip('.')
    found.dots = len(name.value) - len(stripped)

    if found.dots:
        package_node = _argument(call, 1, 'package')
        if (package := _string(package_node)) is not None:
            # `importlib.util.resolve_name()`, without importing anything
            parts = package.value.split('.')
            if found.dots > len(parts):
                return
            base = '.'.join(parts[:len(parts) - found.dots + 1])
            path = f"{base}.{stripped}" if stripped else base
            found.package = package
        elif isinstance(package_node, ast.Name) and package_node.id == '__package__':
            # this module's own package: resolved the way a relative import statement is
            path = _resolve(module_ref, name.value)
        else:
            return
    else:
        path = stripped

    if path:
        found.name, found.path, found.returned = name, path, path


def _dunder_import(module_ref: ModuleRef, found: DynamicImport) -> None:
    call = found.call
    if (name := _string(_argument(call, 0, 'name'))) is None or call.args[5:]:
        return

    level_node = _argument(call, 4, 'level')
    if level_node is None:
        level = 0
    elif isinstance(level_node, ast.Constant) and type(level_node.value) is int and level_node.value >= 0:
        level = level_node.value
    else:
        return

    fromlist_node = _argument(call, 3, 'fromlist')
    if fromlist_node is None or (isinstance(fromlist_node, ast.Constant) and fromlist_node.value is None):
        fromlist = []
    elif isinstance(fromlist_node, (ast.List, ast.Tuple)) and all(_string(e) for e in fromlist_node.elts):
        fromlist = list(fromlist_node.elts)
    else:
        # the module is still known, not what the call returns
        fromlist = None

    if level:
        # relative to this module's package, which `globals` tells the import system
        path = _resolve(module_ref, '.' * level + name.value)
    elif name.value.startswith('.'):
        return  # a relative name needs a level
    else:
        path = name.value

    if not path:
        return

    found.name, found.dots, found.path = name, level, path
    found.fromlist = fromlist or []
    if fromlist is None:
        return
    if fromlist:
        found.returned = path
    elif level:
        # the first name after the package: `__import__("a.b", level=1)` in `p` gives `p.a`
        base = path[:len(path) - len(name.value)].rstrip('.') if name.value else path
        head = name.value.split('.')[0]
        found.returned = f"{base}.{head}" if base and head else base or head
    else:
        found.returned = path.split('.')[0]


def _assigned_once(call: ast.Call) -> list[ast.AST]:
    """The loads of the name `call` is assigned to, if that's its only assignment."""

    stmt = ref(call).parent
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)):
        return []

    binding = ref(stmt.targets[0]).binding
    loads = [node for node in binding.references if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)]
    stores = [node for node in binding.references if node not in loads]
    if stores != [stmt.targets[0]] or isinstance(binding, ImportBinding):
        return []
    return loads


def find(module: ast.Module) -> None:
    """
    Record every `__import__()`/`importlib.import_module()` call of `module` in its
    `ModuleRef.dynamic_imports`. Must run after the module is bound (and its imports resolved), and
    before literals are hoisted.
    """

    module_ref = ref(module)
    module_ref.dynamic_imports = []

    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or (callee := _callee(node)) is None:
            continue

        found = DynamicImport(node, callee)
        (_dunder_import if callee == '__import__' else _import_module)(module_ref, found)
        if found.returned is not None:
            found.roots = [node, *_assigned_once(node)]
        module_ref.dynamic_imports.append(found)


def link(module_ref: ModuleRef, project: dict[str, ModuleRef]) -> None:
    """Tie each dynamic import of `module_ref` to the modules of `project` it imports and returns."""

    for found in module_ref.dynamic_imports:
        if found.path is None:
            continue

        found.target = project.get(found.path)
        found.returns = project.get(found.returned) if found.returned is not None else None
        found.submodules = {
            entry: submodule for entry in found.fromlist
            if (submodule := project.get(f"{found.path}.{entry.value}")) is not None
        }
