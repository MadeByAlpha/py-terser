"""
For each node in an AST set the namespace to use for name binding and resolution
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from alpha93.commons import typed

from terser.ast import ast, ref, is_scoped

if TYPE_CHECKING:
    from terser.ast.ref import Comprehension, ContainsScope, Invokable


class ScopeResolver:
    __LOCK = object()


    @classmethod
    def module(cls, node: ast.Module):
        cls(ScopeResolver.__LOCK).__resolve(node, namespace=node)


    @classmethod
    def child(cls, node: ast.AST, *, namespace: ContainsScope):
        cls(ScopeResolver.__LOCK).__resolve(node, namespace=namespace)


    def __init__(self, lock: object):
        if lock != ScopeResolver.__LOCK:
            raise ValueError


    def __resolve(self, node: ast.AST, *, namespace: ContainsScope):
        """
        Add a namespace attribute to child nodes

        :param node: The tree to add namespace properties to
        :param namespace: The namespace Node that this node is in
        """
        node_ref = ref(node)
        node_ref.namespace = namespace
        namespace_ref = ref(namespace)

        if is_scoped(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.__functions(node)
            elif isinstance(node, (ast.GeneratorExp, ast.SetComp, ast.DictComp, ast.ListComp)):
                self.__comprehension(node, namespace=namespace)
            elif isinstance(node, ast.Lambda):
                self.__function_arguments(node.args, node)
                self.__resolve(node.body, namespace=node)
            elif isinstance(node, ast.ClassDef):
                self.__classes(node)
            else:
                for child in ast.iter_child_nodes(node):
                    self.__resolve(child, namespace=node)
            return

        if isinstance(node, ast.Global):
            namespace_ref.globals.update(node.names)
        if isinstance(node, ast.Nonlocal):
            namespace_ref.nonlocals.update(node.names)

        if isinstance(node, ast.Name) and isinstance(namespace, ast.ClassDef):
            if isinstance(node.ctx, ast.Load):
                namespace_ref.nonlocals.add(node.id)
            elif isinstance(node.ctx, ast.Store) and isinstance(node_ref.parent, ast.AugAssign):
                namespace_ref.nonlocals.add(node.id)

        if isinstance(node, ast.NamedExpr):
            # NamedExpr is 'special'
            self.__namedexpr(node)
            return

        for child in ast.iter_child_nodes(node):
            self.__resolve(child, namespace=namespace)


    def __function_arguments(self, node: ast.arguments, fn: Invokable, /):
        ref(node).namespace = fn
        namespace = ref(fn).namespace

        for arg in (typed[list[ast.arg]].getattr(node, "posonlyargs", []) + node.args):
            self.__resolve(arg, namespace=fn)
            if hasattr(arg, "ref") and arg.annotation is not None:
                self.__resolve(arg.annotation, namespace=namespace)

        if hasattr(node, "kwonlyargs"):
            for arg in node.kwonlyargs:
                self.__resolve(arg, namespace=fn)
                if arg.annotation is not None:
                    self.__resolve(arg.annotation, namespace=namespace)

            for default in node.kw_defaults:
                if default is not None:
                    self.__resolve(default, namespace=namespace)

        for default in node.defaults:
            self.__resolve(default, namespace=namespace)

        if node.vararg:
            if annotation := typed[ast.expr].getattr(node, "varargannotation", None):
                self.__resolve(annotation, namespace=namespace)
            elif isinstance(node.vararg, str):
                pass
            else:
                self.__resolve(node.vararg, namespace=fn)

        if node.kwarg:
            if annotation := typed[ast.expr].getattr(node, "kwargannotation", None):
                self.__resolve(annotation, namespace=namespace)
            elif isinstance(node.kwarg, str):
                pass
            else:
                self.__resolve(node.kwarg, namespace=fn)


    def __functions(self, node: ast.FunctionDef | ast.AsyncFunctionDef, /):
        """
        Add correct parent and namespace attributes to functiondef nodes
        """
        namespace = ref(node).namespace

        if node.args is not None:
            self.__function_arguments(node.args, node)

        for stmt in node.body:
            self.__resolve(stmt, namespace=node)

        for expr in node.decorator_list:
            self.__resolve(expr, namespace=namespace)

        if type_params := typed[list[ast.type_param]].getattr(node, "type_params", None):
            for param in type_params:
                self.__resolve(param, namespace=namespace)

        if returns := typed[ast.expr].getattr(node, "returns", None):
            self.__resolve(returns, namespace=namespace)


    def __classes(self, node: ast.ClassDef, /):
        """
        Add correct parent and namespace attributes to classdef nodes
        """
        namespace = ref(node).namespace

        for base in node.bases:
            self.__resolve(base, namespace=namespace)

        if hasattr(node, 'keywords'):
            for keyword in node.keywords:
                self.__resolve(keyword, namespace=namespace)

        if starargs := typed[ast.arguments].getattr(node, "starargs", None):
            self.__resolve(starargs, namespace=namespace)

        if kwargs := typed[ast.arguments].getattr(node, "kwargs", None):
            self.__resolve(kwargs, namespace=namespace)

        for body in node.body:
            self.__resolve(body, namespace=node)

        for decorator in node.decorator_list:
            self.__resolve(decorator, namespace=namespace)

        if type_params := typed[list[ast.type_param]].getattr(node, "type_params", None):
            for param in type_params:
                self.__resolve(param, namespace=namespace)


    def __comprehension(self, node: Comprehension, /, namespace: ContainsScope):
        if isinstance(node, ast.DictComp):
            self.__resolve(node.key, namespace=node)
            self.__resolve(node.value, namespace=node)
        else:
            self.__resolve(node.elt, namespace=node)

        iter_namespace = namespace
        for generator in node.generators:
            ref(generator).namespace = node

            self.__resolve(generator.target, namespace=node)
            self.__resolve(generator.iter, namespace=iter_namespace)

            for if_ in generator.ifs:
                self.__resolve(if_, namespace=node)

            iter_namespace = node


    def __namedexpr_ns(self, node: ContainsScope, /):
        """
        Get the namespace for a NamedExpr target
        """

        if not isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            return node

        return self.__namedexpr_ns(ref(node).namespace)


    def __namedexpr(self, node: ast.NamedExpr, /):
        namespace = ref(node).namespace
        self.__resolve(node.target, namespace=self.__namedexpr_ns(namespace))
        self.__resolve(node.value, namespace=namespace)
