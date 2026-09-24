from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntFlag, auto
from typing import TYPE_CHECKING, ClassVar, final, override

from alpha93.commons import typed
from terser.ast import NodeVisitor, ast, ref
from terser.ast.ref._node import NodeRef
from ..parser._scope import ScopeResolver
from ..resolver import bind_names, resolve_subtree
from ..resolver.util import scope_ref_global

if TYPE_CHECKING:
    from typing import Final, Self

    from terser.ast.ref import ContainsScope
    from terser.config import TransformConfig


@final
class TransformerFlag(IntFlag):
    REQUIRES_IMPORT_RESOLVE = auto()
    REQUIRES_MODULE_RESOLVE = auto()
    INFLUENCES_MANGLING = auto()


@final
@dataclass()
class TransformCache:
    from dataclasses import field

    config: Final[TransformConfig]

    transforms: list[type[SuiteTransformer]] = field(default_factory=list)
    passes: dict[type[SuiteTransformer], bool] = field(default_factory=dict)


class SuiteTransformer(NodeVisitor, ABC):
    """
    Transform suites of instructions
    """
    FLAGS: ClassVar[TransformerFlag]

    _config: Final[TransformConfig]
    _cache: Final[TransformCache | None]
    _is_node_modified: bool

    @classmethod
    @abstractmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        ...

    @final
    def __new__(cls, ctx: TransformConfig | TransformCache, /) -> Self:
        if not isinstance(ctx, TransformCache) or cls not in ctx.passes:
            obj = super().__new__(cls)
            obj.__init__(ctx)
            return obj

        assert not set(ctx.transforms).difference(set(ctx.passes.keys()))
        for i in range(ctx.transforms.index(cls)):
            if ctx.passes[ctx.transforms[i]]:
                break
        else:
            return lambda _: _  # type: ignore[ty:invalid-return-type]

        obj = super().__new__(cls)
        obj.__init__(ctx)
        return obj

    @final
    def __call__(self, module: ast.Module, /):
        return self.visit(module)

    def __init__(self, ctx: TransformConfig | TransformCache, /):
        config, cache = (ctx.config, ctx) if isinstance(ctx, TransformCache) else (ctx, None)
        self._config = config
        self._cache = cache

    def suite(self, node_list, parent):
        return [self.visit(node) for node in node_list]

    @override
    def generic_visit(self, node: ast.AST):
        for field, old_value in ast.iter_fields(node):
            if isinstance(old_value, list):
                new_values = []
                for value in old_value:
                    if isinstance(value, ast.AST):
                        value = self.visit(value)
                        if value is None:
                            continue
                        elif not isinstance(value, ast.AST):
                            new_values.extend(value)
                            continue
                    new_values.append(value)
                old_value[:] = new_values
            elif isinstance(old_value, ast.AST):
                new_node = self.visit(old_value)
                if new_node is None:
                    delattr(node, field)
                else:
                    setattr(node, field, new_node)
        return node

    @override
    def visit_ClassDef(self, node: ast.ClassDef):
        node.bases = [self.visit(b) for b in node.bases]

        if hasattr(node, 'type_params') and node.type_params is not None:
            node.type_params = [self.visit(t) for t in node.type_params]

        node.body = self.suite(node.body, parent=node)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]

        if starargs := typed[ast.AST].getattr(node, "starargs", None):
            setattr(node, "starargs", self.visit(starargs))

        if kwargs := typed[ast.AST].getattr(node, "kwargs", None):
            setattr(node, "kwargs", self.visit(kwargs))

        if hasattr(node, 'keywords'):
            node.keywords = [self.visit(kw) for kw in node.keywords]

        return node

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef):
        node.args = self.visit(node.args)
        node.body = self.suite(node.body, parent=node)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]

        if hasattr(node, 'returns') and node.returns is not None:
            node.returns = self.visit(node.returns)

        return node

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_FunctionDef(node) # type: ignore[ty:invalid-argument-type]

    @override
    def visit_For(self, node: ast.For):
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)

        node.body = self.suite(node.body, parent=node)

        if node.orelse:
            node.orelse = self.suite(node.orelse, parent=node)

        return node

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor):
        return self.visit_For(node) # type: ignore[ty:invalid-argument-type]

    @override
    def visit_If(self, node: ast.If):
        node.test = self.visit(node.test)

        node.body = self.suite(node.body, parent=node)

        if node.orelse:
            node.orelse = self.suite(node.orelse, parent=node)

        return node

    @override
    def visit_Try(self, node: ast.Try):
        node.body = self.suite(node.body, parent=node)

        node.handlers = [self.visit(h) for h in node.handlers]

        if node.orelse:
            node.orelse = self.suite(node.orelse, parent=node)

        if node.finalbody:
            node.finalbody = self.suite(node.finalbody, parent=node)

        return node

    def visit_TryStar(self, node: ast.TryStar):
        return self.visit_Try(node) # type: ignore[ty:invalid-argument-type]

    @override
    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is not None:
            node.type = self.visit(node.type)

        node.body = self.suite(node.body, parent=node)
        return node

    @override
    def visit_match_case(self, node: ast.match_case):
        node.pattern = self.visit(node.pattern)

        if node.guard is not None:
            node.guard = self.visit(node.guard)

        node.body = self.suite(node.body, parent=node)
        return node

    @override
    def visit_While(self, node: ast.While):
        node.test = self.visit(node.test)

        node.body = self.suite(node.body, parent=node)

        if node.orelse:
            node.orelse = self.suite(node.orelse, parent=node)

        return node

    # noinspection unresolved-references
    @override
    def visit_With(self, node: ast.With):
        if hasattr(node, "items"):
            node.items = [self.visit(i) for i in node.items]
        else:
            if node.context_expr:
                node.context_expr = self.visit(node.context_expr)
            if node.optional_vars:
                node.optional_vars = self.visit(node.optional_vars)

        node.body = self.suite(node.body, parent=node)
        return node

    @override
    def visit_AsyncWith(self, node: ast.AsyncWith):
        return self.visit_With(node)    # type: ignore[ty:invalid-argument-type]

    @override
    def visit_Module(self, node: ast.Module):
        node.body = self.suite(node.body, parent=node)
        return node

    @final
    def add_child(self, child, parent, namespace: ContainsScope | None = None):
        def nearest_function_namespace(node: ast.AST) -> ContainsScope:
            """
            Return the namespace node for the nearest function scope.

            This could be itself.

            :param node: The node to get the function namespace of
            """

            if isinstance(node, (ast.FunctionDef, ast.Module, ast.AsyncFunctionDef)):
                return node
            return nearest_function_namespace(ref(node).parent)

        if namespace is None:
            namespace = nearest_function_namespace(parent)

        NodeRef.new(child, parent)._resolve_all()
        ScopeResolver.child(child, namespace=namespace)

        # Names have already been resolved/bound for the rest of the module by this point,
        # so newly added nodes need the same treatment done incrementally instead of a full re-resolve.
        resolve_subtree(child, scope_ref_global(namespace))
        bind_names(child)

        return child
