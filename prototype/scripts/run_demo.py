#!/usr/bin/env python3
"""Cross-platform launcher for the JourneyRelay demo.

This file intentionally uses only the Python standard library. It prepares the
backend virtual environment and frontend dependencies, starts local Ollama when
available, starts FastAPI and Next.js, opens the browser, and cleans up all
child processes when the launcher exits.

Typical usage:
    python scripts/run_demo.py
    python scripts/run_demo.py --no-browser
    python scripts/run_demo.py --stop
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
RUNTIME_DIR = ROOT / ".runtime"
LOG_DIR = RUNTIME_DIR / "logs"
STATE_FILE = RUNTIME_DIR / "processes.json"
STOP_REQUEST_FILE = RUNTIME_DIR / "stop.requested"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"
PACKAGE_LOCK = FRONTEND_DIR / "package-lock.json"
IS_WINDOWS = os.name == "nt"
DEFAULT_API_PORT = 8000
DEFAULT_WEB_PORT = 3000
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
# Text that must appear in a recorded process's command line before --stop kills it.
PROCESS_MARKERS = {"api": "backend.main:app", "frontend": "next", "ollama": "ollama"}

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LauncherError(RuntimeError):
    """An actionable startup error."""


@dataclass
class ManagedProcess:
    role: str
    process: subprocess.Popen
    log_path: Path


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_port: int
    web_port: int
    install: bool
    open_browser: bool


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse the simple KEY=VALUE .env format used by this project."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _build_environment() -> tuple[dict[str, str], dict[str, str]]:
    file_values = _load_env_file(ROOT / ".env")
    env = os.environ.copy()
    for key, value in file_values.items():
        env.setdefault(key, value)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("NEXT_TELEMETRY_DISABLED", "1")
    return env, file_values


def _which(command: str, env: dict[str, str]) -> str | None:
    return shutil.which(command, path=env.get("PATH"))


def _version_major(version_output: str) -> int | None:
    match = re.search(r"v?(\d+)", version_output.strip())
    return int(match.group(1)) if match else None


def _prepare_node(env: dict[str, str]) -> tuple[str, str]:
    configured_bin = env.get("NODE_BIN_DIR", "").strip()
    candidates = [
        configured_bin,
        "/opt/homebrew/opt/node@22/bin",
        "/usr/local/opt/node@22/bin",
    ]
    for candidate in candidates:
        if candidate and (
            (Path(candidate) / "node").is_file()
            or (Path(candidate) / "node.exe").is_file()
        ):
            env["PATH"] = f"{candidate}{os.pathsep}{env.get('PATH', '')}"
            break

    node = _which("node", env)
    npm = _which("npm", env)
    if not node or not npm:
        raise LauncherError(
            "Node.js 20/22 and npm are required. Install Node.js, reopen the "
            "terminal, then run this command again."
        )

    result = subprocess.run(
        [node, "--version"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    node_version = result.stdout.strip()
    major = _version_major(node_version)
    if major is None or major < 20:
        raise LauncherError(f"Node.js 20/22 is required; found {node_version}.")
    if major not in {20, 22}:
        print(
            f"! Node.js {node_version} found. The project is tested on 20/22; "
            "continuing because the installed version is newer."
        )
    return node, npm


def _venv_python() -> Path:
    if IS_WINDOWS:
        candidates = [
            ROOT / ".venv" / "Scripts" / "python.exe",
            ROOT / ".venv" / "Scripts" / "python",
        ]
    else:
        candidates = [ROOT / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LauncherError(
        "The Python virtual environment is incomplete. Remove .venv and run "
        "the launcher again."
    )


def _prepare_backend(env: dict[str, str], install: bool) -> Path:
    if sys.version_info < (3, 10):
        raise LauncherError(
            f"Python 3.10+ is required; this launcher is using {sys.version.split()[0]}."
        )

    if not (ROOT / ".venv").exists():
        print("== Creating Python virtual environment ==")
        subprocess.run(
            [sys.executable, "-m", "venv", str(ROOT / ".venv")],
            cwd=ROOT,
            env=env,
            check=True,
        )

    python = _venv_python()
    version = subprocess.run(
        [
            str(python),
            "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:3])))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()
    if _version_major(version) is None or tuple(map(int, version.split(".")[:2])) < (
        3,
        10,
    ):
        raise LauncherError(
            f"The existing .venv uses Python {version}. Remove .venv and rerun "
            "the launcher with Python 3.10+."
        )

    if install:
        print("== Checking backend dependencies ==")
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--quiet",
                "-r",
                str(REQUIREMENTS),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
    return python


def _npm_command(npm: str, args: Sequence[str]) -> tuple[str | list[str], bool]:
    if not IS_WINDOWS:
        return [npm, *args], False

    # npm is a .batch file on Windows; CreateProcess cannot run it directly,
    # so hand the quoted command line to the shell (cmd.exe) instead.
    command = subprocess.list2cmdline([npm] + list(args))
    return command, True


def _prepare_frontend(
    env: dict[str, str],
    *,
    node: str,
    npm: str,
    install: bool,
) -> list[str]:
    node_modules = FRONTEND_DIR / "node_modules"
    next_cli = node_modules / "next" / "dist" / "bin" / "next"
    marker = node_modules / ".package-lock.json"
    install_needed = not next_cli.is_file() or not marker.is_file()
    if PACKAGE_LOCK.is_file() and marker.is_file():
        install_needed = (
            install_needed or PACKAGE_LOCK.stat().st_mtime > marker.stat().st_mtime
        )

    if install:
        if install_needed:
            print("== Installing frontend dependencies ==")
            npm_command, use_shell = _npm_command(
                npm,
                ["ci", "--no-audit", "--no-fund"],
            )
            subprocess.run(
                npm_command,
                cwd=FRONTEND_DIR,
                env=env,
                check=True,
                shell=use_shell,
            )
    elif not next_cli.is_file():
        raise LauncherError(
            "frontend/node_modules is missing. Run the launcher without "
            "--no-install once."
        )
    if not next_cli.is_file():
        raise LauncherError(
            "Next.js is not installed in frontend/node_modules. Run `npm ci` "
            "in prototype/frontend, then retry."
        )
    return [node, str(next_cli), "dev", "-H", "0.0.0.0"]


def _validate_loopback_url(raw: str) -> str:
    value = (raw or DEFAULT_BASE_URL).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise LauncherError("LOCAL_LLM_BASE_URL is not a valid URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LauncherError("LOCAL_LLM_BASE_URL must be a plain HTTP(S) origin.")
    host = parsed.hostname.lower()
    if host != "localhost":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise LauncherError("LOCAL_LLM_BASE_URL must use a loopback host.")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _json_request(
    url: str,
    *,
    payload: dict | None = None,
    timeout: float = 2.0,
) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with OPENER.open(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _ensure_port_free(port: int, label: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise LauncherError(
                f"{label} port {port} is already in use. Stop the old process, "
                f"run this launcher with --stop, or choose another port."
            )


def _write_state(managed: list[ManagedProcess]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not managed:
        STATE_FILE.unlink(missing_ok=True)
        return
    payload = {
        "processes": [
            {
                "pid": item.process.pid,
                "role": item.role,
                "marker": PROCESS_MARKERS.get(item.role, item.role),
                "log_path": str(item.log_path),
            }
            for item in managed
            if item.process.poll() is None
        ]
    }
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def _terminate_pid(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return

    try:
        killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return

    time.sleep(0.3)

    try:
        killpg(pid, 0)
    except (ProcessLookupError, PermissionError):
        return

    try:
        killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _stop_managed(managed: list[ManagedProcess]) -> None:
    for item in reversed(managed):
        try:
            if item.process.poll() is None:
                _terminate_pid(item.process.pid)
            try:
                item.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        except (OSError, subprocess.SubprocessError):
            # Cleanup must continue for the remaining child processes.
            pass
    managed.clear()
    _write_state(managed)
    STOP_REQUEST_FILE.unlink(missing_ok=True)


def _command_line(pid: int) -> str | None:
    """Return the running process's command line, or None if it is gone."""
    if IS_WINDOWS:
        command = [
            "powershell", "-NoProfile", "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
        ]
    else:
        command = ["ps", "-p", str(pid), "-o", "command="]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _stop_from_state() -> int:
    if not STATE_FILE.is_file():
        print("No launcher-managed demo processes are recorded.")
        return 0
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LauncherError(f"Cannot read {STATE_FILE}: {exc}") from exc
    entries = payload.get("processes", [])
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STOP_REQUEST_FILE.write_text("stop\n", encoding="utf-8")
    for entry in reversed(entries):
        try:
            pid = int(entry["pid"])
        except (KeyError, TypeError, ValueError):
            continue
        role = entry.get("role", "process")
        # The PID may belong to another program by now (crash, reboot), so
        # only stop it if its command line still looks like ours.
        marker = str(entry.get("marker") or "").lower()
        command_line = _command_line(pid)
        if not marker or command_line is None or marker not in command_line.lower():
            print(f"Skipping stale {role} PID {pid} (no longer a launcher process).")
            continue
        print(f"Stopping launcher-managed {role} PID {pid}...")
        _terminate_pid(pid)
    STATE_FILE.unlink(missing_ok=True)
    print("Demo processes stopped.")
    return 0


