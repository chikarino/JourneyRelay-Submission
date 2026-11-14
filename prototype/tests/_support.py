"""Shared helpers for the API tests: a scripted AI engine and a throwaway database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db
import backend.main as main
from backend.analysis import AnalysisResult
from backend.catalog import get_need


class FakeEngine:
    """Stands in for an AI engine.

    `by_text` maps passenger text to the `CODE:scope` keys to return; otherwise
    the given `events` are streamed after the status event, or `error` ends it.
    """

    name = "local"
    SITUATION = "（測試）情況摘要"

    def __init__(self, events=(), error: str | None = None,
                 by_text: dict[str, list[str]] | None = None):
        self._events = list(events)
        self._error = error
        self._by_text = by_text
        self.calls: list[tuple[str, dict | None]] = []

    def model_label(self) -> str:
        return "fake-model"

    def stream_analyse(self, text: str, context: dict | None):
        self.calls.append((text, context))
        yield {"type": "status", "engine": self.name, "model": "fake-model"}
        if self._error:
            yield {"type": "error", "code": self._error}
            return
        if self._by_text is not None:
            needs = tuple(get_need(*key.split(":")) for key in self._by_text[text])
            yield {"type": "analysis", "needs": needs, "situation": self.SITUATION,
                   "status": "ok" if needs else "empty", "latency_ms": 1,
                   "model": "fake-model", "source": self.name}
            return
        yield from self._events

    def analyse(self, text: str, context: dict | None) -> AnalysisResult:
        for ev in self.stream_analyse(text, context):
            if ev["type"] == "analysis":
                return AnalysisResult(needs=ev["needs"], situation=ev["situation"], source=self.name,
                                      status=ev["status"], latency_ms=1, model="fake-model",
                                      suggestions=ev.get("suggestions", ()),
                                      referrals=ev.get("referrals", ()))
            if ev["type"] == "error":
                return AnalysisResult(needs=(), situation=None, source=self.name, status="error",
                                      latency_ms=1, model="fake-model", error_code=ev["code"])
        raise AssertionError("no analysis event")


class ApiTestCase(unittest.TestCase):
    """The real app on a temporary SQLite file, never the demo database."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        db_path = patch.object(db, "DB_PATH", Path(tmp.name) / "test.db")
        db_path.start()
        self.addCleanup(db_path.stop)
        # No test may call OAG; flight status is "unknown" unless a test sets a demo delay.
        no_oag = patch.object(main.oag, "live_delay", lambda flight, date: None)
        no_oag.start()
        self.addCleanup(no_oag.stop)
        self.client = TestClient(main.app)
        self.client.__enter__()  # runs the lifespan: schema, cleared engine choice
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.post("/api/demo/reset", json={"scenario": "fresh"})

    def use_engine(self, engine: FakeEngine) -> None:
        engine_patch = patch.object(main, "engine_for_request", lambda conn: engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
