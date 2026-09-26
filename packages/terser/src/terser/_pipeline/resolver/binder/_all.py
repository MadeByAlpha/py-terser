from __future__ import annotations

from typing import TYPE_CHECKING

from terser.ast import ast, is_constant_node, ref

if TYPE_CHECKING:
    from typing import TypeIs


def __is_assign(node: ast.AST) -> TypeIs[ast.Assign | ast.AnnAssign | ast.AugAssign]:
    if isinstance(node, ast.Assign):
        for name in node.targets:
            if isinstance(name, ast.Name) and name.id == '__all__':
                return True

    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        if isinstance(node.target, ast.Name) and node.target.id == '__all__':
            return True

    return False

def resolve_all(module: ast.Module):
    names = set[str]()

    for node in ast.iter_child_nodes(module):
        if not __is_assign(node):
            continue

        if not isinstance(node.value, ast.List):
            continue

        for el in node.value.elts:
            if is_constant_node(el, ast.Str):
                names.add(el.s)

    ref(module).all = names
