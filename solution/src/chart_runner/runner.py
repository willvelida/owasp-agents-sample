"""Isolated chart runner (ASI05).

Runs generated chart code where it can do no harm. The container has no network (locally
`network_mode: none`; on Azure a Dynamic Sessions pool with egress disabled), a read-only image, no
secrets, and runs as UID 10001. Each job gets a fresh worker process with an empty environment, its own
temporary directory, CPU, memory, and file size limits, and a 10 second wall clock. Only a PNG under
the size cap comes back.

Served over HTTP on a Unix socket locally (`--uds`) or on a TCP port in a session container (`--port`).
"""

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

JOB_TIMEOUT_SECONDS = 10.0
MAX_CODE_CHARS = 8000
MAX_POINTS = 62
MAX_PNG_BYTES = 1_000_000
MAX_BODY_BYTES = 64_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WORKER = Path(__file__).with_name("worker.py")
# Read-only font cache baked into the runner image; tests and other hosts fall back to the job directory.
MPL_CACHE = "/app/mplconfig" if Path("/app/mplconfig").is_dir() else None


def _limit_worker() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _failure(error: str) -> dict:
    return {"ok": False, "error": error[:200]}


def _collect(job_dir: str) -> dict:
    png_path, result_path = Path(job_dir, "chart.png"), Path(job_dir, "result.json")
    if not png_path.is_file() or png_path.stat().st_size > MAX_PNG_BYTES:
        return _failure("no chart.png under the size cap")
    png = png_path.read_bytes()
    if not png.startswith(PNG_MAGIC):
        return _failure("chart.png is not a PNG")
    try:
        meta = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return {
        "ok": True,
        "title": str(meta.get("title", ""))[:200],
        "caption": str(meta.get("caption", ""))[:200],
        "png_base64": base64.b64encode(png).decode(),
    }


async def run_job(code: str, data: list, *, limit: float = JOB_TIMEOUT_SECONDS) -> dict:
    job_dir = tempfile.mkdtemp(prefix="job-")
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(WORKER),
            cwd=job_dir,
            # Empty environment: nothing the code reads from os.environ exists here.
            env={"MPLCONFIGDIR": MPL_CACHE or job_dir, "HOME": job_dir},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limit_worker if os.name == "posix" else None,  # noqa: PLW1509
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(json.dumps({"code": code, "data": data}).encode()), limit
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return _failure(f"chart code exceeded {limit:.0f} s")
        if process.returncode != 0:
            last = (stderr or b"").decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
            return _failure(f"chart code failed: {last[0]}")
        return await asyncio.to_thread(_collect, job_dir)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


async def run(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return JSONResponse(_failure("request too large"), status_code=413)
    try:
        job = json.loads(body)
        code, data = job["code"], job["data"]
    except (ValueError, KeyError, TypeError):
        return JSONResponse(_failure("bad request"), status_code=400)
    if not isinstance(code, str) or len(code) > MAX_CODE_CHARS or not isinstance(data, list) or len(data) > MAX_POINTS:
        return JSONResponse(_failure("bad request"), status_code=400)
    return JSONResponse(await run_job(code, data))


async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[Route("/run", run, methods=["POST"]), Route("/healthz", healthz, methods=["GET"])])


def main() -> None:
    parser = argparse.ArgumentParser(prog="chart_runner")
    parser.add_argument("--uds", help="Unix socket path (local Compose)")
    parser.add_argument("--port", type=int, default=8080, help="TCP port (Dynamic Sessions container)")
    args = parser.parse_args()
    if args.uds:
        os.umask(0o077)
        Path(args.uds).unlink(missing_ok=True)
        uvicorn.run(app, uds=args.uds, log_level="warning")
    else:
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
