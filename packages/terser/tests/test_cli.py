import ast
import dataclasses

import pytest

from helpers import read_tree, run_py, run_terser, write_tree
from terser.config import RemoveAnnotationOptions, RemoveDocstringOptions, TransformConfig

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


@pytest.mark.parametrize("args", [
    ["{example}", "--in-place"],
    ["{example}", "--in-place", "True"],
    ["{example}", "--in-place", "true"],
    ["--in-place", "{example}"],
    ["--in-place=yes", "{example}"],
])
def test_file_in_place(example, args):
    run_terser(*(a.format(example=example) for a in args))
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


def test_boolean_option_false(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output, "--rename-locals", "False")
    assert "doubled_value" in (output / "helper.py").read_text()


def test_boolean_option_true(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output, "--rename-locals", "True")
    assert "doubled_value" not in (output / "helper.py").read_text()


@pytest.mark.parametrize("option,enabled,disabled", [
    ("--remove-empty-exc-brackets", "raise ValueError\n", "raise ValueError()"),
    ("--convert-posargs", "def check(A):", "def check(A,/):"),
])
def test_transform_options(tmp_path, option, enabled, disabled):
    path = tmp_path / "example.py"
    path.write_text("def check(input_value, /):\n    if not input_value:\n        raise ValueError()\n    return input_value\n")

    assert enabled in run_terser(path).stdout + "\n"
    assert disabled in run_terser(path, option, "False").stdout


def test_optimize(project, tmp_path):
    run_terser(project, "--output", tmp_path / "out", "--optimize", "2")


def test_remove_literal_statements(tmp_path):
    project = write_tree(tmp_path / "project", {
        "main.py": '"""Module docstring."""\n\ndef f():\n    """Function docstring."""\n    return 1\n\nprint(f())\n',
    })
    output = tmp_path / "out"
    result = run_terser(
        project, "--output", output, "--remove-literal-statements", "True",
        "--remove-docstrings", "True", "--also-modules", "True",
    )
    assert "Error" not in result.stderr
    assert "docstring" not in (output / "main.py").read_text()


def test_error_in_project(tmp_path):
    project = write_tree(tmp_path / "project", {"good.py": "x = 1\n", "bad.py": "def f(:\n"})
    result = run_terser(project, "--output", tmp_path / "out", check=False)
    assert result.returncode == 1
    # the worker's error, then the stage it failed in, not an exception group, and no noise from
    # progress bars at shutdown
    assert result.stderr.rstrip().endswith("RuntimeError: Compiling modules failed")
    assert "SyntaxError: invalid syntax" in result.stderr
    assert "RuntimeError: Compiling modules failed while processing bad" in result.stderr
    assert "bad.py" in result.stderr
    assert "Exception Group" not in result.stderr
    assert "Exception ignored" not in result.stderr


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


def test_output_and_in_place_are_exclusive(example, tmp_path):
    result = run_terser(example, "--output", tmp_path / "x.py", "--in-place", "True", check=False)
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


@pytest.mark.parametrize("args,expected", [
    (["a,b"], {"*": ["a", "b"]}),
    (["pkg.*:a", "b"], {"pkg.*": ["a"], "*": ["b"]}),
    ([" pkg : a , b "], {"pkg": ["a", "b"]}),
    ([":a"], {"*": ["a"]}),
    (["pkg.mod::Field:**,*args"], {"pkg.mod::Field": ["**", "*args"]}),
    (["*::Model.*:a"], {"*::Model.*": ["a"]}),
])
def test_parse_preserve(args, expected):
    from terser.cli._argv import parse_preserve

    assert {k: sorted(v) for k, v in parse_preserve(args).items()} == expected


def _argv(*args: str):
    from terser.cli.main import _argv

    return _argv(["file.py", *args])


