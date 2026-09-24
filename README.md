# py-terser

![`Development Status :: 3 -
Alpha`](https://img.shields.io/badge/-3%20--%20Alpha-orange?style=flat&label=Development%20Status)

A mangler/minifier toolkit for Python.

*Fork of [`dflook/python-minifier`](https://github.com/dflook/python-minifier.git), Name inspired by
[`terser`](https://github.com/terser/terser.git)*

Transforms Python project into its most compact representation.

py-terser currently supports Python 3.10 to Python 3.14.

- **Single-file mode** — minifies one module (or stdin) on its own, like `python-minifier`.
- **Project mode** — minifies a whole directory tree at once. Imports are linked across modules, which enables
  renaming global names and module names consistently across the project, and dropping modules that are
  unreachable from the entry points (tree-shaking).
- **Hatch build hook** — minifies the Python sources that go into your wheel at build time.

## Installation

```shell
pip install py-terser
```

The command-line interface additionally requires `pydantic` and `tqdm`:

```shell
pip install py-terser pydantic tqdm
# or, as a standalone tool
uv tool install py-terser --with pydantic --with tqdm
```

To work on py-terser itself:

```shell
git clone https://github.com/MadeByAlpha/py-terser.git
cd py-terser
uv sync --group cli --group dev
uv run terser --help
```

## Command-line usage

```
terser [options] path [path ...]
```

The mode is chosen from the given paths:

| Paths                           | Mode        | Output                                                  |
|---------------------------------|-------------|---------------------------------------------------------|
| `-`                             | single-file | Reads stdin, writes stdout (or `--output`)              |
| a single file                   | single-file | stdout, `--output FILE` or `--in-place`                 |
| a directory, or multiple paths  | project     | `--output DIR` or `--in-place` (one is required)        |

In project mode, directories are searched recursively for `*.py`/`*.pyw` files, and the output directory mirrors the
input layout. A directory that is a package itself (it has an `__init__.py`) keeps its name as the top-level package:
`terser src/mypkg --output build/mypkg` names its modules `mypkg.*` and writes `build/mypkg/__init__.py`.

### Examples

```shell
# Minify stdin to stdout
terser -

# Minify a file to stdout
terser example.py

# Minify a file into another file
terser example.py --output example.min.py

# Minify a file in place
terser example.py --in-place

# Minify a whole project into a separate directory
terser src/ --output build/

# Minify multiple paths in place
terser file1.py file2.py src/ --in-place

# Also rename global names and module names across the project
terser src/ --output build/ --rename-globals --rename-modules

# Keep only modules reachable from `app.main` (tree-shaking)
terser src/ --output build/ --entry app.main
```

`python -m terser` works the same as `terser`.

### Options

Boolean options can be given alone (`--rename-globals`) or with a value (`--rename-locals False`; `yes`/`no` and
`1`/`0` also work). Options that accept several values
(`--preserve-locals`, `--preserve-globals`, `--preserve-modules`, `--entry`, `--contracts`) can be given
multiple values, and can be repeated.

#### General

| Option                 | Default | Description                                                                    |
|------------------------|---------|--------------------------------------------------------------------------------|
| `--output PATH`        | stdout  | File (single-file mode) or directory (project mode) to write output to        |
| `--in-place`           | `False` | Overwrite the input files. Mutually exclusive with `--output`                  |
| `--preserve-shebang`   | `True`  | Keep the shebang (`#!...`) line                                               |
| `--prefer-single-line` | `False` | Join statements with `;` instead of newlines, even when it saves no bytes     |
| `--workers N`          | auto    | Number of worker threads in project mode                                       |
| `--entry MODULE`       | —       | Entry point modules (dotted module path or file path), project mode only. See [Tree-shaking](#tree-shaking) |

#### Transforms

| Option                           | Default | Description                                                                   |
|----------------------------------|---------|-------------------------------------------------------------------------------|
| `--passes N`                     | `5`     | Maximum number of transform passes. Stops early once nothing changes          |
| `--optimize {-1,0,1,2}`          | `-1`    | Passed to `ast.parse()`. `2` also enables `--remove-debug` and `--remove-asserts` |
| `--apply-contracts`              | `True`  | Rewrite calls according to `--contracts`. See [Contracts](#contracts)         |
| `--contracts RULE`               | see below | Contract rules to apply                                                     |
| `--remove-literal-statements`    | `False` | Remove statements that are a single literal (e.g. docstrings)                 |
| `--combine-imports`              | `True`  | Combine adjacent import statements                                            |
| `--remove-annotations`           | `True`  | Remove type annotations, as selected by the four options below               |
| `--remove-variable-annotations`  | `True`  | Remove variable annotations                                                   |
| `--remove-return-annotations`    | `True`  | Remove return annotations                                                     |
| `--remove-argument-annotations`  | `True`  | Remove argument annotations                                                   |
| `--remove-attribute-annotations` | `False` | Remove class attribute annotations                                            |
| `--remove-explicit-base`         | `True`  | Remove explicit base classes (e.g. `class A(object)`)                         |
| `--remove-explicit-return-none`  | `True`  | Replace `return None` with `return`                                           |
| `--fold-constants`               | `True`  | Evaluate constant expressions and shrink literals                             |
| `--remove-debug`                 | `True`  | Remove `if __debug__:` blocks                                                 |
| `--remove-asserts`               | `True`  | Remove `assert` statements                                                    |
| `--convert-pass`                 | `True`  | Remove `pass`, or replace it with the shortest literal statement (`0`)        |
| `--remove-empty-exc-brackets`    | `True`  | `raise ValueError()` → `raise ValueError` for built-in exceptions             |
| `--convert-posargs`              | `True`  | Convert positional-only arguments to normal arguments                        |

#### Mangling

| Option                       | Default | Description                                                                    |
|------------------------------|---------|--------------------------------------------------------------------------------|
| `--hoist-literals`           | `True`  | Replace frequently used literals with short-named variables                   |
| `--rename-locals`            | `True`  | Rename local (including nonlocal) names                                        |
| `--preserve-locals NAMES`    | —       | Local names that are not renamed. See [Preserving names](#preserving-names)   |
| `--rename-globals`           | `False` | Rename module-level names. In project mode, importers in other modules follow |
| `--preserve-globals NAMES`   | —       | Global names that are not renamed                                              |
| `--rename-modules`           | `False` | Rename module/package files and directories. Project mode only, requires `--output` |
| `--preserve-modules PATTERN` | —       | Glob patterns over dotted module paths; matching modules keep their name      |

### Preserving names

`--preserve-locals` and `--preserve-globals` take comma-separated names. Prefix them with a glob pattern and `:` to
limit them to matching modules (matched against the dotted module path, or the filename in single-file mode):

```shell
# Keep `config` and `logger` in every module
terser src/ --output build/ --rename-globals --preserve-globals config,logger

# Keep `handler` only in modules under `app.api`
terser src/ --output build/ --rename-globals --preserve-globals 'app.api.*:handler'
```

### Tree-shaking

When `--entry` is given, modules that are not reachable (through imports) from any entry module are dropped from the
output. Entry modules are never renamed by `--rename-modules`.

```shell
terser src/ --output build/ --entry app.main app.cli --rename-modules
```

## Hatch build hook

py-terser registers a [Hatch](https://hatch.pypa.io/) build hook named `terser`, which minifies the `.py`/`.pyw`
files included in a wheel. Source distributions are left untouched.

```toml
[build-system]
requires = ["hatchling", "py-terser"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel.hooks.terser]
hoist_literals = true
rename_locals = true
rename_globals = false
# glob pattern -> names, same as `--preserve-locals`/`--preserve-globals`
preserve_globals = { "*" = ["VERSION"], "mypkg.api.*" = ["handler"] }

# Transform options (same names as the `Transforms` table above, in snake_case)
[tool.hatch.build.targets.wheel.hooks.terser.config]
passes = 5
remove_literal_statements = true
remove_annotations = true
```

Supported keys:

- Top level: `hoist_literals`, `rename_locals`, `preserve_locals`, `rename_globals`, `preserve_globals`
- `config` table: `passes`, `apply_contracts`, `remove_literal_statements`, `combine_imports`, `remove_annotations`,
  `remove_explicit_base`, `remove_explicit_return_none`, `fold_constants`, `remove_debug`, `remove_asserts`,
  `convert_pass`, `remove_empty_exc_brackets`, `convert_posargs`

## Python API

```python
import anyio
from terser import TransformConfig, minify, minify_project

config = TransformConfig(remove_literal_statements=True)

# Single module
with open("example.py") as f:
    print(minify(f.read(), config, "example.py"))

# Whole project (async)
anyio.run(
    lambda: minify_project(
        config,
        {"src"},
        output=anyio.Path("build"),
        rename_globals=True,
        preserve_globals={"*": ["VERSION"]},
        entry={"app.main"},
    )
)
```

`TransformConfig` has the same fields as the transform options above (`remove_annotations` also accepts a
`RemoveAnnotationOptions` instead of a `bool`). `minify_project` accepts the mangling options as keyword arguments,
plus `workers`, `rename_modules`, `preserve_modules` and `entry`.

## Contracts

Contracts rewrite calls to known functions into a simpler expression. Each rule has the form
`module.function(args) -> replacement`:

- Each argument is a name, or `_` for an argument that is ignored.
- The replacement is an expression over those names, or `None` to replace the call with `None`.

The default rules are:

```
typing.cast(_, value) -> value
typing.assert_never(_) -> None
typing.assert_type(x, _) -> x
```

Calls are matched by resolving the called name to its import (e.g. `from typing import cast`). Passing
`--contracts` replaces the default rules.

## Conditional directives

Before parsing, comment directives select which lines are kept, similar to the C preprocessor:

```python
# if DEBUG
log_everything()
# elif VERBOSE
log_some()
# else
log_nothing()
# endif

check_invariants()  # if DEBUG
```

Values are given with the `defines` argument of the Python API (e.g. `defines={"DEBUG": False}`); names that are
not defined are treated as `True`. With `strict=True`, only the exact `# if NAME` / `#if NAME` spellings are
recognized, and an unbalanced directive (e.g. a missing `# endif`) raises `SyntaxError`. Removed lines are replaced
with empty lines, so line numbers in error messages match the original source.

## License

[MIT](LICENSE.md). See [ACKNOWLEDGMENTS](.github/ACKNOWLEDGMENTS.md).
