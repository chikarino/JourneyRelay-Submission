from __future__ import annotations

import unittest

from backend.analysis import AnalysisError, parse_output, system_prompt, unwrap_final_envelope


class ParseOutputTests(unittest.TestCase):
    """parse_output is the gate: only catalogue needs may reach the database."""

    def test_accepts_needs_and_optional_situation(self) -> None:
        needs, situation, suggestions, _ = parse_output(
            '{"needs":[{"code":"QUIET_WAIT","scope":"full"}],"situation":"你好趕住轉機。"}'
        )
        self.assertEqual({n.key for n in needs}, {"QUIET_WAIT:full"})
        self.assertEqual(situation, "你好趕住轉機。")
        self.assertEqual(suggestions, ())

    def test_unwraps_the_final_envelope_some_models_emit(self) -> None:
        """gpt-oss sometimes hides the whole payload under {"final": …}; it is valid."""
        needs, situation, _, _ = parse_output(
            '{"final": {"needs":[{"code":"WHEELCHAIR","scope":"full"}],'
            '"suggested_needs":[],"referrals":[],'
            '"situation":"You cannot walk long distances."}}'
        )
        self.assertEqual({n.key for n in needs}, {"WHEELCHAIR:full"})
        self.assertEqual(situation, "You cannot walk long distances.")
        # Only a single-key envelope unwraps; "final" alongside other keys stays invalid.
        obj = {"final": {"needs": []}, "extra": 1}
        self.assertIs(unwrap_final_envelope(obj), obj)

    def test_rejects_anything_outside_the_catalogue_or_schema(self) -> None:
        for content in (
            '{"needs":[{"code":"NOPE","scope":"full"}]}',               # unknown code
            '{"needs":[{"code":"QUIET_WAIT","scope":"transfer"}]}',     # code/scope pair not in catalogue
            '{"needs":[{"code":"GUIDE","scope":"full"},{"code":"GUIDE","scope":"full"}]}',  # duplicate
            '{"needs":[],"diagnosis":"autism"}',                        # extra top-level field
            '{"needs":[{"code":"GUIDE","scope":"full","extra":"x"}]}',  # extra need field
            '{"situation":"only"}',                                     # needs missing
            '{"needs":[],"suggested_needs":"oops"}',
            "not json",
        ):
            with self.subTest(content=content):
                with self.assertRaises(AnalysisError):
                    parse_output(content)

    def test_strips_json_fence(self) -> None:
        needs, _, _, _ = parse_output('```json\n{"needs":[{"code":"GUIDE","scope":"full"}]}\n```')
        self.assertEqual({n.key for n in needs}, {"GUIDE:full"})

    def test_suggestions_sorted_in_catalogue_order(self) -> None:
        _, _, suggestions, _ = parse_output(
            '{"needs":[],"suggested_needs":['
            '{"code":"PREBOARD","scope":"full","reason":"可以預先登機"},'
            '{"code":"GUIDE","scope":"full","reason":"可以安排專人引路"}]}'
        )
        self.assertEqual([(s.need.code, s.reason) for s in suggestions],
                         [("PREBOARD", "可以預先登機"), ("GUIDE", "可以安排專人引路")])

    def test_only_listed_referrals_survive(self) -> None:
        *_, referrals = parse_output('{"needs":[],"referrals":["OTHER","NOPE",3,"MEDICAL","MEDICAL"]}')
        self.assertEqual(referrals, ("MEDICAL", "OTHER"))

    def test_bad_suggestions_are_dropped_not_fatal(self) -> None:
        _, _, suggestions, _ = parse_output(
            '{"needs":[],"suggested_needs":['
            '{"code":"NOPE","scope":"full","reason":"x"},'
            '{"code":"PREBOARD","scope":"transfer","reason":"x"},'
            '{"code":"GUIDE","scope":"full"},'
            '{"code":"GUIDE","scope":"full","reason":"  "},'
            '{"code":"GUIDE","scope":"full","reason":"ok"},'
            '{"code":"GUIDE","scope":"full","reason":"ok again"}'
            ']}'
        )
        self.assertEqual([(s.need.code, s.reason) for s in suggestions], [("GUIDE", "ok")])


class PromptExampleTests(unittest.TestCase):
    def test_every_example_output_in_the_prompt_is_valid(self) -> None:
        # The model copies these examples; one the parser rejects teaches it a bad format.
        outputs = [line[len("Output: "):] for line in system_prompt(None).splitlines()
                   if line.startswith("Output: ")]
        self.assertGreater(len(outputs), 5)
        for output in outputs:
            with self.subTest(output=output):
                parse_output(output)


class FlightStatusTests(unittest.TestCase):
    def test_delay_prefers_the_arrival_estimate_and_never_goes_negative(self) -> None:
        from backend.oag import parse_delay

        def reply(**sides) -> dict:
            return {"data": [{"statusDetails": [sides]}]}
        late_out = {"estimatedTime": {"outGateVariation": "00:50:00"}}
        self.assertEqual(parse_delay(reply(departure=late_out)), 50)
        self.assertEqual(parse_delay(reply(departure=late_out, arrival={"estimatedTime": {"inGateVariation": "00:20:00"}})), 20)
        self.assertEqual(parse_delay(reply(departure={"estimatedTime": {"outGateVariation": "-00:05:00"}})), 0)
        self.assertIsNone(parse_delay(reply(departure={})))
        self.assertIsNone(parse_delay({"data": []}))


if __name__ == "__main__":
    unittest.main()
