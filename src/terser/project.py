import os
import shutil
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
from anyio import AsyncFile, CapacityLimiter, Path, to_thread

from alpha93.progression import HeadlessReporter

from ._minify import minify, unparse
from ._pipeline import PathProvider, Pipeline, linker, mangler, transforms, tree_shake
from ._pipeline.mangler.util import preserved_names
from .ast import ref
from .ast.ref import spec as _spec

if TYPE_CHECKING:
    import ast
    from collections.abc import Callable, Coroutine
    from typing import Any

    from alpha93.progression import BaseReporter, Task
    from terser.ast.ref import ModuleRef, ModuleSpec

    from .config import TransformConfig

    type Awaitable[T] = Coroutine[Any, Any, T]


@asynccontextmanager
async def _task_group():
    """A task group that re-raises its only exception by itself, instead of burying it in a group."""

    try:
        async with anyio.create_task_group() as tg:
            yield tg
    except BaseExceptionGroup as group:
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from None
        raise


async def _read_async(path: Path, /, *, limiter: CapacityLimiter) -> str:
    # noinspection bad-argument-type
    source_fp = await to_thread.run_sync(path._path.open, 'r', limiter=limiter)
    source_io = AsyncFile(source_fp, limiter=limiter)
    try:
        # noinspection bad-return
        return await source_io.read()
    finally:
        await source_io.aclose()

async def _write_async(path: Path, source: str, /, *, limiter: CapacityLimiter):
    # noinspection bad-argument-type
    source_fp = await to_thread.run_sync(path._path.open, 'w', limiter=limiter)
    source_io = AsyncFile(source_fp, limiter=limiter)
    try:
        # noinspection bad-argument-type
        await source_io.write(source)
    finally:
        await source_io.aclose()

def _module_output_path(spec: _spec.ModuleSpec, new_dotted: dict[str, str], strip: int = 0) -> Path:
    """
    The relative output path a module should be written to, reflecting its mangled name.

    :param strip: Number of leading dotted components that the output directory itself stands for
    """

    parts = new_dotted.get(str(spec), str(spec)).split('.')[strip:]
    if isinstance(spec, _spec.PackageSpec):
        return Path(*parts, "__init__.py")
    return Path(*parts[:-1], parts[-1] + spec.path.suffix)


