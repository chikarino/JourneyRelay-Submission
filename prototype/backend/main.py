"""JourneyRelay 一路有應 — FastAPI backend (hackathon prototype, v2).

Core flows (REDESIGN.md §3):
  P1  Passenger describes needs in their own words      -> POST /api/passenger/{pnr}/requests
  P2  Neutral draft, editable before sharing           -> PUT  /api/requests/{id}/needs, DELETE (discard)
  P3  Passenger confirms                               -> POST /api/requests/{id}/confirm
  P4  Journey timeline by stage + "no longer needed"   -> GET  /api/passenger/{pnr}, POST /api/needs/{id}/cancel
  P5  Pre-departure "still applies"                    -> POST /api/passenger/{pnr}/reconfirm
  S1  Role + place scoped task list                    -> GET  /api/staff/tasks?role=&place=
  S2  Staff receive / done / amend / flag              -> POST /api/tasks/{id}/{action}
  O1  Duty-manager board                               -> GET  /api/ops/board

Privacy invariant (06-無障礙 §3.6): no response ever contains `raw_text`; staff
responses carry only catalogue labels and their own role's instructions.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # a venv from before python-dotenv: use the environment and defaults
    pass
else:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import engine_registry, oag
from .analysis import AnalysisError, AnalysisResult, booking_context
from .catalog import (
    CATALOG, CS_FILING_INSTRUCTIONS, REFERRALS, booking_remarks, get_need, order_index,
)
from .conversation import ChatDraftIn, ChatIn, run_conversation, validate_needs
from .portals import CompleteChatIn, complete_chat, eligible_portals
from .db import ROLE_LABELS_EN, ROLE_LABELS_ZH, ROLES, connect, get_db, init_schema, insert_ledger, now_hkt
from .journey import STAGE_ORDER, booking_row, file_remarks, journey_stages, open_filing_card, route_request


@asynccontextmanager
async def _lifespan(_: FastAPI):
    init_schema()
    conn = connect()
    try:
        # A restart goes back to the USE_DEEPSEEK_API setting.
        engine_registry.clear_engine_choice(conn)
        conn.commit()
    finally:
        conn.close()
    yield


app = FastAPI(title="JourneyRelay API", version="0.3.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

STAFF_WONT_SEE = ["你輸入的原文", "任何診斷或醫療資料"]
CS_REVIEW_LABEL = "整份安排"
CS_REVIEW_LABEL_EN = "Full arrangement review"


# ---------------------------------------------------------------------------
# Schemas (mirrored in frontend/lib/api.ts)
# ---------------------------------------------------------------------------

class RequestIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description="Passenger's own words (any language)")
    carry_over: bool = Field(False, description="Merge the needs confirmed on the traveller's last trip (REDESIGN.md §5.4)")


class NeedRef(BaseModel):
    code: str
    scope: Literal["full", "transfer"] = "full"


class DraftNeedsIn(BaseModel):
    needs: list[NeedRef]


class TaskActionIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class ResetIn(BaseModel):
    scenario: Literal["midjourney", "fresh", "family-transfer"] = "midjourney"


class DelayIn(BaseModel):
    flight: str = Field(pattern=r"^[A-Z0-9]{2}\d{1,4}$")
    minutes: int = Field(ge=0, le=600)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _need_json(code: str, scope: str, **extra) -> dict | None:
    need = get_need(code, scope)
    if need is None:
        return None
    return {"code": need.code, "scope": need.scope, "label_zh": need.label_zh, "label_en": need.label_en,
            "detail_zh": need.detail_zh, "detail_en": need.detail_en, **extra}


def _require_booking(conn: sqlite3.Connection, pnr: str) -> dict:
    b = booking_row(conn, pnr)
    if not b:
        raise HTTPException(404, f"找不到訂位 {pnr}")
    return b


def _stage_titles(b: dict) -> dict[str, dict]:
    return {s["key"]: s for s in journey_stages(b)}


# --- Flight status and time (REDESIGN.md §5.5) -----------------------------

TIGHT_CONNECTION_MINUTES = 60   # below this, offer a guide to the connecting gate
DUE_SOON_MINUTES = 120          # a home-station task still unclaimed this close to its time is flagged


def _clock(text: str | None) -> int | None:
    """'21:30' or '05:25 (+1)' -> minutes from the travel date's midnight."""
    m = re.match(r"(\d\d):(\d\d)(?: \(\+(\d)\))?", text or "")
    return int(m.group(1)) * 60 + int(m.group(2)) + 1440 * int(m.group(3) or 0) if m else None


