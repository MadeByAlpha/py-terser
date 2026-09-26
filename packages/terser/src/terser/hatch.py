from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import pathspec
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from alpha93.progression import NullReporter, Reporter, auto_reporter

from ._pipeline.path_provider import SUFFIXES
from .config import RemoveAnnotationOptions, TransformConfig
from .project import ProjectMinifier
from .terser import minify_project

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from hatchling.builders.plugin.interface import IncludedFile

# Targets whose final set of files is only known once the artifact is built: `rollup` (rollup-py)
# vendors dependencies from its own hook, which always runs after every other hook's `initialize()`.
# Their wheels are minified in `finalize()` instead, vendored files included.
POSTPROCESS_TARGETS = frozenset({"rollup"})

_SOURCE_SUFFIXES = SUFFIXES
_INIT_FILES = tuple("__init__" + suffix for suffix in SUFFIXES)


class TerserBuildHook(BuildHookInterface):
    PLUGIN_NAME = "terser"

    _out_dir: Path | None = None

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name == "sdist" or self.target_name in POSTPROCESS_TARGETS:
            return

        # only the files hatchling picks from the project tree: forced inclusions can't be taken
        # out again (so neither replaced)
        files: dict[str, IncludedFile] = {}
        sources: dict[str, str] = {}  # named the way `minify_project()` names them: under a resolved root
        roots = set()
        for f in self.build_config.builder.recurse_selected_project_files():
            dist_path = f.distribution_path.replace(os.sep, "/")
            if (
                f.path.endswith(f.distribution_path) and f.relative_path
                and (root := f.path[:-len(f.distribution_path)].rstrip("/\\"))
            ):
                roots.add(root)
                files[dist_path] = f
                sources[dist_path] = os.path.join(os.path.realpath(root), f.distribution_path)

        options = self._options(files)
        if not any(dist_path.endswith(_SOURCE_SUFFIXES) for dist_path in files):
            return

        # outside the build's output directory, and removed again in finalize()
        out_dir = Path(tempfile.mkdtemp(prefix="terser-build-"))
        self._out_dir = out_dir
        with self._reporter() as reporter:
            outputs = self._minify(roots, out_dir, reporter, options)

        moves = _relocate(sources, outputs, out_dir)

        # Minified, renamed and moved files are added via force_include; the originals must be
        # excluded from the normal package walk, or the wheel builder rejects the duplicate
        # distribution path.
        force_include = build_data.setdefault("force_include", {})
        exclude_patterns = []
        for dist_path, f in files.items():
            if (move := moves[dist_path]) == (dist_path, sources[dist_path]):
                continue

            exclude_patterns.append("/" + f.relative_path.replace(os.sep, "/"))
            if move is not None:
                new_path, source = move
                force_include[source] = new_path

        if exclude_patterns:
            new_spec = pathspec.GitIgnoreSpec.from_lines(exclude_patterns)
            existing_spec = self.build_config.exclude_spec
            self.build_config.__dict__["exclude_spec"] = (
                pathspec.GitIgnoreSpec(list(existing_spec.patterns) + list(new_spec.patterns))
                if existing_spec is not None
                else new_spec
            )

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        if self._out_dir is not None:
            shutil.rmtree(self._out_dir, ignore_errors=True)
            self._out_dir = None

        if self.target_name in POSTPROCESS_TARGETS and artifact_path.endswith(".whl"):
            with self._reporter() as reporter:
                # extracting and rewriting the wheel, around minifying it
                reporter.plan(2 + ProjectMinifier.STAGES)
                self._minify_wheel(artifact_path, reporter)

    def _reporter(self) -> Reporter:
        # `hatch build -q` (or `HATCH_QUIET`) asks for less output
        if self.app.verbosity < 0:
            return NullReporter()

        # tqdm comes with py-terser, but a build environment only has what `[build-system].requires` lists
        def warn(message: str) -> None:
            self.app.display_warning(f'terser: {message}; add "tqdm" to `[build-system].requires` to see it')

        return auto_reporter("terser: ", warn=warn)

    def _option[T](self, name: str, check: Callable[[Any], bool], expected: str, default: T) -> T:
        value = self.config.get(name, default)
        if value is not default and not check(value):
            raise ValueError(f"terser: `{name}` must be {expected}, got {value!r}")
        return value

    def _options(self, files: Mapping[str, IncludedFile | None]) -> dict[str, Any]:
        """
        The options for `minify_project()` other than the transforms'.

        :param files: Every file of the distribution by its distribution path, with the file it
            comes from in the project, if any (for telling entry modules given as file paths)
        """

        def strings(value: Any) -> bool:
            return isinstance(value, list) and all(isinstance(item, str) for item in value)

        workers = self._option("workers", lambda v: type(v) is int and v >= 1, "a positive integer", None)
        rename_modules = self._option("rename_modules", lambda v: type(v) is bool, "a boolean", False)
        preserve_modules = self._option("preserve_modules", strings, "a list of strings", [])
        entry = self._option("entry", strings, "a list of strings", [])

        modules = {_dotted(dist_path): dist_path for dist_path in files if dist_path.endswith(_SOURCE_SUFFIXES)}
        by_file = {
            os.path.normpath(f.relative_path): _dotted(dist_path)
            for dist_path, f in files.items() if f is not None and dist_path.endswith(_SOURCE_SUFFIXES)
        }

        entry_modules = set()
        for value in entry:
            dotted = by_file.get(os.path.normpath(value), value)
            if dotted not in modules:
                raise ValueError(f"terser: entry `{value}` is neither a module nor a module file of the build")
            entry_modules.add(dotted)

        # what the distribution's metadata points at must keep its name, and survive tree-shaking
        declared = {
            dotted for dotted in map(_entry_point_module, self._entry_points())
            if dotted in modules
        }
        if entry_modules:
            entry_modules |= declared
        if rename_modules:
            preserve_modules = [*preserve_modules, *(p for d in declared for p in _with_ancestors(d))]

        return {
            "workers": workers,
            "rename_modules": rename_modules,
            "preserve_modules": set(preserve_modules),
            "entry": entry_modules,
        }

    def _entry_points(self) -> list[str]:
        """Every `module:attribute` reference of the project's scripts and entry points."""

        core = self.metadata.core
        references = [*core.scripts.values(), *core.gui_scripts.values()]
        for group in core.entry_points.values():
            references.extend(group.values())
        return references

    def _minify(self, roots: set[str], out_dir: Path, reporter: Reporter, options: dict[str, Any]) -> dict[str, str | None]:
        config_opts = dict(self.config.get("config", {}))
        if isinstance(remove_annotations := config_opts.get("remove_annotations"), dict):
            config_opts["remove_annotations"] = RemoveAnnotationOptions(**remove_annotations)
        config = TransformConfig(**config_opts)

        return asyncio.run(
            minify_project(
                config,
                roots,
                reporter=reporter,
                output=anyio.Path(out_dir),
                hoist_literals=self.config.get("hoist_literals", True),
                rename_locals=self.config.get("rename_locals", True),
                preserve_locals=self.config.get("preserve_locals"),
                rename_globals=self.config.get("rename_globals", False),
                preserve_globals=self.config.get("preserve_globals"),
                **options,
            )
        )

    def _minify_wheel(self, path: str, reporter: Reporter) -> None:
        """Minify every module of a built wheel in place (as one project), and rewrite its `RECORD`."""

        with zipfile.ZipFile(path) as wheel:
            infos = wheel.infolist()
            record_name = next(
                info.filename for info in infos
                if info.filename.count("/") == 1 and info.filename.endswith(".dist-info/RECORD")
            )
            dist_info = record_name.partition("/")[0]
            data_dir = dist_info.removesuffix(".dist-info") + ".data"

            # only what lands in site-packages: scripts and data files are left alone
            contents = [
                info for info in infos
                if not info.is_dir() and info.filename.partition("/")[0] not in (dist_info, data_dir)
            ]
            if not any(info.filename.endswith(_SOURCE_SUFFIXES) for info in contents):
                return

            # entry modules given as files are files of the project, found in the wheel as built
            project_files = {
                f.distribution_path.replace(os.sep, "/"): f
                for f in self.build_config.builder.recurse_included_files() if f.relative_path
            } if self.build_config is not None else {}
            options = self._options({info.filename: project_files.get(info.filename) for info in contents})

            # only the sources: an FFI binary next to a source of the same module (as mypyc builds
            # ship them) would take the source's place in the project. Every other file moves along
            # with a renamed package all the same
            sources = [info for info in contents if info.filename.endswith(_SOURCE_SUFFIXES)]

            with tempfile.TemporaryDirectory(prefix="terser-build-") as tmp:
                src_dir, out_dir = Path(tmp, "src"), Path(tmp, "out")
                with reporter.stage("Extracting wheel", len(sources)) as stage:
                    for info in stage.iter(sources):
                        wheel.extract(info, src_dir)

                outputs = self._minify({str(src_dir)}, out_dir, reporter, options)
                root = os.path.realpath(src_dir)
                moves = _relocate(
                    {info.filename: os.path.join(root, info.filename) for info in contents}, outputs, out_dir,
                )

                fd, tmp_path = tempfile.mkstemp(prefix=".terser-", suffix=".whl", dir=os.path.dirname(path))
                try:
                    with (
                        reporter.stage("Rewriting wheel", len(infos)) as stage,
                        os.fdopen(fd, "wb") as fp,
                        zipfile.ZipFile(fp, "w") as out,
                    ):
                        records = []
                        for info in stage.iter(infos):
                            if info.filename == record_name:
                                continue

                            if info.filename not in moves:  # metadata, scripts and data files
                                name, data = info.filename, wheel.read(info)
                            elif (move := moves[info.filename]) is None:  # tree-shaken away
                                continue
                            else:
                                name, source = move
                                if source == os.path.join(root, info.filename):
                                    data = wheel.read(info)  # contents left as they are (if maybe moved)
                                else:
                                    with open(source, "rb") as source_fp:
                                        data = source_fp.read()

                            if name in out.NameToInfo:
                                raise ValueError(f"terser: two files would be written to `{name}` in the wheel")
                            out.writestr(_copy_info(info, name), data)
                            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                            records.append((name, f"sha256={digest}", str(len(data))))

                        records.append((record_name, "", ""))
                        record = io.StringIO()
                        csv.writer(record, delimiter=",", quotechar='"', lineterminator="\n").writerows(records)
                        out.writestr(_copy_info(wheel.getinfo(record_name)), record.getvalue().encode())
                except BaseException:
                    os.unlink(tmp_path)
                    raise

        os.chmod(tmp_path, os.stat(path).st_mode)
        os.replace(tmp_path, path)


