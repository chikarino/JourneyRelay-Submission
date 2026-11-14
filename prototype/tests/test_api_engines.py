from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.main as main
from backend.analysis import Suggestion
from backend.catalog import get_need

from _support import ApiTestCase, FakeEngine


def sse_events(resp) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in resp.iter_lines() if line.startswith("data: ")]


class StreamEndpointTests(ApiTestCase):
    def test_stream_emits_status_thinking_result_and_persists_draft(self) -> None:
        fake = FakeEngine(events=[{"type": "thinking", "delta": "想一想…"},
                                  {"type": "analysis", "needs": (get_need("GUIDE"),), "situation": "需要引路。",
                                   "status": "ok", "latency_ms": 5, "model": "fake-model",
                                   "source": "local"}])
        self.use_engine(fake)
        with self.client.stream("POST", "/api/passenger/CXDEMO1/requests/stream",
                                json={"text": "請安排職員帶路。"}) as resp:
            self.assertEqual(resp.status_code, 200)
            events = sse_events(resp)
        self.assertEqual([e["type"] for e in events][:2], ["status", "thinking"])
        self.assertEqual(events[-1]["type"], "result")
        draft = events[-1]["draft"]
        self.assertEqual([n["code"] for n in draft["needs"]], ["GUIDE"])
        self.assertEqual(draft["analysis"]["situation"], "需要引路。")
        # The engine receives this passenger's trip as context.
        _, context = fake.calls[0]
        self.assertEqual([f["flight"] for f in context["flights"]], ["CX100", "CX251"])
        self.assertEqual(context["transfer"]["arrives"], "21:30")

    def test_suggestions_are_stored_for_the_passenger_only(self) -> None:
        self.use_engine(FakeEngine(events=[
            {"type": "analysis", "needs": (), "situation": "可以揀選建議。", "status": "empty",
             "latency_ms": 5, "model": "fake-model", "source": "local",
             "suggestions": (Suggestion(need=get_need("GUIDE"), reason="可以安排專人引路"),
                             Suggestion(need=get_need("PREBOARD"), reason="可以預先登機"))},
        ]))
        resp = self.client.post("/api/passenger/CXDEMO1/requests", json={"text": "我雙眼失明。"})
        self.assertEqual(resp.status_code, 201)
        draft = resp.json()
        self.assertEqual(draft["needs"], [])
        self.assertEqual([(s["code"], s["reason"]) for s in draft["suggestions"]],
                         [("PREBOARD", "可以預先登機"), ("GUIDE", "可以安排專人引路")])
        staff = json.dumps(self.client.get("/api/staff/tasks?role=arrival&place=HKG").json(),
                           ensure_ascii=False)
        self.assertNotIn("可以安排專人引路", staff)

    def test_a_callback_tells_customer_care_the_topic_and_no_other_role(self) -> None:
        self.use_engine(FakeEngine(events=[
            {"type": "analysis", "needs": (get_need("PREBOARD"),), "situation": "想預先登機。", "status": "ok",
             "latency_ms": 5, "model": "fake-model", "source": "local", "referrals": ("MEDICAL",)},
        ]))
        draft = self.client.post("/api/passenger/CXDEMO1/requests", json={"text": "機上要用氧氣，想早啲登機。"}).json()
        (referral,) = draft["referrals"]
        self.assertEqual(referral["code"], "MEDICAL")

        callback = get_need("CS_CALLBACK")
        picked = [{"code": n["code"], "scope": n["scope"]} for n in draft["needs"]]
        picked.append({"code": callback.code, "scope": callback.scope})
        self.client.put(f"/api/requests/{draft['request_id']}/needs", json={"needs": picked})
        self.assertEqual(self.client.post(f"/api/requests/{draft['request_id']}/confirm").status_code, 200)

        # Customer Care gets the callback as its own card, next to the booking review.
        care = self.client.get("/api/staff/tasks?role=cs&place=CS").json()
        cards = sorted(i["label_zh"] for g in care["groups"] if g["pnr"] == "CXDEMO1" for i in g["items"])
        self.assertEqual(cards, sorted([callback.label_zh, "整份安排"]))
        topics = {i["label_zh"]: [x["label_zh"] for x in i["topics"]]
                  for g in care["groups"] if g["pnr"] == "CXDEMO1" for i in g["items"]}
        self.assertEqual(topics, {callback.label_zh: [referral["label_zh"]], "整份安排": []})
        others = ""
        for place in ("SYD", "HKG"):
            others += json.dumps(self.client.get(f"/api/staff/tasks?role=gate&place={place}").json(), ensure_ascii=False)
        self.assertNotIn(referral["label_zh"], others)
        self.assertNotIn(referral["advice_zh"], json.dumps(care, ensure_ascii=False) + others)

    def test_engine_error_streams_an_error_and_keeps_no_draft(self) -> None:
        self.use_engine(FakeEngine(error="unreachable"))
        with self.client.stream("POST", "/api/passenger/CXDEMO1/requests/stream",
                                json={"text": "hi"}) as resp:
            events = sse_events(resp)
        self.assertEqual(events[-1], {"type": "error", "code": "unreachable"})
        self.assertIsNone(self.client.get("/api/passenger/CXDEMO1").json()["draft"])
        resp = self.client.post("/api/passenger/CXDEMO1/requests", json={"text": "hi"})
        self.assertEqual(resp.status_code, 503)


class EngineSwitchTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        # No network: the engine probes would call Ollama and DeepSeek.
        probe = patch.object(main, "_engine_probe", lambda name, conn: {})
        probe.start()
        self.addCleanup(probe.stop)
        env = patch.dict(os.environ, {"USE_DEEPSEEK_API": "false", "API_LLM_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_live_switch_survives_a_demo_reset_but_not_a_restart(self) -> None:
        self.client.post("/api/ai/engine", json={"engine": "api"})
        self.client.post("/api/demo/reset", json={"scenario": "fresh"})
        self.assertEqual(self.client.get("/api/ai/engine").json()["engine"], "api")
        with TestClient(main.app) as restarted:
            self.assertEqual(restarted.get("/api/ai/engine").json()["engine"], "local")

    def test_selected_engine_without_a_key_fails_instead_of_switching(self) -> None:
        self.client.post("/api/ai/engine", json={"engine": "api"})
        resp = self.client.post("/api/passenger/CXDEMO1/requests/stream", json={"text": "hi"})
        self.assertEqual(resp.status_code, 503)