def _demo_delays(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute("SELECT value FROM app_settings WHERE key='demo_delay'").fetchone()
    return json.loads(row["value"]) if row else {}


def _delays(conn: sqlite3.Connection, b: dict) -> dict[str, dict]:
    """Minutes late per flight of this booking. A delay set from the demo header
    wins and is labelled as such; otherwise the live OAG status."""
    demo = _demo_delays(conn)
    out = {}
    for flight in (b["flight_1"], b["flight_2"]):
        if not flight:
            continue
        if flight in demo:
            out[flight] = {"minutes": demo[flight], "source": "demo"}
        else:
            # A flight's departure date is the travel date, or the next day when it leaves after midnight.
            dep = b["f1_dep"] if flight == b["flight_1"] else b["f2_dep"]
            day = datetime.strptime(b["travel_date"], "%Y-%m-%d") + timedelta(minutes=_clock(dep) or 0)
            live = oag.live_delay(flight, day.strftime("%Y-%m-%d"))
            if live is not None:
                out[flight] = {"minutes": live, "source": "oag"}
    return out


def _stage_delay(b: dict, stage: str, delays: dict[str, dict]) -> int:
    """Minutes a stage's own time has moved: the inbound flight for a transfer
    or arrival, the flight itself otherwise."""
    flight = {"dep": b["flight_1"], "f1": b["flight_1"], "transfer": b["flight_1"],
              "f2": b["flight_2"], "arr": b["flight_2"] or b["flight_1"]}.get(stage)
    return delays.get(flight, {}).get("minutes", 0)


def _journey_status(conn: sqlite3.Connection, b: dict, active: list, has_draft: bool) -> dict:
    """What the passenger is told about delays, and the one thing we offer: a
    guide to the connecting gate when the connection has become tight."""
    delays = _delays(conn, b)
    flights = [{"flight": f, **d} for f, d in delays.items()]
    connection = offer = None
    if b["via"] and _clock(b["f1_arr"]) is not None and _clock(b["f2_dep"]) is not None:
        scheduled = _clock(b["f2_dep"]) - _clock(b["f1_arr"])
        expected = (scheduled - delays.get(b["flight_1"], {}).get("minutes", 0)
                    + delays.get(b["flight_2"], {}).get("minutes", 0))
        tight = expected < scheduled and expected < TIGHT_CONNECTION_MINUTES
        connection = {"station": b["via"], "scheduled": scheduled, "expected": expected, "tight": tight}
        covered = any(n.code in ("GUIDE", "WHEELCHAIR") for n in active)
        if tight and not covered and not has_draft:
            offer = _need_json("GUIDE", "transfer")
    return {"flights": flights, "connection": connection, "offer": offer}


def _who(stage: dict | None, role: str | None) -> str:
    """'香港轉機 · 抵達／轉機站' — the team that acted, in passenger language."""
    if not role:
        return ""
    label = ROLE_LABELS_ZH.get(role, role)
    if not stage or stage["key"] == "booking":
        return label
    return f"{stage['title']} · {label}"


def _who_en(stage: dict | None, role: str | None) -> str:
    """English mirror of `_who`: 'Hong Kong Transfer · Arrival / Transit'."""
    if not role:
        return ""
    label = ROLE_LABELS_EN.get(role, role)
    if not stage or stage["key"] == "booking":
        return label
    return f"{stage['title_en']} · {label}"


def engine_for_request(conn: sqlite3.Connection):
    """Engine factory; tests patch this to inject a fake engine."""
    return engine_registry.engine(conn)


def _is_review(role: str, task) -> bool:
    """Customer Care's review or remark-update card, as opposed to a callback task (REDESIGN.md §5.2)."""
    return role == "cs" and task["instruction_zh"] in CS_FILING_INSTRUCTIONS


def _referrals_from_row(row: sqlite3.Row | None) -> list[dict]:
    """Stored referral codes -> catalogue wording. The passenger gets all of it; Customer Care
    gets the topic labels on a callback card only (REDESIGN.md §5.2)."""
    try:
        codes = json.loads(row["analysis_referrals"] or "[]") if row is not None else []
    except json.JSONDecodeError:
        return []
    return [
        {"code": r.code, "label_zh": r.label_zh, "label_en": r.label_en,
         "advice_zh": r.advice_zh, "advice_en": r.advice_en}
        for r in REFERRALS if isinstance(codes, list) and r.code in codes
    ]


def _suggestions_json(result: AnalysisResult) -> str | None:
    """Store the passenger-pickable suggestions with the draft (never staff-visible)."""
    if not result.suggestions:
        return None
    return json.dumps(
        [{"code": s.need.code, "scope": s.need.scope, "reason": s.reason} for s in result.suggestions],
        ensure_ascii=False,
    )


def _persist_draft(conn: sqlite3.Connection, pnr: str, result: AnalysisResult) -> dict:
    conn.execute("DELETE FROM assistance_requests WHERE pnr=? AND status='draft'", (pnr,))
    top = conn.execute(
        "SELECT COALESCE(MAX(version),0) AS v FROM assistance_requests WHERE pnr=? AND status='active'",
        (pnr,),
    ).fetchone()
    cur = conn.execute(
        """INSERT INTO assistance_requests
           (pnr, version, status, raw_text, analysis_source, analysis_status,
            analysis_model, analysis_latency_ms, analysis_error_code, analysis_situation,
            analysis_suggestions, analysis_referrals, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pnr, top["v"] + 1, "draft", None, result.source, result.status, result.model,
         result.latency_ms, result.error_code, result.situation,
         _suggestions_json(result), json.dumps(list(result.referrals)) if result.referrals else None,
         now_hkt()),
    )
    for n in result.needs:
        conn.execute("INSERT OR IGNORE INTO needs (request_id, code, scope) VALUES (?,?,?)",
                     (cur.lastrowid, n.code, n.scope))
    draft = conn.execute("SELECT * FROM assistance_requests WHERE id=?", (cur.lastrowid,)).fetchone()
    return _draft_json(conn, draft)


def _suggestions_from_row(row: sqlite3.Row | None) -> list[dict]:
    """Stored suggestions -> passenger-facing JSON with catalogue labels."""
    raw = row["analysis_suggestions"] if row is not None else None
    if not raw:
        return []
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for item in stored if isinstance(stored, list) else []:
        if not isinstance(item, dict):
            continue
        need = get_need(item.get("code", ""), item.get("scope", "full"))
        if need is None:
            continue
        out.append({"code": need.code, "scope": need.scope,
                    "label_zh": need.label_zh, "label_en": need.label_en,
                    "detail_zh": need.detail_zh, "detail_en": need.detail_en,
                    "reason": item.get("reason", ""),
                    "_order": order_index(need.code, need.scope)})
    return [{k: v for k, v in s.items() if k != "_order"}
            for s in sorted(out, key=lambda s: s["_order"])]


def _active_needs(conn: sqlite3.Connection, pnr: str) -> list:
    """Catalogue entries for the booking's confirmed, not-cancelled needs."""
    rows = conn.execute(
        """SELECT n.code, n.scope FROM needs n JOIN assistance_requests r ON r.id=n.request_id
           WHERE r.pnr=? AND r.status='active' AND n.cancelled_at IS NULL""", (pnr,),
    ).fetchall()
    return [n for n in (get_need(r["code"], r["scope"]) for r in rows) if n]


def _draft_json(conn: sqlite3.Connection, req: sqlite3.Row) -> dict:
    has_active = conn.execute(
        "SELECT 1 FROM assistance_requests WHERE pnr=? AND status='active' LIMIT 1", (req["pnr"],),
    ).fetchone() is not None
    # Mark what the last trip already had, so the passenger can see and drop it (REDESIGN.md §5.4).
    last_trip = set() if has_active else {n.key for n in _reusable_needs(conn, booking_row(conn, req["pnr"]))}
    rows = conn.execute("SELECT code, scope FROM needs WHERE request_id=?", (req["id"],)).fetchall()
    needs = [j for j in (_need_json(r["code"], r["scope"], from_last_trip=f"{r['code']}:{r['scope']}" in last_trip)
                         for r in rows) if j]
    needs.sort(key=lambda n: order_index(n["code"], n["scope"]))
    analysis = {
        "source": req["analysis_source"] or "local",
        "status": req["analysis_status"] or "ok",
        "model": req["analysis_model"],
        "latency_ms": req["analysis_latency_ms"],
        "situation": req["analysis_situation"],
    }
    return {
        "request_id": req["id"], "version": req["version"], "is_update": has_active,
        "needs": needs,
        "suggestions": _suggestions_from_row(req),
        # What was asked for but cannot be arranged here, with the way forward (REDESIGN.md §5.2).
        "referrals": _referrals_from_row(req),
        "analysis": analysis,
        # Privacy preview (one-pager-v6 mini-hide): exactly what staff will / won't see.
        "staff_will_see": [n["label_zh"] for n in needs],
        "staff_wont_see": STAFF_WONT_SEE,
        # The whole booking as it would stand after this draft (REDESIGN.md §5.1).
        "booking_remarks": booking_remarks(
            _active_needs(conn, req["pnr"]) + [get_need(n["code"], n["scope"]) for n in needs]),
    }


def _passenger_view(conn: sqlite3.Connection, pnr: str) -> dict:
    b = _require_booking(conn, pnr)
    stages = journey_stages(b)
    by_key = {s["key"]: s for s in stages}

    tasks = conn.execute(
        """SELECT t.id, t.role, t.stage, t.channel, t.instruction_zh, t.instruction_en, t.status, t.note,
                  t.received_at, t.done_at, n.code, n.scope, r.version
           FROM tasks t JOIN needs n ON n.id=t.need_id JOIN assistance_requests r ON r.id=n.request_id
           WHERE r.pnr=? AND r.status='active' ORDER BY t.id""", (pnr,),
    ).fetchall()

    stage_items: dict[str, list[dict]] = {s["key"]: [] for s in stages}
    for t in tasks:
        need = get_need(t["code"], t["scope"])
        if t["stage"] not in stage_items or need is None:
            continue
        stage_items[t["stage"]].append({
            "task_id": t["id"], "role": t["role"], "role_label": ROLE_LABELS_ZH[t["role"]],
            "role_label_en": ROLE_LABELS_EN[t["role"]],
            "need_label": CS_REVIEW_LABEL if _is_review(t["role"], t) else need.label_zh,
            "need_label_en": CS_REVIEW_LABEL_EN if _is_review(t["role"], t) else need.label_en,
            "instruction_zh": t["instruction_zh"], "instruction_en": t["instruction_en"],
            "status": t["status"], "channel": t["channel"],
            "at": t["done_at"] or t["received_at"],
            # Amend notes are written for the passenger; flag reasons stay internal.
            "note": t["note"] if t["status"] == "amended" else None,
            "is_update": t["version"] > 1,
            "_order": (order_index(t["code"], t["scope"]), ROLES.index(t["role"])),
        })
    out_stages = []
    for s in stages:
        items = sorted(stage_items[s["key"]], key=lambda i: i.pop("_order"))
        out_stages.append({**s, "items": items})

    needs = []
    for n in conn.execute(
        """SELECT n.id, n.code, n.scope, n.cancelled_at, r.version FROM needs n
           JOIN assistance_requests r ON r.id=n.request_id
           WHERE r.pnr=? AND r.status='active'""", (pnr,),
    ).fetchall():
        j = _need_json(n["code"], n["scope"], need_id=n["id"], version=n["version"],
                       status="cancelled" if n["cancelled_at"] else "active")
        if j:
            needs.append(j)
    needs.sort(key=lambda n: (n["status"] != "active", order_index(n["code"], n["scope"]), n["version"]))

    live = [t for t in tasks if t["status"] != "cancelled"]
    summary = {
        "total": len(live),
        "done": sum(t["status"] in ("done", "amended") for t in live),
        "received": sum(t["status"] == "received" for t in live),
        "followup": sum(t["status"] == "flagged" for t in live),
        "notified": sum(t["status"] == "notified" for t in live),
    }

    draft_row = conn.execute(
        "SELECT * FROM assistance_requests WHERE pnr=? AND status='draft' ORDER BY id DESC LIMIT 1", (pnr,),
    ).fetchone()
    has_active = conn.execute(
        "SELECT 1 FROM assistance_requests WHERE pnr=? AND status='active' LIMIT 1", (pnr,),
    ).fetchone() is not None

    ledger = []
    for e in conn.execute(
        "SELECT role, stage, detail_zh, detail_en, actor, created_at FROM ledger_events"
        " WHERE pnr=? ORDER BY id DESC LIMIT 40", (pnr,),
    ).fetchall():
        if e["actor"] == "passenger":
            who, who_en = "你", "You"
        else:
            who = _who(by_key.get(e["stage"]), e["role"]) or "系統"
            who_en = _who_en(by_key.get(e["stage"]), e["role"]) or "System"
        ledger.append({"text": e["detail_zh"], "text_en": e["detail_en"], "who": who, "who_en": who_en,
                       "at": e["created_at"]})

    return {
        "pnr": pnr,
        "passenger": {"display_name": b["display_name"], "party_note": b["party_note"]},
        "booking": {k: b[k] for k in ("origin", "via", "destination", "flight_1", "flight_2",
                                      "f1_dep", "f1_arr", "f2_dep", "f2_arr", "travel_date", "reconfirmed_at")},
        "has_active": has_active,
        "summary": summary,
        "stages": out_stages,
        "needs": needs,
        "draft": _draft_json(conn, draft_row) if draft_row else None,
        "ledger": ledger,
        # Needs passport: what this traveller confirmed on another booking (REDESIGN.md §5.4).
        "reusable": [] if has_active else [_need_json(n.code, n.scope) for n in _reusable_needs(conn, b)],
        "journey_status": _journey_status(conn, b, _active_needs(conn, pnr), draft_row is not None),
    }


def _reusable_needs(conn: sqlite3.Connection, b: dict) -> list:
    """Needs still active on this traveller's most recently confirmed other booking,
    minus what cannot carry over: the callback, and transfer-only needs on a direct trip."""
    member = conn.execute("SELECT member_id FROM passengers WHERE pnr=?", (b["pnr"],)).fetchone()["member_id"]
    if not member:
        return []
    last = conn.execute(
        """SELECT r.pnr FROM assistance_requests r JOIN passengers p ON p.pnr=r.pnr
           WHERE p.member_id=? AND r.pnr!=? AND r.status='active'
           ORDER BY r.confirmed_at DESC, r.id DESC LIMIT 1""", (member, b["pnr"]),
    ).fetchone()
    if not last:
        return []
    needs = {n for n in _active_needs(conn, last["pnr"])
             if n.code != "CS_CALLBACK" and (n.scope == "full" or b["via"])}
    return sorted(needs, key=CATALOG.index)


def _require_draft(conn: sqlite3.Connection, req_id: int) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM assistance_requests WHERE id=?", (req_id,)).fetchone()
    if not r:
        raise HTTPException(404, "找不到這份草稿")
    if r["status"] != "draft":
        raise HTTPException(409, "這份說明已經確認分享")
    return r


# ---------------------------------------------------------------------------
# Passenger endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "journeyrelay-api", "version": app.version}


@app.get("/api/ai/status")
def ai_status(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Engine readiness for the demo UI; no prompt or passenger data involved."""
    local = _engine_probe("local", db)
    api = _engine_probe("api", db)
    engine_name = engine_registry.current_engine_name(db)
    ok = local["reachable"] and local["model_installed"] if engine_name == "local" \
        else api.get("reachable", False)
    return {"ok": bool(ok), "engine": engine_name, "local": local, "api": api}


def _engine_probe(name: str, conn: sqlite3.Connection) -> dict:
    try:
        instance = engine_registry.ENGINES[name]()
    except Exception:
        probes = {"local": {"reachable": False, "model": None, "model_installed": False},
                  "api": {"configured": False, "reachable": False, "model": None}}
        return probes[name]
    probe = instance.probe()
    return probe if isinstance(probe, dict) else {}


class EngineIn(BaseModel):
    engine: Literal["local", "api"]


@app.get("/api/ai/engine")
def get_ai_engine(db: sqlite3.Connection = Depends(get_db)) -> dict:
    engine_name = engine_registry.current_engine_name(db)
    return {"engine": engine_name,
            "local": _engine_probe("local", db), "api": _engine_probe("api", db)}


@app.post("/api/ai/engine")
def set_ai_engine(body: EngineIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    engine_registry.set_engine(db, body.engine)
    db.commit()
    return get_ai_engine(db)


@app.get("/api/demo/bookings")
def list_bookings(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Demo navigation helper: all seeded bookings (synthetic passengers)."""
    rows = db.execute(
        "SELECT b.pnr, p.display_name, p.party_note, b.origin, b.via, b.destination,"
        " b.flight_1, b.flight_2, b.travel_date FROM bookings b JOIN passengers p ON p.pnr=b.pnr ORDER BY b.id",
    ).fetchall()
    return {"bookings": [dict(r) for r in rows]}


@app.post("/api/demo/reset")
def demo_reset(body: ResetIn = ResetIn(), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Rebuild the synthetic demo data in place — no API restart needed."""
    from .seed import load_demo_data  # local import: seed imports this package's modules

    counts = load_demo_data(db, body.scenario)
    db.execute("DELETE FROM app_settings WHERE key='demo_delay'")
    db.commit()
    return {"ok": True, "scenario": body.scenario, **counts}


@app.post("/api/demo/delay")
def demo_delay(body: DelayIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Demo scenario: set (or with 0 minutes, clear) a delay on one flight. The UI
    labels it as a demo scenario, never as live status (REDESIGN.md §5.5)."""
    delays = _demo_delays(db)
    delays.pop(body.flight, None)
    if body.minutes:
        delays[body.flight] = body.minutes
    db.execute("INSERT INTO app_settings (key, value) VALUES ('demo_delay', ?)"
               " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(delays),))
    db.commit()
    return {"delays": delays}


@app.get("/api/needs/catalog")
def needs_catalog() -> dict:
    """Every need the passenger can browse in the guided chat."""
    return {"needs": [_need_json(n.code, n.scope, ssr_hint=n.ssr_hint) for n in CATALOG]}


@app.get("/api/passenger/{pnr}")
def passenger_view(pnr: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Booking, journey timeline by stage, current needs, pending draft and ledger."""
    return _passenger_view(db, pnr)


@app.post("/api/passenger/{pnr}/chat")
def assistance_chat(pnr: str, body: ChatIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Read-only LangGraph turn. Never saves a transcript, draft, or staff task."""
    _require_booking(db, pnr)
    context = booking_context(db, pnr)
    try:
        validate_needs(body.selected, context)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return run_conversation(engine_for_request(db), body, context)
    except AnalysisError as exc:
        # No engine details, model reasoning or customer text in the error.
        raise HTTPException(503, detail={"code": exc.code}) from exc


@app.post("/api/passenger/{pnr}/chat/complete")
def complete_assistance_chat(pnr: str, body: CompleteChatIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Passenger-only portal links; no transcript, draft or staff tasks are saved."""
    _require_booking(db, pnr)
    context = booking_context(db, pnr)
    try:
        validate_needs(body.selected, context)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return complete_chat(engine_for_request(db) if body.messages and eligible_portals(context) else None,
                             body, context)
    except AnalysisError as exc:
        raise HTTPException(503, detail={"code": exc.code}) from exc


@app.post("/api/passenger/{pnr}/chat/draft", status_code=201)
def chat_draft(pnr: str, body: ChatDraftIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Explicit selections -> existing preview. Confirmation remains a separate action."""
    _require_booking(db, pnr)
    try:
        needs = validate_needs(body.needs, booking_context(db, pnr))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if any(code not in {r.code for r in REFERRALS} for code in body.referrals):
        raise HTTPException(422, "Unknown referral topic")
    result = AnalysisResult(needs=needs, situation=None, source="chat", status="ok", latency_ms=0,
                            referrals=tuple(dict.fromkeys(body.referrals)))
    draft = _persist_draft(db, pnr, result)
    db.commit()
    return {**draft, "recognised": True}


def _carry_over(conn: sqlite3.Connection, pnr: str, result: AnalysisResult) -> AnalysisResult:
    """Add the needs confirmed on the traveller's last trip to what the engine found.
    The passenger removes any that no longer apply in the preview."""
    has_active = conn.execute(
        "SELECT 1 FROM assistance_requests WHERE pnr=? AND status='active' LIMIT 1", (pnr,)).fetchone()
    previous = [] if has_active else _reusable_needs(conn, _require_booking(conn, pnr))
    if not previous:
        return result
    needs = tuple(sorted({*result.needs, *previous}, key=CATALOG.index))
    return replace(result, needs=needs, status="ok")


@app.post("/api/passenger/{pnr}/requests", status_code=201)
def create_request(pnr: str, body: RequestIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Say once -> neutral draft via the real AI engine. Nothing is shared until confirm."""
    _require_booking(db, pnr)
    try:
        engine = engine_for_request(db)
        result = engine.analyse(body.text, booking_context(db, pnr))
    except AnalysisError:
        raise HTTPException(503, "AI 引擎暫時無法回應，請稍後重試。")
    if result.status == "error":
        raise HTTPException(503, "AI 引擎暫時無法回應，請稍後重試。")
    if body.carry_over:
        result = _carry_over(db, pnr, result)
    draft = _persist_draft(db, pnr, result)
    db.commit()
    return {**draft, "recognised": bool(result.needs)}


@app.post("/api/passenger/{pnr}/requests/offer", status_code=201)
def accept_offer(pnr: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The passenger takes up what a delay prompted (REDESIGN.md §5.5): a draft
    with the offered need, previewed and confirmed like any other. No AI."""
    b = _require_booking(db, pnr)
    offer = _journey_status(db, b, _active_needs(db, pnr), False)["offer"]
    if not offer:
        raise HTTPException(404, "目前沒有建議的安排")
    draft = _persist_draft(db, pnr, AnalysisResult(
        needs=(get_need(offer["code"], offer["scope"]),), situation=None, source="offer", status="ok",
        latency_ms=0))
    db.commit()
    return {**draft, "recognised": True}


@app.post("/api/passenger/{pnr}/requests/reuse", status_code=201)
def reuse_request(pnr: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Needs passport: draft this booking's needs from the traveller's last trip. No AI;
    the passenger still previews and confirms, once per booking (REDESIGN.md §5.4)."""
    needs = _reusable_needs(db, _require_booking(db, pnr))
    if not needs:
        raise HTTPException(404, "沒有可以沿用的需要")
    draft = _persist_draft(db, pnr, AnalysisResult(
        needs=tuple(needs), situation=None, source="profile", status="ok", latency_ms=0))
    db.commit()
    return {**draft, "recognised": True}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/api/passenger/{pnr}/requests/stream")
def create_request_stream(pnr: str, body: RequestIn,
                          db: sqlite3.Connection = Depends(get_db)) -> StreamingResponse:
    """Say once, streamed: status -> thinking* -> result(draft) | error(code)."""
    _require_booking(db, pnr)
    try:
        engine = engine_for_request(db)
    except AnalysisError:
        # Before streaming starts, a plain 503 is correct and the client
        # surfaces `detail` like any other non-OK response.
        raise HTTPException(503, "AI 引擎配置錯誤。")
    context = booking_context(db, pnr)

    def events():
        yield _sse({"type": "status", "engine": engine.name, "model": engine.model_label()})
        try:
            for event in engine.stream_analyse(body.text, context):
                if event["type"] == "analysis":
                    result = AnalysisResult(
                        needs=event["needs"], situation=event["situation"],
                        source=event.get("source", engine.name), status=event["status"],
                        latency_ms=event["latency_ms"], model=event.get("model"),
                        suggestions=event.get("suggestions", ()),
                        referrals=event.get("referrals", ()),
                    )
                    if body.carry_over:
                        result = _carry_over(db, pnr, result)
                    draft = _persist_draft(db, pnr, result)
                    db.commit()
                    yield _sse({"type": "result", "draft": {**draft, "recognised": bool(result.needs)}})
                elif event["type"] == "thinking":
                    yield _sse(event)
                elif event["type"] == "error":
                    yield _sse(event)
                    return
        except AnalysisError as exc:
            yield _sse({"type": "error", "code": exc.code})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.put("/api/requests/{req_id}/needs")
def edit_draft(req_id: int, body: DraftNeedsIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Passenger removes or adds needs in the preview before sharing."""
    r = _require_draft(db, req_id)
    for ref in body.needs:
        if get_need(ref.code, ref.scope) is None:
            raise HTTPException(422, f"未知的需要：{ref.code}（{ref.scope}）")
    db.execute("DELETE FROM needs WHERE request_id=?", (req_id,))
    for ref in body.needs:
        db.execute("INSERT OR IGNORE INTO needs (request_id, code, scope) VALUES (?,?,?)",
                   (req_id, ref.code, ref.scope))
    db.commit()
    return _draft_json(db, r)


@app.delete("/api/requests/{req_id}")
def discard_draft(req_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    _require_draft(db, req_id)
    db.execute("DELETE FROM assistance_requests WHERE id=?", (req_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/requests/{req_id}/confirm")
def confirm_request(req_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Passenger confirms -> role- and stage-scoped tasks (delta-routed for updates)."""
    r = _require_draft(db, req_id)
    rows = db.execute("SELECT code, scope FROM needs WHERE request_id=?", (req_id,)).fetchall()
    if not rows:
        raise HTTPException(422, "請至少保留一項需要，或者取消這次說明。")
    pnr = r["pnr"]
    b = _require_booking(db, pnr)
    stages = _stage_titles(b)
    is_update = db.execute(
        "SELECT 1 FROM assistance_requests WHERE pnr=? AND status='active' LIMIT 1", (pnr,),
    ).fetchone() is not None

    now = now_hkt()
    db.execute("UPDATE assistance_requests SET status='active', confirmed_at=? WHERE id=?", (now, req_id))
    created = route_request(db, pnr, req_id, now)

    need_jsons = sorted(
        (j for j in (_need_json(x["code"], x["scope"]) for x in rows) if j),
        key=lambda n: order_index(n["code"], n["scope"]))
    labels = "、".join(n["label_zh"] for n in need_jsons)
    labels_en = ", ".join(n["label_en"] for n in need_jsons)
    teams = list(dict.fromkeys(_who(stages.get(c["stage"]), c["role"]) for c in created))
    teams_en = list(dict.fromkeys(_who_en(stages.get(c["stage"]), c["role"]) for c in created))
    if is_update:
        reached = "、".join(teams) if teams else "毋須通知新崗位"
        reached_en = ", ".join(teams_en) if teams_en else "no new teams to notify"
        detail = f"你補充了：{labels}。只通知受影響的崗位（{reached}），其他安排不變。"
        detail_en = (f"You added: {labels_en}. Only affected teams were notified ({reached_en});"
                     " other arrangements unchanged.")
    else:
        detail = f"你確認分享：{labels}。客服會先核對並寫入訂位紀錄，沿途 {len(teams)} 個崗位隨後收到。"
        detail_en = (f"You shared: {labels_en}. Customer Care checks and files them first; "
                     f"{len(teams)} teams along the journey then receive them.")
    insert_ledger(db, pnr, r["version"], None, "request_confirmed", detail, "passenger", at=now,
                  detail_en=detail_en)
    db.commit()
    return _passenger_view(db, pnr)


@app.post("/api/needs/{need_id}/cancel")
def cancel_need(need_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Passenger says a need no longer applies -> its open tasks are cancelled."""
    n = db.execute(
        """SELECT n.*, r.pnr, r.version, r.status AS req_status FROM needs n
           JOIN assistance_requests r ON r.id=n.request_id WHERE n.id=?""", (need_id,),
    ).fetchone()
    if not n or n["req_status"] != "active":
        raise HTTPException(404, "找不到這項需要")
    if n["cancelled_at"]:
        raise HTTPException(409, "這項需要已經取消")
    now = now_hkt()
    db.execute("UPDATE needs SET cancelled_at=? WHERE id=?", (now, need_id))
    # Customer Care's filing card covers the whole booking; it only hangs off a need row.
    marks = ",".join("?" * len(CS_FILING_INSTRUCTIONS))
    db.execute(f"UPDATE tasks SET status='cancelled' WHERE need_id=? AND status!='cancelled'"
               f" AND NOT (role='cs' AND instruction_zh IN ({marks}))", (need_id, *CS_FILING_INSTRUCTIONS))
    need = get_need(n["code"], n["scope"])
    label, label_en = need.label_zh, need.label_en
    insert_ledger(db, n["pnr"], n["version"], None, "need_cancelled",
                  f"你取消了「{label}」，相關崗位毋須再安排。", "passenger", at=now,
                  detail_en=f"You cancelled \"{label_en}\". Related teams no longer need to arrange it.")
    # The filed remark still lists this need, so Customer Care gets a card to update it.
    if db.execute("SELECT 1 FROM tasks t JOIN needs x ON x.id=t.need_id JOIN assistance_requests r"
                  " ON r.id=x.request_id WHERE r.pnr=? AND t.role='cs' AND t.status IN ('done','amended')"
                  " LIMIT 1", (n["pnr"],)).fetchone():
        open_filing_card(db, n["pnr"], need_id, now)
    db.commit()
    return _passenger_view(db, n["pnr"])


@app.post("/api/passenger/{pnr}/reconfirm")
def reconfirm(pnr: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Pre-departure check: the passenger confirms the arrangements still apply."""
    _require_booking(db, pnr)
    top = db.execute(
        "SELECT MAX(version) AS v FROM assistance_requests WHERE pnr=? AND status='active'", (pnr,),
    ).fetchone()
    if not top["v"]:
        raise HTTPException(409, "未有需要確認的安排")
    now = now_hkt()
    db.execute("UPDATE bookings SET reconfirmed_at=? WHERE pnr=?", (now, pnr))
    insert_ledger(db, pnr, top["v"], None, "reconfirmed", "你確認出發前安排仍然適用。", "passenger",
                  at=now, detail_en="You confirmed your pre-departure arrangements still apply.")
    db.commit()
    return _passenger_view(db, pnr)


# ---------------------------------------------------------------------------
# Staff endpoints (ROLE + PLACE SCOPED — the privacy core of the product)
# ---------------------------------------------------------------------------

@app.get("/api/staff/tasks")
def staff_tasks(role: str = Query(..., description="cs|checkin|gate|cabin|arrival"),
                place: Optional[str] = Query(None, description="station code (e.g. HKG) or flight (e.g. CX251)"),
                db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Task cards for ONE role at ONE place: catalogue labels + this role's
    instructions only — never raw text, never other roles' work."""
    if role not in ROLES:
        raise HTTPException(422, f"Unknown role '{role}'. Valid: {', '.join(ROLES)}")

    rows = db.execute(
        """SELECT t.id AS task_id, t.stage, t.channel, t.instruction_zh, t.instruction_en, t.status, t.note,
                  t.created_at, t.received_at, t.done_at, n.code, n.scope, r.pnr, r.version,
                  r.analysis_referrals
           FROM tasks t JOIN needs n ON n.id=t.need_id JOIN assistance_requests r ON r.id=n.request_id
           WHERE t.role=? AND r.status='active' ORDER BY t.id""", (role,),
    ).fetchall()

    stages_by_pnr: dict[str, dict[str, dict]] = {}
    places: dict[str, dict] = {}
    for t in rows:
        if t["pnr"] not in stages_by_pnr:
            stages_by_pnr[t["pnr"]] = _stage_titles(booking_row(db, t["pnr"]))
        st = stages_by_pnr[t["pnr"]].get(t["stage"])
        if not st:
            continue
        p = places.setdefault(st["place"], {"place": st["place"], "open": 0, "total": 0})
        p["total"] += 1
        p["open"] += t["channel"] == "app" and t["status"] in ("pending", "received", "flagged")
    place_list = sorted(places.values(), key=lambda p: p["place"])
    if place is None and place_list:
        place = max(place_list, key=lambda p: p["open"])["place"]

    groups: dict[tuple[str, str], dict] = {}
    now = datetime.strptime(now_hkt(), "%Y-%m-%d %H:%M")
    for t in rows:
        st = stages_by_pnr.get(t["pnr"], {}).get(t["stage"])
        if not st or st["place"] != place:
            continue
        need = get_need(t["code"], t["scope"])
        if need is None:
            continue
        g = groups.get((t["pnr"], t["stage"]))
        if g is None:
            b = booking_row(db, t["pnr"])
            g = groups[(t["pnr"], t["stage"])] = {
                "pnr": t["pnr"],
                "passenger": f"{b['display_name']} {b['party_note'] or ''}".strip(),
                "stage": t["stage"], "stage_title": st["title"], "stage_sub": st["sub"],
                "stage_title_en": st["title_en"], "stage_sub_en": st["sub_en"], "time": st["time"],
                "travel_date": b["travel_date"], "items": [],
                "delay_minutes": _stage_delay(b, t["stage"], _delays(db, b)),
                # Customer Care files the whole booking; other roles see only their own tasks.
                "booking_remarks": booking_remarks(_active_needs(db, t["pnr"])) if role == "cs" else [],
            }
        g["items"].append({
            "task_id": t["task_id"], "label_zh": CS_REVIEW_LABEL if _is_review(role, t) else need.label_zh,
            "label_en": CS_REVIEW_LABEL_EN if _is_review(role, t) else need.label_en,
            "ssr_hint": "" if role == "cs" else need.ssr_hint, "scope": t["scope"],
            # What the call is about: topic labels from the closed referral list, callback card only.
            "topics": [{"label_zh": r["label_zh"], "label_en": r["label_en"]} for r in _referrals_from_row(t)]
                      if role == "cs" and need.code == "CS_CALLBACK" else [],
            "instruction_zh": t["instruction_zh"], "instruction_en": t["instruction_en"],
            "status": t["status"], "note": t["note"], "channel": t["channel"],
            "due_soon": t["channel"] == "app" and t["status"] == "pending" and _due_soon(g, now),
            "is_update": t["version"] > 1, "created_at": t["created_at"],
            "received_at": t["received_at"], "done_at": t["done_at"],
            "_order": order_index(t["code"], t["scope"]),
        })
    out = sorted(groups.values(), key=lambda g: (g["time"] or "", STAGE_ORDER.index(g["stage"]), g["pnr"]))
    for g in out:
        g["items"].sort(key=lambda i: i.pop("_order"))

    return {"role": role, "label_zh": ROLE_LABELS_ZH[role], "label_en": ROLE_LABELS_EN[role],
            "place": place, "places": place_list, "groups": out, "updated_at": now_hkt(),
            "privacy_note": "只顯示功能性需要及本崗位任務；旅客原文及任何診斷都不會顯示。"}


def _due_soon(group: dict, now: datetime) -> bool:
    """Is this stage's (delayed) time within DUE_SOON_MINUTES, or already past?
    Only meaningful for home-station stages, whose times are in the demo clock's zone."""
    minutes = _clock(group["time"])
    if minutes is None:
        return False
    due = (datetime.strptime(group["travel_date"], "%Y-%m-%d")
           + timedelta(minutes=minutes + group["delay_minutes"]))
    return now >= due - timedelta(minutes=DUE_SOON_MINUTES)


def _apply_task_action(db: sqlite3.Connection, task_id: int, action: str, note: Optional[str]) -> dict:
    t = db.execute(
        """SELECT t.*, n.code, n.scope, r.pnr, r.version FROM tasks t
           JOIN needs n ON n.id=t.need_id JOIN assistance_requests r ON r.id=n.request_id
           WHERE t.id=?""", (task_id,),
    ).fetchone()
    if not t:
        raise HTTPException(404, "找不到這項任務")
    if t["status"] == "cancelled":
        raise HTTPException(409, "旅客已取消這項需要，毋須處理")
    if t["channel"] == "remark":
        raise HTTPException(409, "這個崗位經訂位紀錄接收安排，毋須在此回報")
    if action in ("amend", "flag") and not (note and note.strip()):
        raise HTTPException(422, "調整安排需要填寫內容" if action == "amend" else "需要跟進請填寫原因")

    now = now_hkt()
    note = note.strip() if note else None
    if action == "receive":
        db.execute("UPDATE tasks SET status='received', received_at=COALESCE(received_at, ?) WHERE id=?",
                   (now, task_id))
    elif action == "done":
        db.execute("UPDATE tasks SET status='done', received_at=COALESCE(received_at, ?), done_at=? WHERE id=?",
                   (now, now, task_id))
    elif action == "amend":
        db.execute("UPDATE tasks SET status='amended', note=?, received_at=COALESCE(received_at, ?), done_at=?"
                   " WHERE id=?", (note, now, now, task_id))
    else:  # flag
        db.execute("UPDATE tasks SET status='flagged', note=?, received_at=COALESCE(received_at, ?) WHERE id=?",
                   (note, now, task_id))

    stage = _stage_titles(booking_row(db, t["pnr"])).get(t["stage"])
    need = get_need(t["code"], t["scope"])
    label = CS_REVIEW_LABEL if _is_review(t["role"], t) else need.label_zh
    label_en = CS_REVIEW_LABEL_EN if _is_review(t["role"], t) else need.label_en
    who = _who(stage, t["role"])
    who_en = _who_en(stage, t["role"])
    detail = {
        "receive": f"{who}：已收到「{label}」",
        "done": f"{who}：已安排「{label}」",
        "amend": f"{who}：已安排「{label}」，有調整（{note}）",
        # The flag reason is internal; the passenger only learns it is being followed up.
        "flag": f"{who}：正在跟進「{label}」",
    }[action]
    detail_en = {
        "receive": f"{who_en}: received \"{label_en}\"",
        "done": f"{who_en}: arranged \"{label_en}\"",
        "amend": f"{who_en}: arranged \"{label_en}\" with an adjustment ({note})",
        "flag": f"{who_en}: is following up on \"{label_en}\"",
    }[action]
    insert_ledger(db, t["pnr"], t["version"], t["role"], f"task_{action}", detail, t["role"],
                  stage=t["stage"], at=now, detail_en=detail_en)
    if action in ("done", "amend") and _is_review(t["role"], t):
        file_remarks(db, t["pnr"], t["version"], now)
    db.commit()
    row = db.execute("SELECT id, status, note, received_at, done_at FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row)


@app.post("/api/tasks/{task_id}/receive")
def receive(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """「已收到」— this team has seen the task and owns it."""
    return _apply_task_action(db, task_id, "receive", None)


@app.post("/api/tasks/{task_id}/done")
def done(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """「已安排」— the arrangement is in place."""
    return _apply_task_action(db, task_id, "done", None)


@app.post("/api/tasks/{task_id}/amend")
def amend(task_id: int, body: TaskActionIn = TaskActionIn(), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """「調整」— arranged differently; the note is shown to the passenger."""
    return _apply_task_action(db, task_id, "amend", body.note)


@app.post("/api/tasks/{task_id}/flag")
def flag(task_id: int, body: TaskActionIn = TaskActionIn(), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """「需要跟進」— escalate; the reason stays internal (ops board)."""
    return _apply_task_action(db, task_id, "flag", body.note)


# ---------------------------------------------------------------------------
# Ops / demand board
# ---------------------------------------------------------------------------

@app.get("/api/ops/board")
def ops_board(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Duty-manager view: per booking × role status, metrics, demand per station
    and flight, staffing load."""
    statuses = ("pending", "received", "done", "amended", "flagged", "notified")
    travel_date = db.execute("SELECT travel_date FROM bookings ORDER BY id LIMIT 1").fetchone()
    travel_date = travel_date["travel_date"] if travel_date else now_hkt()[:10]
    # Only app-channel work counts as open: a remark-channel task waits on Customer Care,
    # whose own card already shows (REDESIGN.md §5.3).
    live_sql = "(t.channel='app' OR t.status='notified')"
    rows = []
    for b in db.execute(
        "SELECT b.*, p.display_name, p.party_note FROM bookings b JOIN passengers p ON p.pnr=b.pnr"
        " WHERE b.travel_date=? ORDER BY b.id", (travel_date,),
    ).fetchall():
        by_role = {r: {s: 0 for s in statuses} for r in ROLES}
        for t in db.execute(
            f"""SELECT t.role, t.status FROM tasks t JOIN needs n ON n.id=t.need_id
                JOIN assistance_requests r ON r.id=n.request_id
                WHERE r.pnr=? AND r.status='active' AND t.status!='cancelled' AND {live_sql}""", (b["pnr"],),
        ).fetchall():
            by_role[t["role"]][t["status"]] += 1
        rows.append({
            "pnr": b["pnr"],
            "passenger": f"{b['display_name']} {b['party_note'] or ''}".strip(),
            "route": " → ".join(x for x in (b["origin"], b["via"], b["destination"]) if x),
            "flights": " · ".join(x for x in (b["flight_1"], b["flight_2"]) if x),
            "by_role": by_role,
        })

    # Demand per station stage and flight, from confirmed needs only (REDESIGN.md §4.4).
    demand: dict[tuple[str, str], dict] = {}
    stages_by_pnr: dict[str, dict[str, dict]] = {}
    bookings: dict[str, dict] = {}
    due_soon = 0
    now = datetime.strptime(now_hkt(), "%Y-%m-%d %H:%M")
    for t in db.execute(
        """SELECT r.pnr, t.stage, t.status, t.channel, n.code, n.scope FROM tasks t JOIN needs n ON n.id=t.need_id
           JOIN assistance_requests r ON r.id=n.request_id JOIN bookings b ON b.pnr=r.pnr
           WHERE r.status='active' AND t.status!='cancelled' AND t.role!='cs' AND b.travel_date=?""",
        (travel_date,),
    ).fetchall():
        if t["pnr"] not in stages_by_pnr:
            bookings[t["pnr"]] = booking_row(db, t["pnr"])
            stages_by_pnr[t["pnr"]] = _stage_titles(bookings[t["pnr"]])
        st = stages_by_pnr[t["pnr"]].get(t["stage"])
        need = get_need(t["code"], t["scope"])
        if not st or need is None:
            continue
        b = bookings[t["pnr"]]
        due_soon += t["channel"] == "app" and t["status"] == "pending" and _due_soon(
            {"time": st["time"], "travel_date": travel_date,
             "delay_minutes": _stage_delay(b, t["stage"], _delays(db, b))}, now)
        d = demand.setdefault((st["place"], st["kind"]), {
            "place": st["place"], "kind": st["kind"], "title": st["title"], "title_en": st["title_en"],
            "time": st["time"], "open_tasks": 0, "_pnrs": set(), "_needs": {}})
        d["open_tasks"] += t["channel"] == "app" and t["status"] in ("pending", "received", "flagged")
        d["_pnrs"].add(t["pnr"])
        d["_needs"].setdefault(need, set()).add(t["pnr"])
    demand_rows = []
    for d in sorted(demand.values(), key=lambda d: ("(+1)" in (d["time"] or ""), d["time"] or "", d["place"])):
        pnrs, needs = d.pop("_pnrs"), d.pop("_needs")
        demand_rows.append({**d, "bookings": len(pnrs), "needs": [
            {"label_zh": n.label_zh, "label_en": n.label_en, "count": len(needs[n])}
            for n in sorted(needs, key=CATALOG.index)]})

    live = db.execute(
        """SELECT t.status, t.received_at, t.done_at FROM tasks t JOIN needs n ON n.id=t.need_id
           JOIN assistance_requests r ON r.id=n.request_id JOIN bookings b ON b.pnr=r.pnr
           WHERE r.status='active' AND t.status!='cancelled' AND t.channel='app' AND b.travel_date=?""",
        (travel_date,),
    ).fetchall()
    handled = [
        row["mins"] for row in db.execute(
            """SELECT (julianday(t.done_at) - julianday(t.received_at)) * 24 * 60 AS mins
               FROM tasks t JOIN needs n ON n.id=t.need_id JOIN assistance_requests r ON r.id=n.request_id
               WHERE r.status='active' AND t.done_at IS NOT NULL AND t.received_at IS NOT NULL""",
        ).fetchall()
    ]
    done_count = sum(t["status"] in ("done", "amended") for t in live)

    open_by_role = {r: sum(row["by_role"][r][s] for row in rows for s in ("pending", "received", "flagged"))
                    for r in ROLES}
    staffing = [
        {"role": s["role"], "label_zh": ROLE_LABELS_ZH[s["role"]], "headcount": s["headcount"],
         "open_tasks": open_by_role.get(s["role"], 0)}
        for s in db.execute("SELECT role, headcount FROM staffing WHERE travel_date=? ORDER BY rowid",
                            (travel_date,)).fetchall()
    ]
    return {
        "date": travel_date,
        "rows": rows,
        "metrics": {
            "avg_handle_minutes": round(sum(handled) / len(handled), 1) if handled else None,
            "due_soon": due_soon,
            "completion_pct": round(100 * done_count / len(live)) if live else None,
            "followups": sum(t["status"] == "flagged" for t in live),
            "open": sum(t["status"] in ("pending", "received") for t in live),
        },
        "demand": demand_rows,
        "staffing": staffing,
    }
