from __future__ import annotations

import math
from typing import TYPE_CHECKING, override

from terser.ast import ast, compare_ast, is_constant_node, ref
from terser.ast.ref import ref_or_none
from terser.utils.imports import qualified_name

from ..resolver.binding import BuiltinBinding
from ..printer.expression_printer import ExpressionPrinter
from ..resolver import forget
from ._suite import SuiteTransformer, TransformerFlag

if __debug__ and TYPE_CHECKING:
    from ...config import TransformConfig


def _is_unshadowed_builtin(node, name: str) -> bool:
    if not isinstance(node, ast.Name):
        return False

    binding = ref(node).binding
    return isinstance(binding, BuiltinBinding) and binding.name == name and not binding.is_redefined()


_CONVERSION_FUNCS = {-1: 'str', 115: 'str', 114: 'repr', 97: 'ascii'}


def is_foldable_constant(node):
    """
    Check if a node is a constant expression that can participate in folding.

    We can asume that children have already been folded, so foldable constants are either:
    - Simple literals (Num, NameConstant)
    - UnaryOp(USub/Invert) on a Num - these don't fold to shorter forms,
      so they remain after child visiting. UAdd and Not would have been
      folded away since they always produce shorter results.
    """
    if is_constant_node(node, (ast.Num, ast.NameConstant)):
        return True

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, (ast.USub, ast.Invert)):
            return is_constant_node(node.operand, ast.Num)

    return False


