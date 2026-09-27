from typing import override

from terser.ast import ast, ref
from terser.ast.ref._node import NodeRef
from terser.config import TransformConfig
from ._suite import SuiteTransformer


class ConvertToInline(SuiteTransformer):
    """
    Convert `if cond: func(x)` to `cond and func(x)`, and
    `if fizz: foo()` / `else: bar()` to `foo() if fizz else bar()`
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_to_inline

    def _wrap(self, expr: ast.expr, *reused: ast.expr, parent: ast.AST, namespace: ast.AST) -> ast.Expr:
        """
        Wrap `expr` (brand new, but holding *reused* subtrees like the `if`'s own test/body)
        in an `Expr` statement.

        This runs pre-resolve (`FLAGS = 0`), before names have been bound at all - `add_child`
        would work here too, but its full recursive re-registration walk calls `bind_names` on
        the reused subtrees as if they were brand new. At this point in the file, a name a reused
        subtree references (e.g. a module imported earlier in the file) may not have its real
        binding yet, so that premature bind creates a placeholder `UnresolvedBinding` which then
        squats the name - once the real declaration is bound later, resolution finds the
        placeholder already there and never upgrades it, breaking any later `qualified_name`-based
        check on it. Only the genuinely new nodes here (`expr`, the `Expr` wrapper) need a fresh
        `NodeRef`; the reused ones just need their `parent` pointer updated.
        """
        new_node = ast.Expr(value=expr)

        new_nodes = [new_node, expr, *([expr.op] if isinstance(expr, ast.BoolOp) else [])]
        for node in new_nodes:
            NodeRef.new(node, parent if node is new_node else expr)
            ref(node).namespace = namespace

        for node in reused:
            ref(node).parent = expr

        return new_node

    @override
    def visit_If(self, node: ast.If):
        node: ast.If = self.generic_visit(node)

        if len(node.body) != 1 or not isinstance(node.body[0], ast.Expr):
            return node

        a = node.body[0].value
        # The new statement takes `node`'s exact place in the tree, so it belongs to
        # exactly the scope `node` already resolved to - no need to recompute it (and
        # `ref(parent).namespace` would be wrong: `parent` here is itself a scope node,
        # so that would walk one level too far up, to the scope *containing* it).
        parent = ref(node).parent
        namespace = ref(node).namespace

        if not node.orelse:
            return self._wrap(ast.BoolOp(op=ast.And(), values=[node.test, a]), node.test, a, parent=parent, namespace=namespace)

        if len(node.orelse) != 1 or not isinstance(node.orelse[0], ast.Expr):
            return node

        b = node.orelse[0].value
        return self._wrap(ast.IfExp(test=node.test, body=a, orelse=b), node.test, a, b, parent=parent, namespace=namespace)
