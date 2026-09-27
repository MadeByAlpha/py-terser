from __future__ import annotations

import fnmatch

from terser.ast import ast, is_constant_node, is_scoped, ref


def preserved_names(module_path: str, preserved: dict[str, list[str]]) -> set[str]:
    """
    Names to leave unchanged for a given module.

    :param module_path: The module's dotted path (or filename, for non-project usage)
    :param preserved: Names to leave unchanged, keyed by a glob pattern matched against
        ``module_path`` (e.g. ``{"foo.bar": ["baz"], "*": ["qux"]}``). A pattern may go on with
        ``::`` and a glob over qualnames (``{"foo.bar::Model.*": ["baz"]}``); its names are then
        returned as ``qualname::name``, for `LocalRule`
    """

    names = set()
    for pattern, pattern_names in preserved.items():
        # `module::qualname` limits the names to that scope: `LocalRule` sorts it out
        module_pattern, sep, qualname = pattern.partition('::')
        if fnmatch.fnmatch(module_path, module_pattern):
            names.update(f"{qualname}::{name}" if sep else name for name in pattern_names)
    return names


def get_global_namespace(node: ast.AST):
    """
    Return the global namespace for a node

    :rtype: :class:`ast.Module`

    """

    namespace = ref(node).namespace
    if namespace is node:
        return node

    return get_global_namespace(namespace)


def get_nonlocal_namespace(node: ast.AST):
    """
    Return the nonlocal namespace for a node

    The nonlocal namespace is the closest parent function scope's namespace.
    """

    namespace = ref(node).namespace
    if isinstance(namespace, ast.ClassDef):
        return get_nonlocal_namespace(namespace)

    return namespace


def arg_rename_in_place(node: ast.AST):
    """
    Can this argument node by safely renamed

    'self', 'cls', 'args', and 'kwargs' are not commonly referenced by the caller, so
    can be safely renamed. Comprehension arguments are not accessible from outside, so
    can be renamed.

    If the argument is positional-only, it can be safely renamed

    Other arguments may be referenced by the caller as keyword arguments, so should not be
    renamed in place. The name assigner may still decide to bind the argument to a new name
    inside the function namespace.

    :param node: The argument node
    :rtype node: :class:`ast.arg`
    :rtype: bool

    """

    func = ref(node).namespace

    if isinstance(func, ast.comprehension):
        return True

    func_namespace = ref(func).namespace
    if isinstance(func_namespace, ast.ClassDef) and not isinstance(func, ast.Lambda):
        all_args = (func.args.posonlyargs if hasattr(func.args, 'posonlyargs') else []) + func.args.args
        if len(all_args) > 0 and node is all_args[0]:
            if len(func.decorator_list) == 0:
                # mangle 'self'
                return True
            elif (
                len(func.decorator_list) == 1
                and isinstance(func.decorator_list[0], ast.Name)
                and func.decorator_list[0].id == 'classmethod'
            ):
                # mangle 'cls'
                return True

    if func.args.vararg is node or func.args.kwarg is node:
        # starargs
        return True

    if hasattr(func.args, 'posonlyargs') and node in func.args.posonlyargs:
        return True

    return False


def insert(suite, new_node):
    """
    Insert a node into a suite

    Inserts new_node as early as possible in the suite, but after docstrings and `import __future__` statements.

    :param suite: The existing suite to insert the node into
    :param new_node: The node to insert
    :return: :class:`collections.Iterable[Node]`

    """

    inserted = False
    for node in suite:

        if not inserted:
            if (isinstance(node, ast.ImportFrom) and node.module == '__future__') or (
                isinstance(node, ast.Expr) and is_constant_node(node.value, ast.Str)
            ):
                pass
            else:
                yield new_node
                inserted = True

        yield node

    if not inserted:
        yield new_node


# `preserve_locals` specs for every `*args` and `**kwargs` parameter: their names show in
# `inspect.signature()`, which some code relies on
STAR_ARGS = ['*', '**']