class FoldConstants(SuiteTransformer):
    """
    Fold Constants if it would reduce the size of the source
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.fold_constants

    def fold(self, node):
        # Evaluate the expression
        try:
            original_expression = unparse_expression(node)
            original_value = safe_eval(original_expression)
        except Exception:
            return node

        # Choose the best representation of the value
        if isinstance(original_value, float) and math.isnan(original_value):
            # There is no nan literal.
            # we could use float('nan'), but that complicates folding as it's not a Constant
            return node
        elif isinstance(original_value, bool):
            new_node = ast.NameConstant(value=original_value)
        elif isinstance(original_value, (int, float, complex)):
            try:
                new_node = ast.Num(n=original_value)
            except Exception:
                # repr(value) failed, most likely due to some limit
                return node
        else:
            return node

        # Evaluate the new value representation
        try:
            folded_expression = unparse_expression(new_node)
            folded_value = safe_eval(folded_expression)
        except Exception:
            # This can happen if the value is too large to be represented as a literal
            # or if the value is unparsed as nan, inf or -inf - which are not valid python literals
            return node

        if len(folded_expression) >= len(original_expression):
            # Result is not shorter than original expression
            return node

        # Check the folded expression parses back to the same AST
        try:
            folded_ast = ast.parse(folded_expression, 'folded expression', mode='eval')
            compare_ast(new_node, folded_ast.body)
        except Exception:
            # This can happen if the printed value doesn't parse back to the same AST
            # e.g. complex numbers can be parsed as BinOp
            return node

        # Check the folded value is the same as the original value
        if not equal_value_and_type(folded_value, original_value):
            return node

        # New representation is shorter and has the same value, so use it
        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)

    def visit_BinOp(self, node):

        node.left = self.visit(node.left)
        node.right = self.visit(node.right)

        # Check this is a constant expression that could be folded
        # We don't try to fold strings or bytes, since they have probably been arranged this way to make the source shorter and we are unlikely to beat that
        if not is_foldable_constant(node.left):
            return node
        if not is_foldable_constant(node.right):
            return node

        if isinstance(node.op, ast.Div):
            # Folding div is subtle, since it can have different results in Python 2 and Python 3
            # Do this once target version options have been implemented
            return node

        if isinstance(node.op, ast.Pow):
            # This can be folded, but it is unlikely to reduce the size of the source
            # It can also be slow to evaluate
            return node

        return self.fold(node)

    def visit_UnaryOp(self, node):

        node.operand = self.visit(node.operand)

        # Only fold if the operand is a foldable constant
        if not is_foldable_constant(node.operand):
            return node

        # Only fold these unary operators
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert, ast.Not)):
            return node

        return self.fold(node)

    def visit_BoolOp(self, node):
        node.values = [self.visit(value) for value in node.values]

        # `and` gives the first falsy operand (`or` the first truthy one), else the last: a constant
        # decides it where it's falsy (truthy), and is skipped otherwise, unless it's the last
        deciding = not isinstance(node.op, ast.And)
        values, dropped = [], []
        for i, value in enumerate(node.values):
            if not isinstance(value, ast.Constant):
                values.append(value)
            elif bool(value.value) is deciding:
                values.append(value)
                dropped += node.values[i + 1:]
                break
            elif i == len(node.values) - 1:
                values.append(value)
            else:
                dropped.append(value)

        if not dropped or not _droppable(dropped):
            return node

        forget(dropped)
        if len(values) == 1:
            [value] = values
            _reparent(value, node)
            return value

        node.values = values
        return node

    def visit_IfExp(self, node):
        node.test = self.visit(node.test)
        node.body = self.visit(node.body)
        node.orelse = self.visit(node.orelse)

        if not isinstance(node.test, ast.Constant):
            return node

        value, dropped = (node.body, node.orelse) if node.test.value else (node.orelse, node.body)
        if not _droppable([dropped]):
            return node

        forget([node.test, dropped])
        _reparent(value, node)
        return value

    def visit_Compare(self, node):
        node.left = self.visit(node.left)
        node.comparators = [self.visit(c) for c in node.comparators]

        if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
            return node

        left, right = node.left, node.comparators[0]
        left_bool = is_constant_node(left, ast.NameConstant) and isinstance(left.value, bool)
        right_bool = is_constant_node(right, ast.NameConstant) and isinstance(right.value, bool)

        if left_bool == right_bool:
            # exactly one side must be a bool literal - both or neither isn't this pattern
            return node

        bool_value, other = (left.value, right) if left_bool else (right.value, left)
        negate = bool_value == isinstance(node.ops[0], (ast.NotEq, ast.IsNot))

        new_node = ast.UnaryOp(op=ast.Not(), operand=other) if negate else other
        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)

    def visit_Name(self, node):
        if node.id != '__debug__' or not _is_unshadowed_builtin(node, '__debug__'):
            return node

        new_node = ast.NameConstant(value=self._config.optimize < 1)
        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)

    def visit_Attribute(self, node):
        node.value = self.visit(node.value)

        if qualified_name(node) != 'typing.TYPE_CHECKING':
            return node

        new_node = ast.NameConstant(value=False)
        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)

    def visit_JoinedStr(self, node):
        node.values = [self.visit(v) for v in node.values]

        if any(isinstance(v, ast.FormattedValue) and v.format_spec is not None for v in node.values):
            return node

        terms = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                terms.append(v)
                continue

            func_name = _CONVERSION_FUNCS.get(v.conversion, None)
            if func_name is None:
                return node

            terms.append(ast.Call(func=ast.Name(id=func_name, ctx=ast.Load()), args=[v.value], keywords=[]))

        if not terms:
            new_node = ast.Constant(value='')
        elif len(terms) == 1 and isinstance(terms[0], ast.Call):
            new_node = terms[0]
        else:
            new_node = terms[0]
            for term in terms[1:]:
                new_node = ast.BinOp(left=new_node, op=ast.Add(), right=term)

        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)

    def visit_Call(self, node):
        node.func = self.visit(node.func)
        node.args = [self.visit(a) for a in node.args]
        node.keywords = [self.visit(k) for k in node.keywords]

        if node.keywords:
            return node

        new_node = None
        if not node.args and _is_unshadowed_builtin(node.func, 'list'):
            new_node = ast.List(elts=[], ctx=ast.Load())
        elif not node.args and _is_unshadowed_builtin(node.func, 'dict'):
            new_node = ast.Dict(keys=[], values=[])
        elif not node.args and _is_unshadowed_builtin(node.func, 'tuple'):
            new_node = ast.Tuple(elts=[], ctx=ast.Load())
        elif (
            len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts
            and _is_unshadowed_builtin(node.func, 'set')
        ):
            new_node = ast.Set(elts=node.args[0].elts)

        if new_node is None:
            return node

        node_ref = ref(node)
        return self.add_child(new_node, node_ref.parent, node_ref.namespace)


def _reparent(node, replaced):
    """Put `node` where `replaced` was"""

    if (node_ref := ref_or_none(node)) is not None and (replaced_ref := ref_or_none(replaced)) is not None:
        node_ref.parent = replaced_ref.parent


def _droppable(nodes) -> bool:
    """If expressions that never run can be dropped: none binds a name, or makes a generator"""

    return not any(
        isinstance(node, (ast.NamedExpr, ast.Yield, ast.YieldFrom))
        for root in nodes for node in ast.walk(root)
    )


def equal_value_and_type(a, b):
    if type(a) != type(b):
        return False

    if isinstance(a, float) and math.isnan(a) and not math.isnan(b):
        return False

    return a == b


def safe_eval(expression):
    empty_globals = {}
    empty_locals = {}

    # This will return the value, or could raise an exception
    return eval(expression, empty_globals, empty_locals)


def unparse_expression(node):
    expression_printer = ExpressionPrinter()
    return expression_printer(node)
