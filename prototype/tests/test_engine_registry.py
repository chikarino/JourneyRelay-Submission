from __future__ import annotations

import os
import sqlite3
import unittest
from unittest.mock import patch

from backend import engine_registry as reg


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        env = patch.dict(os.environ, {"USE_DEEPSEEK_API": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self) -> None:
        self.conn.close()

    def test_deepseek_switch_selects_api(self) -> None:
        for value, expected in (("true", "api"), ("1", "api"), ("false", "local"), ("", "local")):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"USE_DEEPSEEK_API": value}):
                    self.assertEqual(reg.current_engine_name(self.conn), expected)

    def test_live_choice_wins_over_the_switch(self) -> None:
        reg.set_engine(self.conn, "local")
        with patch.dict(os.environ, {"USE_DEEPSEEK_API": "true"}):
            self.assertEqual(reg.current_engine_name(self.conn), "local")


if __name__ == "__main__":
    unittest.main()
