"""Deterministic tests for the shared Godot Android export core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermetic  # noqa: E402,F401  (no downloads, isolated user data)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/godot"))
sys.path.insert(0, str(ROOT / "tools"))

import android_export  # noqa: E402
import mcp_server  # noqa: E402

APK_PRESET = """\
[preset.0]

name="Android"
platform="Android"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path=""

[preset.0.options]

custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
gradle_build/export_format=0
package/unique_name="com.lopodev.fixture"
version/code=1
version/name="1.0"
architectures/arm64-v8a=true
"""

AAB_PRESET = APK_PRESET.replace("gradle_build/use_gradle_build=false",
                                "gradle_build/use_gradle_build=true"
                                ).replace("gradle_build/export_format=0",
                                          "gradle_build/export_format=1")
GRADLE_APK_PRESET = APK_PRESET.replace("gradle_build/use_gradle_build=false",
                                       "gradle_build/use_gradle_build=true")

PROJECT = """\
config_version=5

[application]

config/name="Fixture"

[rendering]

textures/vram_compression/import_etc2_astc=true
"""


def write_artifact(path: Path, export_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        if export_format == "apk":
            archive.writestr("AndroidManifest.xml", b"manifest")
        else:
            archive.writestr("BundleConfig.pb", b"bundle")
            archive.writestr("base/manifest/AndroidManifest.xml", b"manifest")


class FakeRunner:
    def __init__(self, version="4.6.1.stable.official.test", export_rc=0,
                 import_rc=0, import_text="Godot Engine v4.6.1\n",
                 create_artifact=True, signature_rc=0,
                 signature_text="jar verified.\n") -> None:
        self.version = version
        self.export_rc = export_rc
        self.import_rc = import_rc
        self.import_text = import_text
        self.create_artifact = create_artifact
        self.signature_rc = signature_rc
        self.signature_text = signature_text
        self.badging = ("package: name='com.lopodev.fixture' versionCode='1' versionName='1.0'\n"
                        "sdkVersion:'24'\ntargetSdkVersion:'35'\n"
                        "launchable-activity: name='com.godot.game.GodotApp'\n")
        self.xmltree = ""
        self.devices = "List of devices attached\n\n"
        self.pid = ""
        self.logcat = ""
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        stdout = kwargs.get("stdout")
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=self.version + "\n", stderr="")
        if "--import" in command:
            if stdout:
                stdout.write(self.import_text)
            return SimpleNamespace(returncode=self.import_rc, stdout="", stderr="")
        if any(part.startswith("--export-") for part in command):
            target = Path(command[-1])
            if self.create_artifact and self.export_rc == 0:
                export_format = "aab" if target.suffix.lower() == ".aab" else "apk"
                write_artifact(target, export_format)
            if stdout:
                stdout.write("Export successful\n" if self.export_rc == 0 else "export failed\n")
            return SimpleNamespace(returncode=self.export_rc, stdout="", stderr="")
        if any("verify" in part for part in command):
            if stdout:
                stdout.write(self.signature_text)
            return SimpleNamespace(returncode=self.signature_rc, stdout="", stderr="")
        if "xmltree" in command:
            if stdout:
                stdout.write(self.xmltree)
            return SimpleNamespace(returncode=0, stdout=None, stderr=None)
        if "badging" in command:
            if stdout:
                stdout.write(self.badging)
            return SimpleNamespace(returncode=0, stdout=None, stderr=None)
        if command[-1] == "devices":
            return SimpleNamespace(returncode=0, stdout=self.devices, stderr="")
        if "install" in command:
            return SimpleNamespace(returncode=0, stdout="Performing Streamed Install\nSuccess\n", stderr="")
        if "pidof" in command:
            return SimpleNamespace(returncode=0 if self.pid else 1, stdout=self.pid, stderr="")
        if "-d" in command and "logcat" in command:
            return SimpleNamespace(returncode=0, stdout=self.logcat, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class AndroidExportTests(unittest.TestCase):
    def make_sdk(self) -> None:
        for relative in ("Android/Sdk/build-tools/35.0.1/aapt2", "Android/Sdk/platform-tools/adb"):
            tool = self.root / relative
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_text("#!/bin/sh\n", encoding="utf-8")
            tool.chmod(0o755)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.godot_dir = self.root / "projects" / "demo" / "godot"
        self.godot_dir.mkdir(parents=True)
        (self.godot_dir / "project.godot").write_text(PROJECT, encoding="utf-8")
        (self.godot_dir / "export_presets.cfg").write_text(APK_PRESET, encoding="utf-8")
        self.godot = self.root / "godot"
        self.godot.write_text("#!/bin/sh\n", encoding="utf-8")
        self.godot.chmod(0o755)
        self.apksigner = self.root / "apksigner"
        self.apksigner.write_text("#!/bin/sh\n", encoding="utf-8")
        self.apksigner.chmod(0o755)
        self.templates = self.root / "templates"
        self.env = {
            "GODOT_TEMPLATES": str(self.templates),
            "APKSIGNER": str(self.apksigner),
            "JARSIGNER": str(self.apksigner),
            "HOME": str(self.root),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def set_preset(self, text: str) -> None:
        (self.godot_dir / "export_presets.cfg").write_text(text, encoding="utf-8")

    def export(self, **overrides):
        values = {
            "godot_dir": str(self.godot_dir),
            "godot": str(self.godot),
            "env": self.env,
            "check_capabilities": False,
            "min_artifact_bytes": 1,
            "runner": FakeRunner(),
        }
        values.update(overrides)
        return android_export.export_project(**values)

    def test_apk_metadata_is_read_and_checked_against_preset(self) -> None:
        self.make_sdk()
        result = self.export()
        self.assertEqual(result["manifest"]["status"], "PASS")
        self.assertEqual(result["manifest"]["package"], "com.lopodev.fixture")
        self.assertEqual(result["manifest"]["target_sdk"], "35")
        self.assertTrue(Path(result["report"]).is_file())
        self.assertEqual(result["device_gate"], "NOT RUN")

    def test_launcher_activity_alias_is_found_in_manifest_tree(self) -> None:
        # Godot 4.6 launches through <activity-alias>; badging omits it.
        self.make_sdk()
        runner = FakeRunner()
        runner.badging = runner.badging.replace(
            "launchable-activity: name='com.godot.game.GodotApp'\n", "other-activities\n")
        runner.xmltree = ('E: activity-alias (line=48)\n'
                          'A: http://schemas.android.com/apk/res/android:name(0x01010003)='
                          '"com.godot.game.GodotAppLauncher" (Raw: "x")\n'
                          'A: http://schemas.android.com/apk/res/android:name(0x01010003)='
                          '"android.intent.category.LAUNCHER" (Raw: "x")\n')
        result = self.export(runner=runner)
        self.assertEqual(result["manifest"]["launchable_activity"], "com.godot.game.GodotAppLauncher")
        runner = FakeRunner()
        runner.badging = runner.badging.replace(
            "launchable-activity: name='com.godot.game.GodotApp'\n", "")
        with self.assertRaisesRegex(android_export.ExportError, "no launchable activity"):
            self.export(runner=runner)

    def test_aab_default_preset_prefers_gradle_bundle_preset(self) -> None:
        presets = android_export.parse_config(
            '[preset.0]\nname="Android"\nplatform="Android"\n[preset.0.options]\n'
            'gradle_build/use_gradle_build=false\n'
            '[preset.1]\nname="Android AAB"\nplatform="Android"\n[preset.1.options]\n'
            'gradle_build/use_gradle_build=true\ngradle_build/export_format=1\n')
        self.assertEqual(android_export.default_preset_name(presets, "aab", "Android"), "Android AAB")
        self.assertEqual(android_export.default_preset_name(presets, "apk", "Android"), "Android")
        self.assertEqual(android_export.default_preset_name(presets, "aab", "Custom"), "Custom")

    def test_apk_package_mismatch_fails_the_gate(self) -> None:
        self.make_sdk()
        runner = FakeRunner()
        runner.badging = runner.badging.replace("com.lopodev.fixture", "com.other.game")
        with self.assertRaisesRegex(android_export.ExportError, "package 'com.other.game'"):
            self.export(runner=runner)

    def test_missing_aapt2_is_not_run_not_pass(self) -> None:
        result = self.export()
        self.assertEqual(result["manifest"]["status"], "NOT RUN")

    def test_device_gate_without_device_is_not_run(self) -> None:
        self.make_sdk()
        result = self.export(install_run=True)
        self.assertEqual(result["device_gate"], "NOT RUN")
        self.assertIn("no Android device", result["device"]["reason"])
        self.assertEqual(result["status"], "PASS")

    def test_device_gate_installs_launches_and_checks_process(self) -> None:
        self.make_sdk()
        runner = FakeRunner()
        runner.devices = "List of devices attached\nemulator-5554\tdevice\n"
        runner.pid = "4242\n"
        with mock.patch.object(android_export.time, "sleep"):
            result = self.export(runner=runner, install_run=True)
        self.assertEqual(result["device_gate"], "PASS")
        self.assertTrue(any("monkey" in command for command in runner.commands))
        runner = FakeRunner()
        runner.devices = "List of devices attached\nemulator-5554\tdevice\n"
        runner.logcat = "FATAL EXCEPTION: main\nProcess: com.lopodev.fixture, PID: 1\n"
        with mock.patch.object(android_export.time, "sleep"):
            result = self.export(runner=runner, install_run=True)
        self.assertEqual(result["device_gate"], "FAIL")
        self.assertEqual(result["status"], "FAIL")

    def test_parse_preset_and_reject_non_android(self) -> None:
        presets = android_export.parse_config(APK_PRESET)
        self.assertEqual(presets[0]["main"]["name"], '"Android"')
        self.assertEqual(presets[0]["options"]["gradle_build/export_format"], "0")
        self.assertEqual(android_export.find_preset(presets, "Android")["index"], 0)
        with self.assertRaises(android_export.ExportError):
            android_export.find_preset(presets, "Missing")

    def test_debug_apk_export_and_signature(self) -> None:
        result = self.export()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["format"], "apk")
        self.assertEqual(result["signature"], "PASS")
        self.assertEqual(result["device_gate"], "NOT RUN")
        self.assertEqual(result["package_name"], "com.lopodev.fixture")
        self.assertEqual(result["architectures"], ["arm64-v8a"])
        self.assertFalse(result["gradle_build"])
        self.assertTrue(Path(result["artifact"]).is_file())
        self.assertTrue(Path(result["log"]).is_file())

    def test_aab_release_export(self) -> None:
        self.set_preset(AAB_PRESET)
        (self.templates / "4.6.1.stable").mkdir(parents=True)
        (self.templates / "4.6.1.stable" / "android_source.zip").write_bytes(b"source")
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "release-user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        result = self.export(export_format="aab", mode="release", env=env)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["format"], "aab")
        self.assertEqual(result["signature"], "PASS")
        self.assertEqual(result["play_console_gate"], "NOT RUN")
        self.assertTrue(result["artifact"].endswith(".aab"))

    def test_aab_dry_run_requests_build_template_install(self) -> None:
        self.set_preset(AAB_PRESET)
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        result = self.export(export_format="aab", mode="release", env=env,
                             dry_run=True)
        self.assertIn("--install-android-build-template", result["command"])

    def test_aab_requires_release_mode(self) -> None:
        self.set_preset(AAB_PRESET)
        with self.assertRaisesRegex(android_export.ExportError, "release"):
            self.export(export_format="aab", mode="debug")

    def test_aab_rejects_apk_preset(self) -> None:
        self.set_preset(GRADLE_APK_PRESET)
        (self.templates / "4.6.1.stable").mkdir(parents=True)
        (self.templates / "4.6.1.stable" / "android_source.zip").write_bytes(b"source")
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        with self.assertRaisesRegex(android_export.ExportError, "configured for APK"):
            self.export(export_format="aab", mode="release", env=env)

    def test_apk_rejects_aab_preset(self) -> None:
        self.set_preset(AAB_PRESET)
        with self.assertRaisesRegex(android_export.ExportError, "configured for AAB"):
            self.export()

    def test_aab_requires_gradle_source_template(self) -> None:
        self.set_preset(AAB_PRESET)
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        with self.assertRaisesRegex(android_export.ExportError, "android_source.zip"):
            self.export(export_format="aab", mode="release", env=env)

    def test_installed_build_template_skips_source_zip_requirement(self) -> None:
        self.set_preset(AAB_PRESET)
        build = self.godot_dir / "android" / "build"
        build.mkdir(parents=True)
        (build / "settings.gradle").write_text("", encoding="utf-8")
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        result = self.export(export_format="aab", mode="release", env=env)
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("--install-android-build-template", self.export(
            export_format="aab", mode="release", env=env, dry_run=True)["command"])

    def test_release_signing_never_echoes_password(self) -> None:
        self.set_preset(AAB_PRESET)
        with self.assertRaises(android_export.ExportError) as caught:
            self.export(export_format="aab", mode="release")
        self.assertNotIn("secret", str(caught.exception))
        self.assertIn("release signing is incomplete", str(caught.exception))

    def test_dry_run_does_not_create_artifact(self) -> None:
        result = self.export(dry_run=True)
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertIn("--export-debug", result["command"])
        self.assertFalse(Path(result["artifact"]).exists())

    def test_project_without_android_preset(self) -> None:
        self.set_preset(APK_PRESET.replace('name="Android"', 'name="Linux"').replace(
            'platform="Android"', 'platform="Linux/X11"'))
        with self.assertRaisesRegex(android_export.ExportError, "not found"):
            self.export()

    def test_mcp_rejects_paths_outside_workspace(self) -> None:
        project = self.root / "projects" / "demo"
        spec = project / "project.json"
        spec.write_text(json.dumps({"godot_dir": "/etc"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inside the configured workspace"):
            mcp_server.project_godot_dir(self.root, "demo")
        spec.write_text(json.dumps({"godot_dir": "projects/demo/godot"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "output must stay"):
            mcp_server.android_export_project(
                self.root, "demo", output="/tmp/escape.apk",
                check_capabilities=False, min_artifact_bytes=1,
                runner=FakeRunner())
        with self.assertRaisesRegex(ValueError, "godot executable must stay"):
            mcp_server.android_export_project(
                self.root, "demo", godot="/usr/bin/true",
                check_capabilities=False, min_artifact_bytes=1,
                runner=FakeRunner())

    def test_missing_package_name_is_rejected(self) -> None:
        self.set_preset(APK_PRESET.replace(
            'package/unique_name="com.lopodev.fixture"', 'package/unique_name=""'))
        with self.assertRaisesRegex(android_export.ExportError, "package/unique_name"):
            self.export()

    def test_missing_project_godot(self) -> None:
        (self.godot_dir / "project.godot").unlink()
        with self.assertRaisesRegex(android_export.ExportError, "not a Godot project"):
            self.export()

    def test_import_errors_fail_gate(self) -> None:
        runner = FakeRunner(import_text="ERROR: broken scene\n")
        with self.assertRaisesRegex(android_export.ExportError, "project errors"):
            self.export(runner=runner)

    def test_failed_export_fails_gate(self) -> None:
        with self.assertRaisesRegex(android_export.ExportError, "exit 1"):
            self.export(runner=FakeRunner(export_rc=1))

    def test_stale_artifact_is_rejected(self) -> None:
        result = self.export()
        stale = Path(result["artifact"])
        old = time.time() - 30
        os.utime(stale, (old, old))
        with self.assertRaisesRegex(android_export.ExportError, "fresh artifact"):
            self.export(runner=FakeRunner(create_artifact=False))

    def test_invalid_artifact_is_rejected(self) -> None:
        artifact = self.root / "bad.apk"
        artifact.write_bytes(b"x" * 20)
        with self.assertRaisesRegex(android_export.ExportError, "valid zip"):
            android_export.validate_artifact(artifact, "apk", 1)
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("other.txt", b"x" * 10)
        with self.assertRaisesRegex(android_export.ExportError, "AndroidManifest"):
            android_export.validate_artifact(artifact, "apk", 1)

    def test_output_extension_and_directory(self) -> None:
        with self.assertRaisesRegex(android_export.ExportError, "must end with"):
            self.export(output=str(self.root / "wrong.zip"))
        unsafe = self.root / "directory.apk"
        unsafe.mkdir()
        with self.assertRaisesRegex(android_export.ExportError, "unsafe output"):
            self.export(output=str(unsafe))

    def test_default_output_uses_project_slug(self) -> None:
        result = self.export()
        expected = self.godot_dir.parent / "build" / "demo_debug.apk"
        self.assertEqual(Path(result["artifact"]), expected.resolve())

    def test_cli_and_shell_wrapper_dry_run(self) -> None:
        environment = dict(os.environ)
        environment.update(self.env)
        cli = subprocess.run(
            [sys.executable, str(ROOT / "tools/lopodev_cli.py"), "android-export",
             str(self.godot_dir), "--godot", str(self.godot), "--dry-run", "--json"],
            capture_output=True, text=True, env=environment, timeout=30, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["status"], "DRY_RUN")
        shell = subprocess.run(
            [str(ROOT / "tools/godot/export_android.sh"), str(self.godot_dir),
             "--godot", str(self.godot), "--dry-run"],
            capture_output=True, text=True, env=environment, timeout=30, check=False)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        self.assertIn("ANDROID_EXPORT_DRY_RUN=1", shell.stdout)
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        legacy_env = dict(environment)
        legacy_env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        legacy = subprocess.run(
            [str(ROOT / "tools/godot/export_android.sh"), str(self.godot_dir),
             "--release", "--godot", str(self.godot), "--dry-run"],
            capture_output=True, text=True, env=legacy_env, timeout=30, check=False)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertIn("--export-release", legacy.stdout)

    def test_release_credentials_file_in_preset_section(self) -> None:
        credentials = self.godot_dir / ".godot" / "export_credentials.cfg"
        credentials.parent.mkdir()
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        credentials.write_text(
            '[preset.0]\n'
            f'keystore/release="{keystore}"\n'
            'keystore/release_user="credential-user"\n'
            'keystore/release_password="credential-password"\n',
            encoding="utf-8")
        preset = android_export.find_preset(
            android_export.read_presets(self.godot_dir), "Android")
        values = android_export.release_signing(self.godot_dir, {}, preset)
        self.assertEqual(values["GODOT_ANDROID_KEYSTORE_RELEASE_USER"],
                         "credential-user")
        self.assertEqual(values["GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"],
                         "credential-password")

    def test_unsigned_aab_is_not_reported_as_signed(self) -> None:
        self.set_preset(AAB_PRESET)
        (self.templates / "4.6.1.stable").mkdir(parents=True)
        (self.templates / "4.6.1.stable" / "android_source.zip").write_bytes(b"source")
        keystore = self.root / "release.keystore"
        keystore.write_bytes(b"keystore")
        env = dict(self.env)
        env.update({
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": str(keystore),
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER": "user",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": "secret",
        })
        with self.assertRaisesRegex(android_export.ExportError, "signature verification"):
            self.export(export_format="aab", mode="release", env=env,
                        runner=FakeRunner(signature_text="jar is unsigned.\n"))

    def test_mcp_project_godot_dir_and_export(self) -> None:
        project = self.root / "projects" / "demo"
        (project / "project.json").write_text(json.dumps(
            {"godot_dir": "projects/demo/godot"}), encoding="utf-8")
        self.assertEqual(mcp_server.project_godot_dir(self.root, "demo"),
                         self.godot_dir.resolve())
        result = mcp_server.android_export_project(
            self.root, "demo", runner=FakeRunner(), check_capabilities=False,
            min_artifact_bytes=1)
        self.assertEqual(result["slug"], "demo")
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
