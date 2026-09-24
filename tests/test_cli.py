import ast
import dataclasses

import pytest

from helpers import read_tree, run_py, run_terser, write_tree
from terser.config import RemoveAnnotationOptions, TransformConfig

_xfail_bool = pytest.mark.xfail(strict=True, reason="boolean options use type=bool, so 'False' parses as True")
_xfail_argv = pytest.mark.xfail(strict=True, reason="the CLI can't be driven with an argv list")

SOURCE = """\
#!/usr/bin/env python3
from typing import cast


def greet(target_name: str, greeting_word: str = "Hello") -> str:
    \"\"\"Return a greeting.\"\"\"
    message_text = greeting_word + ", " + target_name
    return cast(str, message_text)


print(greet("World"))
"""


@pytest.fixture
def example(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    return path


@pytest.fixture
def project(tmp_path):
    return write_tree(tmp_path / "project", {
        "main.py": "from helper import double_value\n\nprint(double_value(21))\n",
        "helper.py": "def double_value(input_value: int) -> int:\n    doubled_value = input_value * 2\n    return doubled_value\n",
    })


def test_version():
    assert run_terser("--version").stdout.strip() == __import__("terser").version


def test_file_to_stdout(example):
    result = run_terser(example)
    assert result.stdout.startswith("#!/usr/bin/env python3\n")
    assert len(result.stdout) < len(SOURCE)
    assert run_py("-c", result.stdout).stdout == "Hello, World\n"


def test_stdin_to_stdout():
    result = run_terser("-", stdin=SOURCE)
    assert len(result.stdout) < len(SOURCE)
    assert run_py("-c", result.stdout).stdout == "Hello, World\n"


def test_file_to_output(example, tmp_path):
    output = tmp_path / "example.min.py"
    assert run_terser(example, "--output", output).stdout == ""
    assert run_py(output).stdout == "Hello, World\n"
    assert example.read_text() == SOURCE


@_xfail_bool
@pytest.mark.parametrize("flag", [["--in-place"], ["--in-place", "True"], ["--in-place", "true"]])
def test_file_in_place(example, flag):
    run_terser(example, *flag)
    assert len(example.read_text()) < len(SOURCE)
    assert run_py(example).stdout == "Hello, World\n"


def test_directory_to_output(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output)
    assert set(read_tree(output)) == {"main.py", "helper.py"}
    assert run_py("main.py", cwd=output).stdout == "42\n"
    assert run_py("main.py", cwd=project).stdout == "42\n"


def test_directory_in_place(project):
    before = read_tree(project)
    run_terser(project, "--in-place", "True")
    after = read_tree(project)
    assert set(after) == set(before)
    assert sum(map(len, after.values())) < sum(map(len, before.values()))
    assert run_py("main.py", cwd=project).stdout == "42\n"


@_xfail_bool
def test_boolean_option_false(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output, "--rename-locals", "False")
    assert "doubled_value" in (output / "helper.py").read_text()


def test_boolean_option_true(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output, "--rename-locals", "True")
    assert "doubled_value" not in (output / "helper.py").read_text()


@pytest.mark.xfail(strict=True, reason="Literal options are passed to argparse as type=Literal[...]")
def test_optimize(project, tmp_path):
    run_terser(project, "--output", tmp_path / "out", "--optimize", "2")


@pytest.mark.xfail(strict=True, reason="remove_literal_statements crashes on `node.bindings`")
def test_remove_literal_statements(tmp_path):
    project = write_tree(tmp_path / "project", {
        "main.py": '"""Module docstring."""\n\ndef f():\n    """Function docstring."""\n    return 1\n\nprint(f())\n',
    })
    output = tmp_path / "out"
    result = run_terser(project, "--output", output, "--remove-literal-statements", "True")
    assert "Error" not in result.stderr
    assert "docstring" not in (output / "main.py").read_text()


@pytest.mark.parametrize("args,message", [
    (["-", "other.py"], "multiple path arguments, reading from stdin not allowed"),
    (["-", "--in-place", "True"], "reading from stdin, --in-place is not valid"),
    (["a.py", "b.py"], "multiple path arguments, --in-place or --output required"),
    (["{project}"], "is a directory, --in-place or --output required"),
    (["{example}", "--entry", "main"], "--entry/--rename-modules/--preserve-modules require a directory or multiple paths"),
    (["{project}", "--in-place", "True", "--rename-modules", "True"], "--rename-modules requires --output"),
])
def test_invalid_arguments(args, message, example, project):
    args = [a.format(project=project, example=example) for a in args]
    result = run_terser(*args, check=False)
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.xfail(strict=True, reason="the MutuallyExclusive marker is never detected, so no group is created")
def test_output_and_in_place_are_exclusive(example, tmp_path):
    result = run_terser(example, "--output", tmp_path / "x.py", "--in-place", "True", check=False)
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


@pytest.mark.parametrize("args,expected", [
    (["a,b"], {"*": ["a", "b"]}),
    (["pkg.*:a", "b"], {"pkg.*": ["a"], "*": ["b"]}),
    ([" pkg : a , b "], {"pkg": ["a", "b"]}),
    ([":a"], {"*": ["a"]}),
])
def test_parse_preserve(args, expected):
    from terser.cli._argv import parse_preserve

    assert {k: sorted(v) for k, v in parse_preserve(args).items()} == expected


def _argv(*args: str):
    from terser.cli.main import _argv

    return _argv(["file.py", *args])


@_xfail_argv
def test_defaults_match_transform_config():
    assert _argv().transform_options == TransformConfig()


@_xfail_argv
def test_every_transform_option_is_forwarded():
    parsed = _argv(
        "--passes", "2",
        "--optimize", "1",
        "--contracts", "a.b(x) -> x", "c.d(_) -> None",
        "--apply-contracts", "False",
        "--remove-literal-statements", "True",
        "--combine-imports", "False",
        "--remove-annotations", "True",
        "--remove-variable-annotations", "False",
        "--remove-return-annotations", "False",
        "--remove-argument-annotations", "False",
        "--remove-attribute-annotations", "True",
        "--remove-explicit-base", "False",
        "--remove-explicit-return-none", "False",
        "--fold-constants", "False",
        "--remove-debug", "False",
        "--remove-asserts", "False",
        "--convert-pass", "False",
        "--remove-empty-exc-brackets", "False",
        "--convert-posargs", "False",
    )
    expected = TransformConfig(
        passes=2,
        optimize=1,
        contracts=["a.b(x) -> x", "c.d(_) -> None"],
        apply_contracts=False,
        remove_literal_statements=True,
        combine_imports=False,
        remove_annotations=RemoveAnnotationOptions(False, False, False, True),
        remove_explicit_base=False,
        remove_explicit_return_none=False,
        fold_constants=False,
        remove_debug=False,
        remove_asserts=False,
        convert_pass=False,
        remove_empty_exc_brackets=False,
        convert_posargs=False,
    )
    assert parsed.transform_options == expected
    # make sure this test is updated along with TransformConfig
    assert {f.name for f in dataclasses.fields(TransformConfig) if getattr(expected, f.name) == getattr(TransformConfig(), f.name)} == set()


@_xfail_argv
def test_remove_annotations_false():
    assert _argv("--remove-annotations", "False").transform_options.remove_annotations is False


@_xfail_argv
def test_mangling_options():
    parsed = _argv(
        "--hoist-literals", "False",
        "--rename-locals", "False",
        "--preserve-locals", "a,b", "pkg:c",
        "--rename-globals", "True",
        "--preserve-globals", "d",
        "--preserve-modules", "pkg.*",
    )
    options = parsed.mangling_options
    assert (options.hoist_literals, options.rename_locals, options.rename_globals) == (False, False, True)
    assert options.preserve_locals == {"a,b", "pkg:c"}
    assert options.preserve_globals == {"d"}
    assert options.preserve_modules == {"pkg.*"}


def test_help_mentions_every_option():
    help_text = run_terser("--help").stdout
    for field in dataclasses.fields(TransformConfig):
        assert "--" + field.name.replace("_", "-") in help_text


def test_output_parses(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output)
    for source in read_tree(output).values():
        ast.parse(source)
