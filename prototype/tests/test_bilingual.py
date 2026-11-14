from __future__ import annotations

import unittest

from backend.catalog import CATALOG, booking_remarks


class CatalogEnglishTests(unittest.TestCase):
    # The flow tests only route a few needs; this covers every catalogue entry.
    def test_every_need_and_route_has_english(self) -> None:
        for need in CATALOG:
            with self.subTest(need=need.code):
                self.assertTrue(need.detail_en.strip())
        for need in CATALOG:
            for route in need.routes:
                with self.subTest(route=(need.code, route.stage, route.role)):
                    self.assertTrue(route.instruction_en.strip())

    def test_every_need_yields_one_plain_ascii_remark_line(self) -> None:
        # Booking systems take upper-case ASCII; a need with no wording would file an empty remark.
        for need in CATALOG:
            with self.subTest(need=need.key):
                (line,) = booking_remarks([need])
                self.assertTrue(need.remark and line.endswith(need.remark))
                self.assertTrue(line.isascii() and line == line.upper())

    def test_a_full_journey_need_replaces_its_transfer_only_form(self) -> None:
        wheelchair = [n for n in CATALOG if n.code == "WHEELCHAIR"]
        self.assertEqual(booking_remarks(wheelchair), booking_remarks([n for n in wheelchair if n.scope == "full"]))


if __name__ == "__main__":
    unittest.main()
