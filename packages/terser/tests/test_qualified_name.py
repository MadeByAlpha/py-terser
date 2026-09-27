from pathlib import Path

import pytest

from terser._pipeline import parser, resolver
from terser.ast import ast
from terser.ast.ref._module._spec import SingleFileModuleSpec
from terser.utils.imports import qualified_name


def qualified(source: str) -> str | None:
    """`qualified_name` of the last statement's expression, once `source` is bound"""

    module = parser.parse(source, SingleFileModuleSpec(Path("test_module.py")))
    resolver.resolve(module)
    resolver.bind(module)
    last = module.body[-1]
    assert isinstance(last, ast.Expr)
    return qualified_name(last.value)


@pytest.mark.parametrize("source,expected", [
    ("import typing\ntyping.cast", "typing.cast"),
    ("import typing as t\nt.cast", "typing.cast"),
    ("import typing\ntyping", "typing"),
    ("from typing import cast\ncast", "typing.cast"),
    ("from typing import override as ov\nov", "typing.override"),
    ("import os.path\nos.path.join", "os.path.join"),
    ("import os.path as p\np.join", "os.path.join"),
    # dynamic imports
    ("__import__('typing').cast", "typing.cast"),
    ("__import__('os.path').path", "os.path"),  # `__import__()` returns the top package
    ("__import__('os.path', fromlist=['x']).join", "os.path.join"),
    ("import importlib\nimportlib.import_module('os.path').join", "os.path.join"),
    ("t = __import__('typing')\nt.cast", "typing.cast"),
    ("cast = __import__('typing').cast\ncast", "typing.cast"),
    # not an import
    ("x.cast", None),
    ("t = __import__('typing')\nt = x\nt.cast", None),
    ("def __import__(name): pass\n__import__('typing').cast", None),
    ("__import__(name).cast", None),
])
def test_qualified_name(source, expected):
    assert qualified(source) == expected
