from __future__ import annotations

from ._pipeline import (
    dynamic_imports,
    mangler,
    parser,
    preprocessor,
    resolver,
    transforms,
)
from ._pipeline.printer import ModulePrinter
from ._pipeline.transforms.cleanup_local_imports import mark_side_effect_imports
from ._pipeline.transforms.fold_type_checking import keep_type_checking
from .ast import CompareError, ast, compare_ast, ref
from .exceptions import InvalidTransformError, UnbeneficialMinificationError

if __debug__ and __import__("typing").TYPE_CHECKING:
    from .ast.ref import ModuleSpec
    from .config import Config


def unparse(
    path: str,
    source: str | None,
    module: ast.Module,
    prefer_single_line: bool = False
) -> str:
    """
    Turn a module AST into python code

    This returns an exact representation of the given module,
    such that it can be parsed back into the same AST.

    :param ast.Module module: The module to turn into python code
    :param bool prefer_single_line: If semi-colons should be preferred over newlines where there is no difference in output size
    :rtype: str
    """
    printer = ModulePrinter(prefer_single_line=prefer_single_line)
    printer(module)

    try:
        minified_module = ast.parse(printer.code, "<terser.unparse output>")
    except SyntaxError as syntax_error:
        raise InvalidTransformError(syntax_error, path, source, module)

    if source and len(printer.code) >= len(source):
        raise UnbeneficialMinificationError()

    try:
        compare_ast(module, minified_module)
    except CompareError as compare_error:
        raise InvalidTransformError(compare_error, path, source, minified_module)

    return printer.code


def minify(
    source: str,
    spec: ModuleSpec | str,
    config: Config,
    /,
    *,
    preserved_names: list[str] | None = None,
    preserved_globals: list[str] | None = None,
    preserve_type_checking: bool = False,
) -> tuple[ast.Module, str | None]:
    source, shebang = preprocessor.preprocess(source, config.defines, config.strict)
    # `optimize=2` would take the docstrings out before `@terser_hints.preserve_docstring` is seen:
    # `RemoveDocstrings` removes them instead
    module = parser.parse(source, spec, optimize=min(config.transform.optimize, 1))
    ref(module).preserve_type_checking = preserve_type_checking

    for transform in transforms.__transforms__:
        if not transform.is_enabled(config.transform) or transform.FLAGS > 0:
            continue

        module: ast.Module = transform(config.transform)(module)

    resolver.resolve(module)
    resolver.bind(module)
    mangler.mark_preserved(module, preserved_names, preserved_globals)
    mark_side_effect_imports(module)
    if preserve_type_checking:
        keep_type_checking(module)

    cache = transforms.TransformCache(config.transform)
    for _ in range(config.transform.passes):
        module, changed = cache.run(module, 1)
        if not changed:
            break

    # before hoisting literals, which would take the module names out of the calls
    dynamic_imports.find(module)

    if config.hoist_literals:
        mangler.hoist_literals(module)

    if config.rename_locals:
        mangler.mangle_locals(module, config.rename_locals, preserved_names)

    # mangling changed the module behind the previous cache's back, so start over. FLAGS == 2
    # transforms need the module linked, which only happens after this function
    module = transforms.TransformCache(config.transform).run_passes(module, 1)

    # FIXME: lineno problem
    # try:
    #     module = ast.parse(module)
    # except SyntaxError as exc:
    #     raise InvalidTransformError(exc, spec, source, module) from exc

    return module, shebang
