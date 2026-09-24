import ast

import pytest

from helpers import assert_code
from terser._pipeline.preprocessor import preprocess

_xfail_blocks = pytest.mark.xfail(strict=True, reason="code lines inside inactive blocks are kept")
_xfail_chain = pytest.mark.xfail(strict=True, reason="elif/else only look at the previous branch")


def run(source: str, strict: bool = False, **defines: bool) -> str:
    output, _ = preprocess(source, defines, strict)
    return output


BLOCK = """\
# if A
a()
# elif B
b()
# else
c()
# endif
d()
"""


@pytest.mark.parametrize("defines,expected", [
    pytest.param({"A": True}, "a()\nd()", marks=_xfail_blocks),
    pytest.param({"A": False, "B": True}, "b()\nd()", marks=_xfail_blocks),
    pytest.param({"A": False, "B": False}, "c()\nd()", marks=_xfail_blocks),
    # undefined names count as defined
    pytest.param({}, "a()\nd()", marks=_xfail_blocks),
    pytest.param({"A": True, "B": True}, "a()\nd()", marks=_xfail_blocks),
])
def test_if_elif_else(defines, expected):
    assert_code(run(BLOCK, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    pytest.param({"A": True, "B": False, "C": True}, "a()", marks=[_xfail_blocks, _xfail_chain]),
    pytest.param({"A": False, "B": True, "C": True}, "b()", marks=[_xfail_blocks, _xfail_chain]),
    pytest.param({"A": False, "B": False, "C": True}, "c()", marks=_xfail_blocks),
    pytest.param({"A": False, "B": False, "C": False}, "e()", marks=_xfail_blocks),
])
def test_only_first_taken_branch(defines, expected):
    source = "# if A\na()\n# elif B\nb()\n# elif C\nc()\n# else\ne()\n# endif"
    assert_code(run(source, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    ({"OUTER": True, "INNER": True}, "a()\nb()\nc()"),
    pytest.param({"OUTER": True, "INNER": False}, "a()\nc()", marks=_xfail_blocks),
    pytest.param({"OUTER": False, "INNER": True}, "", marks=_xfail_blocks),
])
def test_nested(defines, expected):
    source = "# if OUTER\na()\n# if INNER\nb()\n# endif\nc()\n# endif"
    assert_code(run(source, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    pytest.param(
        {"DEBUG": True}, "def f():\n    check()\n    return 1",
        marks=pytest.mark.xfail(strict=True, reason="inline directives slice the unstripped line at a stripped offset"),
    ),
    ({"DEBUG": False}, "def f():\n    return 1"),
])
def test_inline_directive(defines, expected):
    source = "def f():\n    check()  # if DEBUG\n    return 1"
    assert_code(run(source, **defines), expected)


def test_inline_directive_at_top_level():
    assert_code(run("check()  # if DEBUG\nx = 1", DEBUG=False), "x = 1")
    assert_code(run("check()  # if DEBUG\nx = 1", DEBUG=True), "check()\nx = 1")


@pytest.mark.xfail(strict=True, reason="inline directives inside an inactive block are the only lines dropped")
def test_inline_directive_inside_inactive_block():
    assert_code(run("# if A\nx = 1\ny = 2  # if B\n# endif\nz = 3", A=False, B=True), "z = 3")


@pytest.mark.parametrize("defines,expected", [
    pytest.param({"A": True}, "def f():\n    a()\n    return 1", marks=_xfail_blocks),
    pytest.param({"A": False}, "def f():\n    b()\n    return 1", marks=_xfail_blocks),
])
def test_indented_block(defines, expected):
    source = "def f():\n    # if A\n    a()\n    # else\n    b()\n    # endif\n    return 1"
    assert_code(run(source, **defines), expected)


def test_directives_inside_strings_are_ignored():
    source = 'x = """\n# if A\nkept\n# endif\n"""\n'
    assert ast.literal_eval(ast.parse(run(source, A=False)).body[0].value) == "\n# if A\nkept\n# endif\n"


def test_shebang():
    output, shebang = preprocess("#!/usr/bin/env python3\nx = 1", None)
    assert shebang == "#!/usr/bin/env python3"
    assert_code(output, "x = 1")


def test_no_shebang():
    assert preprocess("x = 1", None)[1] is None


@pytest.mark.xfail(strict=True, reason="dropped lines are removed instead of blanked")
def test_line_numbers_are_preserved():
    source = "# comment\n# if A\na()\n# endif\nb()\n"
    output = run(source, A=False)
    assert output.splitlines()[4] == "b()"


@pytest.mark.parametrize("source,defines,expected", [
    pytest.param("#if A\na()\n#endif", {"A": False}, "", marks=_xfail_blocks),
    pytest.param("# if A\na()\n# endif", {"A": False}, "", marks=_xfail_blocks),
    # not a directive in strict mode: kept as an ordinary comment
    ("#   if   A\na()\n#  endif", {"A": False}, "a()"),
])
def test_strict_spelling(source, defines, expected):
    assert_code(run(source, strict=True, **defines), expected)


@pytest.mark.parametrize("source", [
    "# if A\na()",
    "a()\n# endif",
    "a()\n# else",
    "a()\n# elif B",
])
@pytest.mark.xfail(strict=True, reason="unbalanced directives are ignored even in strict mode")
def test_strict_unbalanced(source):
    with pytest.raises(SyntaxError):
        run(source, strict=True)
