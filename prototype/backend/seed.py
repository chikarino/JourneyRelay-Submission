"""JourneyRelay — seed data (ALL passengers are fictional).

Flights use public Cathay schedules (winter 2026) so the story is realistic:
  CX100  SYD 15:05 → HKG 21:30
  CX251  HKG 23:00 → LHR 05:25 (+1)
All three bookings share these flights, so the Hong Kong transfer desk and gate
see several passengers at once, as they would on a real shift.

Scenarios (REDESIGN.md §7):
  midjourney  陳太 shared her needs at booking; Sydney is done, CX100 crew has
              received, Hong Kong onwards is still open. (default)
  fresh       陳太 has just booked and shared nothing yet — demo the first
              "say it once" from scratch.
  family-transfer  陳太 travels with two children and starts with no saved needs.

Run:  python -m backend.seed [fresh]       (or POST /api/demo/reset from the demo page)
Tasks are created by the same routing code the API uses (journey.route_request),
so seeded data can never drift from live behaviour.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.catalog import get_need  # noqa: E402
from backend.db import ROLE_LABELS_EN, ROLE_LABELS_ZH, connect, insert_ledger, reset_schema  # noqa: E402
from backend.journey import file_remarks, journey_stages, route_request  # noqa: E402

TRAVEL_DATE = "2026-11-14"  # hackathon on-day — the journey happens "today" in the demo
D = TRAVEL_DATE

# Flight numbers and local times are the published schedule for these dates, read from the
# OAG Flight Info API on 2026-11-13. Passengers are fictional.
BOOKINGS = [
    # pnr, name, party, origin, via, destination, f1, f2, f1_dep, f1_arr, f2_dep, f2_arr
    ("CXDEMO1", "陳太", "+ 1 名兒童", "悉尼 SYD", "香港 HKG", "倫敦 LHR", "CX100", "CX251",
     "15:15", "21:30", "23:00", "05:25 (+1)"),
    ("CXDEMO2", "王先生", None, "悉尼 SYD", None, "香港 HKG", "CX100", None, "15:15", "21:30", None, None),
    ("CXDEMO3", "李女士", "+ 1 名兒童", "香港 HKG", None, "倫敦 LHR", "CX251", None,
     "23:00", "05:25 (+1)", None, None),
    # 陳太's return trip: nothing shared yet, so the needs passport can offer the outbound needs.
    ("CXDEMO4", "陳太", "+ 1 名兒童", "倫敦 LHR", "香港 HKG", "悉尼 SYD", "CX252", "CX139",
     "11:00", "07:30 (+1)", "08:45 (+1)", "20:50 (+1)"),
    # 陳太's earlier trip (completed), so today's booking can offer what she confirmed then.
    # Kept last: the ops board takes its date from the first booking.
    ("CXDEMO0", "陳太", "+ 1 名兒童", "悉尼 SYD", None, "香港 HKG", "CX100", None,
     "14:05", "21:30", None, None),
]
# Same traveller across bookings (needs passport, REDESIGN.md §5.4).
MEMBERS = {"CXDEMO0": "MEMBER-CHAN", "CXDEMO1": "MEMBER-CHAN", "CXDEMO4": "MEMBER-CHAN"}
TRAVEL_DATES = {"CXDEMO0": "2026-09-12", "CXDEMO4": "2026-11-28"}
PAST_TRIP_NEEDS = [("QUIET_WAIT", "full"), ("SEAT_ADJACENT", "full")]


def _add_request(conn: sqlite3.Connection, pnr: str, needs: list[tuple[str, str]],
                 created: str, confirmed: str) -> int:
    req = conn.execute(
        "INSERT INTO assistance_requests (pnr, version, status, raw_text, created_at, confirmed_at)"
        " VALUES (?, 1, 'active', NULL, ?, ?)", (pnr, created, confirmed),
    ).lastrowid
    for code, scope in needs:
        conn.execute("INSERT INTO needs (request_id, code, scope) VALUES (?,?,?)", (req, code, scope))
    route_request(conn, pnr, req, confirmed)
    labels = "、".join(get_need(c, s).label_zh for c, s in needs)
    labels_en = ", ".join(get_need(c, s).label_en for c, s in needs)
    n_roles = conn.execute(
        """SELECT COUNT(DISTINCT t.role || t.stage) c FROM tasks t JOIN needs n ON n.id=t.need_id
           WHERE n.request_id=?""", (req,),
    ).fetchone()["c"]
    insert_ledger(conn, pnr, 1, None, "request_confirmed",
                  f"你確認分享：{labels}。客服會先核對並寫入訂位紀錄，沿途 {n_roles} 個崗位隨後收到。",
                  "passenger", at=confirmed,
                  detail_en=f"You shared: {labels_en}. Customer Care checks and files them first; "
                            f"{n_roles} teams along the journey then receive them.")
    return req


def _progress(conn: sqlite3.Connection, pnr: str, stage: str, role: str, status: str,
              received: str | None, done: str | None = None, note: str | None = None) -> None:
    """Move every task of (pnr, stage, role) to a status, with a ledger event per task."""
    b = dict(conn.execute(
        "SELECT b.*, p.display_name FROM bookings b JOIN passengers p ON p.pnr=b.pnr WHERE b.pnr=?", (pnr,),
    ).fetchone())
    st = {s["key"]: s for s in journey_stages(b)}[stage]
    who = ROLE_LABELS_ZH[role] if stage == "booking" else f"{st['title']} · {ROLE_LABELS_ZH[role]}"
    who_en = ROLE_LABELS_EN[role] if stage == "booking" else f"{st['title_en']} · {ROLE_LABELS_EN[role]}"
    rows = conn.execute(
        """SELECT t.id, n.code, n.scope FROM tasks t JOIN needs n ON n.id=t.need_id
           JOIN assistance_requests r ON r.id=n.request_id
           WHERE r.pnr=? AND t.stage=? AND t.role=?""", (pnr, stage, role),
    ).fetchall()
    for t in rows:
        conn.execute("UPDATE tasks SET status=?, received_at=?, done_at=?, note=? WHERE id=?",
                     (status, received, done, note, t["id"]))
        label = "整份安排" if role == "cs" else get_need(t["code"], t["scope"]).label_zh
        label_en = "Full arrangement review" if role == "cs" else get_need(t["code"], t["scope"]).label_en
        if received:
            insert_ledger(conn, pnr, 1, role, "task_receive", f"{who}：已收到「{label}」", role,
                          stage=stage, at=received,
                          detail_en=f"{who_en}: received \"{label_en}\"")
        if status == "done":
            insert_ledger(conn, pnr, 1, role, "task_done", f"{who}：已安排「{label}」", role,
                          stage=stage, at=done,
                          detail_en=f"{who_en}: arranged \"{label_en}\"")
        if status == "flagged":
            insert_ledger(conn, pnr, 1, role, "task_flag", f"{who}：正在跟進「{label}」", role,
                          stage=stage, at=received,
                          detail_en=f"{who_en}: is following up on \"{label_en}\"")


def load_demo_data(conn: sqlite3.Connection, scenario: str = "midjourney") -> dict:
    """Rebuild every table in place and load the synthetic story."""
    reset_schema(conn)
    for (pnr, name, party, origin, via, dest, f1, f2, f1_dep, f1_arr, f2_dep, f2_arr) in BOOKINGS:
        member = MEMBERS.get(pnr)
        if scenario == "family-transfer" and pnr == "CXDEMO1":
            party = "+ 2 名兒童"
            member = None  # This fictional family has no earlier assistance to carry over.
        conn.execute("INSERT INTO passengers (pnr, display_name, party_note, member_id) VALUES (?,?,?,?)",
                     (pnr, name, party, member))
        conn.execute(
            "INSERT INTO bookings (pnr, origin, via, destination, flight_1, flight_2, f1_dep, f1_arr,"
            " f2_dep, f2_arr, travel_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pnr, origin, via, dest, f1, f2, f1_dep, f1_arr, f2_dep, f2_arr, TRAVEL_DATES.get(pnr, TRAVEL_DATE)),
        )

    # 陳太's September trip: needs confirmed, journey over. Only the needs are kept, no
    # tasks, so nothing from it reaches today's staff boards.
    conn.execute("INSERT INTO assistance_requests (pnr, version, status, raw_text, created_at, confirmed_at)"
                 " VALUES ('CXDEMO0', 1, 'active', NULL, '2026-09-01 20:10', '2026-09-01 20:12')")
    past = conn.execute("SELECT id FROM assistance_requests WHERE pnr='CXDEMO0'").fetchone()["id"]
    for code, scope in PAST_TRIP_NEEDS:
        conn.execute("INSERT INTO needs (request_id, code, scope) VALUES (?,?,?)", (past, code, scope))

    # Case 1 — 陳太 + child, SYD → HKG → LHR (the one-pager case).
    if scenario == "midjourney":
        _add_request(conn, "CXDEMO1",
                     [("QUIET_WAIT", "full"), ("PREBOARD", "full"), ("SEAT_ADJACENT", "full"), ("TEXT_INFO", "full")],
                     created="2026-10-20 14:32", confirmed="2026-10-20 14:35")
        _progress(conn, "CXDEMO1", "booking", "cs", "done", "2026-10-20 14:37", "2026-10-20 14:39")
        file_remarks(conn, "CXDEMO1", 1, "2026-10-20 14:39")
        # Ledger rows are inserted in time order: the passenger view lists them by id.
        conn.execute("UPDATE bookings SET reconfirmed_at=? WHERE pnr='CXDEMO1'", ("2026-11-12 15:10",))
        insert_ledger(conn, "CXDEMO1", 1, None, "reconfirmed", "你確認出發前安排仍然適用。", "passenger",
                      at="2026-11-12 15:10",
                      detail_en="You confirmed your pre-departure arrangements still apply.")
        # Outstations and crew work from the remark; Hong Kong's transfer desk has picked the family up.
        _progress(conn, "CXDEMO1", "transfer", "arrival", "received", f"{D} 14:40")

    # Case 2 — 王先生, wheelchair for the whole journey, CX100 SYD → HKG.
    _add_request(conn, "CXDEMO2", [("WHEELCHAIR", "full")],
                 created="2026-11-10 09:12", confirmed="2026-11-10 09:15")
    _progress(conn, "CXDEMO2", "booking", "cs", "done", "2026-11-10 09:17", "2026-11-10 09:19")
    file_remarks(conn, "CXDEMO2", 1, "2026-11-10 09:19")
    _progress(conn, "CXDEMO2", "arr", "arrival", "received", f"{D} 14:30")

    # Case 3 — 李女士 + child, CX251 HKG → LHR; the HKG gate has flagged pre-boarding.
    _add_request(conn, "CXDEMO3", [("QUIET_WAIT", "full"), ("PREBOARD", "full")],
                 created="2026-11-12 18:40", confirmed="2026-11-12 18:44")
    _progress(conn, "CXDEMO3", "booking", "cs", "done", "2026-11-12 18:46", "2026-11-12 18:47")
    _progress(conn, "CXDEMO3", "dep", "checkin", "done", f"{D} 20:30", f"{D} 20:41")
    _progress(conn, "CXDEMO3", "dep", "gate", "flagged", f"{D} 21:05",
              note="登機閘口臨時更改，預先登機時段待新閘口確認")

    # Synthetic staffing for the demand board.
    for role, headcount in [("cs", 3), ("checkin", 6), ("gate", 4), ("cabin", 8), ("arrival", 5)]:
        conn.execute("INSERT INTO staffing (travel_date, role, headcount) VALUES (?,?,?)",
                     (TRAVEL_DATE, role, headcount))
    conn.commit()
    n_tasks = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
    return {"bookings": len(BOOKINGS), "tasks": n_tasks}


def seed(scenario: str = "midjourney") -> None:
    conn = connect()
    try:
        counts = load_demo_data(conn, scenario)
    finally:
        conn.close()
    print(f"Seeded scenario '{scenario}': {counts['bookings']} bookings, {counts['tasks']} tasks, "
          f"travel date {TRAVEL_DATE}")


if __name__ == "__main__":
    seed("fresh" if "fresh" in sys.argv[1:] else "midjourney")
