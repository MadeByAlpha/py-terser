"""
Imports made by calling `__import__()`, `__lazy_import__()` (3.15+) or `importlib.import_module()`.

When every argument naming the module is a literal (a `LiteralString`), the call is as static as
an import statement: `find` resolves the module it imports, `link` ties it to the project, and
tree-shaking and module renaming follow it like any other import - the latter rewriting the
literals. The module a call returns is followed too, where it's used right away
(`__import__("a.b").b.name`) or kept in a name assigned once (`m = import_module("a"); m.name`).

A call whose module name is only known at run time is kept in `ModuleRef.dynamic_imports` as
well, unresolved, for the pipeline to warn about when it relies on knowing every import.
"""

from __future__ import annotations

from enum import StrEnum

from alpha93.commons.types import any_object

from terser.ast import ast, ref

from .resolver.binding import BuiltinBinding, ImportBinding

if __debug__ and __import__("typing").TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeGuard

    from terser.ast import ModuleRef


class Callee(StrEnum):
    """What a dynamic import calls, as written in messages."""

    DUNDER_IMPORT = "__import__"
    DUNDER_LAZY_IMPORT = "__lazy_import__"
    IMPORT_MODULE = "importlib.import_module"

    @property
    def is_dunder(self) -> bool:
        """If it takes `__import__()`'s arguments: `level` and `fromlist`, not `package`."""
        return self is not Callee.IMPORT_MODULE


class DynamicImport:
    """
    One call to `__import__()`, `__lazy_import__()` or `importlib.import_module()`.

    :ivar call: The call
    :ivar callee: What the call calls
    :ivar name: The literal naming the module - None when it's not one, and the import unresolved
    :ivar package: `import_module()`'s literal package, that a relative name is resolved against
    :ivar dots: How many levels up a relative name starts (`level` for `__import__()` and
        `__lazy_import__()`, the leading dots otherwise)
    :ivar path: The dotted path of the module imported, None if unresolved
    :ivar fromlist: `__import__()`/`__lazy_import__()`'s literal `fromlist` entries, that may be
        submodules to import too
    :ivar returned: The dotted path of the module the call evaluates to, None if unknown
    :ivar roots: Nodes evaluating to the returned module: the call, and the loads of a name it's
        assigned to once
    :ivar target: The module imported, once linked and if in the project
    :ivar submodules: The `fromlist` entries that are submodules of `target`, by entry literal
    """

    __slots__ = (
        'call',
        'callee',
        'dots',
        'fromlist',
        'name',
        'package',
        'path',
        'returned',
        'returns',
        'roots',
        'submodules',
        'target',
    )

    def __init__(self, call: ast.Call, callee: Callee):
        self.call = call
        self.callee = callee
        self.name: ast.Str | None = None
        self.package: ast.Str | None = None
        self.dots = 0
        self.path: str | None = None
        self.fromlist: list[ast.Str] = []
        self.returned: str | None = None
        self.roots: list[ast.AST] = []

        self.target: ModuleRef | None = None
        self.returns: ModuleRef | None = None
        self.submodules: dict[ast.Str, ModuleRef] = {}

    @property
    def literals(self) -> list[ast.Constant]:
        """The literals naming modules: pinned, so literal hoisting leaves them in the call."""

        return [node for node in (self.name, self.package, *self.fromlist) if node is not None]

    @property
    def location(self) -> str:
        return f"line {self.call.lineno}" if hasattr(self.call, 'lineno') else "somewhere"


# `any_object()` only casts here: it replaces a falsy object with `object()`, and a node is never falsy
__str: Callable[[ast.AST | None], ast.Str | None] = (
    lambda node: any_object(node) if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
)

__all_str: Callable[[list[ast.expr]], TypeGuard[list[ast.Str]]] = any_object(
    lambda nodes: all(__str(e) for e in nodes)
)

__args: Callable[[ast.Call, int, str], ast.AST | None] = lambda call, position, keyword: (
    call.args[position] if len(call.args) > position
    else next((kw.value for kw in call.keywords if kw.arg == keyword), None)
)


