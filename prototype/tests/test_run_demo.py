from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_demo import (
    LauncherError,
    Settings,
    _load_env_file,
    _npm_command,
    _prepare_ollama,
    _resolve_engine,
    _stop_from_state,
    _validate_loopback_url,
)


class RunDemoTests(unittest.TestCase):
    def test_dotenv_parser_handles_comments_export_and_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "LOCAL_LLM_MODE=local",
                        "export LOCAL_LLM_MODEL='qwen2.5:7b'",
                        'LOCAL_LLM_BASE_URL="http://127.0.0.1:11434"',
                    ]
                ),
                encoding="utf-8",
            )
            values = _load_env_file(path)
        self.assertEqual(values["LOCAL_LLM_MODE"], "local")
        self.assertEqual(values["LOCAL_LLM_MODEL"], "qwen2.5:7b")
        self.assertEqual(values["LOCAL_LLM_BASE_URL"], "http://127.0.0.1:11434")

    def test_only_loopback_ollama_urls_are_accepted(self) -> None:
        for value in ("http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"):
            with self.subTest(value=value):
                self.assertTrue(_validate_loopback_url(value).startswith("http://"))
        for value in (
            "https://models.example.com",
            "http://127.0.0.1.example.com:11434",
            "http://127.0.0.1:11434/proxy",
            "file:///tmp/model",
        ):
            with self.subTest(value=value):
                with self.assertRaises(LauncherError):
                    _validate_loopback_url(value)

    def test_missing_ollama_without_api_config_raises(self) -> None:
        settings = Settings(base_url="https://models.example.com", model="qwen3.5:9b",
                            api_port=8000, web_port=3000, install=True, open_browser=False)
        # Pin the cause: without this patch a machine that has ollama on PATH
        # would raise from the loopback validation instead of this branch, and
        # even with the patch the loopback check would still raise
        # LauncherError — so also match the guard's message.
        with patch("scripts.run_demo._which", return_value=None):
            with self.assertRaisesRegex(LauncherError, "Ollama is required"):
                _prepare_ollama({}, settings)

    def test_engine_follows_override_switch_and_missing_ollama(self) -> None:
        with patch("scripts.run_demo._which", return_value="/usr/local/bin/ollama"):
            self.assertEqual(_resolve_engine({}), "local")
            self.assertEqual(_resolve_engine({"USE_DEEPSEEK_API": "false"}), "local")
            self.assertEqual(_resolve_engine({"USE_DEEPSEEK_API": "true"}), "api")
        with patch("scripts.run_demo._which", return_value=None):
            self.assertEqual(_resolve_engine({}), "local")
            self.assertEqual(_resolve_engine({"API_LLM_API_KEY": "sk-test"}), "api")

    def test_windows_npm_command_uses_command_prompt(self) -> None:
        # On Windows npm is a .batch file, so the command line goes through
        # the shell (cmd.exe) instead of CreateProcess seeing npm.cmd itself.
        with patch("scripts.run_demo.IS_WINDOWS", True):
            command, use_shell = _npm_command(
                r"C:\Program Files\nodejs\npm.cmd",
                ["ci", "--no-audit"],
            )
        self.assertTrue(use_shell)
        self.assertIn("npm.cmd", command)
        self.assertIn(" ci ", command)

    def test_posix_npm_command_stays_an_argv_list(self) -> None:
        # Off Windows the command must remain a list so subprocess.run with
        # shell=False executes npm directly rather than the whole line as one
        # executable name.
        with patch("scripts.run_demo.IS_WINDOWS", False):
            command, use_shell = _npm_command(
                "/usr/local/bin/npm",
                ["ci", "--no-audit"],
            )
        self.assertFalse(use_shell)
        self.assertEqual(command, ["/usr/local/bin/npm", "ci", "--no-audit"])

    def test_stop_skips_pids_that_are_no_longer_launcher_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            state = runtime / "processes.json"
            state.write_text(json.dumps({"processes": [
                {"pid": 101, "role": "api", "marker": "backend.main:app"},
                {"pid": 102, "role": "frontend", "marker": "next"},
                {"pid": 103, "role": "ollama"},  # state written before markers existed
            ]}), encoding="utf-8")
            command_lines = {
                101: "/repo/.venv/bin/python -m uvicorn backend.main:app --port 8000",
                102: "/usr/bin/vim notes.txt",  # PID reused by another program
                103: "ollama serve",
            }
            with patch("scripts.run_demo.RUNTIME_DIR", runtime), \
                    patch("scripts.run_demo.STATE_FILE", state), \
                    patch("scripts.run_demo.STOP_REQUEST_FILE", runtime / "stop.requested"), \
                    patch("scripts.run_demo._command_line", side_effect=command_lines.get), \
                    patch("scripts.run_demo._terminate_pid") as terminate, \
                    contextlib.redirect_stdout(io.StringIO()):
                _stop_from_state()
        terminate.assert_called_once_with(101)


if __name__ == "__main__":
    unittest.main()
