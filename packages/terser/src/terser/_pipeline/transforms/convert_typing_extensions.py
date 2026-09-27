from typing import override

from terser.ast import ast
from terser.config import TransformConfig
from ._suite import SuiteTransformer

# Symbols long-stable in `typing` (project requires Python >=3.14) - safe to
# rewrite a `from typing_extensions import X` to `from typing import X`
_STABLE_IN_TYPING = frozenset((
    "Protocol", "TypedDict", "Literal", "Final", "overload", "override", "TypeAlias", "ParamSpec",
    "Concatenate", "Self", "Never", "assert_never", "assert_type", "runtime_checkable", "get_args", "get_origin",
))


class ConvertTypingExtensions(SuiteTransformer):
    """
    Convert `from typing_extensions import X` to `from typing import X`, for
    symbols that are stable in `typing`. Unknown/newer `typing_extensions`-only
    names (or a mix of stable and unknown names in one statement) are left
    untouched.
    """
    FLAGS = 0

    @override
    @classmethod
    def is_enabled(cls, config: TransformConfig, /) -> bool:
        return config.convert_typing_extensions

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module != "typing_extensions" or any(a.name not in _STABLE_IN_TYPING for a in node.names):
            return node

        node.module = "typing"
        return node
