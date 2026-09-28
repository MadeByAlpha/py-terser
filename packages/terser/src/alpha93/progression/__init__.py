"""
Progress reporting for a run made of consecutive stages.

A `Reporter` opens one `Stage` at a time; a stage counts `total` units of work, completed with
`Stage.advance()` (which may be called from any thread). Stages are context managers: leaving one
normally marks it complete, leaving it by an exception leaves it where it stopped.

`TqdmReporter` draws progress bars on an interactive terminal, and needs tqdm and rich, which are
optional. `LogReporter` writes plain lines instead: `auto_reporter()` picks it in CI, anywhere that is
no interactive terminal, without tqdm and rich, and when asked to report every item of a stage.
"""

from ._auto import auto_reporter, env_flag, in_ci, interactive
from ._log import LogReporter
from ._reporter import NullReporter, Reporter, Stage

if __debug__ and __import__("typing").TYPE_CHECKING:
    from ._tqdm import TqdmReporter

    __all__ = (
        "LogReporter",
        "NullReporter",
        "Reporter",
        "Stage",
        "TqdmReporter",
        "auto_reporter",
        "env_flag",
        "in_ci",
        "interactive",
    )


def __getattr__(name: str):
    # imported on first use only, so that this package works without tqdm and rich
    if name == "TqdmReporter":
        from ._tqdm import TqdmReporter

        return TqdmReporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
