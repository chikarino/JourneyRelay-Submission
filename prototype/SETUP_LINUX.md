# Linux setup and demo launch

The launcher is a normal Python program and does not require Bash project
scripts, PowerShell, WSL, or manual virtual-environment activation.

## Requirements

- Python 3.10 or newer
- Node.js 20/22 LTS with npm
- One AI engine: a DeepSeek API key (the on-day engine), or Ollama for the
  local engine

Install Python and npm with your distribution's package manager. Install Node
from the [official Node.js downloads](https://nodejs.org/en/download) if the
distribution package is older than Node 20. Install Ollama from the
[official download page](https://ollama.com/download) for the local engine,
or put `API_LLM_API_KEY=sk-...` (and `USE_DEEPSEEK_API=true`) in
`prototype/.env` for the hosted engine.

## Verify prerequisites

```bash
python3 --version
node --version
npm --version
ollama --version
```

`python3 --version` must show 3.10 or newer.

## First-time launch

Use the directory where **you** cloned the repository:

```bash
cd /path/to/JourneyRelay-Submission/prototype
python3 scripts/run_demo.py --check
python3 scripts/run_demo.py
```

The repository has no user-specific hardcoded path. The launcher resolves
`.venv`, backend, frontend, logs, and runtime state relative to
`scripts/run_demo.py`.

On first launch it creates `.venv`, installs missing Python/npm dependencies,
prepares Ollama when available, starts both services, health-checks them, and
opens the demo. The first local-model download is roughly 6.6 GB; the hosted
engine needs no download.

## Every demo launch

```bash
cd /path/to/JourneyRelay-Submission/prototype
python3 scripts/run_demo.py
```

For a server, container shell, or machine without a desktop browser:

```bash
python3 scripts/run_demo.py --no-browser
```

Other useful options:

```bash
python3 scripts/run_demo.py --check
python3 scripts/run_demo.py --stop
```

Keep the launcher terminal open. Press `Ctrl+C` to stop FastAPI, Next.js, and
Ollama together. Logs are under `.runtime/logs/`.

## Phone and tablet

1. Connect the laptop, phone, and tablet to the same network.
2. Find a private LAN IPv4 address:

   ```bash
   hostname -I
   ```

3. Open `http://<laptop-LAN-IP>:3000` on the phone or tablet.
4. Allow inbound TCP port 3000 through the host firewall if required.

Next.js listens on `0.0.0.0`; FastAPI remains on `127.0.0.1` and is reached
through the frontend's `/api/*` proxy.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Python is older than 3.10 | Install Python 3.10+ and rerun with `python3` |
| Node/npm not found | Install Node.js 20/22 and reopen the terminal |
| Ollama not found or too slow | Install Ollama, or set `API_LLM_API_KEY` in `prototype/.env` for the hosted engine |
| Port 8000 or 3000 is in use | Stop the old terminal first; otherwise use `--api-port 8100 --web-port 3100` |
| `--stop` says no process is recorded | The port is owned by an older untracked process; close that process first |
| Session has no GUI browser | Add `--no-browser` and open the printed URL from another device |
| Launcher failed | Inspect `.runtime/logs/api.log`, `frontend.log`, and `ollama.log` |
