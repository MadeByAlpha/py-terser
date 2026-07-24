## Implemented transforms

All entries below are implemented and registered in `__transforms__` (`__init__.py`). Config field names are on `TransformConfig` (`terser/config.py`) unless noted.

- Contracts (`contracts.py`, `Contracts`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.apply_contracts`, rules in `config.contracts`.
    - Default contracts: `typing.cast(_, value) -> value` (leave only `value`), `typing.assert_never(x) -> None` (completely remove call), `typing.assert_type(x, _) -> x` (leave only `x`).
- Unfold IIFEs (`unfold_iife.py`, `UnfoldIIFE`) - `config.unfold_iife_lambdas`. Inlines immediately-invoked no-arg lambda calls: `(lambda: x)()` -> `x`.
- Remove dummy assignments (`remove_dummy_assignments.py`, `RemoveDummyAssignments`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_dummy_assignments`. Removes self-assignments like `x = x` (same binding on both sides).
- Remove literal statements (`remove_literal_statements.py`, `RemoveLiteralStatements`) - `config.remove_literal_statements` (default off). Drops `Expr` statements that are just a literal constant. Leaves the first statement of a module/class/function body alone if it's a string literal (a docstring position) - `RemoveDocstrings` decides what happens to those.
- Remove docstrings (`remove_docstrings.py`, `RemoveDocstrings`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_docstrings: bool | RemoveDocstringOptions` (default off; `RemoveDocstringOptions.also_modules` to also strip module docstrings). Preserves a docstring if the class/function is decorated with `@terser_hints.preserve_docstring` (`terser_hints` package, a runtime no-op marker).
- Combine imports (`combine_imports.py`, `CombineImports`) - `config.combine_imports`. Merges consecutive `import`/`from x import` statements where possible (never merges `from x import *`, and leaves a lone un-combinable import untouched rather than rebuilding it).
- Cleanup local imports (`cleanup_local_imports.py`, `CleanupLocalImports`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.cleanup_local_imports`. Removes unused imports inside a function/class body always; removes unused module-level imports too if `config.respect_all` and the name isn't exported (via `__all__`/no leading underscore).
- Remove annotations (`remove_annotations.py`, `RemoveAnnotations`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_annotations: bool | RemoveAnnotationOptions`.
- Remove `type` statements (`remove_type_statements.py`, `RemoveTypeStatements`) - `config.remove_type_statements`. Drops `type X = ...` (PEP 695) alias statements.
- Remove typing classes (`remove_typing_classes.py`, `RemoveTypingClasses`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_typing_classes`. Strips a bare `Protocol` base class, unless the class is decorated with `@typing.runtime_checkable` (needed for `isinstance` to keep working).
- Convert typing constructors (`convert_typing_constructors.py`, `ConvertTypingConstructors`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.convert_typing_constructors`. For simple field-only (no methods) `NamedTuple`/`TypedDict` classes: rewrites a `NamedTuple` class into `X = collections.namedtuple('X', (...), defaults=(...))` (adding `import collections` if needed); rewrites a `TypedDict` class into plain `dict` - the class is dropped and every `X(...)` construction site becomes `dict(...)`, but only when every use is a pure-keyword call (bails out and leaves the class alone otherwise).
- Remove `Generic`s (`remove_generics.py`, `RemoveGenerics`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_generics`. Strips a bare (non-parametrized) `Generic` base class; leaves `Generic[T]` alone since that form has real `__class_getitem__` behavior.
- Remove `@overload`s (`remove_overloads.py`, `RemoveOverloads`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_overloads`, always on when `config.remove_typing_decorators` is set. Drops `@typing.overload`-decorated stub defs, keeping the final undecorated implementation.
- Remove typing decorators (`remove_typing_decorators.py`, `RemoveTypingDecorators`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_typing_decorators`. Strips `@typing.override`/`@typing.final`.
- Remove explicit `return None` (`remove_explicit_return_none.py`, `RemoveExplicitReturnNone`) - `config.remove_explicit_return_none`. Converts `return None` to bare `return`, and drops a trailing bare `return` from a function body.
- Fold constants (`constant_folding.py`, `FoldConstants`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.fold_constants` (numeric/bool folding), `config.remove_debug` (part of the same class).
    - Constant arithmetic/unary operations on number/bool literals, kept only if the folded form is strictly shorter and round-trips to the same value and type.
    - Boolean-identity comparisons: `x == True`/`x is True` -> `x`, `x == False`/`x is False` -> `not x` (and the `!=`/`is not` inverses).
    - `__debug__` -> `True`/`False` literal (based on `config.optimize`), `typing.TYPE_CHECKING` -> `False`.
    - Collection-constructor literals: `list()` -> `[]`, `dict()` -> `{}`, `tuple()` -> `()`, `set([1, 2])`/`set((1, 2))` -> `{1, 2}` (only for a single list/tuple-literal argument).
    - Not implemented: numeric-literal reformatting (`0b1` -> `1`, etc.), `\uXXXX` string unescaping (this is the printer's job, not a transform's - it always picks the shortest valid string representation already), `sys.version_info`/`sys.platform` folding (no target-version/platform config exists to fold against), and f-string folding (`f"{x}"` -> `str(x)` etc. - dropped: whether `x` is already a `str` can't be verified statically, so wrapping unconditionally risks growing the source instead of shrinking it).
- Convert `typing_extensions` (`convert_typing_extensions.py`, `ConvertTypingExtensions`) - `config.convert_typing_extensions`. Rewrites `from typing_extensions import X` to `from typing import X` for a fixed set of symbols long-stable in `typing`, only when every name in the statement is on that list.
- Fold `TYPE_CHECKING` (`fold_type_checking.py`, `FoldTypeChecking`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.fold_type_checking`. `typing.TYPE_CHECKING` (also `typing_extensions`') becomes `False`, and `typing` imports left unused are removed. Modules matching `Config.preserve_type_checking` are left alone.
- Remove dead code (`remove_dead_code.py`, `RemoveDeadCode`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.remove_dead_code`. Removes the branches of `if`/`while` whose condition is known, unless that changes how the function compiles.
- Remove dead blocks (`remove_dead_blocks.py`, `RemoveDeadBlocks`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - runs right after `FoldConstants` in registration order (needs its literal-bool output). Collapses `if <literal bool>:` into just the taken branch.
- Convert early exits (`convert_early_exits.py`, `ConvertEarlyExits`) - `config.convert_early_exits`. Merges `if cond: return a` immediately followed by `return b` into `return a if cond else b`.
- Convert to inline (`convert_to_inline.py`, `ConvertToInline`) - `config.convert_to_inline`.
    - `if cond: func(x)` -> `cond and func(x)`
    - `if fizz: foo()` / `else: bar()` -> `foo() if fizz else bar()`
- Convert to lambda (`convert_to_lambda.py`, `ConvertToLambda`) - `config.convert_to_lambda`. `def foo(...): return expr` -> `foo = lambda ...: expr` (only for a single `return <expr>` body - a bare trailing expression isn't converted, since a lambda's value differs from a statement's implicit `None`).
- Convert dynamic attribute access (`convert_dynamic_attribute_access.py`, `ConvertDynamicAttributeAccess`) `(Flags.REQUIRES_IMPORT_RESOLVE)` - `config.convert_dynamic_attribute_access`. `getattr(obj, "name")` -> `obj.name`, a bare `setattr(obj, "name", value)` statement -> `obj.name = value`. Ignored when: `name` isn't a constant string, `name` isn't a valid/non-keyword identifier, or `getattr` is called with a default value (3-arg form).
- Remove unnecessary base/meta classes (`remove_object_base.py`, `RemoveObject`) - `config.remove_explicit_base`. Removes `object` from a class's bases.
- Remove empty exception brackets (`remove_exception_brackets.py`, `RemoveExceptionBrackets`) `(Flags.REQUIRES_MODULE_RESOLVE)` - `config.remove_empty_exc_brackets`. `raise ValueError()` -> `raise ValueError` for built-in exceptions.
- Convert pass (`remove_pass.py`, `RemovePass`) - `config.convert_pass`. Removes `pass` statements, or converts to `0` if a suite would otherwise be empty.

### Excluded

- `[EXPERIMENTAL]` Inline functions - out of scope, not implemented.
- `[EXPERIMENTAL]` Inline `enum.IntFlag`s - out of scope, not implemented.

### After mangling

- Convert positional arguments (`remove_posargs.py`, `ConvertPosargs`) `(Flags.INFLUENCES_MANGLING)` - `config.convert_posargs`. Converts positional-only arguments to normal arguments, unless the function takes `**kwargs`.
- Remove `__all__` (`remove_all.py`, `RemoveAll`) `(Flags.INFLUENCES_MANGLING)` - `config.remove_dunder_all`. Drops the top-level `__all__` assignment.
