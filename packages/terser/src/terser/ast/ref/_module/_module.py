from __future__ import annotations

from typing import TYPE_CHECKING, final

from terser.ast import ast
from .._scoped import ScopedNode

if __debug__ and TYPE_CHECKING:
    from typing import Final

    # noinspection protected-member
    from terser._pipeline.resolver.binder import ImportTarget, UnresolvedModuleRef
    # noinspection protected-member
    from terser._pipeline.resolver.binding import ImportBinding
    # noinspection protected-member
    from terser._pipeline.dynamic_imports import DynamicImport
    from ._spec import ModuleSpec


@final
class _Root(ast.AST):
    def __repr__(self):
        return "Root()"


@final
class ModuleRef(ScopedNode[ast.Module]):
    spec: Final[ModuleSpec]
    preserved: set[str]
    all: set[str] | None

    import_targets: dict[ImportBinding, UnresolvedModuleRef]
    """Every ImportBinding created while binding this module, mapped to its resolved path once
    `resolve_imports` has run (None until then)"""

    import_aliases: dict[ast.alias, ImportTarget]
    """What each alias of the `ImportBinding`s in `import_targets` imports, resolved by
    `resolve_imports` and linked by `linker.link` (a binding may have more than one alias)"""

    submodule_hops: dict[ast.Attribute, str]
    """The attribute accesses reading a submodule off its package (`pkg.sub`) that renaming modules
    renamed, to the submodule's old dotted path"""

    wildcard_targets: dict[ast.ImportFrom, UnresolvedModuleRef]
    """Every `from x import *` statement in this module, mapped to its resolved path once
    `resolve_imports` has run (None until then)"""

    dynamic_imports: list[DynamicImport]
    """Every `__import__()`/`importlib.import_module()` call in this module, once
    `dynamic_imports.find` has run"""

    tainted: bool

    def __init__(self, module: ast.Module, spec: ModuleSpec):
        self.spec = spec
        self.preserved = set()
        self.all = None
        self.import_targets = {}
        self.import_aliases = {}
        self.submodule_hops = {}
        self.wildcard_targets = {}
        self.dynamic_imports = []
        self.tainted = False

        super().__init__(module, None)  # type: ignore[ty:invalid-argument-type]
        self._resolve_all()

    @property
    def _parent(self):
        raise ValueError("Root node cannot have parent")

ScopedNode._KLASSES[ast.Module] = ModuleRef
