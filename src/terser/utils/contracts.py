from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import EllipsisType


class NodeReplacer(ast.NodeVisitor):
    def __init__(self, replaces: dict[str, ast.AST]):
        self.replaces = replaces

    def visit_Name(self, node: ast.Name):
        return self.replaces.get(node.id, node)


@dataclass(frozen=True)
class ContractFunctionSpec:
    namespace: str
    name: str


@dataclass(frozen=True)
class Contract:
    name: str                               # e.g. "typing.cast", "terser_annotations.not_none"
    args: list[str | None] | EllipsisType   # e.g. [None, "value"], ...
    convert_to: str | None                  # e.g. "value", 또는 None(제거)

    def convert(self, /, **kwargs):
        if not self.convert_to:
            return ast.Constant(value=None)

        convert_to = ast.parse(self.convert_to, mode="eval").body
        return NodeReplacer(kwargs).visit(convert_to)


def __parse_name(node: ast.expr, /) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        raise ValueError(f"Invalid node type: {ast.dump(node)}")
    parts.append(node.id)
    parts.reverse()
    return ".".join(parts)


def __parse_params(call: ast.Call, /) -> list[str | None] | EllipsisType:
    if len(call.args) == 1 and isinstance(arg := call.args[0], ast.Constant) and arg.value is Ellipsis:
        return ...

    params: list[str | None] = []
    for arg in call.args:
        if not isinstance(arg, ast.Name):
            raise ValueError(f"Invalid node type: {ast.dump(arg)}")
        params.append(None if arg.id == "_" else arg.id)
    return params


def __parse_template(rhs: str) -> str | None:
    rhs = rhs.strip()
    node = ast.parse(rhs, mode="eval").body
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    return rhs


def parse(rule: str, /) -> Contract:
    lhs, sep, rhs = rule.partition("->")
    if not sep:
        raise ValueError(f"Separator not found: {rule!r}")

    call = ast.parse(lhs.strip(), mode="eval").body
    if not isinstance(call, ast.Call):
        raise ValueError(f"Invalid function call: {lhs!r}")

    return Contract(
        name=__parse_name(call.func),
        args=__parse_params(call),
        convert_to=__parse_template(rhs),
    )
