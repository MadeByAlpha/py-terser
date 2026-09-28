from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ._log import LogReporter

if __debug__ and __import__("typing").TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from ._reporter import Reporter

MISSING_TQDM = "tqdm or rich is not installed, so only the stages are shown, not their progress"


def env_flag(name: str, /) -> bool:
    """If the environment variable `name` is set, to anything but an empty string, 0, false, no or off."""

    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no", "off")


def in_ci() -> bool:
    """If running in CI, going by the `CI` environment variable most CI services set."""

    return env_flag("CI")


def interactive(file: TextIO, /) -> bool:
    """If `file` is a terminal that can redraw lines in place (i.e. not a log, a pipe, or a dumb terminal)."""

    try:
        if not file.isatty():
            return False
    except (AttributeError, ValueError, OSError):  # not a real file, or a closed one
        return False
    return os.environ.get("TERM", "").strip().lower() not in ("dumb", "unknown")


def auto_reporter(
    prefix: str = "",
    /,
    *,
    file: TextIO | None = None,
    warn: Callable[[str], None] | None = None,
    verbose: bool = False,
) -> Reporter:
    """
    A `TqdmReporter` on an interactive terminal, when tqdm and rich are installed.

    Otherwise a `LogReporter`: in CI or anywhere else that is no interactive terminal (e.g. a log,
    which can't redraw a bar in place), one reporting each stage's progress as it goes; on a
    terminal without tqdm and rich, one listing the stages only, after a warning that they are
    missing.

    :param warn: Receives the warning, which is written to `file` by default
    :param verbose: Report each item of a stage as it starts and ends, and how long it took, always
        as plain lines (to tell which items a run spends its time on)
    """

    out = file or sys.stderr
    if verbose:
        return LogReporter(prefix, file=out, progress=True, items=True)
    if in_ci() or not interactive(out):
        return LogReporter(prefix, file=out, progress=True)

    try:
        import tqdm.rich  # noqa: F401 (needs rich)
    except ImportError:
        pass
    else:
        from ._tqdm import TqdmReporter

        return TqdmReporter(prefix, file=out)

    if warn is None:
        out.write(f"{prefix}warning: {MISSING_TQDM}\n")
    else:
        warn(MISSING_TQDM)
    return LogReporter(prefix, file=out)
