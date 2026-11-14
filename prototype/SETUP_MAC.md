# macOS setup and demo launch

The demo uses one cross-platform Python launcher. You do **not** need PowerShell,
Git Bash, WSL, or any project `.sh` file.

## Requirements

- [Homebrew](https://brew.sh/)
- Python 3.10 or newer, preferably 3.12
- Node.js 20 or 22 LTS
- One AI engine: a DeepSeek API key (the on-day engine), or Ollama with enough
  RAM for `qwen3.5:9b`

## First-time setup

First check whether Homebrew is installed:

```bash
brew --version
```

If `brew` is not found, install it using the command on the
[official Homebrew page](https://brew.sh/) and follow the shell-environment
instructions printed by the installer. Reopen Terminal, then install the
prerequisites:

```bash
brew install python@3.12 node@22 ollama
python3 --version
node --version
npm --version
ollama --version
```

`python3 --version` must show 3.10 or newer. If a command is missing, reopen
Terminal after installation and check it again.

`brew` installs the binaries. `run_demo.py` later creates the project-local
Python venv, installs backend/frontend dependencies, and downloads the Ollama
model; do not run `pip install`, `npm install`, or `npm ci` manually unless
troubleshooting.

From the repository root, enter the prototype directory using a path that
matches where **you** cloned the repository:

```bash
cd /path/to/JourneyRelay-Submission/prototype
python3 scripts/run_demo.py --check
python3 scripts/run_demo.py
```

Do not copy an absolute path from another machine. The launcher determines its
repository from the script location, so the checkout can live anywhere.

If the Homebrew `node@22` formula is keg-only, the launcher checks the standard
Apple Silicon and Intel Homebrew paths automatically. These paths are an
optional fallback, not a requirement. If you need to override Node explicitly:

```bash
export NODE_BIN_DIR="/opt/homebrew/opt/node@22/bin"
python3 scripts/run_demo.py
```

For Intel Homebrew, use `/usr/local/opt/node@22/bin` instead.

On the first launch, the Python launcher:

1. creates `prototype/.venv`;
2. installs backend and frontend dependencies;
3. starts Ollama if necessary;
4. downloads `qwen3.5:9b` once, roughly 6.6 GB;
5. warms the model, starts both services, and opens the demo.

Steps 3–4 apply to the local engine only. With the hosted engine selected
(see "AI engine settings" below) the launcher skips Ollama. When Ollama is
absent and `API_LLM_API_KEY` is set, it uses DeepSeek; with neither it exits
with an error. `python3 scripts/run_demo.py --check` shows which engine it
will use.

## Every demo launch

```bash
cd /path/to/JourneyRelay-Submission/prototype
python3 scripts/run_demo.py
```

No `source`, `activate`, Git Bash, WSL or shell script is needed. The launcher
selects `.venv/bin/python` on macOS automatically.

Useful options:

```bash
python3 scripts/run_demo.py --no-browser
python3 scripts/run_demo.py --check
python3 scripts/run_demo.py --stop
```

Keep the launcher terminal open. Press `Ctrl+C` to stop Ollama, FastAPI, and
Next.js together. Runtime logs are under `.runtime/logs/`.

Open `http://localhost:3000/demo` if the browser does not open automatically.

## Phone and tablet

1. Connect the Mac, phone, and tablet to the same Wi-Fi or hotspot.
2. Find the Mac's LAN address:

   ```bash
   ipconfig getifaddr en0
   ```

3. Open `http://<Mac-LAN-IP>:3000` on the phone or tablet.
4. If macOS asks whether Node may accept incoming connections, choose Allow.

Next.js listens on `0.0.0.0`; the backend remains on `127.0.0.1` and is reached
through the same-origin `/api/*` proxy on port 3000.

## AI engine settings

Copy `.env.example` to `prototype/.env`. For the hosted DeepSeek engine, used
on the day:

```text
API_LLM_API_KEY=sk-...
USE_DEEPSEEK_API=true
```

Optional local-engine values:

```text
LOCAL_LLM_MODEL=qwen3.5:9b
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
```

The local endpoint must stay on loopback. The `/demo` header switches engines
live; an API restart returns to the `.env` choice.

## Verification

```bash
cd /path/to/JourneyRelay-Submission/prototype
python3 scripts/run_demo.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/eval_ai.py --engine api     # or --engine local
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Python not found or too old | `brew install python@3.12`, reopen the terminal, confirm `python3 --version` is 3.10+ |
| Node/npm not found | `brew install node@22`; if keg-only, set `NODE_BIN_DIR` as shown above |
| Ollama not found | `brew install ollama`, reopen the terminal, rerun the launcher |
| First model launch looks slow | The first launch downloads about 6.6 GB; later runs only warm the model |
| Port 8000 or 3000 already in use | Stop the old terminal first; otherwise use `--api-port 8100 --web-port 3100` |
| `--stop` says no process is recorded | The port is owned by an older untracked process; close the terminal that launched it |
| Demo shows “本機 AI 未就緒” | Check Ollama is running and the model is pulled (`ollama list`), or switch to the hosted engine on the demo page |
| Hosted engine not ready | Check `API_LLM_API_KEY` in `prototype/.env` and the network, then restart the launcher |
| Phone cannot open the site | Same Wi-Fi, port 3000 reachable, macOS firewall allows Node |
| Frontend styles look stale | Remove `frontend/.next`, stop with the launcher, and restart |
