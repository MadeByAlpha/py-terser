"""
Minify terser's own source (like upstream's `xtest`), then check the minified terser still produces
the same output as the original.
"""

import pytest

from helpers import SRC, read_tree, run_terser, write_tree

pytestmark = pytest.mark.xfail(strict=True, reason="PackageSpec uses rstrip('.__init__'), e.g. 'ast' becomes 'as'")

SAMPLE = {
    "main.py": "from util import greet\n\nfor name in ['a', 'b']:\n    print(greet(name))\n",
    "util.py": (
        "def greet(target_name: str) -> str:\n"
        "    \"\"\"Greet someone.\"\"\"\n"
        "    if __debug__:\n"
        "        pass\n"
        "    message_text = 'Hello, ' + target_name\n"
        "    return message_text\n"
    ),
}


@pytest.fixture(scope="module")
def minified_src(tmp_path_factory):
    out = tmp_path_factory.mktemp("minified") / "src"
    run_terser(SRC, "--output", out)
    return out


def test_every_module_is_minified(minified_src):
    original = {path: source for path, source in read_tree(SRC).items() if path.endswith(".py")}
    minified = read_tree(minified_src)
    assert set(minified) == set(original)
    assert sum(map(len, minified.values())) < sum(map(len, original.values()))


def test_minified_terser_works(minified_src, tmp_path):
    sample = write_tree(tmp_path / "sample", SAMPLE)

    run_terser(sample, "--output", tmp_path / "expected", env={"PYTHONPATH": str(SRC)})
    run_terser(sample, "--output", tmp_path / "actual", env={"PYTHONPATH": str(minified_src)})

    assert read_tree(tmp_path / "actual") == read_tree(tmp_path / "expected")
