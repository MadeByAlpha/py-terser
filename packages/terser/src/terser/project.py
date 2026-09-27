from __future__ import annotations

import fnmatch
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, override

import anyio
from alpha93.commons.types import typed
from anyio import CapacityLimiter, Path, to_thread

from alpha93.progression import NullReporter

from ._minify import minify, unparse
from ._pipeline import PathProvider, Pipeline, linker, mangler, transforms, tree_shake
from ._pipeline.mangler.util import STAR_ARGS, preserved_names
from ._pipeline.pipeline import PipelineContext, PipelineStep
from .ast import ref
from .ast.ref import spec as _spec
from .config import Config
from .exceptions import DynamicImportWarning

if __debug__ and TYPE_CHECKING:
    import ast
    from collections.abc import Callable, Collection
    from typing import Any

    from alpha93.progression import Reporter, Stage
    from terser.ast.ref import ModuleRef, ModuleSpec


@asynccontextmanager
async def _task_group():
    """A task group that re-raises its only exception by itself, instead of burying it in a group."""

    try:
        async with anyio.create_task_group() as tg:
            yield tg
    except KeyboardInterrupt:
        tg.cancel()
        raise
    except BaseExceptionGroup as group:
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from None
        raise


def _read(path: os.PathLike[str], /) -> str:
    with open(path) as fp:
        return fp.read()


def _write(path: os.PathLike[str], source: str, /) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fp:
        fp.write(source)


def _module_output_path(spec: _spec.ModuleSpec, new_dotted: dict[str, str], strip: int = 0) -> Path:
    """
    The relative output path a module should be written to, reflecting its mangled name.

    :param strip: Number of leading dotted components that the output directory itself stands for
    """

    parts = new_dotted.get(str(spec), str(spec)).split('.')[strip:]
    if isinstance(spec, _spec.PackageSpec):
        return Path(*parts, "__init__.py")
    return Path(*parts[:-1], parts[-1] + spec.path.suffix)


@dataclass(frozen=True)
class _FinalContext(PipelineContext):
    config: Config
    reporter: Reporter
    limiter: CapacityLimiter

    module_specs: list[_spec.ModuleSpec]
    ffi_specs: list[_spec.FfiModuleSpec]
    output_package: str | None = None


@dataclass()
class _Context(PipelineContext):
    frozen: _FinalContext

    entry: set[str]
    project: dict[str, ModuleRef]
    modules: list[ast.Module]
    modules_len: int
    new_dotted: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str | None] = field(default_factory=dict)


class ProjectMinifier(Pipeline[_Context]):
    # how many stages `minify()` reports
    STAGES = 7

    def __init__(self, paths: PathProvider, config: Config, reporter: Reporter, /):
        assert paths.is_resolved, "paths are not resolved yet"

        # when a single package directory is given, the output directory stands for that package:
        # its contents are written straight into it, and the package can't be renamed (since its
        # directory's name is up to the caller)
        output_package = paths.single_package_root
        if output_package is not None:
            config = replace(config, preserve_modules=config.preserve_modules | {output_package})

        limiter = CapacityLimiter(
            total_tokens=config.workers or int((getattr(os, "process_cpu_count", os.cpu_count)() or 1) * 1.6)
        )

        # FFI binaries have no source to parse - they only occupy a namespace slot, so keep them apart
        module_specs: list[_spec.ModuleSpec] = [s for s in paths if not isinstance(s, _spec.FfiModuleSpec)]
        ffi_specs: list[_spec.FfiModuleSpec] = [s for s in paths if isinstance(s, _spec.FfiModuleSpec)]

        super().__init__(
            _Context(
                frozen=_FinalContext(
                    config=config,
                    reporter=reporter,
                    limiter=limiter,
                    module_specs=module_specs,
                    ffi_specs=ffi_specs,
                    output_package=output_package
                ),
                entry=set(config.entry),
                project={},
                modules=[],
                modules_len=0,
            )
        )

    @classmethod
    async def minify(
        cls,
        paths: Collection[str],
        config: Config,
        /,
        reporter: Reporter | None = None,
    ):
        """
        Minify the modules under `paths` as one project.
        """

        reporter = reporter or NullReporter()
        reporter.plan(cls.STAGES)

        if len(paths) > 1 and not config.output_path:
            raise ValueError("Multiple paths are given, but no output path specified")
        if config.rename_modules and not config.output_path:
            raise ValueError("rename_modules requires a separate output directory"
                             " - it would otherwise leave the renamed file's old copy behind")

        # resolving paths awaits one file system call at a time, so it takes one thread at most
        pp = PathProvider(set(paths))
        await pp.resolve()

        # noinspection argument-list
        return await cls(pp, config, reporter)()

    async def __call__(self, /) -> dict[str, str | None]:
        await typed[MinifyModuleStep](MinifyModuleStep.__init__)(self, self._ctx)()
        await typed[LinkStep](LinkStep.__init__)(self, self._ctx)()
        await typed[TransformStep](TransformStep.__init__)(self, self._ctx)()
        await typed[ObfuscationStep](ObfuscationStep.__init__)(self, self._ctx)()
        await typed[MangleStep](MangleStep.__init__)(self, self._ctx)()
        await typed[FinalizationStep](FinalizationStep.__init__)(self, self._ctx)()
        await typed[PrintStep](PrintStep.__init__)(self, self._ctx)()
        return self._ctx.outputs