def test_defaults_match_transform_config():
    assert _argv().transform_options == TransformConfig()


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
        "--fold-type-checking", "False",
        "--remove-dead-code", "False",
        "--remove-debug", "False",
        "--remove-asserts", "False",
        "--convert-pass", "False",
        "--remove-empty-exc-brackets", "False",
        "--convert-posargs", "False",
        "--hint-modules", "my.hints",
        "--target-version", "3", "12",
        "--unfold-iife-lambdas", "False",
        "--remove-type-statements", "True",
        "--convert-early-exits", "False",
        "--convert-to-inline", "False",
        "--convert-to-lambda", "False",
        "--remove-dummy-assignments", "False",
        "--remove-docstrings", "True",
        "--also-modules", "True",
        "--respect-all", "True",
        "--keep-future-annotations", "True",
        "--cleanup-local-imports", "False",
        "--remove-typing-decorators", "False",
        "--remove-overloads", "False",
        "--remove-generics", "False",
        "--remove-typing-classes", "True",
        "--convert-typing-constructors", "False",
        "--convert-typing-extensions", "False",
        "--convert-dynamic-attribute-access", "False",
        "--remove-dunder-all", "True",
        "--remove-dunder-all-modules", "app.*",
        "--preserve-annotations", "app.models", "app.deps::Settings",
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
        fold_type_checking=False,
        remove_dead_code=False,
        remove_debug=False,
        remove_asserts=False,
        convert_pass=False,
        remove_empty_exc_brackets=False,
        convert_posargs=False,
        hint_modules=["my.hints"],
        target_version=(3, 12),
        unfold_iife_lambdas=False,
        remove_type_statements=True,
        convert_early_exits=False,
        convert_to_inline=False,
        convert_to_lambda=False,
        remove_dummy_assignments=False,
        remove_docstrings=RemoveDocstringOptions(also_modules=True),
        respect_all=True,
        keep_future_annotations=True,
        cleanup_local_imports=False,
        remove_typing_decorators=False,
        remove_overloads=False,
        remove_generics=False,
        remove_typing_classes=True,
        convert_typing_constructors=False,
        convert_typing_extensions=False,
        convert_dynamic_attribute_access=False,
        remove_dunder_all=True,
        remove_dunder_all_modules=["app.*"],
        preserve_annotations=["app.models", "app.deps::Settings"],
    )
    assert parsed.transform_options == expected
    # make sure this test is updated along with TransformConfig
    assert {f.name for f in dataclasses.fields(TransformConfig) if getattr(expected, f.name) == getattr(TransformConfig(), f.name)} == set()


def test_remove_annotations_false():
    assert _argv("--remove-annotations", "False").transform_options.remove_annotations is False


@pytest.mark.parametrize("args,expected", [
    ([], False),
    (["--rename-globals"], True),
    (["--rename-globals", "False"], False),
    (["--rename-globals", "no"], False),
    (["--rename-globals", "1"], True),
    (["--rename-globals=0"], False),
])
def test_boolean_values(args, expected):
    assert _argv(*args).mangling_options.rename_globals is expected


def test_bare_boolean_flag_before_path():
    from terser.cli.main import _argv

    parsed = _argv(["--rename-globals", "file.py", "--rename-locals"])
    assert parsed.mangling_options.rename_globals is True
    assert parsed.mangling_options.rename_locals is True
    assert parsed.path == {"file.py"}


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


def test_preserve_type_checking_option():
    assert _argv("--preserve-type-checking", "pkg", "anyio.*").preserve_type_checking == {"pkg", "anyio.*"}
    assert _argv().preserve_type_checking == set()


TYPE_CHECKING_SOURCE = """\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import os
print(1)
"""


@pytest.mark.parametrize(("pattern", "kept"), [("*lazy.py", True), ("*other.py", False)])
def test_preserve_type_checking_single_file(tmp_path, pattern, kept):
    source = write_tree(tmp_path, {"lazy.py": TYPE_CHECKING_SOURCE}) / "lazy.py"
    assert ("TYPE_CHECKING" in run_terser(source, "--preserve-type-checking", pattern).stdout) is kept


def test_help_mentions_every_option():
    help_text = run_terser("--help").stdout
    for field in dataclasses.fields(TransformConfig):
        assert "--" + field.name.replace("_", "-") in help_text


def test_output_parses(project, tmp_path):
    output = tmp_path / "out"
    run_terser(project, "--output", output)
    for source in read_tree(output).values():
        ast.parse(source)


SIGNATURE = """\
import inspect


def Field(default=None, *, alias=None, **extra):
    return default, alias, extra


names = set(inspect.signature(Field).parameters)
names.remove("extra")
print(sorted(names))
"""


@pytest.mark.parametrize("args", [
    ["--rename-star-args", "false"],
    ["--preserve-locals", "**extra"],
    ["--preserve-locals", "*::Field:**"],
])
def test_star_args_kept_for_inspect(tmp_path, args):
    source = write_tree(tmp_path, {"sig.py": SIGNATURE}) / "sig.py"
    minified = run_terser(source, *args).stdout
    assert "**extra" in minified
    assert run_py("-c", minified).stdout == "['alias', 'default']\n"


def test_star_args_renamed_by_default(tmp_path):
    source = write_tree(tmp_path, {"sig.py": SIGNATURE}) / "sig.py"
    assert "**extra" not in run_terser(source).stdout
