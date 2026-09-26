import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import CombineImports


@pytest.mark.parametrize("source,expected", [
    ("import a\nimport b", "import a, b"),
    ("import a as x\nimport b", "import a as x, b"),
    ("from c import d\nfrom c import e as f", "from c import d, e as f"),
    ("import a\nfrom c import d\nimport b", "import a\nfrom c import d\nimport b"),
    ("from c import d\nfrom e import f", "from c import d\nfrom e import f"),
    ("from . import a\nfrom . import b", "from . import a, b"),
    ("from c import *\nfrom c import d", "from c import *\nfrom c import d"),
    ("def f():\n    import a\n    import b\n    return a, b", "def f():\n    import a, b\n    return a, b"),
])
def test_combine_imports(source, expected):
    assert_code(apply_transform(source, CombineImports, only("combine_imports")), expected)
