from __future__ import annotations

from typing import TYPE_CHECKING

from alpha93.commons import typed

from terser.ast import ast, ref, is_constant_node, is_scoped

if TYPE_CHECKING:
    from terser.ast.ref import Invokable, ModuleRef, ScopedNode


def scope_ref_global(node: ast.AST) -> ModuleRef:
    """
    Return the global namespace for a node
    """
    namespace = ref(node).namespace

    if namespace is node:
        assert isinstance(node, ast.Module)
        return ref(node)

    return scope_ref_global(namespace)


def scope_ref_nonlocal(node: ast.AST) -> ScopedNode:
    """
    Return the nonlocal namespace for a node

    The nonlocal namespace is the closest parent function scope's namespace.
    """
    namespace = ref(node).namespace

    if isinstance(namespace, ast.ClassDef):
        return scope_ref_nonlocal(namespace)

    return ref(namespace)


def arg_rename_in_place(node: ast.AST, /) -> bool:
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
    """
    func: Invokable = ref(node).namespace   # type: ignore[ty:invalid-assignment]

    if isinstance(func, ast.comprehension):
        return True

    if isinstance(ref(func).namespace, ast.ClassDef) and not isinstance(func, ast.Lambda):
        all_args = typed[list[ast.arg]].getattr(func.args, "posonlyargs", []) + func.args.args
        if len(all_args) > 0 and node is all_args[0]:
            if len(func.decorator_list) == 0:
                # mangler 'self'
                return True
            elif (
                    len(func.decorator_list) == 1
                    and isinstance(decorator := func.decorator_list[0], ast.Name)
                    and decorator.id == "classmethod"
            ):
                # mangler 'cls'
                return True

    if func.args.vararg is node or func.args.kwarg is node:
        # starargs
        return True

    if hasattr(func.args, "posonlyargs") and node in func.args.posonlyargs:
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
            if (
                    (isinstance(node, ast.ImportFrom) and node.module == '__future__')
                    or (isinstance(node, ast.Expr) and is_constant_node(node.value, ast.Str))
            ):
                pass
            else:
                yield new_node
                inserted = True

        yield node

    if not inserted:
        yield new_node


def allow_rename_locals(node, rename_locals: bool, preserve_locals: list[str] | None = None):
    if preserve_locals is None:
        preserve_locals = []

    if not isinstance(node, ast.Module) and is_scoped(node):
        for binding in ref(node).bindings:
            if not rename_locals:
                binding.disallow_rename()
            elif binding.name in preserve_locals:
                binding.disallow_rename()

    for child in ast.iter_child_nodes(node):
        allow_rename_locals(child, rename_locals, preserve_locals)


def find_all(module_ref: ModuleRef) -> list[str] | None:
    """
    The names listed in `module_ref`'s `__all__`, or None if it has no statically resolvable
    `__all__` (either absent, or built dynamically)
    """

    for stmt in module_ref._ast.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        if stmt.targets[0].id != '__all__':
            continue
        if not isinstance(stmt.value, (ast.List, ast.Tuple)):
            return None

        names = []
        for elt in stmt.value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                return None
            names.append(elt.value)
        return names

    return None
