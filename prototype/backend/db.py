"""JourneyRelay — SQLite persistence layer (stdlib sqlite3, no ORM).

Design notes / assumptions
--------------------------
* Single-file DB at backend/journeyrelay.db. WAL mode so the FastAPI server
  and the seed script can run concurrently during a live demo.
* Privacy rule (research doc `06-無障礙 §3.6`): staff-facing queries must never
  return the passenger's raw free text or any diagnostic wording. Local-LLM
  analysis is stateless, so new requests do not persist `raw_text`. The column
  remains nullable for compatibility with older local databases.
* Role model mirrors demov3.html ROLES: cs / checkin / gate / cabin / arrival.
* Journey stages (booking / dep / f1 / transfer / f2 / arr) are derived from the
  booking in journey.py; every task records the stage it belongs to.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "journeyrelay.db"

# Canonical role order used across UI + API (matches one-pager-v6 journey row).
ROLES: list[str] = ["cs", "checkin", "gate", "cabin", "arrival"]

ROLE_LABELS_ZH: dict[str, str] = {
    "cs": "客服",
    "checkin": "辦理登機手續",
    "gate": "閘口",
    "cabin": "機艙組員",
    "arrival": "抵達／轉機站",
}

ROLE_LABELS_EN: dict[str, str] = {
    "cs": "Customer Care",
    "checkin": "Check-in",
    "gate": "Gate",
    "cabin": "Cabin Crew",
    "arrival": "Arrival / Transit",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS passengers (
  id            INTEGER PRIMARY KEY,
  pnr           TEXT UNIQUE NOT NULL,          -- booking reference code (staff see only this + functional phrases)
  display_name  TEXT NOT NULL,                 -- masked/pseudonymised, e.g. "陳太"
  party_note    TEXT,                          -- e.g. "+ 1 名兒童"
  member_id     TEXT,                          -- same traveller across bookings (needs passport, REDESIGN.md §5.4)
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now','+8 hours'))
);

CREATE TABLE IF NOT EXISTS bookings (
  id            INTEGER PRIMARY KEY,
  pnr           TEXT UNIQUE NOT NULL REFERENCES passengers(pnr),
  origin        TEXT NOT NULL,                 -- "城市 IATA", e.g. "悉尼 SYD"
  via           TEXT,                          -- connecting station, NULL for direct flights
  destination   TEXT NOT NULL,                 -- e.g. "倫敦 LHR"
  flight_1      TEXT NOT NULL,                 -- public CX flight numbers; passengers are fictional
  flight_2      TEXT,
  f1_dep        TEXT,                          -- local times "HH:MM" (may carry "(+1)")
  f1_arr        TEXT,
  f2_dep        TEXT,
  f2_arr        TEXT,
  travel_date   TEXT NOT NULL,                 -- YYYY-MM-DD
  reconfirmed_at TEXT                          -- passenger confirmed "arrangements still apply" before departure
);

CREATE TABLE IF NOT EXISTS assistance_requests (
  id            INTEGER PRIMARY KEY,
  pnr           TEXT NOT NULL REFERENCES passengers(pnr),
  version       INTEGER NOT NULL DEFAULT 1,    -- 1 = first description, 2+ = updates
  status        TEXT NOT NULL DEFAULT 'draft', -- draft | active
  raw_text      TEXT,                          -- legacy nullable field; new requests store NULL
  analysis_source TEXT,                        -- local | api
  analysis_status TEXT,                        -- ok | empty | error
  analysis_model TEXT,
  analysis_latency_ms INTEGER,
  analysis_error_code TEXT,
  analysis_situation TEXT,                     -- one-sentence situation restatement
  analysis_suggestions TEXT,                   -- JSON [{code,scope,reason}] the passenger can pick from
  analysis_referrals TEXT,                     -- JSON [referral code] asked for but not arrangeable here
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now','+8 hours')),
  confirmed_at  TEXT
);

CREATE TABLE IF NOT EXISTS needs (
  id            INTEGER PRIMARY KEY,
  request_id    INTEGER NOT NULL REFERENCES assistance_requests(id) ON DELETE CASCADE,
  code          TEXT NOT NULL,                 -- catalogue code, e.g. QUIET_WAIT (see catalog.py)
  scope         TEXT NOT NULL DEFAULT 'full',  -- full | transfer
  cancelled_at  TEXT,                          -- passenger said "no longer needed"
  UNIQUE(request_id, code, scope)
);

CREATE TABLE IF NOT EXISTS tasks (
  id            INTEGER PRIMARY KEY,
  need_id       INTEGER NOT NULL REFERENCES needs(id) ON DELETE CASCADE,
  role          TEXT NOT NULL,                 -- one of ROLES
  stage         TEXT NOT NULL,                 -- booking | dep | f1 | transfer | f2 | arr (journey.py)
  instruction_zh TEXT NOT NULL,                -- neutral, actionable wording for the staff card
  instruction_en TEXT NOT NULL DEFAULT '',     -- English mirror of instruction_zh (bilingual cards)
  channel       TEXT NOT NULL DEFAULT 'app',   -- app (task card, acknowledged) | remark (booking remark only)
  status        TEXT NOT NULL DEFAULT 'pending', -- pending | received | done | amended | flagged | cancelled
                                               -- | notified (remark channel: the remark has been filed)
  note          TEXT,                          -- amend note (passenger-visible) or flag reason (internal)
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now','+8 hours')),
  received_at   TEXT,
  done_at       TEXT
);

CREATE TABLE IF NOT EXISTS ledger_events (
  id            INTEGER PRIMARY KEY,
  pnr           TEXT NOT NULL,
  request_version INTEGER NOT NULL,
  role          TEXT,                          -- which role the event concerns (NULL = passenger/system)
  stage         TEXT,
  event_type    TEXT NOT NULL,                 -- request_confirmed|need_cancelled|reconfirmed|task_received|task_done|task_amended|task_flagged
  detail_zh     TEXT,                          -- passenger-readable sentence (flag reasons are never written here)
  detail_en     TEXT,                          -- English mirror of detail_zh (Task 6 writes it; NULL until then)
  actor         TEXT,                          -- 'passenger' | role id | 'system'
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now','+8 hours'))
);

CREATE TABLE IF NOT EXISTS staffing (
  id            INTEGER PRIMARY KEY,
  travel_date   TEXT NOT NULL,                 -- YYYY-MM-DD
  role          TEXT NOT NULL,                 -- one of ROLES
  headcount     INTEGER NOT NULL               -- synthetic on-shift count for the demand board
);

-- Runtime key-value settings (currently the selected AI engine). Deliberately
-- NOT listed in TABLES: reset_schema must not clear the engine choice.
CREATE TABLE IF NOT EXISTS app_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_role ON tasks(role, stage, status);
CREATE INDEX IF NOT EXISTS idx_requests_pnr ON assistance_requests(pnr, version);
CREATE INDEX IF NOT EXISTS idx_ledger_pnr ON ledger_events(pnr, created_at);
"""

