from alpha93.progression import EmptyTask

from ._minify import minify as __minify, unparse as __unparse
from ._pipeline import linker, mangler, transforms
from .ast import DummySpec, ast, ref
from .config import TransformConfig
from .project import ProjectMinifier


minify_project = ProjectMinifier.minify

def minify(
    source: str,
    config: TransformConfig,
    path: str = "<unknown>",
    /,
    *,
    preserve_shebang: bool = True,
    prefer_single_line: bool = False,
    hoist_literals: bool = True,
    rename_locals: bool = True,
    preserve_locals: list[str] | None = None,
    rename_globals: bool = False,
    preserve_globals: list[str] | None = None,
    defines: dict[str, bool] | None = None,
    strict: bool = False,
):
    """
    Minify a python module

    The module is transformed according to arguments.
    If all transformation arguments are False, no transformations are made to the AST, the returned string will
    parse into exactly the same module.

    Using the default arguments only transformations that are always or almost always safe are enabled.

    :param str source: The python module source code
    :param TransformConfig config: Options that affect how the source is transformed
    :param str path: The original source filename if known

    :param bool preserve_shebang: Keep any shebang interpreter directive from the source in the minified output
    :param bool prefer_single_line: If semi-colons should be preferred over newlines where there is no difference in output size
    :param bool hoist_literals: If str and byte literals may be hoisted to the module level where possible.
    :param bool rename_locals: If local names may be shortened
    :param preserve_locals: Locals names to leave unchanged when rename_locals is True
    :type preserve_locals: list[str]
    :param bool rename_globals: If global names may be shortened
    :param preserve_globals: Global names to leave unchanged when rename_globals is True
    :type preserve_globals: list[str]
    :param defines: Values of the names used by `# if NAME` directives. Undefined names count as True
    :type defines: dict[str, bool]
    :param bool strict: Only accept the exact `# if NAME` spelling of directives, and reject unbalanced ones

    :rtype: str
    """

    module, shebang = __minify(
        EmptyTask(), source, DummySpec(path), config,
        strict=strict,
        defines=defines,
        rename=rename_locals,
        preserved_names=sorted(preserve_locals or ()),
        hoist_literals=hoist_literals,
    )

    # a single module is linked as a project of its own, so it goes through the same stages
    module_ref = ref(module)
    project = {str(module_ref.spec): module_ref}
    linker.link(module, project)

    cache = transforms.TransformCache(config)
    for _ in range(config.passes):
        for transform in transforms.__transforms__:
            if not transform.is_enabled(config) or transform.FLAGS > 2:
                continue

            module: ast.Module = transform(cache)(module)

        if not any(cache.passes.values()):
            break

    mangler.mangle_globals(project, rename_globals, {"*": list(preserve_globals or ())})

    for transform in transforms.__transforms__:
        if not transform.is_enabled(config) or transform.FLAGS > 4:
            continue

        module: ast.Module = transform(cache)(module)

    minified = __unparse(path, source, module, prefer_single_line=prefer_single_line)
    return (shebang + '\n' + minified) if preserve_shebang and shebang else minified
