from __future__ import annotations

from typing import override

from terser.ast import ast, ref
from terser.config import RemoveAnnotationOptions, TransformConfig
from ._suite import SuiteTransformer, TransformerFlag


class RemoveAnnotations(SuiteTransformer):
    """
    Remove type annotations from source
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.remove_annotations is not False

    def __init__(self, ctx):
        super().__init__(ctx)
        self._options = RemoveAnnotationOptions() if isinstance(self._config.remove_annotations, bool) else self._config.remove_annotations

    def visit_FunctionDef(self, node):
        node.args = self.visit_arguments(node.args)
        node.body = self.suite(node.body, parent=node)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]

        if hasattr(node, 'type_params') and node.type_params is not None:
            node.type_params = [self.visit(t) for t in node.type_params]

        if hasattr(node, 'returns') and self._options.remove_return_annotations:
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
            if self._options.remove_argument_annotations:
                node.varargannotation = None
        else:
            if node.vararg:
                node.vararg = self.visit_arg(node.vararg)

        if hasattr(node, 'kwargannotation'):
            if self._options.remove_argument_annotations:
                node.kwargannotation = None
        else:
            if node.kwarg:
                node.kwarg = self.visit_arg(node.kwarg)

        return node

    def visit_arg(self, node):
        if self._options.remove_argument_annotations:
            node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        def is_dataclass_field(node_ref):
            if not isinstance(node_ref.parent, ast.ClassDef):
                return False

            if len(node_ref.parent.decorator_list) == 0:
                return False

            for decorator_node in node_ref.parent.decorator_list:
                if isinstance(decorator_node, ast.Name) and decorator_node.id == 'dataclass':
                    return True
                elif isinstance(decorator_node, ast.Attribute) and decorator_node.attr == 'dataclass':
                    return True
                elif isinstance(decorator_node, ast.Call) and isinstance(decorator_node.func, ast.Name) and decorator_node.func.id == 'dataclass':
                    return True
                elif isinstance(decorator_node, ast.Call) and isinstance(decorator_node.func, ast.Attribute) and decorator_node.func.attr == 'dataclass':
                    return True

            return False

        def is_typing_sensitive(node_ref):
            if not isinstance(node_ref.parent, ast.ClassDef):
                return False

            if len(node_ref.parent.bases) == 0:
                return False

            tricky_types = ['NamedTuple', 'TypedDict']

            for base_node in node_ref.parent.bases:
                if isinstance(base_node, ast.Name) and base_node.id in tricky_types:
                    return True
                elif isinstance(base_node, ast.Attribute) and base_node.attr in tricky_types:
                    return True

            return False

        # is this a class attribute or a variable?
        node_ref = ref(node)
        if isinstance(node_ref.parent, ast.ClassDef):
            if not self._options.remove_attribute_annotations:
                return node
        else:
            if not self._options.remove_variable_annotations:
                return node

        if is_dataclass_field(node_ref) or is_typing_sensitive(node_ref):
            return node
        elif node.value:
            return self.add_child(ast.Assign([node.target], node.value), parent=node_ref.parent, namespace=node_ref.namespace)
        else:
            # Valueless annotations cause the interpreter to treat the variable as a local.
            # I don't know of another way to do that without assigning to it, so
            # keep it as an AnnAssign, but replace the ref with '0'

            node.annotation = self.add_child(ast.Num(0), parent=node_ref.parent, namespace=node_ref.namespace)
            return node
