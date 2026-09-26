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
])
def test_fold_constants(source, expected):
    assert_code(apply_transform(source, FoldConstants, only("fold_constants")), expected)
