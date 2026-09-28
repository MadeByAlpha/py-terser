"""
Check that minifying the bundle with py-terser keeps the app's behavior.

1. Builds the bundle twice with `hatch build -t rollup` on free-threaded Python 3.14: once from a
   copy of the workspace without the `terser` hook (the baseline), and once as configured.
2. Installs each wheel into its own virtual environment, and imports every module of the minified
   wheel in both: the ones only the minified one fails to import are reported.
3. Serves each with uvicorn (external to the bundle, like on Vercel), sends both servers the same
   requests, and compares status, content type and body.

Run from the workspace root: `uv run --python 3.14t scripts/verify.py` (see README.md), or through
`tests/test_fastapi_app.py` of py-terser.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
PYTHON = "3.14t"
# the free-threaded interpreter only differs by its ABI: keep its environments apart from the default `.venv`
ENV = {**os.environ, "UV_PROJECT_ENVIRONMENT": os.environ.get("UV_PROJECT_ENVIRONMENT", ".venv-3.14t")}
# a build stuck in a module (as `mangle_locals` once was in `numpy.testing.overrides`) fails, rather than hangs
BUILD_TIMEOUT = 3600


def run(*args: str | Path, cwd: Path = ROOT, env: dict[str, str] = ENV, timeout: float | None = None) -> None:
    print("$", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True, timeout=timeout)


def build_minified() -> Path:
    out = BUILD / "minified"
    shutil.rmtree(out, ignore_errors=True)
    # a build environment of its own, so it picks up the py-terser checkout as it is now
    env = {**ENV, "HATCH_DATA_DIR": str(BUILD / "hatch")}
    shutil.rmtree(BUILD / "hatch", ignore_errors=True)
    run("uv", "run", "--python", PYTHON, "hatch", "build", "-t", "rollup", out, env=env, timeout=BUILD_TIMEOUT)
    return _wheel(out)


def build_baseline() -> Path:
    import tomlkit

    out = BUILD / "baseline"
    shutil.rmtree(out, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix="api-baseline-") as tmp:
        src = Path(tmp, "api")
        shutil.copytree(
            ROOT, src, ignore=shutil.ignore_patterns(".venv*", "build", "dist", "__pycache__"), symlinks=True
        )
        pyproject = tomlkit.parse((src / "pyproject.toml").read_text())
        # without the hook, and so without py-terser
        del pyproject["tool"]["hatch"]["build"]["targets"]["rollup"]["hooks"]
        del pyproject["tool"]["hatch"]["envs"]
        del pyproject["tool"]["uv"]["sources"]["py-terser"]
        requires = pyproject["build-system"]["requires"]
        requires.remove("py-terser")
        (src / "pyproject.toml").write_text(tomlkit.dumps(pyproject))

        env = {**ENV, "HATCH_DATA_DIR": str(Path(tmp, "hatch"))}
        run("uv", "lock", cwd=src, env=env)
        run("uv", "run", "--python", PYTHON, "hatch", "build", "-t", "rollup", out, cwd=src, env=env, timeout=BUILD_TIMEOUT)
    return _wheel(out)


def _wheel(directory: Path) -> Path:
    (wheel,) = directory.glob("*.whl")
    return wheel


def install(name: str, wheel: Path) -> Path:
    venv = BUILD / f"venv-{name}"
    shutil.rmtree(venv, ignore_errors=True)
    run("uv", "venv", "--python", PYTHON, venv)
    run("uv", "pip", "install", "--python", venv / "bin" / "python", wheel, "uvicorn")
    return venv / "bin" / "python"


IMPORT_ALL = r"""
import importlib, json, sys, traceback, warnings
warnings.simplefilter("ignore")
failed = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except BaseException as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1:] or [None]
        where = f" ({frame[0].filename}:{frame[0].lineno})" if frame[0] else ""
        failed[name] = f"{type(exc).__name__}: {exc}{where}"