TABLES = ["ledger_events", "tasks", "needs", "assistance_requests", "bookings", "passengers", "staffing"]


def connect() -> sqlite3.Connection:
    # FastAPI may open, use and close a request's connection on different
    # worker threads; each connection is still used by one request at a time.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    """Per-request connection for FastAPI dependencies.

    Plain generator (NOT @contextmanager): FastAPI's Depends() must see a real
    generator function to drive yield/teardown correctly.
    """
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def now_hkt() -> str:
    """Timestamps are stored as 'YYYY-MM-DD HH:MM' (HKT in the demo context).

    We use a fixed demo clock offset of +8h from UTC so ledger ordering is
    stable regardless of the host timezone.
    """
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def insert_ledger(conn: sqlite3.Connection, pnr: str, version: int, role: str | None,
                  event_type: str, detail_zh: str, actor: str, stage: str | None = None,
                  at: str | None = None, detail_en: str | None = None) -> None:
    conn.execute(
        "INSERT INTO ledger_events (pnr, request_version, role, stage, event_type, detail_zh, detail_en, actor, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (pnr, version, role, stage, event_type, detail_zh, detail_en, actor, at or now_hkt()),
    )


def reset_schema(conn: sqlite3.Connection) -> None:
    """Drop and recreate every table in place (used by the seed and /api/demo/reset).

    Dropping tables instead of deleting the DB file keeps it safe to reset while
    the API is running.
    """
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns to databases created by an earlier prototype."""
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(assistance_requests)").fetchall()
    }
    additions = {
        "analysis_source": "TEXT",
        "analysis_status": "TEXT",
        "analysis_model": "TEXT",
        "analysis_latency_ms": "INTEGER",
        "analysis_error_code": "TEXT",
        "analysis_situation": "TEXT",
        "analysis_suggestions": "TEXT",
        "analysis_referrals": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE assistance_requests ADD COLUMN {name} {sql_type}")
    # insert_ledger writes detail_en (consumed by the bilingual ledger in Task 6);
    # databases created before that column existed need the ALTER TABLE.
    ledger_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ledger_events)").fetchall()
    }
    if "detail_en" not in ledger_columns:
        conn.execute("ALTER TABLE ledger_events ADD COLUMN detail_en TEXT")
    # Task 6 bilingual data: route_request writes instruction_en alongside
    # instruction_zh; databases created before that column existed need the
    # ALTER TABLE (NOT NULL is only legal here with a non-NULL default).
    tasks_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }
    if "instruction_en" not in tasks_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN instruction_en TEXT NOT NULL DEFAULT ''")
