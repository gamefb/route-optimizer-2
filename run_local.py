#!/usr/bin/env python3
"""Run Route Planner on this computer, without Docker.

    python run_local.py              set up if needed, start the app, open the browser
    python run_local.py --port 9000  use another port
    python run_local.py --check      start it, confirm it answers, and stop (used by the automated checks)

The first run takes a few minutes: it creates a Python environment in .venv,
installs the app's packages, and builds the interface and the help pages.
Later runs start in a few seconds and only redo a step whose inputs changed.

Everything the app keeps is in the "local-data" folder: the database, the
prepared map and the daily backup files. The app listens on this computer
only (127.0.0.1) unless you pass --host.

Needs Python 3.12, 3.13 or 3.14 (64-bit). Building the interface also needs
Node.js 22 or newer; if frontend/dist is already built, Node.js is not needed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, FRONTEND, DOCS = ROOT / "backend", ROOT / "frontend", ROOT / "docs"
VENV = ROOT / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
PYTHON = BIN / ("python.exe" if os.name == "nt" else "python")
BUILT = ROOT / ".local-build"  # what was built from what, so unchanged steps are skipped
HELP_SITE = BUILT / "help"
PYTHON_VERSIONS = ((3, 12), (3, 13), (3, 14))  # the routing and optimizer packages ship ready-built for these


def say(message: str) -> None:
    print(f"[route planner] {message}", flush=True)


def stop(message: str) -> None:
    sys.exit(f"\n[route planner] {message}\n")


def run(command: list[str], cwd: Path, what: str, **settings: str) -> None:
    say(what)
    if subprocess.run(command, cwd=cwd, env={**os.environ, **settings}).returncode != 0:
        stop(f"That step failed: {what}\nThe messages above say why. Fix that and run this again.")


def fingerprint(*paths: Path) -> str:
    """Changes whenever any of these files (or any file under these folders) changes."""
    digest = hashlib.sha256()
    for path in paths:
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for f in files:
            digest.update(str(f.relative_to(ROOT)).encode())
            digest.update(f.read_bytes())
    return digest.hexdigest()


def stale(step: str, mark: str) -> bool:
    record = BUILT / f"{step}.txt"
    return not record.exists() or record.read_text() != mark


def done(step: str, mark: str) -> None:
    BUILT.mkdir(exist_ok=True)
    (BUILT / f"{step}.txt").write_text(mark)


# ------------------------------------------------------------------ set-up


def check_python() -> None:
    if sys.version_info[:2] not in PYTHON_VERSIONS or sys.maxsize < 2**32:
        wanted = ", ".join(f"{a}.{b}" for a, b in PYTHON_VERSIONS)
        stop(
            f"This needs 64-bit Python {wanted}; you are running {sys.version.split()[0]}.\n"
            "Install Python 3.13 from https://www.python.org/downloads/ and run this again with it."
        )


def install_packages() -> None:
    requirements = [BACKEND / "requirements.txt", DOCS / "requirements.txt"]
    mark = fingerprint(*requirements) + sys.version
    if PYTHON.exists() and not stale("packages", mark):
        return
    if not PYTHON.exists():
        run([sys.executable, "-m", "venv", str(VENV)], ROOT, "Creating a Python environment in .venv")
    install = [str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    for r in requirements:
        install += ["-r", str(r)]
    run(install, ROOT, "Installing the app's Python packages (a few minutes the first time)")
    done("packages", mark)


def build_interface() -> None:
    dist = FRONTEND / "dist"
    sources = [FRONTEND / name for name in ("src", "index.html", "package.json", "package-lock.json", "vite.config.ts")]
    mark = fingerprint(*sources)
    if (dist / "index.html").exists() and not stale("interface", mark):
        return
    npm = shutil.which("npm")
    if npm is None:
        if (dist / "index.html").exists():
            say("Node.js was not found, so the interface was not rebuilt. Using the copy already in frontend/dist.")
            return
        stop(
            "The interface has not been built yet, and building it needs Node.js.\n"
            "Install Node.js 22 (LTS) from https://nodejs.org/ and run this again."
        )
    run([npm, "ci", "--no-audit", "--no-fund"], FRONTEND, "Installing the interface's build tools")
    run([npm, "run", "build"], FRONTEND, "Building the interface")
    done("interface", mark)


def build_help() -> None:
    mark = fingerprint(DOCS, ROOT / "mkdocs.yml")
    if (HELP_SITE / "index.html").exists() and not stale("help", mark):
        return
    command = [str(PYTHON), "-m", "mkdocs", "build", "--quiet", "--clean", "--site-dir", str(HELP_SITE)]
    run(command, ROOT, "Building the help pages", SITE_URL="http://localhost/help/")  # the app serves them at /help/
    done("help", mark)


# --------------------------------------------------------------------- run


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1" if host in ("0.0.0.0", "") else host, port)) != 0


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def app_environment(data: Path) -> dict[str, str]:
    for folder in (data, data / "map", data / "backups"):
        folder.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        DATABASE_URL="sqlite:///" + (data / "routeplanner.db").as_posix(),
        MAP_DATA_DIR=str(data / "map"),
        BACKUP_DIR=str(data / "backups"),
        WEB_DIR=str(FRONTEND / "dist"),
        HELP_DIR=str(HELP_SITE),
        PATH=str(BIN) + os.pathsep + env.get("PATH", ""),
    )
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Route Planner on this computer, without Docker.")
    parser.add_argument("--port", type=int, default=8080, help="port to serve on (default 8080)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on. The default, 127.0.0.1, is this computer only. "
        "0.0.0.0 lets other computers on your network open the app; there is no login, so only do that on a network you trust.",
    )
    parser.add_argument("--data", type=Path, default=ROOT / "local-data", help="where the database, map and backups are kept")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--check", action="store_true", help="start, confirm the app answers, then stop")
    args = parser.parse_args()

    check_python()
    install_packages()
    build_interface()
    build_help()
    if not port_is_free(args.host, args.port):
        stop(
            f"Something is already using port {args.port} (perhaps the Docker version of this app, or another copy).\n"
            f"Close it, or pick another port:  python run_local.py --port {args.port + 1}"
        )

    address = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    command = [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port), "--workers", "1"]
    if not args.check:
        command += ["--log-level", "warning"]
    server = subprocess.Popen(command, cwd=BACKEND, env=app_environment(args.data.resolve()))
    try:
        for _ in range(120):
            if answers(f"{address}/api/health") or server.poll() is not None:
                break
            time.sleep(0.5)
        if server.poll() is not None or not answers(f"{address}/api/health"):
            stop("The app did not start. The messages above say why.")
        if args.check:
            for page in ("/", "/help/"):
                if not answers(address + page):
                    stop(f"The app started but {address}{page} did not answer.")
            say(f"Check passed: the app, the interface and the help pages all answer at {address}")
            return
        say(f"Route Planner is running at {address}   (help: {address}/help/)")
        say("Leave this window open while you use it. Press Ctrl+C here to stop.")
        if not args.no_browser:
            webbrowser.open(address)
        server.wait()
    except KeyboardInterrupt:
        say("Stopping.")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
