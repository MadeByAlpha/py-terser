from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from terser.utils.hints import is_hinted
from terser.utils.imports import qualified_name
from ._suite import SuiteTransformer, TransformerFlag


def _is_invoke_lambda(decorator: ast.expr) -> bool:
    """
    Matches the `@lambda _: _()` idiom: a single-arg lambda whose body is a no-arg call
    of that same argument - used as a decorator to immediately invoke a `def`, since
    Python has no IIFE syntax for function statements.
    """
    if not isinstance(decorator, ast.Lambda):
        return False

    args = decorator.args
    if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or len(args.args) != 1:
        return False

    body = decorator.body
    return (
        isinstance(body, ast.Call) and not body.args and not body.keywords
        and isinstance(body.func, ast.Name) and body.func.id == args.args[0].arg
    )


class ApplyConstantDecorator(SuiteTransformer):
    """
    Un-sugar the `@lambda _: _()` / `@terser_hints.constant` "call this function once and
    rebind its name to the result" marker into a plain call and rebind, so later passes
    (`ConvertToLambda`, `UnfoldIIFE`) can collapse it further.
    """
    FLAGS = TransformerFlag.REQUIRES_IMPORT_RESOLVE

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.unfold_iife_lambdas

    def _is_marked(self, decorator: ast.expr) -> bool:
        return _is_invoke_lambda(decorator) or qualified_name(decorator) in (
            {"terser_hints.constant"} | {f"{m}.constant" for m in self._config.hint_modules}
        )

    @override
    def suite(self, node_list, parent):
        result = []
        for node in node_list:
            node = self.visit(node)

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(self._is_marked(d) for d in node.decorator_list):
                node.decorator_list = [d for d in node.decorator_list if not self._is_marked(d)]
                result.append(node)
                result.append(self.add_child(
                    ast.Assign(
                        targets=[ast.Name(id=node.name, ctx=ast.Store())],
                        value=ast.Call(func=ast.Name(id=node.name, ctx=ast.Load()), args=[], keywords=[]),
                    ),
                    parent=parent,
                ))
                continue

            result.append(node)

        return result
