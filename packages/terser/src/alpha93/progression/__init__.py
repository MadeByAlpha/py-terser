"""
Progress reporting for a run made of consecutive stages.

A `Reporter` opens one `Stage` at a time; a stage counts `total` units of work, completed with
`Stage.advance()` (which may be called from any thread). Stages are context managers: leaving one
normally marks it complete, leaving it by an exception leaves it where it stopped.

`TqdmReporter` needs tqdm, which is optional; `auto_reporter()` falls back to `LogReporter` without it.
"""

from typing import TYPE_CHECKING

from ._auto import auto_reporter, in_ci
from ._log import LogReporter
from ._reporter import NullReporter, Reporter, Stage

if TYPE_CHECKING:
    from ._tqdm import TqdmReporter

__all__ = ["LogReporter", "NullReporter", "Reporter", "Stage", "TqdmReporter", "auto_reporter", "in_ci"]


def __getattr__(name: str):
    # imported on first use only, so that this package works without tqdm
    if name == "TqdmReporter":
        from ._tqdm import TqdmReporter

        return TqdmReporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
