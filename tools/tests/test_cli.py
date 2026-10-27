import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "lopodev"


class LopoDevCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *args], text=True, capture_output=True, check=False
        )

    def test_version_reports_toolkit_root(self) -> None:
        result = self.run_cli("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"lopodev {(ROOT / 'VERSION').read_text().strip()}", result.stdout)
        self.assertIn(f"root={ROOT}", result.stdout)

    def test_new_forwards_bootstrap_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "ws"
            result = self.run_cli("new", "--workspace", str(workspace),
                                  "--slug", "demo", "--title", "Demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PROJECT_BOOTSTRAPPED=", result.stdout)
            self.assertTrue((workspace / "projects/demo/project.json").is_file())
            self.assertTrue((workspace / ".opencode/agents/lopodev.md").is_file())

    def test_install_cli_creates_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "bin"
            result = self.run_cli("install-cli", str(bin_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            target = bin_dir / "lopodev"
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), CLI.resolve())

    def test_install_cli_refuses_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "lopodev"
            target.write_text("user file")
            result = self.run_cli("install-cli", temp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("not a symlink", result.stderr)
            self.assertEqual(target.read_text(), "user file")


if __name__ == "__main__":
    unittest.main()
