import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import android_test  # noqa: E402
import live_session  # noqa: E402


def png(path: Path, width: int, height: int, pixel) -> Path:
    """Write an RGB PNG; `pixel(x, y)` returns (r, g, b)."""
    rows = b"".join(b"\0" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return path


class LiveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mode_is_recorded_and_respects_headless(self) -> None:
        self.assertEqual(live_session.current_mode(self.workspace), "auto")
        live_session.set_mode(self.workspace, "off")
        self.assertEqual(live_session.current_mode(self.workspace), "off")
        self.assertFalse(live_session.enabled(self.workspace))
        events = (self.workspace / ".lopodev/events.jsonl").read_text()
        self.assertIn('"live_mode"', events)
        live_session.set_mode(self.workspace, "auto")
        with mock.patch.dict(os.environ, {"LOPODEV_HEADLESS": "1"}):
            self.assertFalse(live_session.enabled(self.workspace))
        with mock.patch.object(live_session, "has_display", return_value=False):
            self.assertFalse(live_session.enabled(self.workspace))

    def test_stop_closes_only_owned_processes(self) -> None:
        record = live_session.launch(self.workspace, "godot", [sys.executable, "-c", "import time; time.sleep(60)"])
        self.assertTrue(live_session.owned(record))
        result = live_session.stop(self.workspace, "godot")
        self.assertEqual(result["status"], "STOPPED")
        self.assertFalse(live_session.owned(record))
        # A user process whose PID we once recorded but with another start time is never touched.
        user = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            path = live_session.record_path(self.workspace, "blender")
            path.write_text(json.dumps({"tool": "blender", "pid": user.pid, "start_time": "not-the-same"}))
            self.assertEqual(live_session.stop(self.workspace, "blender")["status"], "STALE")
            time.sleep(0.2)
            self.assertIsNone(user.poll(), "user process must keep running")
            self.assertFalse(path.exists())
        finally:
            user.kill()
            user.wait()

    def test_running_user_blender_is_reused_not_replaced(self) -> None:
        with mock.patch.object(live_session, "port_open", return_value=True), \
                mock.patch.object(live_session, "launch") as launch:
            result = live_session.start_blender(self.workspace)
        self.assertEqual((result["status"], result["owned"]), ("REUSED", False))
        launch.assert_not_called()


class FakeAndroid:
    """Scripted adb/emulator/avdmanager responses."""

    def __init__(self, root: Path, *, avds: str = "", crash: bool = False, blank: bool = False,
                 tap_changes: bool = True, alive: bool = True):
        self.root, self.avds, self.crash, self.blank = root, avds, crash, blank
        self.tap_changes, self.alive, self.calls, self.tapped = tap_changes, alive, [], False

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        text = " ".join(str(c) for c in command)
        out = ""
        if "-list-avds" in text:
            out = self.avds
        elif "avdmanager" in text and "create" in text:
            self.avds = "lopodev_api36"
            out = "created"
        elif text.endswith("devices"):
            out = "List of devices attached\nemulator-5584\tdevice\n"
        elif "getprop sys.boot_completed" in text:
            out = "1"
        elif "pidof" in text:
            out = "4242" if self.alive else ""
        elif "logcat -d" in text:
            out = "I godot: started\n" + ("E AndroidRuntime: FATAL EXCEPTION: main com.example.game\n" if self.crash else "")
        elif "input tap" in text:
            self.tapped = True
        elif "screencap" in text:
            changed = self.tapped and self.tap_changes
            image = png(self.root / "cap.png", 40, 30, (lambda x, y: (20, 20, 20)) if self.blank else
                        (lambda x, y: ((x * 6 + (90 if changed else 0)) % 256, y * 8 % 256, 120)))
            return subprocess.CompletedProcess(command, 0, image.read_bytes(), b"")
        return subprocess.CompletedProcess(command, 0, out, "")


class AndroidEmulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.sdk = root / "sdk"
        for tool in ("emulator/emulator", "platform-tools/adb", "cmdline-tools/latest/cmdline-tools/bin/avdmanager"):
            path = self.sdk / tool
            path.parent.mkdir(parents=True)
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)
        (self.sdk / "system-images/android-36/google_apis/x86_64").mkdir(parents=True)
        self.project = root / "ws/projects/demo"
        (self.project / "godot").mkdir(parents=True)
        (self.project / "project.json").write_text(json.dumps({"slug": "demo", "godot_dir": "projects/demo/godot",
                                                              "screens": [{"id": "menu", "controls": ["play"]}],
                                                              "navigation": {"entry": "menu"}}))
        self.apk = root / "game.apk"
        self.apk.write_bytes(b"apk")
        self.env = {"ANDROID_SDK_ROOT": str(self.sdk), "HOME": str(root), "PATH": os.environ.get("PATH", "")}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_test(self, fake: FakeAndroid) -> dict:
        with mock.patch.object(android_test.android_export, "apk_metadata", return_value={"package": "com.example.game"}), \
                mock.patch.object(android_test.android_export, "device_gate",
                                  return_value={"status": "PASS", "serial": "emulator-5584"}), \
                mock.patch.object(android_test.live_session, "has_display", return_value=True):
            return android_test.run(self.project, apk=self.apk, env=self.env, runner=fake, sleep=lambda s: None)

    def test_creates_avd_with_nested_cmdline_tools(self) -> None:
        fake = FakeAndroid(Path(self.temp.name))
        result = android_test.ensure_avd("lopodev_api36", self.env, fake)
        self.assertEqual((result["status"], result["created"]), ("PASS", True))
        create = next(c for c in fake.calls if "create" in c)
        self.assertIn("system-images;android-36;google_apis;x86_64", create)
        env = android_test.sdk_env(self.env)
        self.assertIn("toolsdir=", env["AVDMANAGER_OPTS"])

    def test_pass_when_alive_no_crash_and_tap_changes_screen(self) -> None:
        report = self.run_test(FakeAndroid(Path(self.temp.name)))
        self.assertEqual(report["status"], "PASS", report.get("reason"))
        self.assertEqual(report["emulator"]["owned"], False)  # emulator-5584 already running: reused
        self.assertGreater(report["screens"]["changed_fraction"], 0.01)
        self.assertTrue(Path(report["report"]).is_file())

    def test_failures_are_specific(self) -> None:
        cases = {"crash": ({"crash": True}, "crash"), "blank": ({"blank": True}, "blank"),
                 "static": ({"tap_changes": False}, "tap did not change"),
                 "dead": ({"alive": False}, "not running")}
        for name, (options, expected) in cases.items():
            report = self.run_test(FakeAndroid(Path(self.temp.name), **options))
            self.assertEqual(report["status"], "FAIL", name)
            self.assertIn(expected, report["reason"], name)

    def test_png_decoder_handles_filters_and_detects_blank(self) -> None:
        busy = android_test.image_stats(png(Path(self.temp.name) / "a.png", 64, 48,
                                            lambda x, y: (x * 4 % 256, y * 5 % 256, (x + y) % 256)))
        flat = android_test.image_stats(png(Path(self.temp.name) / "b.png", 64, 48, lambda x, y: (0, 0, 0)))
        self.assertFalse(busy["blank"])
        self.assertTrue(flat["blank"])
        self.assertEqual(android_test.changed_fraction(busy, busy), 0.0)


if __name__ == "__main__":
    unittest.main()
