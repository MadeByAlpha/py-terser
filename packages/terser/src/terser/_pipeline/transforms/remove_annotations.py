from __future__ import annotations

import fnmatch
from typing import override

from terser.ast import ast, ref
from terser.config import RemoveAnnotationOptions, TransformConfig
from terser.utils.hints import is_hinted
from terser.utils.imports import qualified_name
from ._classes import class_definition
from ._suite import SuiteTransformer, TransformerFlag

if __debug__ and __import__("typing").TYPE_CHECKING:
    from terser.ast import ModuleRef

_ANNOTATED_NAMES = ("typing.Annotated", "typing_extensions.Annotated")

# classes built from the annotations in their body (and a subclass of one, or a class of one of the
# metaclasses): `x: int = 0` is a field there, `x = 0` a plain class attribute
_ANNOTATION_READERS = frozenset({
    "typing.NamedTuple", "typing_extensions.NamedTuple",
    "typing.TypedDict", "typing_extensions.TypedDict",
    "pydantic.BaseModel", "pydantic.main.BaseModel",
    "pydantic.RootModel", "pydantic.root_model.RootModel",
    "pydantic._internal._model_construction.ModelMetaclass",
    "pydantic.v1.BaseModel", "pydantic.v1.main.BaseModel", "pydantic.v1.main.ModelMetaclass",
    "pydantic_settings.BaseSettings", "pydantic_settings.main.BaseSettings",
    "sqlmodel.SQLModel", "sqlmodel.main.SQLModel",
    "msgspec.Struct",
})

# class decorators reading the annotations in the class body
_ANNOTATION_READING_DECORATORS = frozenset({
    "dataclasses.dataclass",
    "pydantic.dataclasses.dataclass",
    "attr.s", "attr.attrs", "attr.define", "attr.frozen", "attr.mutable",
    "attrs.define", "attrs.frozen", "attrs.mutable",
})


def _is_annotated(annotation: ast.expr | None) -> bool:
    """
    `Annotated[X, ...]` metadata is often consumed at runtime (e.g. pydantic `Field(...)`, FastAPI
    dependencies) - a bare signature/attribute type can't express that, so stripping it risks
    losing information the annotation itself never encoded. Bare string (forward-ref) annotations
    can't be `Annotated[...]` at the AST level, so they always fall through and get stripped.
    """
    return isinstance(annotation, ast.Subscript) and qualified_name(annotation.value) in _ANNOTATED_NAMES


def _syntactic_reader(node: ast.ClassDef) -> bool:
    """A class read by name alone: `@dataclass`-decorated, or a direct `NamedTuple`/`TypedDict` subclass."""

    for decorator in node.decorator_list:
        func = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(func, ast.Name) and func.id == 'dataclass' or isinstance(func, ast.Attribute) and func.attr == 'dataclass':
            return True

    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ('NamedTuple', 'TypedDict'):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ('NamedTuple', 'TypedDict'):
            return True
    return False


class _Readers:
    """
    Which classes have their annotations read at run time: ones `_syntactic_reader` tells, and the
    ones whose bases or metaclass lead (through the project's linked imports, if any) to one of
    `_ANNOTATION_READERS`, or whose decorators are among `_ANNOTATION_READING_DECORATORS`.
    """

    def __init__(self):
        self._known: dict[int, bool] = {}

    def __call__(self, module_ref: ModuleRef, node: ast.ClassDef) -> bool:
        if (known := self._known.get(id(node))) is not None:
            return known

        self._known[id(node)] = False  # while it's being looked at: a cycle reads nothing
        self._known[id(node)] = result = self._reads(module_ref, node)
        return result

    def _reads(self, module_ref: ModuleRef, node: ast.ClassDef) -> bool:
        if _syntactic_reader(node):
            return True

        if ref(node).namespace is module_ref.ast and f"{module_ref.spec}.{node.name}" in _ANNOTATION_READERS:
            return True

        for decorator in node.decorator_list:
            if qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator) in _ANNOTATION_READING_DECORATORS:
                return True

        metaclasses = [keyword.value for keyword in node.keywords if keyword.arg == 'metaclass']
        return any(self._leads_to_reader(module_ref, base) for base in (*node.bases, *metaclasses))

    def _leads_to_reader(self, module_ref: ModuleRef, node: ast.expr) -> bool:
        while isinstance(node, ast.Subscript):  # `RootModel[int]`, `Generic[T]`
            node = node.value

        if qualified_name(node) in _ANNOTATION_READERS:
            return True

        found = class_definition(module_ref, node)
        return found is not None and self(*found)

