"""JourneyRelay — journey stages and stage-aware task routing.

A booking is turned into ordered stages the passenger and staff both recognise:

  booking  (Customer Care review, before travel)
  dep      departure station          e.g. 悉尼出發 · SYD
  f1       first flight               e.g. 航班 CX100
  transfer connecting station         e.g. 香港轉機 · HKG   (absent on direct flights)
  f2       second flight              e.g. 航班 CX251
  arr      final arrival station      e.g. 倫敦抵達 · LHR

Catalogue routes name a stage *kind* (dep / flight / transfer / arr); this module
expands them into the stages of a particular booking and creates the tasks.
"""

from __future__ import annotations

import sqlite3

from .catalog import (
    CS_FILING_INSTRUCTIONS, CS_REVIEW_INSTRUCTION, CS_REVIEW_INSTRUCTION_EN, CS_UPDATE_INSTRUCTION,
    CS_UPDATE_INSTRUCTION_EN, get_need,
)
from .db import insert_ledger

STAGE_ORDER = ["booking", "dep", "f1", "transfer", "f2", "arr"]

# Stations where Cathay's own teams work from the task cards (REDESIGN.md §5.3).
HOME_STATIONS = {"HKG"}


def task_channel(stage: dict, role: str) -> str:
    """How a task reaches its team. 'app': a task card the team acknowledges
    (Customer Care, home-station roles). 'remark': outstation handlers and
    cabin crew, who get the booking remark through existing systems."""
    return "app" if role == "cs" or stage["place"] in HOME_STATIONS else "remark"

# Chinese city names used in bookings -> their English forms (stage title_en).
CITY_EN = {"悉尼": "Sydney", "香港": "Hong Kong", "倫敦": "London"}


def split_place(text: str | None) -> tuple[str, str]:
    """'悉尼 SYD' -> ('悉尼', 'SYD')."""
    if not text:
        return "", ""
    parts = text.rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (text, text)


def journey_stages(b: dict) -> list[dict]:
    """Ordered stages for a booking row. `place` is what staff filter by:
    a station code for station stages, a flight number for flight stages.
    Each stage carries zh title/sub plus their English mirrors (title_en/sub_en)."""
    o_city, o = split_place(b["origin"])
    d_city, d = split_place(b["destination"])
    via_city, via = split_place(b.get("via"))
    first_to = via or d

    stages = [
        {"key": "booking", "kind": "booking", "title": "訂位及客服", "place": "CS", "time": None,
         "sub": "出發前核對安排",
         "title_en": "Booking & Customer Care", "sub_en": "Confirm arrangements before travel"},
        {"key": "dep", "kind": "dep", "title": f"{o_city}出發", "place": o, "time": b["f1_dep"],
         "sub": f"{b['flight_1']} {b['f1_dep']} 起飛",
         "title_en": f"{CITY_EN.get(o_city, o_city)} Departure",
         "sub_en": f"{b['flight_1']} departs {b['f1_dep']}"},
        {"key": "f1", "kind": "flight", "title": f"航班 {b['flight_1']}", "place": b["flight_1"],
         "time": b["f1_dep"], "sub": f"{o} {b['f1_dep']} → {first_to} {b['f1_arr']}",
         "title_en": f"Flight {b['flight_1']}",
         "sub_en": f"{o} {b['f1_dep']} → {first_to} {b['f1_arr']}"},
    ]
    if via:
        stages.append({"key": "transfer", "kind": "transfer", "title": f"{via_city}轉機", "place": via,
                       "time": b["f1_arr"], "sub": f"{b['f1_arr']} 抵達 · {b['f2_dep']} 轉乘 {b['flight_2']}",
                       "title_en": f"{CITY_EN.get(via_city, via_city)} Transfer",
                       "sub_en": f"Arrive {b['f1_arr']} · connect to {b['flight_2']} at {b['f2_dep']}"})
        stages.append({"key": "f2", "kind": "flight", "title": f"航班 {b['flight_2']}", "place": b["flight_2"],
                       "time": b["f2_dep"], "sub": f"{via} {b['f2_dep']} → {d} {b['f2_arr']}",
                       "title_en": f"Flight {b['flight_2']}",
                       "sub_en": f"{via} {b['f2_dep']} → {d} {b['f2_arr']}"})
    last_arr = b["f2_arr"] if via else b["f1_arr"]
    stages.append({"key": "arr", "kind": "arr", "title": f"{d_city}抵達", "place": d, "time": last_arr,
                   "sub": f"{last_arr} 抵達",
                   "title_en": f"{CITY_EN.get(d_city, d_city)} Arrival",
                   "sub_en": f"Arrive {last_arr}"})
    return stages


def stage_keys(stages: list[dict], kind: str) -> list[str]:
    """Concrete stage keys for a catalogue route kind on this booking."""
    if kind == "flight":
        return [s["key"] for s in stages if s["kind"] == "flight"]
    return [s["key"] for s in stages if s["kind"] == kind]


