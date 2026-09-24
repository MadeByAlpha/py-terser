from terser.ast import ast, is_constant_node, ref
from ._suite import SuiteTransformer


class RemoveDebug(SuiteTransformer):
    """
    Remove if statements where the condition tests __debug__ is True

    If a statement is syntactically necessary, use an empty expression instead
    """
    FLAGS = 0

    @classmethod
    def is_enabled(cls, config, /) -> bool:
        return config.optimize == 2 or config.remove_debug

    @staticmethod
    def __constant(node):
        if is_constant_node(node, ast.NameConstant):
            return node.value
        return None

    def __can_remove(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.If):
            return False

        def is_simple_debug_check(node: ast.If):
            # Simple case: if __debug__:
            if isinstance(node.test, ast.Name) and node.test.id == '__debug__':
                return True
            return False

        def is_truthy_debug_comparison(node: ast.If):
            # Comparison case: if __debug__ is True / False / etc.
            if not isinstance(node.test, ast.Compare):
                return False

            if not isinstance(node.test.left, ast.Name):
                return False

            if node.test.left.id != '__debug__':
                return False

            if len(node.test.ops) == 1:
                op = node.test.ops[0]
                comparator_value = self.__constant(node.test.comparators[0])

                if isinstance(op, ast.Is) and comparator_value is True:
                    return True
                if isinstance(op, ast.IsNot) and comparator_value is False:
                    return True
                if isinstance(op, ast.Eq) and comparator_value is True:
                    return True

            return False

        if is_simple_debug_check(node) or is_truthy_debug_comparison(node):
            return True
        return False

    def __without_debug(self, node_list, parent):
        result = []
        for node in node_list:
            if not self.__can_remove(node):
                result.append(self.visit(node))
                continue

            # the branch taken when __debug__ is False stays: `else` statements, or an `elif` chain
            for statement in node.orelse:
                ref(statement).parent = parent
            result.extend(self.__without_debug(node.orelse, parent))

        return result

    def suite(self, node_list, parent):
        without_debug = self.__without_debug(node_list, parent)

        if len(without_debug) == 0:
            if isinstance(parent, ast.Module):
                return []
            else:
                return [self.add_child(ast.Expr(value=ast.Num(0)), parent=parent)]

        return without_debug
