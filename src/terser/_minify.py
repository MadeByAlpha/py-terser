from typing import TYPE_CHECKING

from ._pipeline import preprocessor, parser, resolver, transforms, mangler
from ._pipeline.printer import ModulePrinter
from .ast import CompareError, ast, compare_ast
from .exceptions import InvalidTransformError, UnbeneficialMinificationError

if TYPE_CHECKING:
    from alpha93.progression import Task
    from .ast.ref import ModuleSpec
    from .config import TransformConfig


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
    task: Task,
    source: str,
    spec: ModuleSpec | str,
    /,
    config: TransformConfig,
    *,
    strict: bool = False,
    defines: dict[str, bool] | None = None,
    rename: bool = True,
    preserved_names: list[str] | None = None,
    hoist_literals: bool = True,
) -> tuple[ast.Module, str | None]:
    with task("Preprocessing sources"):
        source, shebang = preprocessor.preprocess(source, defines, strict)

    with task("Parsing AST"):
        module = parser.parse(source, spec, optimize=config.optimize)

        for transform in transforms.__transforms__:
            if not transform.is_enabled(config) or transform.FLAGS > 0:
                continue

            module: ast.Module = transform(config)(module)

    with task("Resolving names"):
        resolver.resolve(module)
        resolver.bind(module)

    cache = transforms.TransformCache(config)
    for _ in task("Applying transforms", range(config.passes)):
        module, changed = cache.run(module, 1)
        if not changed:
            break

    with task("Mangling"):
        if hoist_literals:
            mangler.hoist_literals(module)

        if rename:
            mangler.mangle_locals(module, rename, preserved_names)

        # mangling changed the module behind the previous cache's back, so start over
        module = transforms.TransformCache(config).run_passes(module, 2)

    # FIXME: lineno problem
    # try:
    #     module = ast.parse(module)
    # except SyntaxError as exc:
    #     raise InvalidTransformError(exc, spec, source, module) from exc

    return module, shebang
