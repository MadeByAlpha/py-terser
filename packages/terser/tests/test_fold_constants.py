import pytest

from helpers import apply_transform, assert_code, only
from terser._pipeline.transforms import FoldConstants


@pytest.mark.parametrize("source,expected", [
    ("x = 60 * 60 * 24", "x = 86400"),
    ("x = 1 + 2", "x = 3"),
    ("x = 7 // 2 - 1", "x = 2"),
    ("x = +5", "x = 5"),
    ("x = not 0", "x = True"),
    # only folded when the result is shorter
    ("x = 1 << 20", "x = 1 << 20"),
    # strings are left alone, since they are likely arranged that way for a reason
    ("x = 'a' * 3", "x = 'a' * 3"),
    # division and powers are not folded
    ("x = 10 / 4", "x = 10 / 4"),
    ("x = 10 ** 100", "x = 10 ** 100"),
    ("x = y * 2", "x = y * 2"),
    # a constant operand decides `and`/`or` where it's falsy/truthy, and is skipped otherwise
    ("x = False and y", "x = False"),
    ("x = 0 and y and z", "x = 0"),
    ("x = y and False and z", "x = y and False"),
    ("x = True and y", "x = y"),
    ("x = y and True and z", "x = y and z"),
    ("x = y and True", "x = y and True"),
    ("x = True or y", "x = True"),
    ("x = None or y", "x = y"),
    ("x = y or '' or z", "x = y or z"),
    ("x = not (False and y)", "x = True"),
    ("x = y if True else z", "x = y"),
    ("x = y if 0 else z", "x = z"),
    # operands binding a name, or making a generator, are left
    ("x = False and (y := 1)", "x = False and (y := 1)"),
    ("def f():\n    return False and (yield)", "def f():\n    return False and (yield)"),
    ("x = y if True else (z := 1)", "x = y if True else (z := 1)"),
])
def test_fold_constants(source, expected):
    assert_code(apply_transform(source, FoldConstants, only("fold_constants")), expected)


@pytest.mark.parametrize("source,expected", [
    # `x is True` is a truthiness check only for a bool
    ("x = (y < 1) == True", "x = y < 1"),
    ("x = (y < 1) is False", "x = not y < 1"),
    ("x = (not y) != False", "x = not y"),
    ("x = y == True", "x = y == True"),
    ("x = y is False", "x = y is False"),
    # empty collections
    ("x = list()", "x = []"),
    ("x = dict()", "x = {}"),
    ("x = tuple()", "x = ()"),
    ("x = set([1, 2])", "x = {1, 2}"),
    ("x = set()", "x = set()"),
    ("x = list(y)", "x = list(y)"),
    ("list = tuple\nx = list()", "list = tuple\nx = list()"),
])
def test_fold_builtins(source, expected):
    assert_code(apply_transform(source, FoldConstants, only("fold_constants")), expected)


@pytest.mark.parametrize("source,expected", [
    ("import sys\nx = sys.version_info >= (3, 10)", "import sys\nx = True"),
    ("import sys\nx = (3, 13) > sys.version_info", "import sys\nx = True"),
    ("import sys\nx = sys.version_info >= (3, 12)", "import sys\nx = True"),
    ("import sys\nx = sys.version_info == (3, 12)", "import sys\nx = False"),
    ("from sys import version_info\nx = version_info < (3, 11, 9)", "from sys import version_info\nx = False"),
    # 3.12.x may come before or after 3.12.1
    ("import sys\nx = sys.version_info < (3, 12, 1)", "import sys\nx = sys.version_info < (3, 12, 1)"),
    ("import sys\nx = sys.version_info[:2] == (3, 12)", "import sys\nx = sys.version_info[:2] == (3, 12)"),
])
def test_fold_version_info(source, expected):
    config = only("fold_constants", target_version=(3, 12))
    assert_code(apply_transform(source, FoldConstants, config), expected)


def test_version_info_unknown_by_default():
    source = "import sys\nx = sys.version_info >= (3, 10)"
    assert_code(apply_transform(source, FoldConstants, only("fold_constants")), source)


@pytest.mark.parametrize("optimize,expected", [
    (-1, "x = __debug__"),
    (0, "x = True"),
    (1, "x = False"),
])
def test_fold_debug(optimize, expected):
    config = only("fold_constants", optimize=optimize)
    assert_code(apply_transform("x = __debug__", FoldConstants, config), expected)
