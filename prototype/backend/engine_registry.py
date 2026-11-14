"""JourneyRelay — runtime AI-engine selection.

The USE_DEEPSEEK_API environment variable decides which engine the API starts
with. The /demo header can switch engines live; that choice is kept in
app_settings so POST /api/demo/reset does not lose it mid-presentation, and the
API clears it on startup so USE_DEEPSEEK_API applies again after a restart.
"""

from __future__ import annotations

import os
import sqlite3

from .engines import OpenAICompatEngine, OllamaEngine

ENGINES = {"local": OllamaEngine, "api": OpenAICompatEngine}


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value),
    )


def default_engine_name() -> str:
    """USE_DEEPSEEK_API=true: DeepSeek's hosted API; otherwise local Ollama."""
    use_api = os.getenv("USE_DEEPSEEK_API", "").strip().lower() in {"1", "true", "yes", "on"}
    return "api" if use_api else "local"


def current_engine_name(conn: sqlite3.Connection) -> str:
    stored = get_setting(conn, "ai_engine")
    if stored in ENGINES:
        return stored
    return default_engine_name()


def set_engine(conn: sqlite3.Connection, name: str) -> None:
    if name not in ENGINES:
        raise ValueError(f"Unknown engine '{name}'. Valid: {', '.join(ENGINES)}")
    set_setting(conn, "ai_engine", name)


def clear_engine_choice(conn: sqlite3.Connection) -> None:
    """Forget the live /demo switch so default_engine_name() applies again."""
    conn.execute("DELETE FROM app_settings WHERE key='ai_engine'")


def engine(conn: sqlite3.Connection) -> OllamaEngine | OpenAICompatEngine:
    """The selected engine; raises AnalysisError when it is not configured."""
    return ENGINES[current_engine_name(conn)]()