class LocalRule:
    """
    One entry of `preserve_locals`: `[qualname glob::]name`, where `name` is a local name, or a
    parameter kind - `*`/`**` for a function's `*args`/`**kwargs` parameter, `*name`/`**name`
    for it only when it has that name.

    The qualname glob is matched against the `__qualname__` of the function or class the name
    is bound in (e.g. `Field`, `Model.__init__`, `outer.<locals>.inner`); without one, the rule
    applies in every scope.
    """

    __slots__ = ('kind', 'name', 'qualname')

    def __init__(self, spec: str, /):
        qualname, sep, name = spec.rpartition('::')
        self.qualname = qualname if sep else None
        self.kind = '**' if name.startswith('**') else '*' if name.startswith('*') else ''
        self.name = name[len(self.kind):] or None

        if not self.kind and self.name is None:
            raise ValueError(f"preserve_locals: {spec!r} names nothing")

    def preserves(self, name: str, namespace: ast.AST, qualname: str | None) -> bool:
        if self.qualname is not None and (qualname is None or not fnmatch.fnmatchcase(qualname, self.qualname)):
            return False

        if not self.kind:
            return name == self.name

        args = getattr(namespace, 'args', None)
        param = getattr(args, 'vararg' if self.kind == '*' else 'kwarg', None) if isinstance(args, ast.arguments) else None
        return param is not None and param.arg == name and self.name in (None, name)


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _qualname(node: ast.AST, enclosing: str | None, in_function: bool) -> str | None:
    """
    The `__qualname__` of the scope `node` introduces, within the one whose own is `enclosing`:
    names in a function are qualified by `<locals>`, the ones in a class body are not.
    """

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        name = node.name
    elif isinstance(node, ast.Lambda):
        name = '<lambda>'
    elif isinstance(node, ast.GeneratorExp):
        name = '<genexpr>'
    else:
        # other comprehensions are inlined in the scope they're in (PEP 709)
        return enclosing

    if enclosing is None:
        return name
    return f"{enclosing}.<locals>.{name}" if in_function else f"{enclosing}.{name}"


def _local_bindings(node, _enclosing=(None, False)):
    """(namespace, qualname, binding) for every binding of the function and class scopes in `node`"""

    if not isinstance(node, ast.Module) and is_scoped(node):
        qualname = _qualname(node, *_enclosing)
        for binding in ref(node).bindings:
            yield node, qualname, binding

        if qualname is not _enclosing[0]:
            _enclosing = qualname, isinstance(node, (*_FUNCTIONS, ast.GeneratorExp))

    for child in ast.iter_child_nodes(node):
        yield from _local_bindings(child, _enclosing)


def allow_rename_locals(node, rename_locals, preserve_locals=None):
    """
    Disallow renaming the local bindings that are not to be renamed.

    :param preserve_locals: `LocalRule` specs of the names to leave unchanged
    :type preserve_locals: list[str] | None
    """

    rules = [LocalRule(spec) for spec in preserve_locals or ()]
    for namespace, qualname, binding in _local_bindings(node):
        if rename_locals is False or any(rule.preserves(binding.name, namespace, qualname) for rule in rules):
            binding.disallow_rename()


def mark_preserved(module: ast.Module, preserve_locals=None, preserve_globals=None):
    """
    Mark the bindings named by `preserve_locals`/`preserve_globals` as preserved, for the
    transforms not to unbind them (e.g. by removing an import nothing in the module reads).

    :param preserve_locals: `LocalRule` specs of the local names
    :type preserve_locals: list[str] | None
    :param preserve_globals: The global (module-level) names
    :type preserve_globals: list[str] | None
    """

    rules = [LocalRule(spec) for spec in preserve_locals or ()]
    for namespace, qualname, binding in _local_bindings(module):
        if any(rule.preserves(binding.name, namespace, qualname) for rule in rules):
            binding.mark_preserved()

    preserve_globals = set(preserve_globals or ())
    for binding in ref(module).bindings:
        if binding.name in preserve_globals:
            binding.mark_preserved()
