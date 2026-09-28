# py-terser

![`Development Status :: 3 -
Alpha`](https://img.shields.io/badge/-3%20--%20Alpha-orange?style=flat&label=Development%20Status)

A mangler/minifier toolkit for Python.

*Fork of [`dflook/python-minifier`](https://github.com/dflook/python-minifier.git), Name inspired by
[`terser`](https://github.com/terser/terser.git)*

Transforms Python project into its most compact representation.

py-terser currently supports Python 3.13 to Python 3.14.

- **Single-file mode** — minifies one module (or stdin) on its own, like `python-minifier`.
- **Project mode** — minifies a whole directory tree at once. Imports are linked across modules, which enables
  renaming global names and module names consistently across the project, and dropping modules that are
  unreachable from the entry points (tree-shaking).
- **Hatch build hook** — minifies the Python sources that go into your wheel at build time.

## Installation

```shell
pip install py-terser
```

The command-line interface additionally requires `pydantic`:

```shell
pip install py-terser pydantic
# or, as a standalone tool
uv tool install py-terser --with pydantic
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
(`--preserve-locals`, `--preserve-globals`, `--preserve-modules`, `--preserve-type-checking`, `--preserve-annotations`, `--entry`, `--contracts`) can be given
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
| `--preserve-type-checking PATTERN` | — | Glob patterns over dotted module paths (filenames in single-file mode); matching modules keep `TYPE_CHECKING` and the code it guards. See [Keeping `TYPE_CHECKING`](#keeping-type_checking) |

#### Transforms

| Option                           | Default | Description                                                                   |
|----------------------------------|---------|-------------------------------------------------------------------------------|
| `--passes N`                     | `5`     | Maximum number of transform passes. Stops early once nothing changes          |
| `--optimize {-1,0,1,2}`          | `-1`    | Passed to `ast.parse()`. `2` also enables `--remove-debug` and `--remove-asserts` |
| `--apply-contracts`              | `True`  | Rewrite calls according to `--contracts`. See [Contracts](#contracts)         |
| `--contracts RULE`               | see below | Contract rules to apply                                                     |
| `--remove-literal-statements`    | `False` | Remove statements that are a single literal, except docstrings (see `--remove-docstrings`) |
| `--combine-imports`              | `True`  | Combine adjacent import statements                                            |
| `--remove-annotations`           | `True`  | Remove type annotations, as selected by the four options below (not `Annotated[...]`, nor under `@terser_hints.preserve_annotations`) |
| `--remove-variable-annotations`  | `True`  | Remove variable annotations                                                   |
| `--remove-return-annotations`    | `True`  | Remove return annotations                                                     |
| `--remove-argument-annotations`  | `True`  | Remove argument annotations                                                   |
| `--remove-attribute-annotations` | `False` | Remove class attribute annotations, except in the classes that read them. See [Keeping annotations](#keeping-annotations) |
| `--preserve-annotations PATTERN` | —       | Glob patterns over dotted module paths, optionally with `::` and a glob over qualnames; what they match keeps its annotations |
| `--remove-explicit-base`         | `True`  | Remove explicit base classes (e.g. `class A(object)`)                         |
| `--remove-explicit-return-none`  | `True`  | Replace `return None` with `return`                                           |
| `--fold-constants`               | `True`  | Evaluate constant expressions and shrink literals, and decide `and`/`or`/`x if c else y` by their constant operands (`False and x` → `False`) |
| `--fold-type-checking`           | `True`  | Replace `typing.TYPE_CHECKING` (also `typing_extensions`') with `False`, its value at run time, removing the import when nothing else uses it |
| `--remove-dead-code`             | `True`  | Remove the branches of `if`/`while` whose condition is constant (`if False:`, `if TYPE_CHECKING:`), unless that changes how the function compiles (`if False: yield`, a `global`, or the only assignment of a local) |
| `--remove-debug`                 | `True`  | Remove `if __debug__:` blocks                                                 |
| `--remove-asserts`               | `True`  | Remove `assert` statements                                                    |
| `--convert-pass`                 | `True`  | Remove `pass`, or replace it with the shortest literal statement (`0`)        |
| `--remove-empty-exc-brackets`    | `True`  | `raise ValueError()` → `raise ValueError` for built-in exceptions (not in modules using `exec()`, an external `import *`, …) |
| `--convert-posargs`              | `True`  | Convert positional-only arguments to normal arguments (not for functions taking `**kwargs`) |
| `--hint-modules MODULE`          | —       | Modules whose members are recognized like `terser_hints`' (`preserve_docstring`, `preserve_annotations`, `constant`) |
| `--target-version MAJOR MINOR…`  | —       | Python version the output runs under: `sys.version_info` comparisons it decides are folded (`3 12` is any 3.12.x) |
| `--unfold-iife-lambdas`          | `True`  | `(lambda: x)()` → `x`, and `@lambda _: _()` / `@terser_hints.constant` → a call rebinding the function's name |
| `--remove-type-statements`       | `False` | Remove `type X = ...` statements. Unsafe when another module imports the alias |
| `--convert-early-exits`          | `True`  | `if c: return a` followed by `return b` → `return a if c else b`               |
| `--convert-to-inline`            | `True`  | `if c: f()` → `c and f()`, `if c: f()` / `else: g()` → `f() if c else g()`     |
| `--convert-to-lambda`            | `True`  | `def f(x): return e` → `f = lambda x: e` (not for decorated or annotated functions, or ones `--preserve-locals` names) |
| `--remove-dummy-assignments`     | `True`  | Remove `x = x` where `x` is bound elsewhere too, outside a class body         |
| `--remove-docstrings`            | `False` | Remove docstrings, except under `@terser_hints.preserve_docstring` (a class keeps its attribute docstrings too), and ones that may be read (`__doc__`) |
| `--also-modules`                 | `False` | With `--remove-docstrings`, remove module docstrings too                      |
| `--cleanup-local-imports`        | `True`  | Remove unused imports in functions and classes                                |
| `--respect-all`                  | `False` | With `--cleanup-local-imports`, remove unused module-level imports not in `__all__` too |
| `--remove-typing-decorators`     | `True`  | Remove `@typing.override` and `@typing.final`                                  |
| `--remove-overloads`             | `True`  | Remove `@typing.overload` stubs (also on with `--remove-typing-decorators`)   |
| `--remove-generics`              | `True`  | Remove a bare `Generic` base, and unused type parameters of a class defined in a function |
| `--remove-typing-classes`        | `False` | Remove a bare `Protocol` base (not under `@runtime_checkable`, nor of a class another class derives from: in project mode, across modules) |
| `--convert-typing-constructors`  | `True`  | Field-only `NamedTuple` classes → `collections.namedtuple()`, and `TypedDict` classes only called with keywords (in a function) → `dict` |
| `--convert-typing-extensions`    | `True`  | `from typing_extensions import X` → `from typing import X`, for names long in `typing` |
| `--convert-dynamic-attribute-access` | `True` | `getattr(o, 'name')` → `o.name`, `setattr(o, 'name', v)` → `o.name = v`   |
| `--remove-dunder-all`            | `False` | Remove the module-level `__all__` (not in project mode of a module another module imports `*` from, or reads the `__all__` of) |
| `--remove-dunder-all-modules PATTERN` | — | Glob patterns over dotted module paths where `__all__` is removed          |

#### Mangling

| Option                       | Default | Description                                                                    |
|------------------------------|---------|--------------------------------------------------------------------------------|
| `--hoist-literals`           | `True`  | Replace frequently used literals with short-named variables                   |
| `--rename-locals`            | `True`  | Rename local (including nonlocal) names                                        |
| `--preserve-locals NAMES`    | —       | Local names that are not renamed. See [Preserving names](#preserving-names)   |
| `--rename-star-args`         | `True`  | Rename `*args`/`**kwargs` parameters, whose names show in `inspect.signature()` |
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

`--preserve-locals` is more specific still:

- `*` and `**` stand for a function's `*args` and `**kwargs` parameters, whatever their names; `*name` and `**name`
  for them only when they have that name. Other locals of the same names are still renamed.
- The module pattern may go on with `::` and a glob over the `__qualname__` of the function or class the name is bound
  in (`Field`, `Model.__init__`, `outer.<locals>.inner`). A list, set or dict comprehension counts as part of the
  function it is in.

```shell
# pydantic reads `**extra` of `Field` back through `inspect.signature()`
terser src/ --output build/ --preserve-locals 'pydantic.fields::Field:**'

# Keep the names of every `*args`/`**kwargs` parameter
terser src/ --output build/ --rename-star-args false
```

In the hatch build hook, the same goes in the keys of the tables: `preserve_locals = { "pydantic.fields::Field" =
["**"] }`.

### Keeping `TYPE_CHECKING`

Some code reads `TYPE_CHECKING` back at run time: anyio's lazy importer deletes it from its packages' globals, and
parses their source for the imports under `if TYPE_CHECKING or ...`. `--fold-type-checking` would fold that block
away, so leave it as is in the modules matching `--preserve-type-checking`: `TYPE_CHECKING` (or `typing`) keeps its
name, and the code it guards its literals:

```shell
terser src/ --output build/ --preserve-type-checking 'anyio' 'anyio.*'
```

### Keeping annotations

Some classes are built from the annotations in their body: `x: int = 0` is a field there, `x = 0` a plain class
attribute. Their annotations are kept, the methods' too (pydantic's `computed_field` reads the return type), when the
class

- is decorated with `dataclasses.dataclass`, `pydantic.dataclasses.dataclass` or an `attrs` class decorator,
- or leads, through its bases or metaclass, to `pydantic.BaseModel`, `pydantic.RootModel`, pydantic's `ModelMetaclass`,
  `pydantic.v1.BaseModel`, `pydantic_settings.BaseSettings`, `sqlmodel.SQLModel`, `msgspec.Struct`, `TypedDict` or
  `NamedTuple`, or to a class reading annotations itself (its body reads `__annotations__`, or calls
  `typing.get_type_hints()` or `inspect.get_annotations()`: a base checking its subclasses in `__init_subclass__`, a
  metaclass). In project mode, bases are followed into the other modules of the project.

Other code reading annotations (FastAPI endpoints and dependencies, `inspect.signature()`, `typing.get_type_hints()`)
keeps them under `@terser_hints.preserve_annotations`, or when `--preserve-annotations` names it:

```shell
# every annotation of `app.models`, and the ones of `Settings` (and its methods) in `app.deps`
terser src/ --output build/ --preserve-annotations 'app.models' 'app.deps::Settings'
```

### Tree-shaking

When `--entry` is given, modules that are not reachable (through imports) from any entry module are dropped from the
output. A native extension a kept module imports keeps the modules whose names are in its binary (the ones
it imports from C). Entry modules, and the packages they are in, are never renamed by `--rename-modules`.

Both follow imports statically. `__import__()` and `importlib.import_module()` count as imports when the module is
named by literals (a relative name too, against a literal package or `__package__`): tree-shaking keeps what they
import, renaming rewrites the literals, and the attributes of the module they return follow renamed submodules and
globals, used right away or through a name assigned once:

```python
settings = importlib.import_module("app.settings")   # followed
handler = importlib.import_module(f"app.handlers.{name}")   # not followed: a warning
```

A module named otherwise, only known at run time (or looked up in `sys.modules`), is neither kept by tree-shaking nor
followed when renamed: keep it with `--entry` and `--preserve-modules` (and its globals with `--preserve-globals`).
With `--rename-modules`, `--rename-globals` or `--entry`, each such call is reported as a `DynamicImportWarning`.

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

- Top level: `hoist_literals`, `rename_locals`, `preserve_locals`, `rename_star_args`, `rename_globals`,
  `preserve_globals`, `workers`, `rename_modules`, `preserve_modules`, `preserve_type_checking` and `entry`, the same
  as the command-line options:
  - `workers`: the most threads to minify with (and so to create); a positive integer.
  - `rename_modules`: renamed modules and packages are renamed in the wheel too, and a renamed package takes its other
    files (data files, stubs, extension modules) along. Modules the project's scripts and entry points refer to keep
    their names.
  - `entry`: dotted module paths, or paths of module files relative to the project root. Modules unreachable from
    them are left out of the wheel. The modules the scripts and entry points refer to count as entries too. An entry
    that is not a module of the build is an error.
- `config` table: every `TransformConfig` field (see [Python API](#python-api)). `remove_annotations` also takes a
  table of the four `remove_*_annotations` options, and `remove_docstrings` a table with `also_modules`.

The hook shows its progress on stderr; `hatch build -q` (or `HATCH_QUIET=1`) turns it off. On a terminal, the top bar
shows the whole build (every stage counted alike), the one below the current stage, and the line below them the modules
being compiled or written; elsewhere, each stage leaves one line when done. Progress bars need `tqdm` and `rich`; when
the build environment lacks them, the hook lists the stages as they start
after a warning, or, in CI (the `CI` environment variable is set), reports each stage's progress every tenth as plain
lines.

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
plus `workers`, `rename_modules`, `preserve_modules`, `preserve_type_checking` and `entry`. `minify_project()` returns
where each module and extension module went: its source path to its output path, or to `None` when tree-shaking
dropped it. `minify()` takes `preserve_type_checking` as a `bool`, for its one module.

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
