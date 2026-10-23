"""Tests for task-level pipeline state and next-task selection."""

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


def task_args(project: str, task_id: str, status: str, **overrides) -> dict:
    values = {
        "project": project, "id": task_id, "title": None, "status": status,
        "skill": [], "depends_on": None, "evidence": [], "owner": None,
        "changed_file": [], "acceptance": None, "verification": None,
        "issue": [], "gate": None, "note": None,
    }
    values.update(overrides)
    return values


class PipelineTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = str(Path(self.temp.name) / "projects" / "test_game")
        code, output = call(
            ps.cmd_init, project=self.project, slug="test_game",
            title="Test Game", workspace=self.temp.name,
        )
        self.assertEqual(code, 0, output)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def load(self) -> dict:
        return json.loads((Path(self.project) / ps.STATE_FILENAME).read_text())

    def test_legacy_complete_is_accepted_but_verified_needs_evidence(self) -> None:
        code, output = call(ps.cmd_record_task,
                            **task_args(self.project, "T1", "complete",
                                        evidence=["evidence/legacy.json"]))
        self.assertEqual(code, 0, output)
        self.assertEqual(ps.validate_state(self.load()), [])
        code, output = call(ps.cmd_record_task, **task_args(self.project, "T2", "verified"))
        self.assertEqual(code, 2)
        self.assertIn("needs --evidence or --verification", output)

    def test_verified_task_with_evidence_passes_validation(self) -> None:
        code, output = call(
            ps.cmd_record_task,
            **task_args(self.project, "T2", "verified", owner="gameplay",
                        evidence=["artifacts/qa_report.json"],
                        verification="smoke PASS", changed_file=["godot/scripts/player.gd"]),
        )
        self.assertEqual(code, 0, output)
        task = self.load()["tasks"][0]
        self.assertEqual(task["owner"], "gameplay")
        self.assertEqual(task["verification"], "smoke PASS")
        self.assertEqual(ps.validate_state(self.load()), [])

    def test_failed_gate_test_blocks_verification(self) -> None:
        call(ps.cmd_record_test, project=self.project, gate="B", name="asset",
             status="FAIL", command="validate", evidence="log", details="")
        code, output = call(
            ps.cmd_record_task,
            **task_args(self.project, "T2", "verified", gate="B",
                        evidence=["artifacts/qa_report.json"]),
        )
        self.assertEqual(code, 2)
        self.assertIn("FAIL test", output)

    def test_next_task_respects_dependencies_and_blocked_status(self) -> None:
        call(ps.cmd_record_task, **task_args(self.project, "T1", "verified",
                                             evidence=["evidence/a"]))
        call(ps.cmd_record_task,
             **task_args(self.project, "T2", "planned", depends_on=["T1"]))
        call(ps.cmd_record_task,
             **task_args(self.project, "T3", "blocked", depends_on=["T1"]))
        code, output = call(ps.cmd_next_task, project=self.project)
        self.assertEqual(code, 0)
        self.assertIn("READY T2", output)
        self.assertNotIn("READY T3", output)
        self.assertIn("BLOCKED T3", output)

    def test_validation_detects_dependency_cycle(self) -> None:
        call(ps.cmd_record_task, **task_args(self.project, "T1", "planned",
                                             depends_on=["T2"]))
        call(ps.cmd_record_task, **task_args(self.project, "T2", "planned",
                                             depends_on=["T1"]))
        errors = ps.validate_state(self.load())
        self.assertTrue(any("cycle" in error for error in errors), errors)

    def test_sync_spec_adds_tasks_and_assets_without_overwriting(self) -> None:
        spec = Path(self.temp.name) / "project.json"
        spec.write_text(json.dumps({
            "tasks": [
                {"id": "T1", "title": "Plan", "skills": ["game-planner"],
                 "depends_on": [], "verify": "spec reviewed"},
                {"id": "T2", "title": "Build", "skills": ["blender-modeling"],
                 "depends_on": ["T1"], "verify": "validate"},
            ],
            "assets": [{"id": "sm_rock", "animated": False}],
        }))
        code, output = call(ps.cmd_sync_spec, project=self.project,
                            spec=str(spec), dry_run=False)
        self.assertEqual(code, 0, output)
        data = self.load()
        self.assertEqual([task["id"] for task in data["tasks"]], ["T1", "T2"])
        self.assertEqual(data["tasks"][0]["owner"], "game-design")
        self.assertEqual(data["tasks"][1]["owner"], "modeling")
        self.assertEqual(data["assets"][0]["status"], "pending")
        call(ps.cmd_record_task, **task_args(self.project, "T1", "verified",
                                             evidence=["evidence/spec"]))
        code, output = call(ps.cmd_sync_spec, project=self.project,
                            spec=str(spec), dry_run=False)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.load()["tasks"][0]["status"], "verified")
        self.assertEqual(self.load()["tasks"][0]["evidence"], ["evidence/spec"])

    def test_sync_spec_rejects_duplicate_task_ids(self) -> None:
        spec = Path(self.temp.name) / "project.json"
        spec.write_text(json.dumps({
            "tasks": [
                {"id": "T1", "title": "One", "skills": ["game-planner"]},
                {"id": "T1", "title": "Two", "skills": ["game-planner"]},
            ],
        }))
        code, output = call(ps.cmd_sync_spec, project=self.project,
                            spec=str(spec), dry_run=False)
        self.assertEqual(code, 2)
        self.assertIn("duplicate task id", output)
        self.assertEqual(self.load()["tasks"], [])

    def test_update_preserves_existing_fields(self) -> None:
        call(ps.cmd_record_task, **task_args(self.project, "T1", "planned",
                                             owner="gameplay", depends_on=[]))
        call(ps.cmd_record_task, **task_args(self.project, "T1", "in_progress",
                                             note="started"))
        task = self.load()["tasks"][0]
        self.assertEqual(task["owner"], "gameplay")
        self.assertEqual(task["note"], "started")
        self.assertEqual(task["depends_on"], [])


if __name__ == "__main__":
    unittest.main()
