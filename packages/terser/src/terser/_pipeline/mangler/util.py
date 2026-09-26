from __future__ import annotations

import fnmatch

from terser.ast import ast, is_constant_node, is_scoped, ref


def preserved_names(module_path: str, preserved: dict[str, list[str]]) -> set[str]:
    """
    Names to leave unchanged for a given module.

    :param module_path: The module's dotted path (or filename, for non-project usage)
    :param preserved: Names to leave unchanged, keyed by a glob pattern matched against
        ``module_path`` (e.g. ``{"foo.bar": ["baz"], "*": ["qux"]}``)
    """

    names = set()
    for pattern, pattern_names in preserved.items():
        if fnmatch.fnmatch(module_path, pattern):
            names.update(pattern_names)
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


def allow_rename_locals(node, rename_locals, preserve_locals=None):

    if preserve_locals is None:
        preserve_locals = []

    if not isinstance(node, ast.Module) and is_scoped(node):
        for binding in ref(node).bindings:
            if rename_locals is False:
                binding.disallow_rename()
            elif binding.name in preserve_locals:
                binding.disallow_rename()

    for child in ast.iter_child_nodes(node):
        allow_rename_locals(child, rename_locals, preserve_locals)