def _spawn(
    managed: list[ManagedProcess],
    *,
    role: str,
    command: Sequence[str],
    cwd: Path,
    env: dict[str, str],
) -> ManagedProcess:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{role}.log"
    with log_path.open("wb") as log:
        log.write(
            f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting {role} ===\n".encode()
        )
        kwargs: dict = {
            "cwd": cwd,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
        }
        if IS_WINDOWS:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(list(command), **kwargs)
    item = ManagedProcess(role=role, process=process, log_path=log_path)
    managed.append(item)
    _write_state(managed)
    return item


def _tail_log(path: Path, lines: int = 18) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(log unavailable)"
    return "\n".join(content[-lines:])


def _wait_http(
    url: str,
    *,
    timeout: float,
    process: ManagedProcess,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise LauncherError(
                f"{process.role} exited before becoming ready.\n"
                f"{_tail_log(process.log_path)}"
            )
        try:
            with OPENER.open(url, timeout=1.0) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(0.4)
    raise LauncherError(
        f"{process.role} did not become ready within {timeout:.0f}s. "
        f"Last error: {last_error}\n{_tail_log(process.log_path)}"
    )


def _ollama_tags(base_url: str, timeout: float = 1.5) -> set[str]:
    data = _json_request(f"{base_url}/api/tags", timeout=timeout)
    return {
        item.get("name", "")
        for item in data.get("models", [])
        if isinstance(item, dict)
    }


def _api_key_set(env: dict[str, str]) -> bool:
    return bool(env.get("API_LLM_API_KEY", "").strip())


def _resolve_engine(env: dict[str, str]) -> str:
    """The engine the API should start with: "local" or "api".

    USE_DEEPSEEK_API=true selects the hosted API. A local choice moves to the
    hosted API when Ollama is not installed but API_LLM_API_KEY is set.
    """
    use_api = env.get("USE_DEEPSEEK_API", "").strip().lower() in {"1", "true", "yes", "on"}
    if use_api or (not _which("ollama", env) and _api_key_set(env)):
        return "api"
    return "local"


def _prepare_engine(
    env: dict[str, str],
    settings: Settings,
    managed: list[ManagedProcess],
) -> str:
    """Prepare the selected engine and pass the choice to the API process."""
    engine = _resolve_engine(env)
    if engine == "api":
        if not _api_key_set(env):
            raise LauncherError(
                "The hosted engine needs API_LLM_API_KEY in .env (DeepSeek by default)."
            )
        print(f"== AI mode: hosted API ({env.get('API_LLM_MODEL') or 'DeepSeek default model'}) ==")
    else:
        _prepare_ollama(env, settings, managed)
    env["USE_DEEPSEEK_API"] = "true" if engine == "api" else "false"
    return engine


def _prepare_ollama(
    env: dict[str, str],
    settings: Settings,
    managed: list[ManagedProcess] | None = None,
) -> str:
    """Ensure the local engine can serve; returns "local".

    Any failure raises LauncherError — the launcher fails honestly instead of
    substituting a deterministic mock.
    """
    if managed is None:
        managed = []
    ollama = _which("ollama", env)
    if not ollama:
        raise LauncherError(
            "Ollama is required for the local engine. Install Ollama, or set "
            "API_LLM_API_KEY in .env to use the hosted DeepSeek engine."
        )

    base_url = _validate_loopback_url(settings.base_url)

    try:
        tags = _ollama_tags(base_url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        print("== Starting Ollama ==")
        ollama_env = env.copy()
        ollama_env.update(
            {
                "OLLAMA_HOST": urlsplit(base_url).netloc,
                "OLLAMA_NO_CLOUD": "1",
                "OLLAMA_FLASH_ATTENTION": "1",
                "OLLAMA_KV_CACHE_TYPE": "q8_0",
            }
        )
        ollama_process = _spawn(
            managed,
            role="ollama",
            command=[ollama, "serve"],
            cwd=ROOT,
            env=ollama_env,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if ollama_process.process.poll() is not None:
                break
            try:
                tags = _ollama_tags(base_url)
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                time.sleep(0.5)
        else:
            tags = set()
        if ollama_process.process.poll() is not None:
            tags = set()
        if not tags and not (
            ollama_process.process.poll() is None and _ollama_ready(base_url)
        ):
            raise LauncherError(
                f"Ollama did not start.\n{_tail_log(ollama_process.log_path)}"
            )

    if (
        settings.model not in tags
        and f"{settings.model}:latest" not in tags
    ):
        print(
            f"== Downloading {settings.model} ==\n"
            "This happens only on first use and may take several minutes."
        )
        result = subprocess.run(
            [ollama, "pull", settings.model],
            cwd=ROOT,
            env={**env, "OLLAMA_HOST": urlsplit(base_url).netloc},
            check=False,
        )
        if result.returncode != 0:
            raise LauncherError(f"Could not install Ollama model {settings.model}.")

    try:
        _json_request(
            f"{base_url}/api/chat",
            payload={
                "model": settings.model,
                "messages": [{"role": "user", "content": "Reply with READY"}],
                "stream": False,
                "options": {"num_predict": 8, "temperature": 0},
            },
            timeout=45,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LauncherError(f"Ollama model warm-up failed: {exc}") from exc

    print(f"== AI mode: local Ollama ({settings.model}) ==")
    env["LOCAL_LLM_BASE_URL"] = base_url
    env["LOCAL_LLM_MODEL"] = settings.model
    return "local"


def _ollama_ready(base_url: str) -> bool:
    try:
        _ollama_tags(base_url)
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> None:
    try:
        subprocess.run(list(command), cwd=cwd, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise LauncherError(
            f"Command failed with exit code {exc.returncode}: {' '.join(command)}"
        ) from exc


def _print_check(env: dict[str, str], settings: Settings, node: str, npm: str) -> None:
    if sys.version_info < (3, 10):
        raise LauncherError(
            f"Python 3.10+ is required; this launcher is using {sys.version.split()[0]}."
        )
    print(f"OS             : {sys.platform}")
    print(f"Python         : {sys.version.split()[0]}")
    print(
        f"Node.js        : {subprocess.run([node, '--version'], capture_output=True, text=True, env=env).stdout.strip()}"
    )
    print(f"npm            : {npm}")
    venv = ROOT / ".venv"
    if venv.exists():
        try:
            venv_version = subprocess.run(
                [str(_venv_python()), "--version"],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            ).stdout.strip()
        except LauncherError:
            print("Backend venv   : incomplete")
        else:
            print(f"Backend venv   : {venv_version}")
            match = re.search(r"(\d+)\.(\d+)", venv_version)
            if not match or (int(match.group(1)), int(match.group(2))) < (3, 10):
                raise LauncherError(
                    f"The existing .venv uses {venv_version or 'an unknown Python'}. "
                    "Remove .venv and rerun the launcher with Python 3.10+."
                )
    else:
        print("Backend venv   : will be created")
    ollama = _which("ollama", env)
    print(f"Ollama         : {ollama or 'not found'}")
    engine = _resolve_engine(env)
    print(f"AI engine      : {engine} (switchable at /api/ai/engine)")
    # A warning, not a failure: CI checks prerequisites without any AI engine.
    if engine == "api" and not _api_key_set(env):
        print("! The hosted engine needs API_LLM_API_KEY in .env; the launch will stop.")
    elif engine == "local" and not ollama:
        print("! Install Ollama or set API_LLM_API_KEY in .env; the launch will stop.")
    print(f"API / Web port : {settings.api_port} / {settings.web_port}")
    print("Launcher check passed.")


def _supervise(managed: list[ManagedProcess]) -> None:
    print("Demo is running. Press Ctrl+C to stop all services.")
    while True:
        if STOP_REQUEST_FILE.is_file():
            print("Stop requested; shutting down the demo.")
            return
        for item in managed:
            if item.process.poll() is not None:
                raise LauncherError(
                    f"{item.role} stopped unexpectedly "
                    f"(exit code {item.process.returncode}).\n"
                    f"{_tail_log(item.log_path)}"
                )
        time.sleep(0.75)


def _run(args: argparse.Namespace) -> int:
    env, _file_values = _build_environment()
    settings = Settings(
        base_url=env.get("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL),
        model=env.get("LOCAL_LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        api_port=args.api_port,
        web_port=args.web_port,
        install=not args.no_install,
        open_browser=not args.no_browser,
    )

    node, npm = _prepare_node(env)
    if args.check:
        _print_check(env, settings, node, npm)
        return 0

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STOP_REQUEST_FILE.unlink(missing_ok=True)
    _ensure_port_free(settings.api_port, "API")
    _ensure_port_free(settings.web_port, "Frontend")

    managed: list[ManagedProcess] = []
    try:
        python = _prepare_backend(env, settings.install)
        next_command = _prepare_frontend(
            env,
            node=node,
            npm=npm,
            install=settings.install,
        )

        print("== Seeding synthetic demo data ==")
        _run_checked([str(python), "-m", "backend.seed"], cwd=ROOT, env=env)

        ai_mode = _prepare_engine(env, settings, managed)

        print(f"== Starting API on {settings.api_port} ==")
        api = _spawn(
            managed,
            role="api",
            command=[
                str(python),
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(settings.api_port),
            ],
            cwd=ROOT,
            env=env,
        )
        _wait_http(
            f"http://127.0.0.1:{settings.api_port}/api/health",
            timeout=30,
            process=api,
        )

        frontend_env = env.copy()
        frontend_env["API_ORIGIN"] = f"http://127.0.0.1:{settings.api_port}"
        print(f"== Starting frontend on {settings.web_port} ==")
        web = _spawn(
            managed,
            role="frontend",
            command=[
                *next_command,
                "-p",
                str(settings.web_port),
            ],
            cwd=FRONTEND_DIR,
            env=frontend_env,
        )
        _wait_http(
            f"http://127.0.0.1:{settings.web_port}/",
            timeout=120,
            process=web,
        )

        demo_url = f"http://127.0.0.1:{settings.web_port}/demo"
        print()
        print(f"API  : http://127.0.0.1:{settings.api_port}")
        print(f"Demo : {demo_url}")
        print(f"AI   : {ai_mode}")
        print(f"Logs : {LOG_DIR}")
        if args.smoke:
            print("Launcher smoke test passed; stopping services.")
            return 0
        if settings.open_browser:
            webbrowser.open(demo_url)
        _supervise(managed)
    except KeyboardInterrupt:
        print("\nStopping demo...")
        _stop_managed(managed)
        return 0
    except (LauncherError, OSError, subprocess.SubprocessError) as exc:
        _stop_managed(managed)
        raise LauncherError(str(exc)) from exc
    finally:
        if managed:
            _stop_managed(managed)
    return 0


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and launch the complete JourneyRelay demo.",
        epilog=(
            "Examples:\n"
            "  python scripts/run_demo.py\n"
            "  python scripts/run_demo.py --no-browser --api-port 8100\n"
            "  python scripts/run_demo.py --stop"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api-port", type=_port, default=DEFAULT_API_PORT)
    parser.add_argument("--web-port", type=_port, default=DEFAULT_WEB_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--check", action="store_true", help="check prerequisites only")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="start both services, verify their health, then stop",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop processes recorded by a previous launcher run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = _parser().parse_args(argv)
    if args.stop:
        try:
            return _stop_from_state()
        except LauncherError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    def _handle_term(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_term)
    try:
        return _run(args)
    except LauncherError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
