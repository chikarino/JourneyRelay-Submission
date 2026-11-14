"""The passenger → staff flow over the real API, with a scripted engine.

Covers the product rules: nothing is shared before confirm, tasks per role and
journey stage, delta routing on updates, privacy of the raw text and of flag
reasons, cancellation, and English text on every screen.
"""

from __future__ import annotations

import json
import sqlite3

from unittest.mock import patch

import backend.db as db
import backend.main as main
from backend.catalog import get_need

from _support import ApiTestCase, FakeEngine

SAY_FIRST = "我個仔怕嘈，排隊會好驚；要同我坐埋一齊，佢聽唔明廣播，請用文字通知我哋。"
SAY_UPDATE = "我只需要轉機嗰段用輪椅。"
SAY_NOTHING = "謝謝，冇特別需要。"
FIRST_NEEDS = ["QUIET_WAIT:full", "PREBOARD:full", "SEAT_ADJACENT:full", "TEXT_INFO:full"]
# The update repeats a need already shared, as a real update often does.
SCRIPT = {SAY_FIRST: FIRST_NEEDS, SAY_UPDATE: ["QUIET_WAIT:full", "WHEELCHAIR:transfer"], SAY_NOTHING: []}


def live_tasks(view: dict) -> list[tuple[str, str, str]]:
    return sorted((s["key"], i["role"], i["need_label"]) for s in view["stages"] for i in s["items"]
                  if i["status"] != "cancelled")


class PassengerFlowTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine = FakeEngine(by_text=SCRIPT)
        self.use_engine(self.engine)

    def say(self, text: str) -> dict:
        resp = self.client.post("/api/passenger/CXDEMO1/requests", json={"text": text})
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def confirm(self, draft: dict) -> dict:
        resp = self.client.post(f"/api/requests/{draft['request_id']}/confirm")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def passenger(self) -> dict:
        return self.client.get("/api/passenger/CXDEMO1").json()

    def staff(self, role: str, place: str) -> dict:
        return self.client.get(f"/api/staff/tasks?role={role}&place={place}").json()

    def chen_items(self, role: str, place: str) -> list[dict]:
        return [i for g in self.staff(role, place)["groups"] if g["pnr"] == "CXDEMO1" for i in g["items"]]

    def test_nothing_is_shared_or_stored_before_confirm(self) -> None:
        draft = self.say(SAY_FIRST)
        self.assertEqual([f"{n['code']}:{n['scope']}" for n in draft["needs"]], FIRST_NEEDS)
        self.assertNotIn(SAY_FIRST, json.dumps(draft, ensure_ascii=False))
        conn = sqlite3.connect(db.DB_PATH)
        self.addCleanup(conn.close)
        raw = conn.execute("SELECT raw_text FROM assistance_requests WHERE id=?",
                           (draft["request_id"],)).fetchone()
        self.assertIsNone(raw[0])
        self.assertEqual(sum(len(s["items"]) for s in self.passenger()["stages"]), 0)
        self.assertEqual(self.chen_items("checkin", "SYD"), [])

    def test_draft_edits_stay_inside_the_catalogue(self) -> None:
        draft = self.say(SAY_FIRST)
        url = f"/api/requests/{draft['request_id']}/needs"
        kept = [{"code": n["code"], "scope": n["scope"]} for n in draft["needs"] if n["code"] != "PREBOARD"]
        self.assertEqual(len(self.client.put(url, json={"needs": kept}).json()["needs"]), 3)
        bad = self.client.put(url, json={"needs": [{"code": "NOPE", "scope": "full"}]})
        self.assertEqual(bad.status_code, 422)

    def test_confirm_reaches_every_stage_and_an_update_reaches_only_new_roles(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        view = self.passenger()
        for stage in view["stages"]:
            self.assertTrue(stage["items"], f"no task at stage {stage['key']}")
        before = live_tasks(view)

        update = self.say(SAY_UPDATE)
        self.assertTrue(update["is_update"])
        _, context = self.engine.calls[-1]
        self.assertEqual(sorted(context["active_needs"]), sorted(FIRST_NEEDS))

        wheelchair = get_need("WHEELCHAIR", "transfer")
        after = live_tasks(self.confirm(update))
        added = list(after)
        for task in before:
            added.remove(task)
        self.assertEqual(added, [("transfer", "arrival", wheelchair.label_zh)])
        new_cards = [i for g in self.staff("arrival", "HKG")["groups"] for i in g["items"] if i["is_update"]]
        self.assertEqual([i["ssr_hint"] for i in new_cards], [wheelchair.ssr_hint])

    def test_raw_text_and_situation_never_reach_staff(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        self.confirm(self.say(SAY_UPDATE))
        passenger_blob = json.dumps(self.passenger(), ensure_ascii=False)
        staff_blob = ""
        for role in ("cs", "checkin", "gate", "cabin", "arrival"):
            for place in self.client.get(f"/api/staff/tasks?role={role}").json()["places"]:
                staff_blob += json.dumps(self.staff(role, place["place"]), ensure_ascii=False)
        for raw in (SAY_FIRST, SAY_UPDATE):
            self.assertNotIn(raw, passenger_blob + staff_blob)
        self.assertNotIn(FakeEngine.SITUATION, staff_blob)

    def test_flag_reason_stays_internal_and_amend_note_reaches_the_passenger(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        gate = self.chen_items("gate", "HKG")[0]
        empty = self.client.post(f"/api/tasks/{gate['task_id']}/flag", json={"note": " "})
        self.assertEqual(empty.status_code, 422)
        self.client.post(f"/api/tasks/{gate['task_id']}/flag", json={"note": "INTERNAL-REASON"})
        transit = self.chen_items("arrival", "HKG")[0]
        self.client.post(f"/api/tasks/{transit['task_id']}/amend", json={"note": "改為 40 號閘口旁的座位區"})
        blob = json.dumps(self.passenger(), ensure_ascii=False)
        self.assertNotIn("INTERNAL-REASON", blob)
        self.assertIn("改為 40 號閘口旁的座位區", blob)

    def test_cancelling_a_need_withdraws_its_tasks(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        view = self.confirm(self.say(SAY_UPDATE))
        need = next(n for n in view["needs"] if n["code"] == "WHEELCHAIR" and n["status"] == "active")
        view = self.client.post(f"/api/needs/{need['need_id']}/cancel").json()
        cancelled = [i for s in view["stages"] for i in s["items"] if i["status"] == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        late = self.client.post(f"/api/tasks/{cancelled[0]['task_id']}/done")
        self.assertEqual(late.status_code, 409)

    def test_booking_remarks_cover_the_whole_booking_and_only_customer_care_gets_them(self) -> None:
        draft = self.say(SAY_FIRST)
        # Written updates join the booking's DPNA line instead of opening a DEAF one.
        dpna = [line for line in draft["booking_remarks"] if line.startswith("SR DPNA ")]
        self.assertEqual(len(dpna), 1)
        self.assertIn(get_need("TEXT_INFO").remark, dpna[0])
        self.assertFalse([line for line in draft["booking_remarks"] if line.startswith("SR DEAF ")])
        self.confirm(draft)

        update = self.say(SAY_UPDATE)
        self.assertEqual(update["booking_remarks"][:1], dpna)  # the preview shows the booking, not the delta
        self.confirm(update)

        def care_lines() -> list[str]:
            return [line for g in self.staff("cs", "CS")["groups"] if g["pnr"] == "CXDEMO1"
                    for line in g["booking_remarks"]]
        self.assertEqual(care_lines(), update["booking_remarks"])
        self.assertTrue([line for line in care_lines() if line.startswith("SR WCHR ")])
        for role, place in (("checkin", "SYD"), ("gate", "SYD"), ("cabin", "CX100"), ("arrival", "HKG")):
            for group in self.staff(role, place)["groups"]:
                self.assertEqual(group["booking_remarks"], [], (role, place))

        need = next(n for n in self.passenger()["needs"] if n["code"] == "WHEELCHAIR")
        self.client.post(f"/api/needs/{need['need_id']}/cancel")
        self.assertFalse([line for line in care_lines() if line.startswith("SR WCHR ")])

    def test_ops_demand_counts_confirmed_needs_per_station(self) -> None:
        def chen_demand() -> dict:
            board = self.client.get("/api/ops/board").json()
            return {(d["place"], d["kind"]): {n["label_zh"]: n["count"] for n in d["needs"]}
                    for d in board["demand"]}
        self.say(SAY_FIRST)
        before = chen_demand()  # a draft is not demand
        self.confirm(self.say(SAY_FIRST))
        quiet, wheelchair = get_need("QUIET_WAIT"), get_need("WHEELCHAIR", "transfer")
        added = chen_demand()
        self.assertEqual(added[("SYD", "dep")][quiet.label_zh], before.get(("SYD", "dep"), {}).get(quiet.label_zh, 0) + 1)
        self.assertNotIn(("CS", "booking"), added)

        view = self.confirm(self.say(SAY_UPDATE))
        self.assertEqual(chen_demand()[("HKG", "transfer")][wheelchair.label_zh], 1)
        need = next(n for n in view["needs"] if n["code"] == "WHEELCHAIR")
        self.client.post(f"/api/needs/{need['need_id']}/cancel")
        self.assertNotIn(wheelchair.label_zh, chen_demand()[("HKG", "transfer")])

    def test_outstations_and_crew_are_notified_by_the_remark_once_customer_care_files_it(self) -> None:
        def statuses() -> dict[str, set[str]]:
            return {s["key"]: {i["status"] for i in s["items"]} for s in self.passenger()["stages"]}
        self.confirm(self.say(SAY_FIRST))
        # An outstation handler has no task card to tap.
        sydney = self.chen_items("checkin", "SYD")[0]
        self.assertEqual(self.client.post(f"/api/tasks/{sydney['task_id']}/done").status_code, 409)
        self.assertEqual(statuses()["dep"], {"pending"})

        care = self.chen_items("cs", "CS")
        self.assertEqual(len(care), 1)
        self.client.post(f"/api/tasks/{care[0]['task_id']}/done")
        after = statuses()
        for stage in ("dep", "f1", "f2", "arr"):
            self.assertEqual(after[stage], {"notified"}, stage)
        self.assertEqual(after["transfer"], {"pending"})  # Hong Kong's own teams still acknowledge

        # A later change puts one remark-update card back with Customer Care.
        self.confirm(self.say(SAY_UPDATE))
        care = self.chen_items("cs", "CS")
        self.assertEqual([i["status"] for i in care], ["done", "pending"])
        self.assertNotEqual(care[0]["instruction_zh"], care[1]["instruction_zh"])

    def test_needs_carry_over_to_the_travellers_next_booking_only_after_they_confirm(self) -> None:
        def chen_return() -> dict:
            return self.client.get("/api/passenger/CXDEMO4").json()
        # Before today's trip is confirmed, both bookings offer what September's trip had.
        september = ["QUIET_WAIT:full", "SEAT_ADJACENT:full"]
        for pnr in ("CXDEMO1", "CXDEMO4"):
            offered = self.client.get(f"/api/passenger/{pnr}").json()["reusable"]
            self.assertEqual([f"{n['code']}:{n['scope']}" for n in offered], september)

        view = self.confirm(self.say(SAY_FIRST))
        dropped = next(n for n in view["needs"] if n["code"] == "PREBOARD")
        self.client.post(f"/api/needs/{dropped['need_id']}/cancel")
        kept = [k for k in FIRST_NEEDS if k != "PREBOARD:full"]
        self.assertEqual([f"{n['code']}:{n['scope']}" for n in chen_return()["reusable"]], kept)
        # The most recent trip wins; another traveller's booking is offered nothing.
        self.assertEqual(self.client.get("/api/passenger/CXDEMO3").json()["reusable"], [])

        draft = self.client.post("/api/passenger/CXDEMO4/requests/reuse").json()
        self.assertEqual([f"{n['code']}:{n['scope']}" for n in draft["needs"]], kept)
        self.assertEqual(sum(len(s["items"]) for s in chen_return()["stages"]), 0)  # still a draft
        self.client.post(f"/api/requests/{draft['request_id']}/confirm")
        self.assertTrue(all(s["items"] for s in chen_return()["stages"] if s["key"] != "arr"))
        self.assertEqual(chen_return()["reusable"], [])

    def test_a_delay_that_squeezes_the_connection_offers_a_guide_once(self) -> None:
        def status() -> dict:
            return self.passenger()["journey_status"]
        self.confirm(self.say(SAY_FIRST))
        self.assertIsNone(status()["offer"])
        self.client.post("/api/demo/delay", json={"flight": "CX100", "minutes": 20})
        self.assertEqual(status()["connection"]["expected"], 70)
        self.assertIsNone(status()["offer"])  # late, but the connection is still comfortable

        self.client.post("/api/demo/delay", json={"flight": "CX100", "minutes": 50})
        self.assertEqual(status()["connection"], {"station": "香港 HKG", "scheduled": 90, "expected": 40, "tight": True})
        self.assertEqual((status()["offer"]["code"], status()["offer"]["scope"]), ("GUIDE", "transfer"))
        transit = next(g for g in self.staff("arrival", "HKG")["groups"] if g["pnr"] == "CXDEMO1")
        self.assertEqual(transit["delay_minutes"], 50)  # the transfer desk sees the new arrival time

        draft = self.client.post("/api/passenger/CXDEMO1/requests/offer").json()
        self.assertEqual([f"{n['code']}:{n['scope']}" for n in draft["needs"]], ["GUIDE:transfer"])
        self.confirm(draft)
        self.assertIsNone(status()["offer"])  # arranged, so not offered again
        self.assertEqual(self.client.post("/api/passenger/CXDEMO1/requests/offer").status_code, 404)

    def test_cancelling_after_the_remark_is_filed_asks_customer_care_to_update_it(self) -> None:
        view = self.confirm(self.say(SAY_FIRST))
        quiet, seat = (next(n for n in view["needs"] if n["code"] == c) for c in ("QUIET_WAIT", "SEAT_ADJACENT"))
        self.client.post(f"/api/needs/{quiet['need_id']}/cancel")
        self.assertEqual(len(self.chen_items("cs", "CS")), 1)  # the review has not been done yet; it covers this

        self.client.post(f"/api/tasks/{self.chen_items('cs', 'CS')[0]['task_id']}/done")
        self.client.post(f"/api/needs/{seat['need_id']}/cancel")
        self.assertEqual([i["status"] for i in self.chen_items("cs", "CS")], ["done", "pending"])

    def test_an_unclaimed_home_station_task_is_flagged_as_its_time_approaches(self) -> None:
        self.confirm(self.say(SAY_FIRST))

        def at(clock: str) -> tuple[list[bool], int]:
            with patch.object(main, "now_hkt", lambda: f"2026-11-14 {clock}"):
                items = self.chen_items("arrival", "HKG")
                return [i["due_soon"] for i in items], self.client.get("/api/ops/board").json()["metrics"]["due_soon"]
        self.assertEqual(at("12:00"), ([False, False], 0))      # CX100 lands 21:30
        flags, count = at("19:45")
        self.assertEqual(flags, [True, True])
        self.assertGreaterEqual(count, 2)
        self.client.post("/api/demo/delay", json={"flight": "CX100", "minutes": 60})
        self.assertEqual(at("19:45")[0], [False, False])        # a later arrival moves the deadline
        first = self.chen_items("arrival", "HKG")[0]
        self.client.post(f"/api/tasks/{first['task_id']}/receive")
        self.client.post("/api/demo/delay", json={"flight": "CX100", "minutes": 0})
        self.assertEqual(at("19:45")[0], [False, True])         # claimed tasks are not flagged

    def test_a_description_on_the_next_booking_can_carry_the_last_trips_needs(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        for carry_over, expected in ((False, ["QUIET_WAIT:full", "WHEELCHAIR:transfer"]),
                                     (True, sorted(FIRST_NEEDS + ["WHEELCHAIR:transfer"]))):
            draft = self.client.post("/api/passenger/CXDEMO4/requests",
                                     json={"text": SAY_UPDATE, "carry_over": carry_over}).json()
            self.assertEqual(sorted(f"{n['code']}:{n['scope']}" for n in draft["needs"]), expected)
        marked = {f"{n['code']}:{n['scope']}" for n in draft["needs"] if n["from_last_trip"]}
        self.assertEqual(marked, set(FIRST_NEEDS))  # the new need is not marked
        # A booking that already has confirmed needs carries nothing over, so the flag changes nothing.
        update = self.client.post("/api/passenger/CXDEMO1/requests", json={"text": SAY_UPDATE, "carry_over": True}).json()
        self.assertEqual(sorted(f"{n['code']}:{n['scope']}" for n in update["needs"]), ["QUIET_WAIT:full", "WHEELCHAIR:transfer"])

    def test_an_empty_draft_cannot_be_shared(self) -> None:
        draft = self.say(SAY_NOTHING)
        self.assertFalse(draft["recognised"])
        resp = self.client.post(f"/api/requests/{draft['request_id']}/confirm")
        self.assertEqual(resp.status_code, 422)

    def test_every_screen_has_english_text(self) -> None:
        self.confirm(self.say(SAY_FIRST))
        task = self.chen_items("arrival", "HKG")[0]
        self.client.post(f"/api/tasks/{task['task_id']}/receive")
        care = self.chen_items("cs", "CS")[0]
        self.client.post(f"/api/tasks/{care['task_id']}/done")  # also writes the remark-filed ledger line
        view = self.passenger()
        for stage in view["stages"]:
            self.assertTrue(stage["title_en"], stage["key"])
            for item in stage["items"]:
                self.assertTrue(item["instruction_en"] and item["need_label_en"], item)
        for entry in view["ledger"]:
            self.assertTrue(entry["text_en"] and entry["who_en"], entry)
        for role, place in (("cs", "CS"), ("checkin", "SYD"), ("arrival", "HKG"), ("cabin", "CX251")):
            for group in self.staff(role, place)["groups"]:
                self.assertTrue(group["stage_title_en"], group)
                for item in group["items"]:
                    self.assertTrue(item["instruction_en"] and item["label_en"], item)