def booking_row(conn: sqlite3.Connection, pnr: str) -> dict | None:
    row = conn.execute(
        "SELECT b.*, p.display_name, p.party_note FROM bookings b"
        " JOIN passengers p ON p.pnr=b.pnr WHERE b.pnr=?", (pnr,),
    ).fetchone()
    return dict(row) if row else None


def route_request(conn: sqlite3.Connection, pnr: str, request_id: int,
                  created_at: str) -> list[dict]:
    """Create role- and stage-scoped tasks for a confirmed request.

    Delta routing: a task is skipped when this booking already holds a live
    (not cancelled) task for the same need, role and stage — so an update only
    reaches the roles it actually changes ("原有安排不變").
    Returns the created tasks as {need_id, code, scope, role, stage}.
    """
    b = booking_row(conn, pnr)
    stages = journey_stages(b)
    by_key = {s["key"]: s for s in stages}
    needs = conn.execute(
        "SELECT id, code, scope FROM needs WHERE request_id=? AND cancelled_at IS NULL ORDER BY id",
        (request_id,),
    ).fetchall()
    created: list[dict] = []

    def live_task_exists(code: str, scope: str, role: str, stage: str) -> bool:
        return conn.execute(
            """SELECT 1 FROM tasks t JOIN needs n ON n.id=t.need_id
               JOIN assistance_requests r ON r.id=n.request_id
               WHERE r.pnr=? AND r.status='active' AND n.code=? AND n.scope=?
                 AND t.role=? AND t.stage=? AND t.status!='cancelled' LIMIT 1""",
            (pnr, code, scope, role, stage),
        ).fetchone() is not None

    for n in needs:
        need = get_need(n["code"], n["scope"])
        if need is None:
            continue
        for route in need.routes:
            for stage in stage_keys(stages, route.stage):
                if live_task_exists(n["code"], n["scope"], route.role, stage):
                    continue
                conn.execute(
                    "INSERT INTO tasks (need_id, role, stage, channel, instruction_zh, instruction_en, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (n["id"], route.role, stage, task_channel(by_key[stage], route.role),
                     route.instruction_zh, route.instruction_en, created_at),
                )
                created.append({"need_id": n["id"], "code": n["code"], "scope": n["scope"],
                                "role": route.role, "stage": stage})

    if needs and (created or not _filings(conn, pnr)) and open_filing_card(conn, pnr, needs[0]["id"], created_at):
        created.append({"need_id": needs[0]["id"], "code": needs[0]["code"], "scope": needs[0]["scope"],
                        "role": "cs", "stage": "booking"})
    return created


def _filings(conn: sqlite3.Connection, pnr: str) -> list[str]:
    """Statuses of this booking's Customer Care review and remark-update cards."""
    marks = ",".join("?" * len(CS_FILING_INSTRUCTIONS))
    return [f["status"] for f in conn.execute(
        f"""SELECT t.status FROM tasks t JOIN needs n ON n.id=t.need_id
            JOIN assistance_requests r ON r.id=n.request_id
            WHERE r.pnr=? AND t.role='cs' AND t.instruction_zh IN ({marks})""",
        (pnr, *CS_FILING_INSTRUCTIONS),
    ).fetchall()]


def open_filing_card(conn: sqlite3.Connection, pnr: str, need_id: int, at: str) -> bool:
    """Give Customer Care a card to file the remark: a review the first time, a
    remark update after that. One open card at a time (REDESIGN.md §5.3)."""
    filings = _filings(conn, pnr)
    if any(status in ("pending", "received", "flagged") for status in filings):
        return False
    zh, en = ((CS_UPDATE_INSTRUCTION, CS_UPDATE_INSTRUCTION_EN) if filings
              else (CS_REVIEW_INSTRUCTION, CS_REVIEW_INSTRUCTION_EN))
    conn.execute(
        "INSERT INTO tasks (need_id, role, stage, instruction_zh, instruction_en, created_at)"
        " VALUES (?,?,?,?,?,?)", (need_id, "cs", "booking", zh, en, at),
    )
    return True


def file_remarks(conn: sqlite3.Connection, pnr: str, version: int, at: str) -> int:
    """Customer Care has filed the booking remark: every waiting remark-channel
    task counts as notified, and the passenger gets one ledger line.

    'Notified' is all we claim for outstations and crew — the remark was sent,
    not that the arrangement is in place (REDESIGN.md §5.3)."""
    count = conn.execute(
        """UPDATE tasks SET status='notified', done_at=? WHERE status='pending' AND channel='remark'
           AND need_id IN (SELECT n.id FROM needs n JOIN assistance_requests r ON r.id=n.request_id
                           WHERE r.pnr=? AND r.status='active')""", (at, pnr),
    ).rowcount
    if count:
        insert_ledger(conn, pnr, version, "cs", "remark_filed",
                      f"客服：已把需要寫入訂位紀錄，外站及機組的 {count} 項安排已獲通知", "cs",
                      stage="booking", at=at,
                      detail_en=f"Customer Care: filed your needs in the booking record; "
                                f"{count} outstation and crew arrangements have been notified")
    return count