class ProjectMinifier(Pipeline):
    def __init__(
        self,
        path_provider: PathProvider,
        config: TransformConfig,
        /,
        reporter: BaseReporter,
        output: Path | None = None,
        workers: int | None = None,
        *,
        rename_locals: bool = True,
        preserve_locals: dict[str, list[str]] | None = None,
        rename_globals: bool = False,
        preserve_globals: dict[str, list[str]] | None = None,
        hoist_literals: bool = True,
        prefer_single_line: bool = True,
        rename_modules: bool = False,
        preserve_modules: set[str] | None = None,
        entry: set[str] | None = None,
    ):
        assert path_provider.is_resolved, "paths are not resolved yet"
        assert not (rename_modules and output is None), \
            "rename_modules requires a separate output directory - it would otherwise leave the renamed file's old copy behind"

        self.__config = config
        self.__output = output

        self.__pp = path_provider
        # FFI binaries have no source to parse - they only occupy a namespace slot, so keep them apart
        self.__module_specs = [s for s in path_provider.iter() if not isinstance(s, _spec.FfiModuleSpec)]
        self.__ffi_specs = [s for s in path_provider.iter() if isinstance(s, _spec.FfiModuleSpec)]
        self.__reporter = reporter
        self.__limiter = CapacityLimiter(total_tokens=workers or int(
                (getattr(os, "process_cpu_count", os.cpu_count)() or 1) * 1.6
        ))

        self.rename_locals = rename_locals
        self.preserve_locals = preserve_locals or {}
        self.rename_globals = rename_globals
        self.preserve_globals = preserve_globals or {}
        self.hoist_literals = hoist_literals
        self.prefer_single_line = prefer_single_line
        self.rename_modules = rename_modules
        self.preserve_modules = preserve_modules or set()

        # when a single package directory is given, the output directory stands for that package:
        # its contents are written straight into it, and the package can't be renamed (since its
        # directory's name is up to the caller)
        self.__output_package = path_provider.single_package_root
        if self.__output_package is not None:
            self.preserve_modules = self.preserve_modules | {self.__output_package}
        self.entry = entry or set()

    @classmethod
    async def minify(
        cls,
        config: TransformConfig,
        paths: set[str],
        /,
        reporter: BaseReporter | None = None,
        output: Path | None = None,
        *args,
        **kwargs
    ):
        # noinspection argument-list,bad-assignment
        reporter: BaseReporter = reporter or HeadlessReporter()

        if len(paths) > 1 and not output:
            raise ValueError("Multiple paths are given, but no output path specified")

        with reporter.prepare("Resolving paths"):
            pp = PathProvider(paths)
            await pp.resolve()

        await cls(pp, config, reporter, output, *args, **kwargs)()

    async def __call__(self, /):
        with self.__reporter.prepare("Calculating task graph"):
            from terser.utils.cli_helper import TqdmDebugTaskGraph
            m, f = len(self.__module_specs), len(self.__ffi_specs)

            tg = TqdmDebugTaskGraph(
                TqdmDebugTaskGraph.Task(m,
                    TqdmDebugTaskGraph.Step(),
                    TqdmDebugTaskGraph.Step(),
                    TqdmDebugTaskGraph.Step(),
                    TqdmDebugTaskGraph.IterableStep(self.__config.passes),
                    TqdmDebugTaskGraph.Step(),
                ),
                TqdmDebugTaskGraph.IterableStep(m),
                TqdmDebugTaskGraph.Step(),
                TqdmDebugTaskGraph.Step(),
                TqdmDebugTaskGraph.IterableStep(m * self.__config.passes),
                TqdmDebugTaskGraph.IterableStep(m + 1),
                TqdmDebugTaskGraph.Task(m + f),
            )
            del TqdmDebugTaskGraph, m, f

        with self.__reporter as reporter:
            reporter.init(task_graph=tg)
            del tg

            modules, project = await self.__minify_modules()

            for module in self.__reporter("Linking", modules):
                linker.link(module, project)

            with self.__reporter("Tree-shaking"):
                entry = await self.__resolve_entry(project)
                project = tree_shake.shake(project, entry)
                modules = [module_ref.ast for module_ref in project.values()]

            with self.__reporter("Mangling modules"):
                new_dotted = mangler.mangle_modules(project, self.rename_modules, self.preserve_modules, entry)

            # whole passes over every module, until a pass changes none of them
            caches = [transforms.TransformCache(self.__config) for _ in modules]
            modules_len, changed = len(modules), False
            for j in self.__reporter("Applying transforms", range(self.__config.passes * len(modules))):
                i = j % modules_len
                modules[i], modified = caches[i].run(modules[i], 2)
                changed |= modified

                if i == modules_len - 1:
                    if not changed:
                        break
                    changed = False

            # for richer progress bar support
            iter_ = iter(self.__reporter("Mangling", range(-1, modules_len)))
            next(iter_)
            mangler.mangle_globals(project, self.rename_globals, self.preserve_globals)

            for i in iter_:
                # global mangling changed the modules, so the caches start over
                modules[i] = transforms.TransformCache(self.__config).run_passes(modules[i], 4)

            await self.__dump_results(modules, project, new_dotted)

    async def __minify_modules(self, /) -> tuple[list[ast.Module], dict[str, ModuleRef]]:
        def __run(task: Task, source: str, spec: ModuleSpec, /):
            local = sorted(preserved_names(str(spec), self.preserve_locals))
            return minify(
                task, source, spec,
                self.__config,
                hoist_literals=self.hoist_literals,
                rename=self.rename_locals,
                preserved_names=local,
            )

        modules: list = [None] * len(self.__module_specs)
        async def __worker(i: int, task: Task, spec: ModuleSpec, /):
            source = await _read_async(spec.path, limiter=self.__limiter)
            module, _ = await to_thread.run_sync(__run, task, source, spec, limiter=self.__limiter)
            modules[i] = module
            task.done()

        async with _task_group() as tg:
            # TODO: Cleanup this shit
            j = len(self.__module_specs) - 1
            for i, (task, spec) in enumerate(self.__reporter.iter(self.__module_specs, "Compiling modules")):
                # noinspection async-call
                t = tg.start_soon(__worker, i, task, spec)

                if i == j:
                    await t.wait()  # forcefully blocks the generator from finishing

        if not all(modules):
            raise RuntimeError("Failed to compile all modules")

        modules: list[ast.Module]
        project: dict[str, ModuleRef] = {str(ref(x).spec): ref(x) for x in modules}
        return modules, project

    async def __resolve_entry(self, project: dict[str, ModuleRef], /) -> set[str]:
        """Resolve `self.entry` (dotted module paths or file paths) against `project`'s modules."""

        resolved: set[str] = set()
        for value in self.entry:
            if value in project:
                resolved.add(value)
                continue

            candidate = await Path(value).resolve()
            for dotted, module_ref in project.items():
                if module_ref.spec.path == candidate:
                    resolved.add(dotted)
                    break

        return resolved

    async def __dump_results(
        self,
        modules: list[ast.Module],
        project: dict[str, ModuleRef],
        new_dotted: dict[str, str],
        /,
    ):
        async def module(node: ast.Module, /):
            spec = ref(node).spec

            if self.__output is None:
                # in-place: write each module back to its own original file
                dest = spec.path
            else:
                dest = self.__output / _module_output_path(spec, new_dotted, self.__output_package is not None)
                await dest.parent.mkdir(parents=True, exist_ok=True)

            source = await to_thread.run_sync(unparse, str(spec.path), None, node, self.prefer_single_line)
            await _write_async(dest, source, limiter=self.__limiter)

        async def binary(ffi_spec: _spec.FfiModuleSpec, /):
            if self.__output is None:
                # in-place: the FFI file is already where it should be
                return

            parent, _, _ = str(ffi_spec).rpartition('.')

            if parent and parent not in project:
                # the containing package was tree-shaken away - no reachable consumer left
                return

            new_parent = new_dotted.get(parent, parent).split('.') if parent else []
            if self.__output_package is not None:
                new_parent = new_parent[1:]
            dest = self.__output.joinpath(*new_parent, ffi_spec.path.name)

            await dest.parent.mkdir(parents=True, exist_ok=True)
            await to_thread.run_sync(shutil.copy2, str(ffi_spec.path), str(dest))

        def wrap[T](func: Callable[[T], Awaitable[None]]) -> Callable[[T], Callable[[Task], Awaitable[None]]]:
            def wrapper(t: T) -> Callable[[Task], Awaitable[None]]:
                async def runner(task: Task, /):
                    await func(t)
                    task.done()
                return runner
            return wrapper

        tasks = set(map(wrap(module), modules)) | set(map(wrap(binary), self.__ffi_specs))
        async with _task_group() as tg:
            j = len(tasks) - 1
            for i, (task, func) in enumerate(self.__reporter.iter(tasks, "Writing output")):
                # noinspection async-call
                t = tg.start_soon(func, task)

                if i == j:
                    await t.wait()
