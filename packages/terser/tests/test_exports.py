from pathlib import Path

import pytest

from terser._pipeline import parser, resolver
from terser.ast import ref
from terser.ast.ref._module._spec import SingleFileModuleSpec


def exported(source: str) -> set[str]:
    module = parser.parse(source, SingleFileModuleSpec(Path("test_module.py")))
    resolver.resolve(module)
    resolver.bind(module)
    return {binding.name for binding in ref(module).bindings if binding.exported}


@pytest.mark.parametrize("source,expected", [
    ("x = 1\n_y = 2\n__z = 3", {"x", "_y"}),
    ("__all__ = ['x']\nx = y = 1", {"x"}),
    ("__all__ = ('x',)\nx = y = 1", {"x"}),
    ("__all__ = []\nx = 1", set()),
    # without `__all__`, an import is only re-exported as `import x as x`
    ("import os\nfrom typing import cast\nfrom a import b as b\nimport c as c", {"b", "c"}),
    ("__all__ = ['os']\nimport os", {"os"}),
])
def test_exports(source, expected):
    assert exported(source) == expected
