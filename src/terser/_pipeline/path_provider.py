from collections.abc import MutableSet
from typing import TYPE_CHECKING, final, override

from anyio import Path

from terser.ast.ref import spec

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Final

    type NestedDict[T] = dict[str, T | NestedDict[T]]


SUFFIXES = (".py", ".pyw",)
FFI_SUFFIXES = (".so", ".dll", ".dylib", ".pyd",)

@final
class UnresolvedModule(spec.ModuleSpec):
    __path: Final[Path]

    def __init__(self, root: _SourceRoot, path: Path):
        super().__init__(str(path.relative_to(root.path).with_suffix("")).replace(path.parser.sep, '.'))
        self.__path = path

    @override
    @property
    def path(self):
        return self.__path

    @override
    def resolve(self, module: str) -> str:
        raise NotImplementedError

class _SourceRoot:
    __resolver: Final[_SpecResolver]
    __path: Final[Path]

    __unresolved: dict[str, UnresolvedModule]

    @property
    def path(self):
        return self.__path

    def __init__(self, resolver: _SpecResolver, source: Path):
        assert source.is_absolute(), "Path is not resolved yet (not an absolute path)"

        self.__resolver = resolver
        self.__path = source
        self.__unresolved = {}

    def register(self, path: Path):
        namespace = UnresolvedModule(self, path)
        self.__unresolved[str(namespace)] = namespace
        return namespace

    def align(self):
        aligned: NestedDict[UnresolvedModule] = {}
        resolved: dict[str, spec.PackageSpec | spec.SingleFileModuleSpec] = {}

        def walk(d: NestedDict[UnresolvedModule], ns: list[str]) -> NestedDict[UnresolvedModule]:
            if not len(ns):
                return d

            t: NestedDict[UnresolvedModule] | UnresolvedModule | None = d.get(c := ns.pop(0))
            if not t:
                t = d[c] = {}
            elif isinstance(t, UnresolvedModule):
                raise RuntimeError("conflict")

            t: NestedDict[UnresolvedModule]
            return walk(t, ns)

        def resolve(t: NestedDict[UnresolvedModule], parent: spec.PackageSpec | None = None):
            current = None
            if unresolved := t.get("__init__"):
                if isinstance(unresolved, dict):
                    raise TypeError

                current = spec.PackageSpec(unresolved, parent)
                if parent:
                    parent.register(current)
                else:
                    resolved[str(current)] = current

            for k, v in t.items():
                if k == "__init__":
                    continue

                if isinstance(v, dict):
                    resolve(v, current)
                    continue

                v: UnresolvedModule
                if not current:
                    ns = spec.SingleFileModuleSpec(v.path)
                    resolved[str(ns)] = ns
                    continue
                ns = spec.PackageModuleSpec(v, current)
                current.register(ns)

        for k, v in self.__unresolved.items():
            ns = k.split('.')
            walk(aligned, ns[:-1])[ns[-1]] = v

        resolve(aligned)
        return resolved

class _SpecResolver:
    __sources: dict[str, _SourceRoot]
    __specs: dict[str, spec.ModuleSpec]

    def __init__(self):
        self.__sources = {}
        self.__specs = {}

    def __call__(self, path: Path):
        namespace = spec.SingleFileModuleSpec(path)
        self.__specs[str(namespace)] = namespace
        return namespace

    def __getitem__(self, source: Path):
        return self.__sources[str(source)]

    def register(self, source: Path):
        self.__sources[str(source)] = _SourceRoot(self, source)

    def align(self):
        for root in self.__sources.values():
            self.__specs |= root.align()

        return self.__specs

class PathProvider(MutableSet[str]):
    __queue: set[str]
    __discarded: set[str]

    __specs: dict[str, spec.ModuleSpec]
    __iter: set[spec.ModuleSpec]
    __roots: set[Path]
    __ffi_files: set[Path]

    def __init__(self, paths: set[str]):
        self.__specs = {}
        self.__iter = set()
        self.__queue = set() | paths
        self.__discarded = set()
        self.__roots = set()
        self.__ffi_files = set()

    @property
    def specs(self):
        return self.__specs

    @property
    def ffi_files(self) -> set[Path]:
        return self.__ffi_files

    @property
    def roots(self) -> set[Path]:
        """Resolved absolute directory roots that were walked to build the specs."""
        return self.__roots

    @property
    def is_resolved(self) -> bool:
        return not len(self.__queue) and not len(self.__discarded)

    @override
    def add(self, value: str, /):
        self.__queue.add(value)

    @override
    def discard(self, value: str, /):
        self.__discarded.add(value)

    async def __resolve(self, *, strict: bool):
        discarded, self.__discarded = {str(await Path(s).resolve()) for s in self.__discarded}, set()

        ns, queue = _SpecResolver(), self.__queue
        while len(queue):
            path = await Path(queue.pop()).resolve(strict=strict)
            if str(path) in discarded:
                continue

            if not (await path.exists()):
                raise FileNotFoundError(path)
            if not (await path.is_dir()):
                if await self.__assert_ffi(path):
                    self.__ffi_files.add(path)
                    continue
                if not await self.__assert_file(path):
                    continue

                ns(path)
                continue

            ns.register(path)
            self.__roots.add(path)
            async for root, _, children in path.walk(follow_symlinks=not strict):
                for child in children:
                    path_ = root / child
                    if await self.__assert_ffi(path_):
                        self.__ffi_files.add(path_)
                        continue
                    if not await self.__assert_file(path_):
                        continue

                    ns[path].register(path_)

        self.__queue = set(queue)
        self.__specs = ns.align()

    async def resolve(self, *, strict: bool = False):
        await self.__resolve(strict=strict)
        if not self.is_resolved:
            raise RuntimeError

        collect = set()
        def walk(d: dict[str, spec.ModuleSpec]):
            for v in d.values():
                collect.add(v)
                if isinstance(v, spec.PackageSpec):
                    walk(v.children)
                    continue
        walk(self.__specs)
        self.__iter = collect

    @override
    def __contains__(self, _, /):
        raise NotImplementedError

    @override
    def __len__(self, /):
        assert self.is_resolved, "Path provider is not resolved yet"
        return len(self.__iter)

    @override
    def __iter__(self):
        pass

    def iter(self, /) -> Iterator[spec.ModuleSpec]:
        assert self.is_resolved, "Path provider is not resolved yet"
        return iter(self.__iter)

    @staticmethod
    async def __assert_ffi(path: Path):
        if not (await path.is_file()):
            return False

        if path.suffix.lower() not in FFI_SUFFIXES:
            return False

        return True

    @staticmethod
    async def __assert_file(path: Path):
        if not (await path.is_file()):
            return False

        if path.suffix not in SUFFIXES:
            return False

        return True