print(json.dumps(failed))
"""


def modules(wheel: Path) -> list[str]:
    """Every module of `wheel` but tests and scripts, by its dotted path"""

    import zipfile

    names = []
    with zipfile.ZipFile(wheel) as whl:
        for name in whl.namelist():
            parts = name.removesuffix(".py").split("/")
            if not name.endswith(".py") or parts[0].endswith((".dist-info", ".data")):
                continue
            if parts[-1] == "__init__":
                parts.pop()
            if any(p in ("tests", "testing", "__main__", "conftest") or p.startswith("test_") for p in parts):
                continue
            names.append(".".join(parts))
    return sorted(names)


def import_all(python: Path, names: list[str]) -> dict[str, str]:
    """The modules of `names` that `python` fails to import, with why"""

    env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "UV_", "PYTHON"))}
    result = subprocess.run(
        [python, "-c", IMPORT_ALL, json.dumps(names)], cwd=BUILD, env={**env, "PYTHON_GIL": "0"},
        capture_output=True, text=True, timeout=1200,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class Server:
    def __init__(self, name: str, python: Path, extra_env: dict[str, str] | None = None) -> None:
        self.name = name
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.log = open(BUILD / f"{name}.log", "w")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "UV_", "PYTHON"))}
        env |= {"PYTHON_GIL": "0", "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")}
        env |= extra_env or {}
        self.process = subprocess.Popen(
            [python, "-m", "uvicorn", "api.main:app", "--port", str(self.port), "--no-access-log"],
            cwd=BUILD, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{name}: server exited, see {self.log.name}")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/openapi.json", timeout=1).close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"{name}: server did not start, see {self.log.name}")

    def request(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        headers = dict(headers or {})
        data = None
        if isinstance(body, str):
            data = body.encode()
            headers.setdefault("content-type", "application/yaml")
        elif body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("content-type", "application/json")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=headers
        )
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            content_type = response.headers.get("content-type", "")
            payload: Any = raw.decode()
            if content_type.startswith("application/json"):
                payload = json.loads(raw)
            return {
                "status": response.status,
                "content-type": content_type,
                "x-api": response.headers.get("x-api"),
                "body": payload,
            }

    def stop(self) -> None:
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.log.close()


MANIFEST = """\
name: demo
version: [1, 2, 3]
server:
  host: 0.0.0.0
  port: 8080
  tags: [edge, blue]
extra:
  origin: !point [1.5, -2]
  weights: [0.25, 0.75]
