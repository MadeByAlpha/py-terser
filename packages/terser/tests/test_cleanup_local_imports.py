import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import CleanupLocalImports
from terser.ast import ref


@pytest.mark.parametrize("source,expected", [
    ("def f():\n    import os\n    import json\n    return json", "def f():\n    import json\n    return json"),
    ("def f():\n    import os, json\n    return json", "def f():\n    import json\n    return json"),
    ("def f():\n    from os import path, sep\n    return sep", "def f():\n    from os import sep\n    return sep"),
    ("def f():\n    import os", "def f():\n    0"),
    # module-level imports may be used by other modules
    ("import os", "import os"),
])
def test_cleanup_local_imports(source, expected):
    assert_code(apply_transform(source, CleanupLocalImports, only("cleanup_local_imports")), expected)


@pytest.mark.parametrize("source,expected", [
    ("import os\nimport sys\n__all__ = ['x']\nx = sys", "import sys\n__all__ = ['x']\nx = sys"),
    ("import os\n__all__ = ['os']", "import os\n__all__ = ['os']"),
])
def test_respect_all(source, expected):
    config = only("cleanup_local_imports", "respect_all")
    assert_code(apply_transform(source, CleanupLocalImports, config), expected)


def test_removed_import_is_forgotten():
    # a binding left behind still referenced the removed alias: once `ConvertToLambda` moved it
    # into the lambda the function became, local renaming never found the alias in it, and hung
    module = apply_transform(
        "def f():\n    from os import path\n    return 1", CleanupLocalImports, only("cleanup_local_imports")
    )
    assert_code(module, "def f():\n    return 1")
    function = module.body[0]
    assert [binding.name for binding in ref(function).bindings] == []
