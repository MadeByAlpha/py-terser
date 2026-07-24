from terser.ast import ast, is_scoped, ref

from ..resolver.binding import NameBinding
from .name_generator import name_filter
from .util import allow_rename_locals


def all_bindings(node):
    """
    All bindings in a namespace tree

    :param node: The root node to get bindings in
    :type node: :class:`ast.AST`
    :rtype: Iterable[ast.AST, Binding]

    """

    if is_scoped(node):
        for binding in ref(node).bindings:
            yield node, binding

    for child in ast.iter_child_nodes(node):
        for namespace, binding in all_bindings(child):
            yield namespace, binding


def sorted_bindings(module):
    """
    All bindings in a namespace tree sorted by descending number of references

    :param module: The root node to get bindings in
    :type module: :class:`ast.AST`
    :rtype: Iterable[ast.AST, Binding]

    """

    def comp(tup):
        _namespace, binding = tup
        return binding.new_mention_count()

    return sorted(all_bindings(module), key=comp, reverse=True)


def reservation_scope(namespace, binding):
    """
    Get the namespaces that are in the bindings reservation scope

    Returns the namespace nodes the binding name must be resolvable in

    :param namespace: The local namespace of a binding
    :type namespace: :class:`ast.AST`
    :param binding: The binding to get the reservation scope for
    :type binding: Binding
    :rtype: set[ast.AST]

    """

    namespaces = {namespace}

    for node in binding.references:
        current = node
        while current is not namespace:
            current_namespace = ref(current).namespace
            namespaces.add(current_namespace)
            current = current_namespace

    return namespaces


def add_assigned(node):
    """
    Add the assigned_names attribute to namespace nodes in a tree, if not already present

    Left alone if already set, so a later mangle pass (e.g. project-wide global mangling)
    doesn't forget the names an earlier pass (e.g. per-module local mangling) already reserved.

    :param node: The root node to add the assigned_names attribute to
    :type node: :class:`ast.AST`

    """

    if is_scoped(node):
        node_ref = ref(node)
        if not hasattr(node_ref, 'assigned_names'):
            node_ref.assigned_names = set()

    for child in ast.iter_child_nodes(node):
        add_assigned(child)


def reserve_name(name, reservation_scope):
    """
    Reserve a name in a reservation scope

    :param str name: The name to reserve
    :param reservation_scope:
    :type reservation_scope: Iterable[:class:`ast.AST`]

    """

    for namespace in reservation_scope:
        namespace_ref = ref(namespace)
        if not hasattr(namespace_ref, 'assigned_names'):
            # namespace is no longer reachable from the module root (a transform deleted
            # the subtree it belonged to) - nothing will ever rename anything in it, so
            # there's nothing to reserve
            continue

        namespace_ref.assigned_names.add(name)


def should_rename(binding, name, scope, is_available):
    if binding.should_rename(name):
        return True

    # It's no longer efficient to do this mangle

    if isinstance(binding, NameBinding):
        # Check that the original name is still available

        if binding.reserved == binding.name:
            # We already reserved it (this is probably an arg)
            return False

        if not is_available(binding.name, scope):
            # The original name has already been assigned to another binding,
            # so we need to mangle this anyway.
            return True

    return False


class UniqueNameAssigner:
    """
    Assign new names to renamed bindings

    Assigns a unique name to every binding
    """

    def __init__(self):
        self.name_generator = name_filter()
        self.names = []

    def available_name(self):
        return next(self.name_generator)

    def __call__(self, module):
        assert isinstance(module, ast.Module)

        for _namespace, binding in sorted_bindings(module):
            if binding.allow_rename:
                binding.new_name = self.available_name()

        return module


