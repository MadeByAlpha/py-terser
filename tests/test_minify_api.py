import contextlib
import io

import pytest

import terser
from helpers import assert_code, minify_src, only
from terser.config import TransformConfig

pytestmark = pytest.mark.xfail(strict=True, reason="terser.minify instantiates the abstract Task")

SOURCE = """\
import os
from collections import OrderedDict

GREETING = "Hello"


def greet(target_name: str) -> str:
    \"\"\"Greet someone.\"\"\"
    message_text = GREETING + ", " + target_name
    assert message_text
    return message_text


class Counter(object):
    def __init__(self):
        self.counts = OrderedDict()

    def add(self, key_name):
        current_value = self.counts.get(key_name, 0)
        self.counts[key_name] = current_value + 1
        return None


counter = Counter()
for word in ["a", "b", "a"]:
    counter.add(word)
print(greet("World"), dict(counter.counts), os.sep == os.path.sep)
"""


def execute(source: str) -> str:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exec(compile(source, "<test>", "exec"), {"__name__": "__main__"})
    return stdout.getvalue()


def test_default_minify_behaves_the_same():
    minified = terser.minify(SOURCE, TransformConfig())
    assert len(minified) < len(SOURCE)
    assert execute(minified) == execute(SOURCE)


def test_no_transforms_round_trip():
    minified = minify_src(SOURCE, only(), hoist_literals=False, rename_locals=False)
    assert_code(minified, SOURCE)


def test_rename_locals():
    minified = minify_src(SOURCE, only(), hoist_literals=False, rename_locals=True)
    assert "message_text" not in minified
    assert "current_value" not in minified
    # globals are not renamed unless asked
    assert "def greet(" in minified
    assert execute(minified) == execute(SOURCE)


def test_preserve_locals():
    minified = minify_src(SOURCE, only(), hoist_literals=False, rename_locals=True, preserve_locals=["message_text"])
    assert "message_text" in minified
    assert "current_value" not in minified


def test_rename_globals():
    minified = minify_src(SOURCE, only(), hoist_literals=False, rename_globals=True, preserve_globals=["Counter"])
    assert "def greet(" not in minified
    assert "GREETING" not in minified
    assert "class Counter" in minified
    assert execute(minified) == execute(SOURCE)


def test_hoist_literals():
    source = "a = 'a very long string literal'\nb = 'a very long string literal'\nc = 'a very long string literal'\nprint(a, b, c)"
    minified = minify_src(source, only(), hoist_literals=True, rename_locals=False)
    assert minified.count("a very long string literal") == 1
    assert execute(minified) == execute(source)


def test_preserve_shebang():
    source = "#!/usr/bin/env python3\n" + SOURCE
    assert terser.minify(source, TransformConfig()).startswith("#!/usr/bin/env python3\n")
    assert not terser.minify(source, TransformConfig(), preserve_shebang=False).startswith("#!")


def test_prefer_single_line():
    source = "def f(value):\n    first = value + 1\n    return first * 2\nprint(f(1))\nprint(f(2))\n"
    single = terser.minify(source, TransformConfig(), prefer_single_line=True)
    assert "\n" not in single.rstrip("\n").split("def f")[0]
    assert execute(single) == execute(source)


def test_defines():
    source = "x = 1\n# if DEBUG\nprint('debug')\n# endif\nprint(x)\n"
    assert "debug" not in terser.minify(source, TransformConfig(), defines={"DEBUG": False})
    assert "debug" in terser.minify(source, TransformConfig(), defines={"DEBUG": True})


def test_unknown_keyword_argument():
    with pytest.raises(TypeError, match="bogus_option"):
        terser.minify(SOURCE, TransformConfig(), bogus_option=True)
