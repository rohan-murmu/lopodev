"""Tests for the evidence-required QA report helper."""

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

import qa_report  # noqa: E402


def call(func, **kwargs) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = func(argparse.Namespace(**kwargs))
    return code, output.getvalue()


class QAReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "projects" / "test_game"
        self.project.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def args(self, name: str, status: str, **overrides) -> dict:
        values = {
            "project": str(self.project), "name": name, "status": status,
            "command": "", "exit_code": None, "evidence": "", "notes": "",
            "reason": "", "environment": [], "reset": False,
        }
        values.update(overrides)
        return values

    def test_pass_requires_command_and_evidence(self) -> None:
        code, output = call(qa_report.cmd_record, **self.args("content", "PASS"))
        self.assertEqual(code, 2)
        self.assertIn("requires --command", output)
        code, output = call(qa_report.cmd_record,
                            **self.args("content", "PASS", command="validate.sh"))
        self.assertEqual(code, 2)
        self.assertIn("requires --evidence", output)

    def test_not_run_requires_reason(self) -> None:
        code, output = call(qa_report.cmd_record, **self.args("device", "NOT RUN"))
        self.assertEqual(code, 2)
        self.assertIn("requires --reason", output)
        code, output = call(qa_report.cmd_record,
                            **self.args("device", "NOT RUN", reason="no device"))
        self.assertEqual(code, 0, output)

    def test_legacy_report_is_readable_without_rewriting(self) -> None:
        path = self.project / "artifacts" / "qa_report.json"
        path.parent.mkdir(parents=True)
        legacy = {
            "updated_at_utc": "2026-10-23T00:00:00+00:00",
            "gates": [{"gate": "asset", "status": "PASS",
                       "command": "validate_asset.py", "evidence": "log.txt"}],
        }
        text = json.dumps(legacy, indent=2) + chr(10)
        path.write_text(text)
        code, output = call(qa_report.cmd_validate, project=str(self.project))
        self.assertEqual(code, 0, output)
        self.assertIn("QA_REPORT_CHECK=PASS gates=1", output)
        self.assertEqual(path.read_text(), text)

    def test_records_and_replaces_gates(self) -> None:
        for name, status in (("content", "PASS"), ("device", "NOT RUN")):
            code, output = call(qa_report.cmd_record,
                                **self.args(name, status, command="cmd",
                                            evidence="evidence.json",
                                            reason="no device" if status == "NOT RUN" else ""))
            self.assertEqual(code, 0, output)
        code, output = call(qa_report.cmd_record,
                            **self.args("content", "FAIL", command="validate",
                                        evidence="log.txt"))
        self.assertEqual(code, 0, output)
        data = json.loads((self.project / "artifacts" / "qa_report.json").read_text())
        self.assertEqual(len(data["gates"]), 2)
        content = next(g for g in data["gates"] if g["name"] == "content")
        self.assertEqual(content["status"], "FAIL")
        code, output = call(qa_report.cmd_validate, project=str(self.project))
        self.assertEqual(code, 0, output)
        self.assertIn("QA_REPORT_CHECK=PASS gates=2", output)


if __name__ == "__main__":
    unittest.main()
