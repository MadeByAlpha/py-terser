import ast

import pytest

from helpers import assert_code
from terser._pipeline.preprocessor import preprocess


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
    ({"A": True}, "a()\nd()"),
    ({"A": False, "B": True}, "b()\nd()"),
    ({"A": False, "B": False}, "c()\nd()"),
    # undefined names count as defined
    ({}, "a()\nd()"),
    ({"A": True, "B": True}, "a()\nd()"),
])
def test_if_elif_else(defines, expected):
    assert_code(run(BLOCK, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    ({"A": True, "B": False, "C": True}, "a()"),
    ({"A": False, "B": True, "C": True}, "b()"),
    ({"A": False, "B": False, "C": True}, "c()"),
    ({"A": False, "B": False, "C": False}, "e()"),
])
def test_only_first_taken_branch(defines, expected):
    source = "# if A\na()\n# elif B\nb()\n# elif C\nc()\n# else\ne()\n# endif"
    assert_code(run(source, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    ({"OUTER": True, "INNER": True}, "a()\nb()\nc()"),
    ({"OUTER": True, "INNER": False}, "a()\nc()"),
    ({"OUTER": False, "INNER": True}, ""),
])
def test_nested(defines, expected):
    source = "# if OUTER\na()\n# if INNER\nb()\n# endif\nc()\n# endif"
    assert_code(run(source, **defines), expected)


@pytest.mark.parametrize("defines,expected", [
    ({"DEBUG": True}, "def f():\n    check()\n    return 1"),
    ({"DEBUG": False}, "def f():\n    return 1"),
])
def test_inline_directive(defines, expected):
    source = "def f():\n    check()  # if DEBUG\n    return 1"
    assert_code(run(source, **defines), expected)


def test_inline_directive_at_top_level():
    assert_code(run("check()  # if DEBUG\nx = 1", DEBUG=False), "x = 1")
    assert_code(run("check()  # if DEBUG\nx = 1", DEBUG=True), "check()\nx = 1")


def test_inline_directive_inside_inactive_block():
    assert_code(run("# if A\nx = 1\ny = 2  # if B\n# endif\nz = 3", A=False, B=True), "z = 3")


@pytest.mark.parametrize("defines,expected", [
    ({"A": True}, "def f():\n    a()\n    return 1"),
    ({"A": False}, "def f():\n    b()\n    return 1"),
])
def test_indented_block(defines, expected):
    source = "def f():\n    # if A\n    a()\n    # else\n    b()\n    # endif\n    return 1"
    assert_code(run(source, **defines), expected)


def test_directives_inside_strings_are_ignored():
    source = 'x = """\n# if A\nkept\n# endif\n"""\n'
    assert ast.literal_eval(ast.parse(run(source, A=False)).body[0].value) == "\n# if A\nkept\n# endif\n"


def test_directive_like_text_on_a_string_opening_line():
    source = 'x = """text  # if A\nmore"""\n'
    assert run(source, A=False) == source.rstrip("\n")


def test_ordinary_comments():
    assert run("x = 1  # a comment\n# another\ny = 2", A=False) == "x = 1  # a comment\n\ny = 2"


def test_shebang():
    output, shebang = preprocess("#!/usr/bin/env python3\nx = 1", None)
    assert shebang == "#!/usr/bin/env python3"
    assert_code(output, "x = 1")


def test_no_shebang():
    assert preprocess("x = 1", None)[1] is None


def test_line_numbers_are_preserved():
    source = "# comment\n# if A\na()\n# endif\nb()\n"
    output = run(source, A=False)
    assert output.splitlines()[4] == "b()"


@pytest.mark.parametrize("source,defines,expected", [
    ("#if A\na()\n#endif", {"A": False}, ""),
    ("# if A\na()\n# endif", {"A": False}, ""),
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
def test_strict_unbalanced(source):
    with pytest.raises(SyntaxError):
        run(source, strict=True)
