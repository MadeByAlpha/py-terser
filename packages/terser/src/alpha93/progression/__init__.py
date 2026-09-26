"""
Progress reporting for a run made of consecutive stages.

A `Reporter` opens one `Stage` at a time; a stage counts `total` units of work, completed with
`Stage.advance()` (which may be called from any thread). Stages are context managers: leaving one
normally marks it complete, leaving it by an exception leaves it where it stopped.
"""

from ._reporter import NullReporter, Reporter, Stage
from ._tqdm import TqdmReporter

__all__ = ["NullReporter", "Reporter", "Stage", "TqdmReporter"]
