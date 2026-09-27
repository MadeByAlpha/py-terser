from __future__ import annotations

from ._minify import minify as __minify
from ._minify import unparse as __unparse
from ._pipeline import linker, mangler, transforms
from ._pipeline.mangler.util import STAR_ARGS
from .ast import DummySpec, ref
from .config import Config, TransformConfig
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
    rename_star_args: bool = True,
    rename_globals: bool = False,
    preserve_globals: list[str] | None = None,
    preserve_type_checking: bool = False,
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
    :param preserve_locals: Locals names to leave unchanged when rename_locals is True. Besides
        names, `*`/`**` stand for `*args`/`**kwargs` parameters (`*name`/`**name` for those named
        so), and a `qualname glob::` prefix limits an entry to matching functions and classes
    :type preserve_locals: list[str]
    :param bool rename_star_args: If `*args`/`**kwargs` parameter names may be shortened, when
        rename_locals is True
    :param bool rename_globals: If global names may be shortened
    :param preserve_globals: Global names to leave unchanged when rename_globals is True
    :type preserve_globals: list[str]
    :param bool preserve_type_checking: Leave `TYPE_CHECKING` and the code it guards as they
        are, even when `config.fold_type_checking` is True
    :param defines: Values of the names used by `# if NAME` directives. Undefined names count as True
    :type defines: dict[str, bool]
    :param bool strict: Only accept the exact `# if NAME` spelling of directives, and reject unbalanced ones

    :rtype: str
    """

    module, shebang = __minify(
        source,
        DummySpec(path),
        Config(
            defines=defines or {},
            strict=strict,
            transform=config,
            preserve_shebang=preserve_shebang,
            prefer_single_line=prefer_single_line,
            hoist_literals=hoist_literals,
            rename_locals=rename_locals,
            rename_star_args=rename_star_args,
        ),
        preserved_names=sorted(preserve_locals or ())
        + ([] if rename_star_args else STAR_ARGS),
        preserved_globals=list(preserve_globals or ()),
        preserve_type_checking=preserve_type_checking,
    )

    # a single module is linked as a project of its own, so it goes through the same stages
    module_ref = ref(module)
    project = {str(module_ref.spec): module_ref}
    linker.link(module, project)
    transforms.mark_classes(project)

    module = transforms.TransformCache(config).run_passes(module, 2)
    mangler.mangle_globals(project, rename_globals, {"*": list(preserve_globals or ())})
    module = transforms.TransformCache(config).run_passes(module, 4)

    minified = __unparse(path, source, module, prefer_single_line=prefer_single_line)
    return (shebang + '\n' + minified) if preserve_shebang and shebang else minified
