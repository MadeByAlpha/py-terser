from __future__ import annotations

import sys

import terser.ast.ast as ast

from terser._pipeline.transforms._suite import SuiteTransformer


class RemoveObject(SuiteTransformer):
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.remove_explicit_base

    def visit_ClassDef(self, node):
        node.bases = [
            b for b in node.bases if not isinstance(b, ast.Name) or (isinstance(b, ast.Name) and b.id != 'object')
        ]

        if hasattr(node, 'type_params') and node.type_params is not None:
            node.type_params = [self.visit(t) for t in node.type_params]

        node.body = [self.visit(n) for n in node.body]

        return node
