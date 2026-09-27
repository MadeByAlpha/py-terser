from terser.ast import ast
from terser.config import TransformConfig
from .imports import qualified_name


def is_hinted(decorator_list: list[ast.expr], hint: str, config: TransformConfig) -> bool:
    """
    Check if any decorator in `decorator_list` matches the terser hint named `hint`
    (`terser_hints.<hint>`, or `<module>.<hint>` for any alias in `config.hint_modules`).
    """
    names = {f"terser_hints.{hint}"}
    names.update(f"{module}.{hint}" for module in config.hint_modules)
    return any(qualified_name(d) in names for d in decorator_list)