def _dotted(dist_path: str) -> str:
    """The dotted module path of the module at `dist_path`."""

    parts = dist_path.rsplit(".", 1)[0].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" and len(parts) > 1 else parts)


def _entry_point_module(reference: str) -> str:
    """The module of an entry point reference: `module:attr [extra]`."""

    return reference.partition(":")[0].strip()


def _with_ancestors(dotted: str) -> list[str]:
    parts = dotted.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _relocate(
    files: Mapping[str, str],
    outputs: Mapping[str, str | None],
    out_dir: Path,
) -> dict[str, tuple[str, str] | None]:
    """
    Where every file of the distribution goes once the project is minified.

    :param files: Every file's source on disk, by its distribution path
    :param outputs: What `minify_project()` returned: output paths by source path, or None for a
        module that tree-shaking dropped
    :param out_dir: Where `minify_project()` wrote its outputs
    :return: By distribution path, the file's new distribution path and where its contents are
        now, or None for a file dropped from the distribution
    """

    def relative(output: str) -> str:
        return Path(output).relative_to(out_dir).as_posix()

    # a renamed package takes the files in its directory (data files, stubs...) along
    directories = {}
    for dist_path, source in files.items():
        if dist_path.rsplit("/", 1)[-1] in _INIT_FILES and (output := outputs.get(source)) is not None:
            old, new = dist_path.rpartition("/")[0], relative(output).rpartition("/")[0]
            if old != new:
                directories[old] = new

    def moved(dist_path: str) -> str:
        parts = dist_path.split("/")
        for i in range(len(parts) - 1, 0, -1):
            if (new := directories.get("/".join(parts[:i]))) is not None:
                return "/".join((new, *parts[i:]))
        return dist_path

    moves: dict[str, tuple[str, str] | None] = {}
    for dist_path, source in files.items():
        if source not in outputs:
            # not part of the minified project (a data file, say)
            moves[dist_path] = moved(dist_path), source
        elif (output := outputs[source]) is not None:
            moves[dist_path] = relative(output), output
        elif dist_path.endswith(_SOURCE_SUFFIXES):
            moves[dist_path] = None
        else:
            # an FFI binary of a dropped package: left where it was, in case it's used some other way
            moves[dist_path] = dist_path, source
    return moves


def _copy_info(info: zipfile.ZipInfo, name: str | None = None) -> zipfile.ZipInfo:
    """A fresh entry with `info`'s timestamp, permissions and compression, for other contents (and name)."""

    copy = zipfile.ZipInfo(name or info.filename, info.date_time)
    copy.external_attr = info.external_attr
    copy.create_system = info.create_system
    copy.compress_type = info.compress_type
    return copy
