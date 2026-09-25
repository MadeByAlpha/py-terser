from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, override

from terser.ast import NodeVisitor, ast, ref
from .binding import Binding, ImportBinding, NameBinding
from .util import arg_rename_in_place, scope_ref_global

if TYPE_CHECKING:
    from collections.abc import Callable

    from terser.ast.ref import ContainsScope, ModuleRef


def resolve(module: ast.Module):
    """
    Bind names to their local namespace

    :param module: The module to bind names in
    """

    NameResolver()(module)


def resolve_subtree(node: ast.AST, module_ref: "ModuleRef"):
    """
    Bind names to their local namespace within a subtree added after the initial resolve pass

    Unlike `resolve`, this does not walk from an `ast.Module` - `node`'s namespace/parent refs
    must already be set (see `SuiteTransformer.add_child`).

    :param node: The subtree root
    :param module_ref: The module `node` belongs to
    """

    name_resolver = NameResolver()
    name_resolver.module_ref = module_ref
    name_resolver.visit(node)


class NameResolver(NodeVisitor):
    """
    Create a NameBinding for each name that is bound

    The NameBinding is added to the bindings dictionary in the namespace node the name is local to.
    """
    module_ref: ModuleRef

    def __call__(self, module: ast.Module):
        self.module_ref = ref(module)
        return self.visit(module)

    def __get_binding(self, name: str, namespace: ContainsScope, factory: Callable[[str], Binding] = NameBinding):
        namespace_ref = ref(namespace)
        if name in namespace_ref.globals and not isinstance(namespace, ast.Module):
            return self.__get_binding(name, scope_ref_global(namespace).ast, factory=factory)

        # nonlocal names should not create a binding in any context
        assert name not in namespace_ref.nonlocals

        for binding in namespace_ref.bindings:
            if binding.name == name:
                break
        else:  # weeee!
            binding = factory(name)
            namespace_ref.bindings.append(binding)

            if name in dir(builtins):
                binding.disallow_rename()

        if name in namespace_ref.nonlocals and isinstance(namespace, ast.Module):
            # This is actually a syntax error - but we want the same syntax error after minifying!
            binding.disallow_rename()

        if isinstance(namespace, ast.ClassDef):
            # This name will become an attribute of the class, so it can't be renamed
            binding.disallow_rename()

        return binding

    @override
    def visit_Name(self, node: ast.Name):
        namespace = ref(node).namespace
        if node.id in ref(namespace).nonlocals:
            # A nonlocal name does not create a binding.
            # We will resolve the binding later
            return

        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.__get_binding(node.id, namespace).add_reference(node)

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        namespace = ref(node).namespace
        if node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)
        self.generic_visit(node)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        namespace = ref(node).namespace
        if node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)
        self.generic_visit(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)    # type: ignore[ty:invalid-argument-type]

    @override
    def visit_alias(self, node: ast.alias):
        if node.name == '*':
            # Deferred: the bound names depend on the target module's exports,
            # which are only known once every module in the project has been bound.
            from_node = ref(node).parent
            assert isinstance(from_node, ast.ImportFrom)
            self.module_ref.wildcard_targets.setdefault(from_node, None)    # type: ignore[ty:no-matching-overload]
            return

        root_module = node.name.split('.')[0]

        if root_module == 'timeit':
            scope_ref_global(node).tainted = True

        namespace = ref(node).namespace

        factory = lambda name: ImportBinding(name, node, self.module_ref)
        if node.asname is not None:
            if node.asname not in ref(namespace).nonlocals:
                binding = self.__get_binding(node.asname, namespace, factory)
                binding.add_reference(node)
                if isinstance(binding, ImportBinding):
                    self.module_ref.import_targets.setdefault(binding, None)    # type: ignore[ty:no-matching-overload]
        else:
            # This binds the root module only for a dotted import

            if root_module not in ref(namespace).nonlocals:
                binding = self.__get_binding(root_module, namespace, factory)
                binding.add_reference(node)
                if isinstance(binding, ImportBinding):
                    self.module_ref.import_targets.setdefault(binding, None)    # type: ignore[ty:no-matching-overload]

                if '.' in node.name:
                    binding.disallow_rename()

    @override
    def visit_arguments(self, node: ast.arguments):
        namespace = ref(node).namespace

        # varargs, kwarg can't be nonlocal
        if isinstance(node.vararg, str):
            binding = self.__get_binding(node.vararg, namespace)
            binding.add_reference(node)

        if isinstance(node.kwarg, str):
            binding = self.__get_binding(node.kwarg, namespace)
            binding.add_reference(node)

        self.generic_visit(node)

    @override
    def visit_arg(self, node: ast.arg):
        namespace = ref(node).namespace

        # Args can't be nonlocal
        binding = self.__get_binding(node.arg, namespace)

        if arg_rename_in_place(node):
            binding.add_reference(node)
        else:
            binding.add_reference(node, reserved=node.arg)

            if isinstance(namespace, ast.Lambda):
                # Lambda function arguments can't be renamed without breaking keyword arguments
                binding.disallow_rename()

        self.generic_visit(node)

    @override
    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        namespace = ref(node).namespace

        if node.name is not None:
            if isinstance(node.name, str) and node.name not in ref(namespace).nonlocals:
                # python 3
                self.__get_binding(node.name, namespace).add_reference(node)
            else:
                # In python 2 the name is a Name node,
                # which will be visited by generic_visit
                pass

        self.generic_visit(node)

    @override
    def visit_Global(self, node: ast.Global):
        for name in node.names:
            self.__get_binding(name, ref(node).namespace).add_reference(node)

    @override
    def visit_MatchAs(self, node: ast.MatchAs):
        namespace = ref(node).namespace
        if node.name is not None and node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)

        self.generic_visit(node)

    @override
    def visit_MatchStar(self, node: ast.MatchStar):
        namespace = ref(node).namespace
        if node.name is not None and node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)

        self.generic_visit(node)

    @override
    def visit_MatchMapping(self, node: ast.MatchMapping):
        namespace = ref(node).namespace
        if node.rest is not None and node.rest not in ref(namespace).nonlocals:
            self.__get_binding(node.rest, namespace).add_reference(node)

        self.generic_visit(node)

    @override
    def visit_TypeVar(self, node: ast.TypeVar):
        namespace = ref(node).namespace
        if node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)

        scope_ref_global(namespace).preserved.add(node.name)

    @override
    def visit_TypeVarTuple(self, node: ast.TypeVarTuple):
        namespace = ref(node).namespace
        if node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)

        scope_ref_global(namespace).preserved.add(node.name)

    @override
    def visit_ParamSpec(self, node: ast.ParamSpec):
        namespace = ref(node).namespace
        if node.name not in ref(namespace).nonlocals:
            self.__get_binding(node.name, namespace).add_reference(node)

        scope_ref_global(namespace).preserved.add(node.name)
