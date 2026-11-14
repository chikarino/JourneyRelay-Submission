# JourneyRelay 一路有應 — Runnable Prototype

**用母語，說一次。** *(Say it once, in your own language.)*

Cathay Hackathon 2026 · Challenge #3 Accessibility · Team Cathay/Gradient

> All passengers and bookings are synthetic (陳太, 王先生, 李女士).

## 1. What it is

Non-visible needs — a child who panics in long queues, a passenger who needs
written updates instead of PA announcements, seats next to a caregiver — only
survive today if the passenger repeats them at every stage. JourneyRelay guides
the passenger through a conversation, discovers relevant catalogue assistance,
and lets them select options or keep chatting. The passenger reviews and
confirms neutral functional needs, and each team receives only its own part, by
the channel it already uses.

```
guided chat (any language, short replies or voice)
  → LangGraph: discover → catalogue tools → respond → validate
  → choose recommended assistance or keep chatting
  → anything the catalogue cannot carry becomes a referral: why not, and "ask Customer Care to contact me"
  → passenger confirms (sees what staff will and won't see)
  → Customer Care checks and files a suggested SSR remark (shown, not really filed)
  → outstations and crew: "notified via the booking record"; Hong Kong's own teams: task cards they acknowledge
  → the next booking can reuse the confirmed needs
  → a flight delay that squeezes the connection prompts an offer (flight status from OAG)
  → passenger timeline + ops board (status matrix, demand by station and flight)
```

Staff endpoints return only catalogue labels and their own role's
instructions. The passenger's raw text is not stored. Chat history lives in
browser memory and clears on refresh; only a generated draft can be resumed.

## 2. Run it

Requirements: **Python 3.10+**, **Node.js 20/22 LTS**, and one AI engine:

- **DeepSeek (hosted)**: put `API_LLM_API_KEY=sk-...` in `prototype/.env`. The on-day demo uses this engine.
- **Ollama (local)**: install Ollama. The launcher downloads `qwen3.5:9b` (about 6.6 GB) on first use.

From the repository root, follow a platform guide or run the commands below.

Platform guides: [`SETUP_MAC.md`](prototype/SETUP_MAC.md), [`SETUP_WINDOWS.md`](prototype/SETUP_WINDOWS.md), [`SETUP_LINUX.md`](prototype/SETUP_LINUX.md).

```bash
cd prototype
python3 scripts/run_demo.py --check   # prerequisites and the engine it will use
python3 scripts/run_demo.py           # venv, deps, reseed, engine, API :8000, web :3000, opens /demo
```

On Windows use `py scripts\run_demo.py`. Options: `--no-browser`,
`--api-port` / `--web-port`, `--stop`. `Ctrl+C` stops every service; logs are
in `.runtime/logs/`. The launcher reseeds the `midjourney` scenario on every
start. Clone the repository anywhere: all paths resolve relative to it.

### Choosing the engine

Set `USE_DEEPSEEK_API=true` in `prototype/.env` to start with DeepSeek (the
demo laptop does this); `false` or unset starts with the local engine. The
engine chips on the `/demo` header switch live; that choice survives demo
resets and is cleared when the API restarts.

If the local engine is selected but Ollama is not installed and
`API_LLM_API_KEY` is set, the launcher uses DeepSeek instead. With no usable
engine it stops with an error. There is no rule-based fallback: when the
engine fails, the passenger sees an error and can retry.

| Setting | Default | Engine |
|---|---|---|
| `USE_DEEPSEEK_API` | `false` | `true` starts with the hosted engine |
| `API_LLM_API_KEY` | — (required) | hosted |
| `API_LLM_BASE_URL` | `https://api.deepseek.com` | hosted; any OpenAI-compatible provider works |
| `API_LLM_MODEL` | `deepseek-flash` | hosted |
| `API_LLM_TIMEOUT_SECONDS` | `60` | hosted |
| `OAG_FLIGHT_INFO_KEY` | — (optional) | live flight delays from OAG; without it no delay is shown |
| `LOCAL_LLM_BASE_URL` | `http://127.0.0.1:11434` | local; loopback addresses only |
| `LOCAL_LLM_MODEL` | `qwen3.5:9b` | local |
| `LOCAL_LLM_TIMEOUT_SECONDS` | `120` | local |

