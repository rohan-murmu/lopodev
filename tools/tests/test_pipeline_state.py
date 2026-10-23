"""Deterministic tests for the approval-gated pipeline state."""

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

import pipeline_state as ps  # noqa: E402


def call(func, **kwargs) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = func(argparse.Namespace(**kwargs))
    return code, output.getvalue()


class PipelineStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = str(Path(self.temp.name) / "projects" / "test_game")
        code, output = call(
            ps.cmd_init,
            project=self.project,
            slug="test_game",
            title="Test Game",
            workspace=self.temp.name,
        )
        self.assertEqual(code, 0, output)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def load(self) -> dict:
        with open(Path(self.project) / ps.STATE_FILENAME, encoding="utf-8") as handle:
            return json.load(handle)

    def test_init_creates_pending_gate_a(self) -> None:
        data = self.load()
        self.assertEqual(data["current_gate"], "A")
        self.assertEqual(data["gates"]["A"]["status"], "pending")
        self.assertEqual(len(data["gates"]), 6)

    def test_init_refuses_overwrite(self) -> None:
        code, output = call(
            ps.cmd_init,
            project=self.project,
            slug="test_game",
            title="Test Game",
            workspace=self.temp.name,
        )
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", output)

    def test_approve_requires_proposal(self) -> None:
        code, output = call(
            ps.cmd_approve,
            project=self.project,
            gate="A",
            user_statement="Approved",
            evidence=[],
        )
        self.assertEqual(code, 2)
        self.assertIn("not proposed", output)

    def test_gate_a_approval_advances_to_b(self) -> None:
        code, output = call(
            ps.cmd_propose,
            project=self.project,
            gate="A",
            evidence=["GAME_SPEC.md", "project.json"],
            note="Scope and plan",
            skip_reason="",
        )
        self.assertEqual(code, 0, output)
        code, output = call(
            ps.cmd_approve,
            project=self.project,
            gate="A",
            user_statement="Approved, build this plan.",
            evidence=[],
        )
        self.assertEqual(code, 0, output)
        data = self.load()
        self.assertEqual(data["gates"]["A"]["status"], "approved")
        self.assertEqual(data["gates"]["A"]["user_statement"],
                         "Approved, build this plan.")
        self.assertEqual(data["current_gate"], "B")
        self.assertEqual(ps.validate_state(data), [])

    def test_gate_order_is_enforced(self) -> None:
        code, output = call(
            ps.cmd_propose,
            project=self.project,
            gate="C",
            evidence=[],
            note="",
            skip_reason="",
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot be proposed", output)

    def test_rejection_then_revision_can_be_approved(self) -> None:
        call(ps.cmd_propose, project=self.project, gate="A", evidence=[],
             note="", skip_reason="")
        code, output = call(
            ps.cmd_reject,
            project=self.project,
            gate="A",
            reason="The scale is wrong.",
            user_statement="Rejected, revise the scale.",
        )
        self.assertEqual(code, 0, output)
        data = self.load()
        self.assertEqual(data["gates"]["A"]["status"], "rejected")
        self.assertEqual(data["current_gate"], "A")

        code, output = call(
            ps.cmd_propose,
            project=self.project,
            gate="A",
            evidence=["GAME_SPEC.md"],
            note="Revised scale",
            skip_reason="",
        )
        self.assertEqual(code, 0, output)
        data = self.load()
        self.assertEqual(data["gates"]["A"]["revision"], 2)
        self.assertEqual(data["gates"]["A"]["status"], "proposed")

        code, _ = call(ps.cmd_approve, project=self.project, gate="A",
                       user_statement="Approved.", evidence=[])
        self.assertEqual(code, 0)
        data = self.load()
        self.assertEqual(data["gates"]["A"]["status"], "approved")
        self.assertEqual(len(data["rejections"]), 1)

    def test_reopen_requires_authorization(self) -> None:
        call(ps.cmd_propose, project=self.project, gate="A", evidence=[],
             note="", skip_reason="")
        call(ps.cmd_approve, project=self.project, gate="A",
             user_statement="Approved.", evidence=[])
        code, output = call(
            ps.cmd_reopen,
            project=self.project,
            gate="A",
            reason="Change the setting.",
            user_statement="Please change the setting.",
        )
        self.assertEqual(code, 0, output)
        data = self.load()
        self.assertEqual(data["gates"]["A"]["status"], "pending")
        self.assertEqual(data["current_gate"], "A")

    def test_state_survives_a_new_process(self) -> None:
        call(ps.cmd_propose, project=self.project, gate="A", evidence=[],
             note="", skip_reason="")
        call(ps.cmd_approve, project=self.project, gate="A",
             user_statement="Approved.", evidence=[])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = ps.cmd_show(argparse.Namespace(project=self.project, json=True))
        self.assertEqual(code, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["current_gate"], "B")
        self.assertEqual(data["gates"]["A"]["status"], "approved")

    def test_validate_detects_missing_user_statement(self) -> None:
        data = self.load()
        data["gates"]["A"]["status"] = "approved"
        data["gates"]["A"]["approved_at_utc"] = ps.utc_now()
        data["gates"]["A"]["proposed_at_utc"] = ps.utc_now()
        errors = ps.validate_state(data)
        self.assertTrue(any("user_statement" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
