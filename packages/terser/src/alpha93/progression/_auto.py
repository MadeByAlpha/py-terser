from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ._log import LogReporter

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from ._reporter import Reporter

MISSING_TQDM = "tqdm is not installed, so only the stages are shown, not their progress"


def in_ci() -> bool:
    """If running in CI, going by the `CI` environment variable most CI services set."""

    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no", "off")


def auto_reporter(
    prefix: str = "",
    /,
    *,
    file: TextIO | None = None,
    warn: Callable[[str], None] | None = None,
) -> Reporter:
    """
    A `TqdmReporter` when tqdm is installed. Otherwise a `LogReporter`: a verbose one in CI (whose
    logs are read afterwards anyway), else one listing the stages only, after a warning that tqdm is
    missing.

    :param warn: Receives the warning, which is written to `file` by default
    """

    try:
        import tqdm  # noqa: F401
    except ImportError:
        pass
    else:
        from ._tqdm import TqdmReporter

        return TqdmReporter(prefix, file=file)

    if in_ci():
        return LogReporter(prefix, file=file, verbose=True)

    if warn is None:
        out = file or sys.stderr
        out.write(f"{prefix}warning: {MISSING_TQDM}\n")
    else:
        warn(MISSING_TQDM)
    return LogReporter(prefix, file=file)