def __callee(call: ast.Call) -> Callee | None:
    """`__import__`/`__lazy_import__`/`importlib.import_module`, if that's what `call` calls."""

    func = call.func

    if isinstance(func, ast.Name):
        binding = ref(func).binding
        # a builtin only where the interpreter running terser has it: `__lazy_import__` from 3.15
        if isinstance(binding, BuiltinBinding) and binding.name in (Callee.DUNDER_IMPORT, Callee.DUNDER_LAZY_IMPORT):
            return Callee(binding.name)

        # `from importlib import import_module [as y]`
        if (
            isinstance(binding, ImportBinding) and binding.source_module == 'importlib'
            and isinstance(binding.node, ast.alias) and isinstance(ref(binding.node).parent, ast.ImportFrom)
            and binding.node.name == 'import_module'
        ):
            return Callee.IMPORT_MODULE

    # `import importlib [as x]`, then `x.import_module(...)`
    if isinstance(func, ast.Attribute) and func.attr == 'import_module' and isinstance(func.value, ast.Name):
        binding = ref(func.value).binding
        if (
            isinstance(binding, ImportBinding) and binding.source_module == 'importlib'
            and isinstance(binding.node, ast.alias) and isinstance(ref(binding.node).parent, ast.Import)
            and binding.node.name == 'importlib'
        ):
            return Callee.IMPORT_MODULE

    return None


def __resolve(module_ref: ModuleRef, relative: str) -> str | None:
    try:
        return module_ref.spec.resolve(relative)
    except ImportError:
        return None


def __parse_importlib_import(module_ref: ModuleRef, found: DynamicImport) -> None:
    call = found.call
    if (name := __str(__args(call, 0, 'name'))) is None or call.args[2:]:
        return

    stripped = name.value.lstrip('.')
    found.dots = len(name.value) - len(stripped)

    if found.dots:
        package_node = __args(call, 1, 'package')
        if (package := __str(package_node)) is not None:
            # `importlib.util.resolve_name()`, without importing anything
            parts = package.value.split('.')
            if found.dots > len(parts):
                return
            base = '.'.join(parts[:len(parts) - found.dots + 1])
            path = f"{base}.{stripped}" if stripped else base
            found.package = package
        elif isinstance(package_node, ast.Name) and package_node.id == '__package__':
            # this module's own package: resolved the way a relative import statement is
            path = __resolve(module_ref, name.value)
        else:
            return
    else:
        path = stripped

    if path:
        found.name, found.path, found.returned = name, path, path


def __parse_dunder_import(module_ref: ModuleRef, found: DynamicImport) -> None:
    call = found.call
    if (name := __str(__args(call, 0, 'name'))) is None or call.args[5:]:
        return

    level_node = __args(call, 4, 'level')
    if level_node is None:
        level = 0
    elif isinstance(level_node, ast.Constant) and type(level_node.value) is int and level_node.value >= 0:
        level = level_node.value
    else:
        return

    fromlist_node = __args(call, 3, 'fromlist')

    fromlist: list[ast.Str] | None
    if fromlist_node is None or (isinstance(fromlist_node, ast.Constant) and fromlist_node.value is None):
        fromlist = []
    elif isinstance(fromlist_node, (ast.List, ast.Tuple)) and __all_str(fromlist_node.elts):
        fromlist = list(fromlist_node.elts)
    else:
        # the module is still known, not what the call returns
        fromlist = None

    if level:
        # relative to this module's package, which `globals` tells the import system
        path = __resolve(module_ref, '.' * level + name.value)
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


def __assigned_once(call: ast.Call) -> list[ast.Name]:
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
    Record every `__import__()`/`__lazy_import__()`/`importlib.import_module()` call of `module` in
    its `ModuleRef.dynamic_imports`. Must run after the module is bound (and its imports resolved),
    and before literals are hoisted.
    """

    module_ref = ref(module)
    module_ref.dynamic_imports = []

    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or (callee := __callee(node)) is None:
            continue

        found = DynamicImport(node, callee)
        (__parse_dunder_import if callee.is_dunder else __parse_importlib_import)(module_ref, found)
        if found.returned is not None:
            found.roots = [node, *__assigned_once(node)]
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
