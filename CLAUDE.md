# CLAUDE.md

`py-terser` (package `terser`) is a fork of [dflook/python-minifier](https://github.com/dflook/python-minifier), being rewritten to minify across a whole project. Planned to provide hatch build hook along with the CLI. The goal is to add a project-wide pipeline in addition to the original single-file pipeline. Source root is `src/`, package manager is `uv`.

Codebase is in mid-migration (dead imports, commented-out code, `# TEMP` markers, empty stubs) — ignore name errors that appear in the type checker. Tests live in `tests/` (pytest, modeled on upstream's suite): run them with `uv run --all-groups pytest`. `tests/helpers.py` holds the shared helpers (`only()` to enable a single transform, `apply_transform()`, `assert_code()`, subprocess runners for the CLI). Known bugs are marked `xfail(strict=True)`, so fixing one requires removing its marker. `test.py` at the root is an ad-hoc manual script for IDE debugging, not a pytest target; do not run or modify it.

## Architecture

Pipelines live under `terser._pipeline`, consists of these components:

- `minify()` — new async minifier, shared across single-file and project-wide mode.
    1. Preprocess (`preprocessor.py`) — strips shebang, handles preprocessing (directives).
    2. Parse (`parser/parser.py`) — parses source into `ast.Module`, wrapping it in a `ModuleRef` (attached via the `ref()`/`NodeRef` mechanism, see below).
    3. Apply pre-transforms — apply transforms with `FLAGS <= 0`.
    4. Resolve names (`resolver/`) — two phase: `resolver.resolve()` in `resolver.py` walks the AST, binding every name to a `Binding` in its namespace (`ScopedNode`), mirroring CPython scoping rules. `binder/` (in `resolver/binder/__init__.py`, running `resolve_all` → `mark_exports` → `resolve_imports` → `bind`) then figures out `__all__`, module exports, and unresolved import targets (`UnresolvedModuleRef`) *within* a single module, deferring cross-module linking.
    5. Apply module transforms — apply transforms with `FLAGS <= 1`, repeat up to `config.passes` times. `TransformCache.run()` (`transforms/_suite.py`) detects changes by comparing `ast.dump()` before/after each transform, skips a transform when nothing changed since it last ran, and a pass that changes nothing stops the loop. A cache is only valid for one module and one stage: create a new one after anything edits the module outside it (e.g. mangling).
    6. Module-level mangle — apply mangling for module-level names (locals/nonlocals, `__` prefixed names).
- Transformers — per-node rewrite passes, inherits `SuiteTransformer`. Some transformers need bindings already resolved (see `FLAGS`) — check the ordering there before adding a new one.
- Mangler — name-shortening (rename, hoist literals). Currently disconnected from the new minifier.

### Project-wide architecture

Project-wide pipeline stages live under `terser._pipeline`, run roughly in this order:

1. Resolve paths — `PathProvider` (`path_provider.py`) takes a set of file/dir paths, walks directories for `*.py`/`*.pyw`, and `align()`s them into a namespace tree of `ModuleSpec` (`terser.ast.ref.module.spec`). This must run and resolve (`await pp.resolve()`) before any module is parsed, since parsing needs a module's `ModuleSpec` to know its dotted path and how to resolve relative imports.
2. Process individual modules asynchronously (multi-threaded) via `minify`.
3. Linking (`linker.py`) — the actual project-aware step: once every module in the project has been through resolver, `link()` matches each module's `import_targets`/`wildcard_targets` against the full `project: dict[str, ModuleRef]` to resolve `import x.y` and`from x import *` across files. Wildcard imports can only be expanded once the target module's exports are known, which is why this is a separate, later pass.
4. Apply project transforms — apply transforms with `FLAGS <= 2`, in whole passes over every module (one `TransformCache` each), until a pass changes none of them or `config.passes` is reached.
5. Project-level mangle — apply project-wide mangling using linked information.
6. Apply mangle-sensitive transforms — apply transforms with `FLAGS <= 4`.

### Node references (`terser.ast.ref`)

AST nodes are plain `ast.AST` subclasses (re-exported from `terser/ast/ast.py`); metadata (parent, namespace, bindings, module spec, etc.) is never stored on the node itself. Instead, `NodeRef.new()` attaches a side-table object to each node via a hidden attribute, retrieved with `ref(node)`.

Which `NodeRef` subclass wraps a node is decided by `NodeRef._KLASSES[type(node)]`: plain nodes get a bare `NodeRef`, namespace-introducing nodes (`SCOPED_T` in `_scoped.py`) get a `ScopedNode` (adds `bindings`/`globals`/`nonlocals`), and `ast.Module` specifically gets `ModuleRef` (`ast/ref/_module/_module.py`, inherits `ScopedNode`), which additionally carries the module's `ModuleSpec`, `preserved`/`all`/`tainted` state, and the `import_targets`/`wildcard_targets` maps that `linker.py` consumes. When adding a new node kind that needs extra metadata, register it in `_KLASSES` rather than adding attributes to the AST node class.

### Name binding (`terser._pipeline.resolver.binder`)

After applying the pre-transform (phase 3 of `minify()`), the declaration of the name is bound. Bindings include `NameBinding`, `ImportBinding`, `UnresolvedBinding`, and `BuiltinBinding`. These will be used for project-wide processing.

## Stub files

There are some hand-written stubs (per the user's Python type-checking convention: complex types go in `.pyi` rather than runtime annotations to save resources) — check these when a type-checker error exists and the runtime source doesn't explain it.
