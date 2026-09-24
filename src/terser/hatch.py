import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import anyio
import pathspec
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from .config import RemoveAnnotationOptions, TransformConfig
from .terser import minify_project


class TerserBuildHook(BuildHookInterface):
    PLUGIN_NAME = "terser"

    _out_dir: Path | None = None

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name == "sdist":
            return

        included_files = list(self.build_config.builder.recurse_included_files())
        py_files = [
            f for f in included_files
            if f.path.endswith(".py") or f.path.endswith(".pyw")
        ]
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

        config_opts = dict(self.config.get("config", {}))
        if isinstance(remove_annotations := config_opts.get("remove_annotations"), dict):
            config_opts["remove_annotations"] = RemoveAnnotationOptions(**remove_annotations)
        config = TransformConfig(**config_opts)

        # outside the build's output directory, and removed again in finalize()
        out_dir = Path(tempfile.mkdtemp(prefix="terser-build-"))
        self._out_dir = out_dir

        asyncio.run(
            minify_project(
                config,
                roots,
                reporter=None,
                output=anyio.Path(out_dir),
                hoist_literals=self.config.get("hoist_literals", True),
                rename_locals=self.config.get("rename_locals", True),
                preserve_locals=self.config.get("preserve_locals"),
                rename_globals=self.config.get("rename_globals", False),
                preserve_globals=self.config.get("preserve_globals"),
            )
        )

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