class NameAssigner:
    """
    Assign new names to renamed bindings

    This assigner creates a name 'reservation scope' containing each namespace a binding is referenced in, including
    transitive namespaces. Bindings are then assigned the first available name that has no references in their
    reservation scope. This means names will be reused in sibling namespaces, and shadowed where possible in child
    namespaces.

    Bindings are assigned names in order of most references, with names assigned shortest first.

    A single instance may be reused across multiple, unrelated namespace trees (e.g. every module in a
    project) - the name cache is shared, but availability is always checked against the binding's own
    reservation scope, so there's no cross-tree leakage.

    """

    def __init__(self, name_generator=None):
        self.name_generator = name_generator if name_generator is not None else name_filter()
        self.names = []

    def iter_names(self):
        for name in self.names:
            yield name

        while True:
            name = next(self.name_generator)
            self.names.append(name)
            yield name

    def available_name(self, reservation_scope, prefix=''):
        """
        Search for the first name that is not in reservation scope
        """

        for name in self.iter_names():
            if self.is_available(prefix + name, reservation_scope):
                return prefix + name

        return None

    def is_available(self, name, reservation_scope):
        """
        Is a name unreserved in a reservation scope

        :param str name: the name to check availability of
        :param reservation_scope: The scope to check
        :type reservation_scope: Iterable[:class:`ast.AST`]
        :rtype: bool

        """

        return all(name not in ref(namespace).assigned_names for namespace in reservation_scope)

    def assign(self, namespace, binding, *, prefix=''):
        """
        Assign a new name to a single binding, in its reservation scope

        Shared by both :func:`mangle_locals` (walking one module's namespace tree) and
        :func:`terser._pipeline.mangler.global_mangle.mangle_globals` (walking module-level
        bindings across a whole project).

        :param namespace: The binding's local namespace
        :param binding: The binding to assign a name to
        :param str prefix: A prefix to apply to the assigned name (e.g. to avoid colliding
            with builtins at module level)
        """

        scope = reservation_scope(namespace, binding)

        if binding.allow_rename:
            name = self.available_name(scope, prefix=prefix)

            if should_rename(binding, name, scope, self.is_available):
                binding.rename(name)
            else:
                binding.disallow_rename()

        if binding.name is not None:
            reserve_name(binding.name, scope)

    def __call__(self, module, prefix_globals=False, reserved_globals=None):
        assert isinstance(module, ast.Module)
        add_assigned(module)

        for namespace, binding in all_bindings(module):
            if binding.reserved is not None:
                scope = reservation_scope(namespace, binding)
                reserve_name(binding.reserved, scope)

        if reserved_globals is not None:
            for name in reserved_globals:
                ref(module).assigned_names.add(name)

        for namespace, binding in sorted_bindings(module):
            prefix = '_' if prefix_globals and isinstance(namespace, ast.Module) else ''
            self.assign(namespace, binding, prefix=prefix)

        return module


def mangle_locals(module, rename_locals=True, preserve_locals=None):
    """
    Mangle locals/nonlocals - names bound in function and class namespaces

    Module-level (global) bindings are left untouched here; use
    :func:`terser._pipeline.mangler.global_mangle.mangle_globals` for those, once every module
    in the project has been through this step and linking has run.

    :param module: The module to mangle locals in
    :type module: :class:`ast.Module`
    :param bool rename_locals: If local names may be renamed
    :param preserve_locals: Local names to leave unchanged
    :type preserve_locals: list[str] | None
    """

    allow_rename_locals(module, rename_locals, preserve_locals)

    add_assigned(module)

    for namespace, binding in all_bindings(module):
        if binding.reserved is not None:
            reserve_name(binding.reserved, reservation_scope(namespace, binding))

    assigner = NameAssigner()

    for namespace, binding in sorted_bindings(module):
        if isinstance(namespace, ast.Module):
            # Module-level (global) bindings are mangled later, project-wide, by
            # global_mangle.mangle_globals - just reserve the current name so local
            # renaming doesn't collide with it.
            if binding.name is not None:
                reserve_name(binding.name, reservation_scope(namespace, binding))
            continue

        assigner.assign(namespace, binding)

    return module
