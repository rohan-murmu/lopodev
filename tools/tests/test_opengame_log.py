"""Tests for structured OpenGame event logging."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opengame_log as log  # noqa: E402


def call(func, **kwargs) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = func(argparse.Namespace(**kwargs))
    return code, output.getvalue()


class EventLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "projects" / "test_game"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_append_writes_valid_jsonl_and_redacts_secrets(self) -> None:
        code, output = call(
            log.cmd_append,
            log=None, project=str(self.project), event="delegation",
            agent="modeling", gate="B", task="T1", status="started",
            command="tool --token hunter2", evidence="", message="start",
            data=["api_key=secret", "note=visible"], json_data=None,
        )
        self.assertEqual(code, 0, output)
        path = self.project / "artifacts" / "events.jsonl"
        event = json.loads(path.read_text().splitlines()[0])
        self.assertEqual(event["event"], "delegation")
        self.assertEqual(event["data"]["api_key"], "<redacted>")
        self.assertEqual(event["data"]["note"], "visible")
        self.assertTrue(event["ts_utc"].endswith("+00:00"))

    def test_validate_accepts_appended_events(self) -> None:
        for name in ("task_start", "task_complete"):
            code, output = call(
                log.cmd_append, log=None, project=str(self.project), event=name,
                agent="gameplay", gate="", task="T2", status="pass",
                command="", evidence="", message="", data=[], json_data=None,
            )
            self.assertEqual(code, 0, output)
        code, output = call(log.cmd_validate, log=None, project=str(self.project))
        self.assertEqual(code, 0, output)
        self.assertIn("EVENT_LOG_CHECK=PASS events=2", output)

    def test_validate_rejects_bad_line(self) -> None:
        path = self.project / "artifacts" / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"event": "ok"}\nnot json\n')
        code, output = call(log.cmd_validate, log=None, project=str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("EVENT_LOG_CHECK=FAIL", output)

    def test_long_values_are_truncated(self) -> None:
        long_text = "x" * (log.MAX_VALUE_CHARS + 50)
        code, output = call(
            log.cmd_append, log=None, project=str(self.project), event="error",
            agent="", gate="", task="", status="fail", command="",
            evidence="", message=long_text, data=[], json_data=None,
        )
        self.assertEqual(code, 0, output)
        event = json.loads((self.project / "artifacts" / "events.jsonl").read_text())
        self.assertLess(len(event["message"]), len(long_text) + 80)
        self.assertIn("<truncated", event["message"])


if __name__ == "__main__":
    unittest.main()
