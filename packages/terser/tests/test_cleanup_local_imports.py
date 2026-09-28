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
    # a compiler directive: the annotations left stay unevaluated strings
    ("from __future__ import annotations\n__all__ = ['x']\nx: Undefined = 1", "from __future__ import annotations\n__all__ = ['x']\nx: Undefined = 1"),
    ("from __future__ import annotations as _a\ndef f(x: Undefined): pass", "from __future__ import annotations as _a\ndef f(x: Undefined): pass"),
    # nothing left for it to do
    ("from __future__ import annotations\nx = 1\nclass A:\n    b: 0", "x = 1\nclass A:\n    b: 0"),
    ("from __future__ import annotations, division, barry_as_FLUFL\nx = 1", "from __future__ import barry_as_FLUFL\nx = 1"),
    # whether it raises `ImportError` is what it's for, like FastAPI's
    (
        "try:\n    import email_validator\n    from pydantic import EmailStr\nexcept ImportError:\n    EmailStr = str\n__all__ = ['EmailStr']",
        "try:\n    import email_validator\n    from pydantic import EmailStr\nexcept ImportError:\n    EmailStr = str\n__all__ = ['EmailStr']",
    ),
])
def test_respect_all(source, expected):
    config = only("cleanup_local_imports", "respect_all")
    assert_code(apply_transform(source, CleanupLocalImports, config, link=True), expected)


def test_respect_all_waits_for_the_project_to_be_linked():
    # before, it's not known if other modules import `os` from this one
    source = "import os\nimport sys\n__all__ = ['x']\nx = sys"
    config = only("cleanup_local_imports", "respect_all")
    assert_code(apply_transform(source, CleanupLocalImports, config), source)


def test_removed_import_is_forgotten():
    # a binding left behind still referenced the removed alias: once `ConvertToLambda` moved it
    # into the lambda the function became, local renaming never found the alias in it, and hung
    module = apply_transform(
        "def f():\n    from os import path\n    return 1", CleanupLocalImports, only("cleanup_local_imports")
    )
    assert_code(module, "def f():\n    return 1")
    function = module.body[0]
    assert [binding.name for binding in ref(function).bindings] == []
