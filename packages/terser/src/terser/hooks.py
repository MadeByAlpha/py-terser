from hatchling.plugin import hookimpl

from .hatch import TerserBuildHook


@hookimpl
def hatch_register_build_hook():
    return TerserBuildHook