class MinifyModuleStep(PipelineStep[_Context]):
    def __run(self, source: str, spec: ModuleSpec, /):
        local = sorted(preserved_names(str(spec), self._ctx.frozen.config.preserve_locals))
        if not self._ctx.frozen.config.rename_star_args:
            local += STAR_ARGS

        return minify(
            source,
            spec,
            self._ctx.frozen.config,
            preserved_names=local,
            preserved_globals=sorted(
                preserved_names(str(spec), self._ctx.frozen.config.preserve_globals)
            ),
            preserve_type_checking=any(
                fnmatch.fnmatch(str(spec), pattern)
                for pattern in self._ctx.frozen.config.preserve_type_checking
            ),
        )

    @override
    async def __call__(self, /) -> None:
        modules: list = [None] * len(self._ctx.frozen.module_specs)
        with self._ctx.frozen.reporter.stage("Compiling modules", len(modules)) as stage:
            def __compile(spec: ModuleSpec, /):
                # in the thread: a module waiting for one is not being compiled yet
                with stage.item(str(spec)):
                    return self.__run(_read(spec.path), spec)

            async def __worker(i: int, spec: ModuleSpec, /):
                # one thread per module, for reading and compiling it
                module, _ = await to_thread.run_sync(__compile, spec, limiter=self._ctx.frozen.limiter)
                modules[i] = module

            async with _task_group() as tg:
                for n, m in enumerate(self._ctx.frozen.module_specs):
                    # noinspection async-call
                    tg.start_soon(__worker, n, m)

        if not all(modules):
            raise RuntimeError("Failed to compile all modules")

        modules: list[ast.Module]
        project: dict[str, ModuleRef] = {str(ref(x).spec): ref(x) for x in modules}
        self._ctx.modules, self._ctx.project = modules, project
        self._ctx.modules_len = len(modules)


class LinkStep(PipelineStep[_Context]):
    @override
    async def __call__(self, /) -> None:
        with self._ctx.frozen.reporter.stage("Linking", self._ctx.modules_len) as stage:
            for module in stage.iter(self._ctx.modules):
                linker.link(module, self._ctx.project)
            transforms.mark_classes(self._ctx.project)
            self._ctx.entry = await self.__resolve_entry(self._ctx.project)

        if self._ctx.frozen.config.rename_modules or self._ctx.frozen.config.rename_globals or self._ctx.entry:
            self.__warn_dynamic_imports(self._ctx.project)

    async def __resolve_entry(self, project: dict[str, ModuleRef], /) -> set[str]:
        """Resolve `self.entry` (dotted module paths or file paths) against `project`'s modules."""

        resolved: set[str] = set()
        for value in self._ctx.entry:
            if value in project:
                resolved.add(value)
                continue

            candidate = await Path(value).resolve()
            for dotted, module_ref in project.items():
                if module_ref.spec.path == candidate:
                    resolved.add(dotted)
                    break

        return resolved

    def __warn_dynamic_imports(self, project: dict[str, ModuleRef], /) -> None:
        """Warn about the dynamic import calls (`__import__()`, ...) this run can't follow."""

        for dotted, module_ref in sorted(project.items()):
            for found in module_ref.dynamic_imports:
                if found.name:
                    continue
                self._ctx.frozen.reporter.warn(
                    f"{dotted}, {found.location}: `{found.callee}()` is given a module name that is not a "
                    "literal, so renaming modules or globals and tree-shaking can't follow it (keep what it "
                    "imports with `preserve_modules`, `preserve_globals` and `entry`)",
                    DynamicImportWarning,
                )


