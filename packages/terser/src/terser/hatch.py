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
from typing import Any

import anyio
import pathspec
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from alpha93.progression import NullReporter, Reporter, auto_reporter

from .config import RemoveAnnotationOptions, TransformConfig
from .project import ProjectMinifier
from .terser import minify_project

# Targets whose final set of files is only known once the artifact is built: `rollup` (rollup-py)
# vendors dependencies from its own hook, which always runs after every other hook's `initialize()`.
# Their wheels are minified in `finalize()` instead, vendored files included.
POSTPROCESS_TARGETS = frozenset({"rollup"})

_SOURCE_SUFFIXES = (".py", ".pyw")


class TerserBuildHook(BuildHookInterface):
    PLUGIN_NAME = "terser"

    _out_dir: Path | None = None

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name == "sdist" or self.target_name in POSTPROCESS_TARGETS:
            return

        included_files = list(self.build_config.builder.recurse_included_files())
        py_files = [f for f in included_files if f.path.endswith(_SOURCE_SUFFIXES)]
        if not py_files:
            return

        roots = set()
        for f in included_files:
            str_path = str(f.path)
            dist_path = str(f.distribution_path)
            if str_path.endswith(dist_path):
                root = str_path[:-len(dist_path)].rstrip("/\\")
                if root:
                    roots.add(root)

        if not roots:
            return

        # outside the build's output directory, and removed again in finalize()
        out_dir = Path(tempfile.mkdtemp(prefix="terser-build-"))
        self._out_dir = out_dir
        with self._reporter() as reporter:
            self._minify(roots, out_dir, reporter)

        # Minified files are added via force_include; the originals must be excluded
        # from the normal package walk, or the wheel builder rejects the duplicate
        # distribution path.
        force_include = build_data.setdefault("force_include", {})
        exclude_patterns = []
        for f in py_files:
            minified_path = out_dir / f.distribution_path
            if minified_path.is_file():
                force_include[str(minified_path)] = f.distribution_path
                exclude_patterns.append("/" + f.relative_path)

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

    def _minify(self, roots: set[str], out_dir: Path, reporter: Reporter) -> None:
        config_opts = dict(self.config.get("config", {}))
        if isinstance(remove_annotations := config_opts.get("remove_annotations"), dict):
            config_opts["remove_annotations"] = RemoveAnnotationOptions(**remove_annotations)
        config = TransformConfig(**config_opts)

        asyncio.run(
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
            sources = [
                info for info in infos
                if info.filename.endswith(_SOURCE_SUFFIXES)
                and info.filename.partition("/")[0] not in (dist_info, data_dir)
            ]
            if not sources:
                return

            with tempfile.TemporaryDirectory(prefix="terser-build-") as tmp:
                src_dir, out_dir = Path(tmp, "src"), Path(tmp, "out")
                with reporter.stage("Extracting wheel", len(sources)) as stage:
                    for info in stage.iter(sources):
                        wheel.extract(info, src_dir)

                self._minify({str(src_dir)}, out_dir, reporter)

                minified = {
                    info.filename: (out_dir / info.filename).read_bytes()
                    for info in sources
                    if (out_dir / info.filename).is_file()
                }

            records = list(csv.reader(io.StringIO(wheel.read(record_name).decode())))
            for row in records:
                if (data := minified.get(row[0])) is not None:
                    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                    row[1:3] = f"sha256={digest}", str(len(data))

            record = io.StringIO()
            csv.writer(record, delimiter=",", quotechar='"', lineterminator="\n").writerows(records)

            fd, tmp_path = tempfile.mkstemp(prefix=".terser-", suffix=".whl", dir=os.path.dirname(path))
            try:
                with (
                    reporter.stage("Rewriting wheel", len(infos)) as stage,
                    os.fdopen(fd, "wb") as fp,
                    zipfile.ZipFile(fp, "w") as out,
                ):
                    for info in stage.iter(infos):
                        if info.filename == record_name:
                            data = record.getvalue().encode()
                        elif (data := minified.get(info.filename)) is None:
                            data = wheel.read(info)
                        out.writestr(_copy_info(info), data)
            except BaseException:
                os.unlink(tmp_path)
                raise

        os.chmod(tmp_path, os.stat(path).st_mode)
        os.replace(tmp_path, path)


def _copy_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """A fresh entry with `info`'s name, timestamp, permissions and compression, for other contents."""

    copy = zipfile.ZipInfo(info.filename, info.date_time)
    copy.external_attr = info.external_attr
    copy.create_system = info.create_system
    copy.compress_type = info.compress_type
    return copy
