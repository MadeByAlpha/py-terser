import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import RemoveDeadCode


@pytest.mark.parametrize("source,expected", [
    ("if False:\n    a()\nb()", "b()"),
    ("if 0:\n    a()\nelse:\n    b()", "b()"),
    ("if True:\n    a()\nelse:\n    b()", "a()"),
    ("if False:\n    a()\nelif x:\n    b()\nelse:\n    c()", "if x:\n    b()\nelse:\n    c()"),
    ("if x:\n    a()\nelif False:\n    b()\nelse:\n    c()", "if x:\n    a()\nelse:\n    c()"),
    ("if not True:\n    a()", ""),
    ("if False and x:\n    a()", ""),
    ("if x and False:\n    a()", "if x and False:\n    a()"),  # `x` is still evaluated
    ("if __debug__ and False:\n    a()", ""),
    ("if __debug__ or True:\n    a()", "a()"),
    ("if __debug__:\n    a()", "if __debug__:\n    a()"),
    ("while False:\n    a()\nelse:\n    b()", "b()"),
    ("while True:\n    break", "while True:\n    break"),
    ("def f():\n    if False:\n        a()", "def f():\n    0"),
    ("if False:\n    import os\nprint(os)", "print(os)"),
    ("def f():\n    if False:\n        x = 1\n    else:\n        x = 2\n    return x", "def f():\n    x = 2\n    return x"),
    # still how the function compiles
    ("def f():\n    if False:\n        yield", "def f():\n    if False:\n        yield"),
    ("def f():\n    if False:\n        global x\n    x = 1", "def f():\n    if False:\n        global x\n    x = 1"),
    ("def f():\n    if False:\n        x = 1\n    return x", "def f():\n    if False:\n        x = 1\n    return x"),
    ("def f():\n    if False:\n        def g():\n            yield\n    return 1", "def f():\n    return 1"),
])
def test_remove_dead_code(source, expected):
    assert_code(apply_transform(source, RemoveDeadCode, only("remove_dead_code")), expected)


def test_bindings_follow():
    from terser.ast import ref
    from terser._pipeline.resolver.binding import ImportBinding, UnresolvedBinding

    module = apply_transform("if False:\n    import os\nprint(os)", RemoveDeadCode, only("remove_dead_code"))
    module_ref = ref(module)
    assert not module_ref.import_targets
    assert not any(isinstance(binding, ImportBinding) for binding in module_ref.bindings)
    [call] = module.body
    assert isinstance(ref(call.value.args[0]).binding, UnresolvedBinding)
