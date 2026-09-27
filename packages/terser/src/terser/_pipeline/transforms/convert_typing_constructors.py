from typing import override

from terser.ast import ast, ref
from terser.config import TransformConfig
from terser.utils.imports import qualified_name
from ..resolver.util import insert
from ._suite import SuiteTransformer, TransformerFlag

_NAMEDTUPLE_NAMES = ("typing.NamedTuple", "typing_extensions.NamedTuple")
_TYPEDDICT_NAMES = ("typing.TypedDict", "typing_extensions.TypedDict")

# Sentinel: the class isn't safe to convert as-is - leave it as a plain ClassDef
_UNSAFE = object()


def _simple_fields(node: ast.ClassDef) -> list[ast.AnnAssign] | None:
    if len(node.bases) != 1 or node.keywords:
        return None

    fields: list[ast.AnnAssign] = []
    for stmt in node.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            return None
        fields.append(stmt)

    return fields


class ConvertTypingConstructors(SuiteTransformer):
    """
    Convert simple `NamedTuple`/`TypedDict` class definitions (fields only, no
    methods) to `collections.namedtuple`/`dict` constructors, dropping the
    dependency on `typing`.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    _module: ast.Module
    _collections_imported: bool
    _needs_collections_import: bool

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_typing_constructors

    @override
    def visit_Module(self, node: ast.Module):
        self._module = node
        self._collections_imported = any(
            isinstance(stmt, ast.Import) and any(a.name == 'collections' for a in stmt.names) for stmt in node.body
        )
        self._needs_collections_import = False

        node.body = self.suite(node.body, parent=node)

        if self._needs_collections_import and not self._collections_imported:
            import_stmt = self.add_child(ast.Import(names=[ast.alias(name='collections', asname=None)]), parent=node)
            node.body = list(insert(node.body, import_stmt))

        return node

    def _ensure_collections_import(self):
        if not self._collections_imported:
            self._needs_collections_import = True

    def _convert_named_tuple(self, node: ast.ClassDef, fields: list[ast.AnnAssign]):
        names: list[str] = []
        for f in fields:
            assert isinstance(f.target, ast.Name)
            names.append(f.target.id)

        values = [f.value for f in fields]

        # namedtuple only allows a trailing run of fields to have defaults
        first_default = next((i for i, v in enumerate(values) if v is not None), len(values))
        if any(v is None for v in values[first_default:]):
            return _UNSAFE

        defaults: list[ast.expr] = []
        for v in values[first_default:]:
            assert v is not None
            defaults.append(v)

        call = ast.Call(
            func=ast.Attribute(value=ast.Name(id='collections', ctx=ast.Load()), attr='namedtuple', ctx=ast.Load()),
            args=[ast.Constant(value=node.name), ast.Tuple(elts=[ast.Constant(value=n) for n in names], ctx=ast.Load())],
            keywords=[ast.keyword(arg='defaults', value=ast.Tuple(elts=defaults, ctx=ast.Load()))] if defaults else [],
        )
        new_node = ast.Assign(targets=[ast.Name(id=node.name, ctx=ast.Store())], value=call)

        self._ensure_collections_import()
        return self.add_child(new_node, parent=ref(node).parent)

    def _convert_typed_dict(self, node: ast.ClassDef):
        binding = ref(node).binding
        if binding.exported:
            return _UNSAFE  # may be used from other modules, which this per-module pass can't see

        other_refs = [r for r in binding.references if r is not node]

        for r in other_refs:
            if not isinstance(r, ast.Name):
                return _UNSAFE  # used somewhere other than a plain name (e.g. as a base class)

            call = ref(r).parent
            if not isinstance(call, ast.Call) or call.func is not r or call.args:
                return _UNSAFE  # not a pure-keyword constructor call

        for r in other_refs:
            call = ref(r).parent
            assert isinstance(call, ast.Call)
            call.func = self.add_child(ast.Name(id='dict', ctx=ast.Load()), parent=call)

        return None  # the class definition itself is dropped

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            fields = _simple_fields(node) if isinstance(node, ast.ClassDef) else None
            base_name = qualified_name(node.bases[0]) if fields is not None else None

            if fields is not None and base_name in _NAMEDTUPLE_NAMES:
                converted = self._convert_named_tuple(node, fields)
                result.append(self.visit(node) if converted is _UNSAFE else converted)
                continue

            if fields is not None and base_name in _TYPEDDICT_NAMES:
                converted = self._convert_typed_dict(node)
                if converted is _UNSAFE:
                    result.append(self.visit(node))
                elif converted is not None:
                    result.append(self.visit(converted))
                continue

            result.append(self.visit(node))

        if not result:
            return [] if isinstance(parent, ast.Module) else [self.add_child(ast.Expr(ast.Num(0)), parent=parent)]

        return result
