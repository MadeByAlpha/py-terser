"""
End to end: `tests/fixtures/fastapi_app`, a FastAPI app bundled with rollup-py and minified by the
`terser` hook of this checkout (every transform on, tree-shaking from its entries), must behave the
same as the bundle left as it is. See its README.md.

Deselected by default: run with `uv run --all-groups pytest -m e2e`. It builds on free-threaded
Python 3.14 (which uv downloads), needs network access (PyPI, rollup-py's repository), and takes
some 20 minutes. Set `CHROMIUM_EXECUTABLE` to use a Chromium other than the one Playwright expects.
"""

import os
import shutil
import subprocess

import pytest

from helpers import ROOT

APP = ROOT / "tests" / "fixtures" / "fastapi_app"


@pytest.mark.e2e
def test_minified_bundle_behaves_the_same(tmp_path):
    if shutil.which("uv") is None:
        pytest.skip("needs uv")

    # the app's workspace is not the one of py-terser: its own environment, out of the checkout
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIRTUAL_ENV")}
    env["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "venv")
    result = subprocess.run(
        ["uv", "run", "--python", "3.14t", "scripts/verify.py", "--build-dir", str(tmp_path / "build")],
        cwd=APP, env=env, capture_output=True, text=True, timeout=3 * 60 * 60,
    )
    # progress bars aside
    output = "\n".join(line for line in result.stdout.replace("\r", "\n").splitlines() if "it/s]" not in line)
    assert result.returncode == 0, output[-20_000:] + result.stderr[-5_000:]
    assert "responses match" in output
