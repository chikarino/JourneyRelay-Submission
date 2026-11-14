# Windows setup and demo launch

You can launch the demo from **PowerShell or Command Prompt**. The project does
not require Git Bash, WSL, or a PowerShell script.

## Requirements

- [Python 3.12](https://www.python.org/downloads/windows/) — enable
  “Add Python to PATH” during installation
- [Node.js 22 LTS](https://nodejs.org/en/download) with npm
- One AI engine: a DeepSeek API key (the on-day engine), or
  [Ollama for Windows](https://ollama.com/download) for the local engine

## Install Python

1. Open the [Python Windows downloads](https://www.python.org/downloads/windows/)
   page.
2. Download the latest **Python 3.12.x Windows installer** that matches the PC
   architecture (usually 64-bit x64; choose ARM64 on an ARM Windows PC).
3. Run the installer and enable **Add python.exe to PATH** before choosing
   Install.
4. Keep the standard optional features enabled.
5. Open a new PowerShell window and run:

   ```powershell
   python --version
   py --version
   ```

Either command should show Python 3.10 or newer. Python Launcher (`py`) is
installed together with the official Windows installer.

## Install Node.js and npm

1. Open the [Node.js download page](https://nodejs.org/en/download).
2. Select the **Windows Installer (.msi)** for the **22.x LTS** release matching
   the PC architecture. If it is not on the main page, use the archive or
   previous-releases link.
3. Run the installer with the default npm option enabled.
4. Open a new PowerShell window and verify:

   ```powershell
   node --version
   npm --version
   ```

`node --version` should start with `v22`. If a newer LTS is installed, the
launcher accepts it but prints a warning because the project is tested on 20/22.

## Install Ollama (optional)

Ollama runs the local engine. To use the hosted DeepSeek engine instead, put
`API_LLM_API_KEY=sk-...` (and `USE_DEEPSEEK_API=true` to start with it) in
`prototype\.env`. With neither, the launcher exits with an error.

1. Open the [Ollama download page](https://ollama.com/download).
2. Download and run the **Windows** installer.
3. Allow the installer to finish, then launch Ollama once from the Start menu.
4. Open a new PowerShell window and verify:

   ```powershell
   ollama --version
   ```

Do not manually download the model in advance. On first demo launch,
`run_demo.py` starts Ollama if necessary and pulls `qwen3.5:9b` automatically.

## Verify prerequisites

```powershell
python --version
node --version
npm --version
ollama --version
```

If `python` is unavailable but Windows Python Launcher is installed:

```powershell
py --version
```

`python --version` or `py --version` must show 3.10 or newer.

## First-time launch

Open PowerShell and enter the prototype directory using the location where
**you** cloned the repository:

```powershell
cd C:\path\to\JourneyRelay-Submission\prototype
py scripts\run_demo.py --check
py scripts\run_demo.py
```

If `py` is unavailable, replace it with `python`:

```powershell
python scripts\run_demo.py
```

Do not copy an absolute path from another machine. The launcher works with any
checkout location and resolves the repository from `scripts\run_demo.py`.

No activation step is needed. The launcher creates the Windows venv under
`.venv\Scripts\`, installs dependencies, starts Ollama when available, starts
both services, and opens the browser.

On first use, the local model download is roughly 6.6 GB; the hosted engine
needs no download. `py scripts\run_demo.py --check` shows which engine the
launcher will use.

## Every demo launch

```powershell
cd C:\path\to\JourneyRelay-Submission\prototype
py scripts\run_demo.py
```

Useful options:

```powershell
py scripts\run_demo.py --no-browser
py scripts\run_demo.py --check
py scripts\run_demo.py --stop
```

Press `Ctrl+C` in the launcher window to stop Ollama, FastAPI, and Next.js.
Runtime logs are under `.runtime\logs\`.

Open `http://localhost:3000/demo` if the browser does not open automatically.

## Phone and tablet

1. Connect the Windows laptop, phone, and tablet to the same network.
2. Run `ipconfig` and use the laptop's IPv4 address.
3. Open `http://<laptop-IPv4>:3000` on the phone or tablet.
4. Allow Node.js through Windows Defender Firewall for private networks when
   prompted.

## Verification

```powershell
cd C:\path\to\JourneyRelay-Submission\prototype
python scripts\run_demo.py --check
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts\eval_ai.py --engine api
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` is not recognized | Reinstall Python with “Add Python to PATH”, or use `py` |
| Node/npm not found | Reinstall Node.js 22 LTS and reopen PowerShell |
| Ollama not found | Install Ollama for Windows, start it once, and reopen PowerShell |
| Browser blocks the connection | Check Windows Firewall for Node.js on private networks |
| Port 8000 or 3000 is in use | Stop the old terminal first; otherwise use `--api-port 8100 --web-port 3100` |
| `--stop` says no process is recorded | An older untracked process owns the port; close the window that launched it |
| Demo shows “本機 AI 未就緒” | Start Ollama and pull the model, retry normally, or switch to the hosted engine on the demo page |
| Hosted engine not ready | Check `API_LLM_API_KEY` in `prototype\.env` and the network, then restart the launcher |
| `Activate.ps1` appears in `.venv` | It is auto-generated by Python venv and ignored by Git; it is not a project script |