Template: [`.env.example`](prototype/.env.example).

### URLs

| View | URL |
|---|---|
| Team hub | http://localhost:3000 |
| Two-screen demo | http://localhost:3000/demo |
| Passenger (phone) | http://localhost:3000/passenger/CXDEMO1 |
| Staff (tablet) | http://localhost:3000/staff?role=arrival&place=HKG |
| Ops board | http://localhost:3000/ops |
| API docs | http://localhost:8000/docs |

Phones and tablets on the same network open `http://<laptop-LAN-IP>:3000`.
The API stays on `127.0.0.1` behind the frontend's `/api/*` proxy.

## 3. Demo

Open [the two-screen demo](http://localhost:3000/demo). Choose **家庭轉機**
to follow Mrs Chan and her child through a Hong Kong connection.

1. On the phone, describe a need, review the recommended assistance, and
   confirm sharing.
2. In **客服**, acknowledge or arrange the booking task, then switch to
   **轉機站 · HKG** to handle the transfer task.
3. Return to the phone to see the updated itinerary. Use **補充或更新需要**
   to add a request, or **結束對話，查看實用連結** for recommendations based on the itinerary and needs.

The **重設** buttons restore synthetic demo scenarios.

## 4. Verify

```bash
python3 scripts/run_demo.py --check
.venv/bin/python -m unittest discover -s tests       # whole flow with a scripted engine; CI runs these
cd frontend && npm test && cd ..                     # frontend unit tests
.venv/bin/python scripts/eval_chat.py --engine api   # chat: first-turn recommendations on 64 golden cases
.venv/bin/python scripts/eval_ai.py --engine api     # single-description API on the same cases (--engine local: Ollama)
```

The unit tests use a temporary database, so they are safe to run during a
live demo. `eval_chat.py` and `eval_ai.py` call the real engine. On Windows use
`.venv\Scripts\python.exe`.

**Chat (what the UI uses).** One full run, hosted engine on 2026-11-14
(`deepseek-flash`), first turn only: on 45 of 49 cases every need the passenger
stated was among the recommendations (56 of 63 stated needs); nothing was
recommended in the 3 cases where the passenger said they need nothing; written
updates were never offered for difficulty seeing; referrals were right on all
62 cases that completed; p50 4.9 s, p95 10.8 s per turn; 2 turns failed with
an empty reply. That run was taken **before** two fixes the same day (option
IDs without a scope were being dropped, which matches the two misses that
returned no recommendations at all; empty replies are now retried once). A rerun was cut short by a dropped
connection, now handled as an engine error. Rerun before quoting a number.

**Single-description API** (`eval_ai.py`, no longer used by the UI), hosted
engine on 2026-11-13: 63/64 exact matches on needs, referrals correct on 64/64,
p50 1.6 s. The local engine has not been measured with the current prompts.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `python3` / `python` not found | Install Python 3.10+ and reopen the terminal; on Windows try `py` |
| `node` or `npm` not found | Install Node.js 20/22 LTS and reopen the terminal |
| "Ollama is required for the local engine" | Install Ollama, or set `API_LLM_API_KEY` in `prototype/.env` |
| "The hosted engine needs API_LLM_API_KEY" | Add the key to `prototype/.env` |
| Port 8000 or 3000 already in use | Stop the old terminal, or use `--api-port 8100 --web-port 3100` |
| `--stop` says no process is recorded | An older, untracked process owns the port; close it |
| `/demo` header says the AI is not ready | Open `:8000/api/ai/status`. Local: start Ollama or run `ollama pull qwen3.5:9b`. Hosted: check the key and the network |
| Chat shows an error | Retry the reply, switch engines on `/demo`, or choose Browse assistance options. Replies and selections are kept; nothing is shared automatically |
| Pages look unstyled after pulling | Delete `frontend/.next`, run `npm ci` in `frontend/`, restart |
| Demo data looks wrong | 重設 on `/demo`, or `.venv/bin/python -m backend.seed` |
