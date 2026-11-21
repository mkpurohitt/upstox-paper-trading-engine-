"""One-command local launcher (Windows, macOS, Linux).

    uv run python scripts/dev.py            # API on 127.0.0.1:8000 + web on localhost:3000
    uv run python scripts/dev.py --reset    # wipe the local SQLite database first
    uv run python scripts/dev.py --env-db   # use DATABASE_URL / REDIS_URL from .env (e.g. Postgres) instead of SQLite

It creates ``.env`` from ``.env.example`` if missing, installs JavaScript dependencies on first run, seeds the
database (idempotent), starts the API and the web app, waits until both answer, and stops both on Ctrl+C.
Everything runs offline with mock data unless you configure keys in ``.env``.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "apps" / "api"
IS_WINDOWS = os.name == "nt"
LITE_DB = "sqlite+aiosqlite:///./var/algo.db"


def say(msg: str) -> None:
    print(f"[dev] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\n[dev] ERROR: {msg}\n", file=sys.stderr, flush=True)
    sys.exit(1)


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_http(url: str, timeout: float, proc: subprocess.Popen[bytes] | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - fixed local URL
                if r.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def spawn(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    kwargs: dict = {"cwd": str(cwd), "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)  # noqa: S603 - fixed commands


def stop(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            # Kill the whole tree (pnpm -> node -> next-server; uvicorn reloader -> worker).
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)  # noqa: S603,S607
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run AlgoDesk locally (API + web).")
    ap.add_argument("--reset", action="store_true", help="delete the local SQLite database before starting")
    ap.add_argument("--env-db", action="store_true", help="use DATABASE_URL/REDIS_URL from .env instead of SQLite")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=3000)
    ap.add_argument("--no-reload", action="store_true", help="run the API without auto-reload")
    ap.add_argument("--api-only", action="store_true", help="start only the API")
    args = ap.parse_args()

    if sys.version_info < (3, 12):  # noqa: UP036 - someone may run it with an old system Python instead of uv
        fail(f"Python 3.12+ is required (found {sys.version.split()[0]}). Run this with: uv run python scripts/dev.py")

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        fail("Python dependencies are missing. From the repository root run:  uv sync   then:  uv run python scripts/dev.py")

    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and example.exists():
        shutil.copyfile(example, env_file)
        say("created .env from .env.example (edit it later to add API keys)")

    pnpm = shutil.which("pnpm")
    if not args.api_only:
        if pnpm is None:
            fail("pnpm was not found. Install Node.js 22 LTS, then run:  npm install -g pnpm@10")
        if not (ROOT / "node_modules").exists() or not (ROOT / "apps" / "web" / "node_modules").exists():
            say("installing JavaScript dependencies (first run only)...")
            if subprocess.run([pnpm, "install"], cwd=ROOT, check=False).returncode != 0:  # noqa: S603
                fail("pnpm install failed (see the output above)")

    for port, name in ((args.api_port, "API"), (args.web_port, "web")):
        if name == "web" and args.api_only:
            continue
        if port_busy(port):
            fail(
                f"port {port} ({name}) is already in use. Close the other terminal running AlgoDesk "
                f"(or the program using that port) and try again."
            )

    (ROOT / "var").mkdir(exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["LOG_JSON"] = "false"
    env.setdefault("EMBEDDED_WORKERS", "true")
    if not args.env_db:
        env["DATABASE_URL"] = LITE_DB
        env["REDIS_URL"] = "none"  # in-process bus/cache
        env["EMBEDDED_WORKERS"] = "true"
        if args.reset:
            for suffix in ("", "-wal", "-shm"):
                (ROOT / "var" / f"algo.db{suffix}").unlink(missing_ok=True)
            say("local database reset")
    api_url = f"http://127.0.0.1:{args.api_port}"
    env["API_INTERNAL_URL"] = api_url
    env["NEXT_PUBLIC_WS_URL"] = f"ws://127.0.0.1:{args.api_port}/ws"

    say("preparing the database (migrations/tables + demo data)...")
    seed = subprocess.run([sys.executable, "-m", "app.seed"], cwd=API_DIR, env=env, check=False)
    if seed.returncode != 0:
        fail("database seed failed (see the error above)")

    api_cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.api_port)]
    if not args.no_reload:
        api_cmd += ["--reload", "--reload-dir", str(ROOT / "apps" / "api"), "--reload-dir", str(ROOT / "services"),
                    "--reload-dir", str(ROOT / "packages")]
    api = web = None
    try:
        say(f"starting API on {api_url} ...")
        api = spawn(api_cmd, API_DIR, env)
        if not wait_http(f"{api_url}/api/health", 120, api):
            fail("the API did not start (see the error above)")
        say("API is up")
        if not args.api_only:
            say(f"starting web on http://localhost:{args.web_port} (first page load compiles for ~20-60 s) ...")
            assert pnpm is not None
            subprocess.run([pnpm, "--filter", "@algo/web", "run", "monaco"], cwd=ROOT, env=env, check=False)  # noqa: S603
            web = spawn([pnpm, "--filter", "@algo/web", "exec", "next", "dev", "-p", str(args.web_port)], ROOT, env)
            if not wait_http(f"http://127.0.0.1:{args.web_port}/login", 240, web):
                fail("the web app did not start (see the error above)")
        print(
            "\n"
            "  ============================================================\n"
            f"   AlgoDesk is running:  http://localhost:{args.web_port}\n"
            "   Click 'Try the demo account', or log in as\n"
            "     demo@algodesk.in / demo12345   (admin: admin@algodesk.in / admin12345)\n"
            f"   API docs:             {api_url}/docs\n"
            "   Press Ctrl+C to stop.\n"
            "  ============================================================\n",
            flush=True,
        )
        while True:
            for proc, name in ((api, "API"), (web, "web")):
                if proc is not None and proc.poll() is not None:
                    fail(f"the {name} process exited (code {proc.returncode}); see the output above")
            time.sleep(1)
    except KeyboardInterrupt:
        say("stopping...")
    finally:
        stop(web)
        stop(api)


if __name__ == "__main__":
    main()