class TransformStep(PipelineStep[_Context]):
    def __tree_shake(self, /) -> None:
        self._ctx.project = tree_shake.shake(self._ctx.project, self._ctx.entry)
        self._ctx.modules = [module_ref.ast for module_ref in self._ctx.project.values()]
        self._ctx.modules_len = len(self._ctx.modules)

    def _prepare_cache(self):
        self.__caches = [transforms.TransformCache(self._ctx.frozen.config.transform) for _ in self._ctx.modules]

    def _transform(self, i: int, stage: Stage, separated: bool, flags: int, /) -> Any:
        with stage.item(str(ref(node := self._ctx.modules[i]).spec)):
            cache = self.__caches[i]
            # noinspection argument-list
            value = (cache.run_passes if separated else cache.run)(node, flags)
            self._ctx.modules[i] = value if separated else value[0] # type: ignore[ty:invalid-assignment,ty:not-subscriptable]
            return value

    @override
    async def __call__(self, /) -> None:
        self.__tree_shake()
        self._prepare_cache()
        total = self._ctx.frozen.config.transform.passes * self._ctx.modules_len
        with self._ctx.frozen.reporter.stage("Applying transforms", total) as stage:
            for _ in range(self._ctx.frozen.config.transform.passes):
                changed = False
                for i in range(self._ctx.modules_len):
                    _, diff = self._transform(i, stage, False, 2)
                    changed |= diff

                if not changed:
                    break


class FinalizationStep(TransformStep):
    @override
    async def __call__(self, /) -> None:
        self._prepare_cache()

        async def __worker(i: int, stage: Stage, /):
            # one thread per module, for finalizing it
            await to_thread.run_sync(self._transform, i, stage, True, 4, limiter=self._ctx.frozen.limiter)

        with self._ctx.frozen.reporter.stage("Finalizing", self._ctx.modules_len) as p:
            async with _task_group() as tg:
                for q in range(self._ctx.modules_len):
                    # noinspection async-call
                    tg.start_soon(__worker, q, p)


class ObfuscationStep(PipelineStep[_Context]):
    @override
    async def __call__(self, /) -> None:
        with self._ctx.frozen.reporter.stage("Mangling globals"):
            mangler.mangle_globals(self._ctx.project, self._ctx.frozen.config.rename_globals, self._ctx.frozen.config.preserve_globals)


class MangleStep(PipelineStep[_Context]):
    @override
    async def __call__(self, /) -> None:
        with self._ctx.frozen.reporter.stage("Mangling modules"):
            self._ctx.new_dotted = mangler.mangle_modules(self._ctx.project, self._ctx.frozen.config.rename_modules, self._ctx.frozen.config.preserve_modules, self._ctx.entry)


class PrintStep(PipelineStep[_Context]):
    def module(self, node: ast.Module, /):
        spec = ref(node).spec

        # in-place: write each module back to its own original file
        dest = spec.path if self._ctx.frozen.config.output_path is None else \
            self._ctx.frozen.config.output_path / _module_output_path(spec, self._ctx.new_dotted, self._ctx.frozen.output_package is not None)

        _write(dest, unparse(str(spec.path), None, node, self._ctx.frozen.config.prefer_single_line))
        self._ctx.outputs[str(spec.path)] = str(dest)

    def binary(self, ffi_spec: _spec.FfiModuleSpec, /):
        if self._ctx.frozen.config.output_path is None:
            # in-place: the FFI file is already where it should be
            self._ctx.outputs[str(ffi_spec.path)] = str(ffi_spec.path)
            return

        parent, _, _ = str(ffi_spec).rpartition('.')

        if parent and parent not in self._ctx.project:
            # the containing package was tree-shaken away - no reachable consumer left
            return

        new_parent = self._ctx.new_dotted.get(parent, parent).split('.') if parent else []
        if self._ctx.frozen.output_package is not None:
            new_parent = new_parent[1:]
        dest = Path(self._ctx.frozen.config.output_path).joinpath(*new_parent, ffi_spec.path.name)

        os.makedirs(dest.parent, exist_ok=True)
        shutil.copy2(ffi_spec.path, dest)
        self._ctx.outputs[str(ffi_spec.path)] = str(dest)

    @override
    async def __call__(self, /) -> None:
        self._ctx.outputs = dict.fromkeys(
            str(spec.path) for spec in (*self._ctx.frozen.module_specs, *self._ctx.frozen.ffi_specs)
        )

        with self._ctx.frozen.reporter.stage("Writing output", self._ctx.modules_len + len(self._ctx.frozen.ffi_specs)) as stage:
            def write[T](func: Callable[[T], None], t: T, name: str, /):
                # in the thread: a file waiting for one is not being written yet
                with stage.item(name):
                    func(t)

            async def writer[T](func: Callable[[T], None], t: T, name: str, /):
                # one thread per file, for everything writing it takes
                await to_thread.run_sync(write, func, t, name, limiter=self._ctx.frozen.limiter)

            async with _task_group() as tg:
                for node in self._ctx.modules:
                    # noinspection async-call
                    tg.start_soon(writer, self.module, node, str(ref(node).spec))
                for ffi_spec in self._ctx.frozen.ffi_specs:
                    # noinspection async-call
                    tg.start_soon(writer, self.binary, ffi_spec, str(ffi_spec))