class RemoveAnnotations(SuiteTransformer):
    """
    Remove type annotations from source

    Left alone: `Annotated[...]`, what `@terser_hints.preserve_annotations` or
    `config.preserve_annotations` names, and the body of every class whose annotations are read at
    run time (pydantic models, dataclasses, `TypedDict`s... see `_Readers`): its fields, and its
    methods' too (pydantic's `computed_field` reads the return type). Needs the module linked, to
    follow a class's bases into the other modules of the project.
    """
    FLAGS = TransformerFlag.REQUIRES_MODULE_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_annotations is not False

    def __init__(self, ctx):
        super().__init__(ctx)
        self._options = RemoveAnnotationOptions() if isinstance(self._config.remove_annotations, bool) else self._config.remove_annotations
        self._readers = _Readers()
        self._scopes: list[str] = []
        # `__qualname__` of the class or function being visited, and if it's a function
        self._enclosing: tuple[str | None, bool] = (None, False)

    @override
    def visit_Module(self, node: ast.Module):
        self._module_ref = ref(node)
        module_path = str(self._module_ref.spec)

        for pattern in self._config.preserve_annotations:
            module_pattern, sep, qualname = pattern.partition('::')
            if fnmatch.fnmatch(module_path, module_pattern):
                if not sep:
                    return node  # the whole module
                self._scopes.append(qualname)

        return super().visit_Module(node)

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[str | None, bool]:
        """Visit `node`'s scope: the enclosing one to go back to after, and if `node` is preserved as a whole"""

        enclosing, in_function = previous = self._enclosing
        qualname = node.name if enclosing is None else f"{enclosing}.<locals>.{node.name}" if in_function else f"{enclosing}.{node.name}"
        self._enclosing = qualname, not isinstance(node, ast.ClassDef)
        return previous

    def _preserved(self) -> bool:
        return any(fnmatch.fnmatchcase(self._enclosing[0], scope) for scope in self._scopes)

    def _reads_annotations(self, node: ast.ClassDef) -> bool:
        marked = getattr(ref(node), 'reads_annotations', None)
        return marked if marked is not None else self._readers(self._module_ref, node)

    @override
    def visit_ClassDef(self, node):
        previous = self._enter(node)
        try:
            if (
                self._preserved() or self._reads_annotations(node)
                or is_hinted(node.decorator_list, "preserve_annotations", self._config)
            ):
                return node
            return super().visit_ClassDef(node)
        finally:
            self._enclosing = previous

    def visit_FunctionDef(self, node):
        previous = self._enter(node)
        try:
            if self._preserved():
                return node
            return self._visit_function(node)
        finally:
            self._enclosing = previous

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def _visit_function(self, node):
        preserved = is_hinted(node.decorator_list, "preserve_annotations", self._config)

        node.args = node.args if preserved else self.visit_arguments(node.args)
        node.body = self.suite(node.body, parent=node)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]

        if hasattr(node, 'type_params') and node.type_params is not None:
            node.type_params = [self.visit(t) for t in node.type_params]

        if hasattr(node, 'returns') and self._options.remove_return_annotations and not preserved and not _is_annotated(node.returns):
            node.returns = None

        return node

    def visit_arguments(self, node):
        assert isinstance(node, ast.arguments)

        if hasattr(node, 'posonlyargs') and node.posonlyargs:
            node.posonlyargs = [self.visit_arg(a) for a in node.posonlyargs]

        if node.args:
            node.args = [self.visit_arg(a) for a in node.args]

        if hasattr(node, 'kwonlyargs') and node.kwonlyargs:
            node.kwonlyargs = [self.visit_arg(a) for a in node.kwonlyargs]

        if hasattr(node, 'varargannotation'):
            if self._options.remove_argument_annotations and not _is_annotated(node.varargannotation):
                node.varargannotation = None
        else:
            if node.vararg:
                node.vararg = self.visit_arg(node.vararg)

        if hasattr(node, 'kwargannotation'):
            if self._options.remove_argument_annotations and not _is_annotated(node.kwargannotation):
                node.kwargannotation = None
        else:
            if node.kwarg:
                node.kwarg = self.visit_arg(node.kwarg)

        return node

    def visit_arg(self, node):
        if self._options.remove_argument_annotations and not _is_annotated(node.annotation):
            node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        # a class whose annotations are read, or that is preserved, isn't visited at all
        node_ref = ref(node)
        if isinstance(node_ref.parent, ast.ClassDef):
            if not self._options.remove_attribute_annotations:
                return node
        elif not self._options.remove_variable_annotations:
            return node

        if _is_annotated(node.annotation):
            return node
        elif node.value:
            return self.add_child(ast.Assign([node.target], node.value), parent=node_ref.parent, namespace=node_ref.namespace)
        else:
            # Valueless annotations cause the interpreter to treat the variable as a local.
            # I don't know of another way to do that without assigning to it, so
            # keep it as an AnnAssign, but replace the ref with '0'

            node.annotation = self.add_child(ast.Num(0), parent=node_ref.parent, namespace=node_ref.namespace)
            return node