"""

PAGE = """\
<html><head><title>terser check</title></head>
<body><h1>Hello</h1><p>minified <b>and</b> bundled</p>
<a href="https://example.com/a">a</a><a href="/b">b</a></body></html>
"""

REQUESTS: list[tuple[str, str, Any, dict[str, str] | None]] = [
    ("GET", "/", None, None),
    ("GET", "/teapot?reason=tipped+over", None, None),
    ("GET", "/numeric/stats?values=1,2,3,4,10.5", None, None),
    ("GET", "/numeric/stats?values=1,x", None, None),
    ("GET", "/numeric/stats", None, None),
    ("POST", "/numeric/matrix", {"a": [[1, 2], [3, 4]], "b": [[5, 6], [7, 8]]}, None),
    ("POST", "/numeric/matrix", {"a": [[1, 2, 3]], "b": [[1], [2], [3]]}, None),
    ("POST", "/numeric/matrix", {"a": [[1, 2]], "b": [[1, 2]]}, None),
    ("GET", "/numeric/primes?limit=500", None, None),
    ("GET", "/numeric/primes?limit=1", None, None),
    ("GET", "/numeric/collatz/27", None, None),
    ("GET", "/numeric/collatz/0", None, None),
    ("POST", "/documents/manifest", MANIFEST, None),
    ("POST", "/documents/manifest", "name: [unclosed", None),
    ("POST", "/documents/manifest", "name: x\nversion: [1, two]\nserver: {port: -}\n", None),
    ("GET", "/documents/schema", None, None),
    ("GET", "/documents/points?count=4", None, None),
    ("POST", "/browser/render", {"html": PAGE, "script": "[...document.querySelectorAll('p, h1')].length"}, None),
    ("POST", "/files/attributes", {"name": "notes", "attrs": {"owner": "api", "stage": "minified"}}, None),
    ("POST", "/files/attributes", {"name": "Bad Name"}, None),
    ("GET", "/files/pipeline?count=12&workers=4", None, None),
    ("GET", "/relay/echo?word=terser", None, None),
    ("POST", "/relay/reports/Latency", [12.5, 3, 7.25, 30, 18], None),
    ("POST", "/relay/reports/empty", [], None),
    ("GET", "/platform/geo", None, {
        "x-real-ip": "203.0.113.7", "x-vercel-ip-country": "KR", "x-vercel-ip-city": "Seoul",
        "x-vercel-ip-country-region": "11", "x-vercel-ip-latitude": "37.56", "x-vercel-ip-longitude": "126.97",
        "x-vercel-id": "icn1::abcde-1234",
    }),
    ("GET", "/platform/schedule?expr=*/5+2+*+*+1-5", None, None),
    ("GET", "/platform/schedule?expr=every+day", None, None),
    ("GET", "/crons/", None, None),
    ("POST", "/reports/samples", {"name": " Queue ", "unit": "count", "data": [4, 8, 15, 16, 23, 42]}, None),
    ("POST", "/reports/samples", {"name": "", "unit": "hours", "data": []}, None),
    ("GET", "/reports/samples/QUEUE", None, None),
    ("GET", "/reports/samples/queue/histogram?bins=3", None, None),
    ("GET", "/reports/samples/missing", None, None),
    ("GET", "/reports/export.yaml", None, None),
    ("GET", "/openapi.json", None, None),
    ("GET", "/reports/openapi.json", None, None),
    ("GET", "/docs", None, None),
]


def exchange(server: Server) -> list[tuple[str, dict[str, Any]]]:
    results = []
    for method, path, body, headers in REQUESTS:
        results.append((f"{method} {path}", server.request(method, path, body, headers)))
    # the jobs are only known once the app runs
    for job in results[[r[0] for r in results].index("GET /crons/")][1]["body"]:
        for path in (f"/crons/{job}", f"/crons/{job}/source"):
            results.append((f"GET {path}", server.request("GET", path)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-build", action="store_true", help="reuse the wheels under build/")
    parser.add_argument("--no-baseline", action="store_true", help="only rebuild the minified wheel")
    parser.add_argument("--build-dir", type=Path, help="where wheels, environments and logs go (default: build/)")
    args = parser.parse_args()

    global BUILD
    BUILD = (args.build_dir or BUILD).resolve()
    BUILD.mkdir(parents=True, exist_ok=True)
    if args.no_build:
        baseline, minified = _wheel(BUILD / "baseline"), _wheel(BUILD / "minified")
    else:
        baseline = _wheel(BUILD / "baseline") if args.no_baseline else build_baseline()
        minified = build_minified()

    print(f"baseline: {baseline.stat().st_size:>11,} bytes  {baseline.name}")
    print(f"minified: {minified.stat().st_size:>11,} bytes  {minified.name}")

    pythons = {name: install(name, wheel) for name, wheel in (("baseline", baseline), ("minified", minified))}

    names = modules(minified)
    failed = {name: import_all(python, names) for name, python in pythons.items()}
    broken = {name: why for name, why in failed["minified"].items() if name not in failed["baseline"]}
    print(f"{len(names) - len(broken)}/{len(names)} modules import")
    for name, why in sorted(broken.items()):
        print(f"  FAIL  import {name}: {why}")

    results = {}
    for name, python in pythons.items():
        server = Server(name, python)
        try:
            results[name] = exchange(server)
        finally:
            server.stop()

    failures = len(broken)
    for (request, expected), (_, actual) in zip(results["baseline"], results["minified"], strict=True):
        if expected == actual:
            print(f"  ok    {request}  ({expected['status']})")
            continue
        failures += 1
        print(f"  FAIL  {request}")
        diff = difflib.unified_diff(
            json.dumps(expected, indent=1, sort_keys=True).splitlines(),
            json.dumps(actual, indent=1, sort_keys=True).splitlines(),
            "baseline", "minified", lineterm="", n=2,
        )
        print("\n".join("        " + line for line in diff))

    (BUILD / "results.json").write_text(json.dumps(results, indent=1))
    print(f"{len(results['baseline']) - failures + len(broken)}/{len(results['baseline'])} responses match")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
