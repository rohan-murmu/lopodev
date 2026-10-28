#!/usr/bin/env python3
"""Deterministic Godot Android APK/AAB export with verification.

This module owns validation and artifact checks. The shell wrapper
``tools/godot/export_android.sh`` and the ``lopodev android-export`` command call
the same implementation, and the optional MCP server exposes it without
duplicating export logic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXPORT_FORMATS = ("apk", "aab")
EXPORT_MODES = ("debug", "release")
DEFAULT_PRESET = "Android"
MIN_ARTIFACT_BYTES = 1_000_000

RELEASE_ENV = {
    "GODOT_ANDROID_KEYSTORE_RELEASE_PATH": (
        "GODOT_ANDROID_KEYSTORE_RELEASE_PATH", "ANDROID_KEYSTORE_RELEASE_PATH"),
    "GODOT_ANDROID_KEYSTORE_RELEASE_USER": (
        "GODOT_ANDROID_KEYSTORE_RELEASE_USER", "ANDROID_KEYSTORE_RELEASE_USER"),
    "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD": (
        "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD", "ANDROID_KEYSTORE_RELEASE_PASSWORD"),
}
RELEASE_FIELDS = (
    ("GODOT_ANDROID_KEYSTORE_RELEASE_PATH", "keystore/release", "keystore path"),
    ("GODOT_ANDROID_KEYSTORE_RELEASE_USER", "keystore/release_user", "keystore user"),
    ("GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD", "keystore/release_password",
     "keystore password"),
)
SECTION_RE = re.compile(r"^\[preset\.(\d+)(\.options)?\]$")
INLINE_ERROR_RE = re.compile(r"(^|\s)(ERROR:|SCRIPT ERROR:)", re.MULTILINE)


class ExportError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def toolkit_root() -> Path:
    configured = os.environ.get("LOPODEV_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_config(text: str) -> list[dict]:
    presets: dict[int, dict] = {}
    current: int | None = None
    options = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            match = SECTION_RE.fullmatch(line)
            if match:
                current = int(match.group(1))
                options = bool(match.group(2))
                presets.setdefault(current, {"main": {}, "options": {}})
            else:
                current = None
                options = False
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        section = "options" if options else "main"
        presets[current][section][key.strip()] = value.strip()
    output = []
    for index in sorted(presets):
        entry = presets[index]
        entry["index"] = index
        output.append(entry)
    return output


def read_presets(godot_dir: Path) -> list[dict]:
    path = godot_dir / "export_presets.cfg"
    if not path.is_file():
        raise ExportError(f"export_presets.cfg not found: {path}", 2)
    try:
        return parse_config(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExportError(f"cannot read {path}: {exc}", 2) from exc


def read_credentials(godot_dir: Path) -> dict[int, dict]:
    path = godot_dir / ".godot" / "export_credentials.cfg"
    if not path.is_file():
        return {}
    try:
        presets = parse_config(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {entry["index"]: {**entry["main"], **entry["options"]}
            for entry in presets}


def default_preset_name(presets: list[dict], export_format: str, requested: str) -> str:
    """For AAB with the default name, prefer a Gradle AAB preset when one exists."""
    if export_format != "aab" or requested != DEFAULT_PRESET:
        return requested
    for preset in presets:
        options = preset.get("options", {})
        if (unquote(preset["main"].get("platform", "")).lower() == "android"
                and truthy(options.get("gradle_build/use_gradle_build"))
                and unquote(options.get("gradle_build/export_format", "0")) == "1"):
            return unquote(preset["main"].get("name", ""))
    return requested


def find_preset(presets: list[dict], name: str) -> dict:
    for entry in presets:
        if unquote(entry["main"].get("name", "")) == name:
            if unquote(entry["main"].get("platform", "")).lower() != "android":
                raise ExportError(f"export preset '{name}' is not an Android preset", 2)
            return entry
    available = ", ".join(unquote(entry["main"].get("name", "(unnamed)"))
                          for entry in presets) or "(none)"
    raise ExportError(
        f"Android export preset '{name}' not found; available presets: {available}", 2)


def validate_preset_format(preset: dict, name: str, export_format: str) -> None:
    options = preset["options"]
    gradle = truthy(options.get("gradle_build/use_gradle_build"))
    export_format_value = options.get("gradle_build/export_format", "0")
    try:
        configured = int(export_format_value)
    except ValueError as exc:
        raise ExportError(
            f"preset '{name}' has an invalid gradle_build/export_format value", 2) from exc
    if export_format == "aab":
        if not gradle:
            raise ExportError(
                f"preset '{name}' does not enable Gradle build. Enable Use Gradle Build "
                "and set Export Format to Android App Bundle.", 2)
        if configured != 1:
            raise ExportError(
                f"preset '{name}' is configured for APK, not AAB. Set Export Format to "
                "Android App Bundle in Godot or choose a dedicated AAB preset.", 2)
    elif configured == 1:
        raise ExportError(
            f"preset '{name}' is configured for AAB. Use --format aab or select an APK "
            "preset.", 2)


def preset_metadata(preset: dict) -> dict:
    options = preset["options"]
    architectures = [
        key.split("/", 1)[1] for key in (
            "architectures/armeabi-v7a", "architectures/arm64-v8a",
            "architectures/x86", "architectures/x86_64")
        if truthy(options.get(key))
    ]
    return {
        "package_name": unquote(options.get("package/unique_name", "")),
        "version_code": unquote(options.get("version/code", "")),
        "version_name": unquote(options.get("version/name", "")),
        "architectures": architectures,
        "gradle_build": truthy(options.get("gradle_build/use_gradle_build")),
    }


def godot_version(godot: str, runner=subprocess.run) -> str:
    try:
        result = runner([godot, "--version"], capture_output=True, text=True,
                        timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0] if text else "unknown"


def template_directory(godot: str, env: dict, runner=subprocess.run) -> Path:
    base = Path(env.get("GODOT_TEMPLATES") or
                Path.home() / ".local/share/godot/export_templates").expanduser()
    version = godot_version(godot, runner)
    version_dir = version.split(".official", 1)[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\w+)?", version_dir):
        version_dir = version.split()[0] if version != "unknown" else ""
    return base / version_dir


def resolve_godot(explicit: str | None = None, root: Path | None = None) -> str:
    root = root or toolkit_root()
    candidates: list[str] = []
    if explicit:
        candidates.append(str(Path(explicit).expanduser()))
    configured = os.environ.get("GODOT")
    if configured:
        candidates.append(str(Path(configured).expanduser()))
    for pattern in (".tools/godot/Godot_v*_linux.x86_64",
                    ".tools/godot/Godot_v*_macos.universal"):
        candidates.extend(str(path) for path in root.glob(pattern))
    for name in ("godot", "godot4"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    raise ExportError(
        "Godot executable not found. Set GODOT or pass --godot /path/to/godot.", 2)


def android_sdk(env: dict) -> Path:
    # Honor the HOME in `env` (not the process home) so callers and tests
    # that pass an isolated environment get an isolated SDK lookup.
    home = Path(env.get("HOME") or Path.home())
    return Path(env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT") or
                home / "Android/Sdk").expanduser()


def java_home(env: dict) -> Path | None:
    configured = env.get("JAVA_HOME")
    if configured:
        candidate = Path(configured).expanduser()
        if (candidate / "bin/java").is_file():
            return candidate
    java = env.get("JAVA") or shutil.which("java")
    if not java:
        return None
    path = Path(java).resolve()
    try:
        return path.parents[1]
    except IndexError:
        return None


def debug_keystore(env: dict) -> Path:
    configured = (env.get("GODOT_ANDROID_KEYSTORE_DEBUG_PATH") or
                  env.get("ANDROID_DEBUG_KEYSTORE"))
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local/share/godot/keystores/debug.keystore"


def find_apksigner(env: dict) -> str | None:
    configured = env.get("APKSIGNER")
    if configured and Path(configured).is_file():
        return configured
    build_tools = android_sdk(env) / "build-tools"
    if not build_tools.is_dir():
        return None
    versions = sorted((path for path in build_tools.iterdir() if path.is_dir()),
                      key=lambda path: path.name, reverse=True)
    for version in versions:
        candidate = version / "apksigner"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_build_tool(env: dict, name: str) -> str | None:
    """Newest executable `name` under the SDK build-tools, or None."""
    build_tools = android_sdk(env) / "build-tools"
    if not build_tools.is_dir():
        return None
    for version in sorted((p for p in build_tools.iterdir() if p.is_dir()),
                          key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")],
                          reverse=True):
        candidate = version / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_adb(env: dict) -> str | None:
    candidate = android_sdk(env) / "platform-tools/adb"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which("adb")


BADGING_PATTERNS = {
    "package": re.compile(r"package: name='([^']+)'"),
    "version_code": re.compile(r"versionCode='([^']*)'"),
    "version_name": re.compile(r"versionName='([^']*)'"),
    "min_sdk": re.compile(r"(?:minSdkVersion|sdkVersion):'(\d+)'"),
    "target_sdk": re.compile(r"targetSdkVersion:'(\d+)'"),
    "launchable_activity": re.compile(r"launchable-activity: name='([^']+)'"),
}


def apk_metadata(apk: Path, expected: dict, env: dict, log_path: Path,
                 runner=subprocess.run) -> dict:
    """Read the packaged manifest with aapt2 and compare it with the preset."""
    aapt2 = find_build_tool(env, "aapt2")
    if not aapt2:
        return {"status": "NOT RUN", "reason": "aapt2 not found in Android SDK build-tools"}
    result = run_logged([aapt2, "dump", "badging", str(apk)], log_path, env, 120, runner)
    if result.returncode != 0:
        return {"status": "FAIL", "reason": f"aapt2 exit {result.returncode}", "log": str(log_path)}
    # run_logged streams output into the log file; parse that, not stdout.
    text = log_path.read_text(encoding="utf-8", errors="replace")
    found = {key: (match.group(1) if (match := pattern.search(text)) else "")
             for key, pattern in BADGING_PATTERNS.items()}
    if not found["launchable_activity"]:
        # Godot 4.6 launches through an <activity-alias>, which `badging` does
        # not report; find the LAUNCHER category in the manifest tree instead.
        tree_log = log_path.with_name(log_path.stem + "_manifest.log")
        tree = run_logged([aapt2, "dump", "xmltree", "--file", "AndroidManifest.xml", str(apk)],
                          tree_log, env, 120, runner)
        text = tree_log.read_text(encoding="utf-8", errors="replace") if tree_log.is_file() else ""
        if tree.returncode == 0 and "android.intent.category.LAUNCHER" in text:
            names = re.findall(r'android:name\(0x01010003\)="([^"]+)"', text.split(
                "android.intent.category.LAUNCHER")[0])
            components = [name for name in names if "." in name and not name.startswith("android.")]
            found["launchable_activity"] = components[-1] if components else "LAUNCHER"
    problems = []
    if expected.get("package_name") and found["package"] != expected["package_name"]:
        problems.append(f"package {found['package']!r} != preset {expected['package_name']!r}")
    if expected.get("version_code") and found["version_code"] != expected["version_code"]:
        problems.append(f"versionCode {found['version_code']!r} != preset {expected['version_code']!r}")
    if not found["launchable_activity"]:
        problems.append("no launchable activity")
    return {"status": "FAIL" if problems else "PASS", "problems": problems, **found,
            "log": str(log_path)}


def device_gate(apk: Path, package: str, env: dict, log_path: Path,
                runner=subprocess.run, settle_seconds: float = 6.0,
                sleep=time.sleep) -> dict:
    """Install, launch and confirm the process is alive on a connected device."""
    adb = find_adb(env)
    if not adb:
        return {"status": "NOT RUN", "reason": "adb not found"}
    listed = runner([adb, "devices"], capture_output=True, text=True, timeout=30, check=False)
    devices = [line.split()[0] for line in (listed.stdout or "").splitlines()[1:]
               if line.strip().endswith("device")]
    if not devices:
        return {"status": "NOT RUN", "reason": "no Android device or emulator connected (`adb devices`)"}
    serial = env.get("ANDROID_SERIAL") or devices[0]
    base = [adb, "-s", serial]
    steps = [("install", [*base, "install", "-r", str(apk)], 300),
             ("clear_log", [*base, "logcat", "-c"], 30),
             ("launch", [*base, "shell", "monkey", "-p", package, "-c",
                         "android.intent.category.LAUNCHER", "1"], 60)]
    transcript = []
    for name, command, timeout in steps:
        result = runner(command, capture_output=True, text=True, timeout=timeout, check=False)
        transcript.append(f"$ {' '.join(command)}\nexit={result.returncode}\n{result.stdout}{result.stderr}")
        if result.returncode != 0 or (name == "install" and "Success" not in (result.stdout or "")):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("\n".join(transcript), encoding="utf-8")
            return {"status": "FAIL", "serial": serial, "step": name, "log": str(log_path)}
    sleep(settle_seconds)
    alive = runner([*base, "shell", "pidof", package], capture_output=True, text=True,
                   timeout=30, check=False)
    logcat = runner([*base, "logcat", "-d", "-t", "400"], capture_output=True, text=True,
                    timeout=60, check=False)
    transcript.append(f"pidof={alive.stdout.strip()}\n--- logcat\n{logcat.stdout}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(transcript), encoding="utf-8")
    crashed = "FATAL EXCEPTION" in (logcat.stdout or "") and package in (logcat.stdout or "")
    running = alive.returncode == 0 and alive.stdout.strip() != ""
    return {"status": "PASS" if running and not crashed else "FAIL", "serial": serial,
            "pid": alive.stdout.strip(), "crash_in_logcat": crashed, "log": str(log_path),
            "note": "launch smoke only; interaction and performance remain NOT RUN"}


def release_signing(godot_dir: Path, env: dict, preset: dict) -> dict[str, str]:
    credentials = read_credentials(godot_dir).get(preset["index"], {})
    values: dict[str, str] = {}
    for canonical, preset_key, _label in RELEASE_FIELDS:
        value = ""
        for alias in RELEASE_ENV[canonical]:
            if env.get(alias):
                value = env[alias]
                break
        if not value:
            value = unquote(credentials.get(preset_key, ""))
        if not value:
            value = unquote(preset["options"].get(preset_key, ""))
        if value:
            values[canonical] = value
    missing = [label for canonical, _key, label in RELEASE_FIELDS
               if not values.get(canonical)]
    if missing:
        raise ExportError(
            "release signing is incomplete: " + ", ".join(missing) +
            ". Configure Release keystore, user and password in Godot, or set "
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH/USER/PASSWORD.", 2)
    keystore = Path(values["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"]).expanduser()
    if not keystore.is_absolute():
        keystore = godot_dir / keystore
    if not keystore.is_file():
        raise ExportError(
            "release keystore file was not found. Check the configured release path.", 2)
    return values


def canonical_release_environment(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items()
            if key in RELEASE_ENV}


def build_editor_settings(env: dict, godot: str,
                          runner=subprocess.run) -> tuple[str, str]:
    sdk = android_sdk(env)
    java = java_home(env)
    keystore = debug_keystore(env)
    version = godot_version(godot, runner)
    match = re.search(r"(\d+)\.(\d+)", version)
    suffix = f"{match.group(1)}.{match.group(2)}" if match else "4.6"
    lines = [
        '[gd_resource type="EditorSettings" format=3]',
        "",
        "[resource]",
    ]
    if sdk.is_dir():
        lines.append(f'export/android/android_sdk_path = "{sdk}"')
    if java:
        lines.append(f'export/android/java_sdk_path = "{java}"')
    lines.append(f'export/android/debug_keystore = "{keystore}"')
    lines.append('export/android/debug_keystore_pass = "android"')
    return f"editor_settings-{suffix}.tres", "\n".join(lines) + "\n"


def run_logged(command: list[str], log_path: Path, env: dict, timeout: int,
               runner=subprocess.run):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            return runner(command, stdout=log, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"command timed out after {timeout}s: {command[0]}; "
                          f"log={log_path}") from exc
    except OSError as exc:
        raise ExportError(f"could not run {command[0]}: {exc}; log={log_path}") from exc


def run_capability_check(godot: str, env: dict, log_path: Path,
                         runner=subprocess.run) -> None:
    command = [str(toolkit_root() / "tools/godot/check_android.sh")]
    if not Path(command[0]).is_file():
        raise ExportError("Android capability check script is missing", 2)
    result = run_logged(command, log_path, env, 120, runner)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if result.returncode != 0 or "ANDROID_EXPORT_READY=1" not in text:
        tail = "\n".join(text.splitlines()[-30:])
        raise ExportError(
            "Android prerequisites are incomplete; see "
            f"{log_path}\n{tail}", 1)


def run_import_gate(godot: str, godot_dir: Path, log_path: Path, env: dict,
                    runner=subprocess.run) -> None:
    command = [godot, "--headless", "--path", str(godot_dir), "--import"]
    result = run_logged(command, log_path, env, 180, runner)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if result.returncode != 0:
        raise ExportError(f"Godot import failed with exit {result.returncode}; log={log_path}",
                          result.returncode or 1)
    errors = INLINE_ERROR_RE.findall(text)
    if errors:
        raise ExportError(f"Godot import logged project errors; log={log_path}", 1)


def validate_artifact(path: Path, export_format: str,
                      min_bytes: int = MIN_ARTIFACT_BYTES) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise ExportError(f"expected {export_format.upper()} artifact is missing or empty: {path}",
                          1)
    size = path.stat().st_size
    if size < min_bytes:
        raise ExportError(
            f"{export_format.upper()} artifact is implausibly small: {size} bytes", 1)
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExportError(f"{export_format.upper()} artifact is not a valid zip archive: {exc}",
                          1) from exc
    if export_format == "apk":
        if "AndroidManifest.xml" not in names:
            raise ExportError(f"APK has no AndroidManifest.xml: {path}", 1)
    elif not ({"BundleConfig.pb", "base/manifest/AndroidManifest.xml"} & names):
        raise ExportError(f"AAB has no bundle manifest: {path}", 1)
    return size


def find_jarsigner(env: dict) -> str | None:
    configured = env.get("JARSIGNER")
    if configured and Path(configured).is_file():
        return configured
    home = java_home(env)
    if home:
        candidate = home / "bin" / "jarsigner"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("jarsigner")


def verify_aab_signature(aab: Path, env: dict, log_path: Path,
                         runner=subprocess.run) -> str:
    jarsigner = find_jarsigner(env)
    if not jarsigner:
        return "NOT RUN"
    result = run_logged([jarsigner, "-verify", str(aab)],
                        log_path, env, 120, runner)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if result.returncode != 0 or "jar verified" not in text.lower():
        raise ExportError(f"AAB signature verification failed; log={log_path}", 1)
    return "PASS"


def verify_apk_signature(apk: Path, env: dict, log_path: Path,
                         runner=subprocess.run) -> str:
    apksigner = find_apksigner(env)
    if not apksigner:
        return "NOT RUN"
    result = run_logged([apksigner, "verify", "--verbose", str(apk)],
                        log_path, env, 120, runner)
    if result.returncode != 0:
        raise ExportError(f"APK signature verification failed; log={log_path}", 1)
    return "PASS"


def output_path(godot_dir: Path, export_format: str, mode: str,
                requested: str | None) -> Path:
    if requested:
        path = Path(requested).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        slug = godot_dir.parent.name
        suffix = "_debug" if mode == "debug" else ""
        path = godot_dir.parent / "build" / f"{slug}{suffix}.{export_format}"
    if path.suffix.lower() != f".{export_format}":
        raise ExportError(
            f"output path must end with .{export_format}: {path}", 2)
    if path.is_symlink() or path.is_dir():
        raise ExportError(f"refusing unsafe output path: {path}", 2)
    return path.resolve()


def build_template_installed(godot_dir: Path) -> bool:
    build = godot_dir / "android" / "build"
    return (build / "build.gradle").is_file() or (build / "settings.gradle").is_file()


def export_command(godot: str, godot_dir: Path, mode: str, preset: str,
                   out: Path, install_build_template: bool = False) -> list[str]:
    command = [godot, "--headless", "--path", str(godot_dir)]
    if install_build_template:
        command.append("--install-android-build-template")
    command.extend([f"--export-{mode}", preset, str(out)])
    return command


def export_project(godot_dir: str, export_format: str = "apk", mode: str = "debug",
                   preset_name: str = DEFAULT_PRESET, output: str | None = None,
                   godot: str | None = None, check_capabilities: bool = True,
                   run_import: bool = True, dry_run: bool = False,
                   min_artifact_bytes: int = MIN_ARTIFACT_BYTES,
                   env: dict | None = None, runner=subprocess.run,
                   root: Path | None = None, install_run: bool = False) -> dict:
    godot_dir = Path(godot_dir).expanduser().resolve()
    if export_format not in EXPORT_FORMATS:
        raise ExportError(f"format must be one of: {', '.join(EXPORT_FORMATS)}", 2)
    if mode not in EXPORT_MODES:
        raise ExportError(f"mode must be one of: {', '.join(EXPORT_MODES)}", 2)
    if export_format == "aab" and mode != "release":
        raise ExportError("AAB is a distribution format; use --mode release", 2)
    if not (godot_dir / "project.godot").is_file():
        raise ExportError(f"not a Godot project (missing project.godot): {godot_dir}", 2)

    presets = read_presets(godot_dir)
    preset_name = default_preset_name(presets, export_format, preset_name)
    preset = find_preset(presets, preset_name)
    validate_preset_format(preset, preset_name, export_format)
    metadata = preset_metadata(preset)
    if not metadata["package_name"]:
        raise ExportError(
            f"preset '{preset_name}' has no Android package/unique_name", 2)
    try:
        project_text = (godot_dir / "project.godot").read_text(
            encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExportError(f"cannot read project.godot: {exc}", 2) from exc
    if "textures/vram_compression/import_etc2_astc=true" not in project_text:
        raise ExportError(
            "Android export requires [rendering] "
            "textures/vram_compression/import_etc2_astc=true in project.godot", 2)

    environment = dict(os.environ if env is None else env)
    resolved_godot = resolve_godot(godot, root)
    environment["GODOT"] = resolved_godot
    out = output_path(godot_dir, export_format, mode, output)
    signing = release_signing(godot_dir, environment, preset) if mode == "release" else {}
    environment.update(canonical_release_environment(signing))
    templates = template_directory(resolved_godot, environment, runner)

    logs = godot_dir.parent / "artifacts/logs"
    stamp = utc_stamp()
    suffix = f"{export_format}_{mode}"
    import_log = logs / f"android_import_{stamp}.log"
    capability_log = logs / f"android_capability_{stamp}.log"
    export_log = logs / f"android_export_{suffix}_{stamp}.log"
    signature_log = logs / f"android_signature_{stamp}.log"
    install_template = (export_format == "aab" and
                        not build_template_installed(godot_dir))
    command = export_command(resolved_godot, godot_dir, mode, preset_name, out,
                             install_build_template=install_template)
    started = time.time()

    if dry_run:
        return {"status": "DRY_RUN", "format": export_format, "mode": mode,
                "preset": preset_name, "artifact": str(out), "command": command,
                "godot": resolved_godot, "logs": str(logs), **metadata}

    if check_capabilities:
        run_capability_check(resolved_godot, environment, capability_log, runner)

    if export_format == "aab" and install_template:
        source_template = templates / "android_source.zip"
        if not source_template.is_file():
            raise ExportError(
                "AAB export must install the Gradle Android build template, but "
                f"android_source.zip is missing under {templates}. Install matching "
                "Godot export templates or set GODOT_TEMPLATES.", 1)

    if run_import:
        run_import_gate(resolved_godot, godot_dir, import_log, environment, runner)

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lopodev_android_cfg_") as temporary:
        settings_name, settings_text = build_editor_settings(environment, resolved_godot, runner)
        settings_dir = Path(temporary) / "godot"
        settings_dir.mkdir()
        (settings_dir / settings_name).write_text(settings_text, encoding="utf-8")
        environment["XDG_CONFIG_HOME"] = temporary
        result = run_logged(command, export_log, environment, 900, runner)
    if result.returncode != 0:
        raise ExportError(
            f"Godot Android export failed with exit {result.returncode}; log={export_log}",
            result.returncode or 1)
    if not out.is_file() or out.stat().st_mtime < started - 1:
        raise ExportError(
            f"Godot reported success but did not write a fresh artifact: {out}", 1)

    size = validate_artifact(out, export_format, min_artifact_bytes)
    signature = "NOT RUN"
    if export_format == "apk":
        signature = verify_apk_signature(out, environment, signature_log, runner)
    else:
        signature = verify_aab_signature(out, environment, signature_log, runner)
    manifest = {"status": "NOT RUN", "reason": "AAB manifests are protobuf; inspect with bundletool"}
    if export_format == "apk":
        manifest = apk_metadata(out, metadata, environment, logs / f"android_badging_{stamp}.log", runner)
        if manifest["status"] == "FAIL":
            raise ExportError(f"APK metadata check failed: {'; '.join(manifest.get('problems', []))} "
                              f"log={manifest.get('log')}", 1)
    device = {"status": "NOT RUN", "reason": "not requested (use --install-run)"}
    if install_run:
        if export_format != "apk":
            device = {"status": "NOT RUN", "reason": "device install needs an APK"}
        else:
            device = device_gate(out, metadata["package_name"], environment,
                                 logs / f"android_device_{stamp}.log", runner)
    report = {
        "status": "PASS" if device["status"] != "FAIL" else "FAIL",
        "gate": "PASS", "format": export_format, "mode": mode,
        "preset": preset_name, "artifact": str(out), "bytes": size,
        "signature": signature, "log": str(export_log), **metadata,
        "manifest": manifest,
        "import_log": str(import_log) if run_import else "NOT RUN",
        "capability_log": str(capability_log) if check_capabilities else "NOT RUN",
        "device_gate": device["status"], "device": device,
        "interaction_gate": "NOT RUN", "performance_gate": "NOT RUN",
        "play_console_gate": "NOT RUN" if export_format == "aab" else "NOT APPLICABLE",
    }
    report_path = logs / f"android_report_{suffix}_{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="android_export.py",
        description="Export a Godot Android APK or release AAB with verification.")
    parser.add_argument("godot_dir", help="Godot project directory containing project.godot")
    parser.add_argument("--format", choices=EXPORT_FORMATS, default="apk")
    parser.add_argument("--mode", choices=EXPORT_MODES, default="debug")
    parser.add_argument("--preset", default=DEFAULT_PRESET,
                        help=f"Android export preset name (default: {DEFAULT_PRESET})")
    parser.add_argument("--out", help="output .apk/.aab path")
    parser.add_argument("--godot", help="Godot executable (default: GODOT or pinned build)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the request and print the command without exporting")
    parser.add_argument("--json", action="store_true", help="print a JSON result")
    parser.add_argument("--install-run", action="store_true",
                        help="install and launch the APK on a connected device/emulator")
    args = parser.parse_args(argv)
    try:
        result = export_project(
            args.godot_dir, args.format, args.mode, args.preset, args.out,
            godot=args.godot, dry_run=args.dry_run, install_run=args.install_run)
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"ANDROID_EXPORT_GATE=FAIL format={args.format} mode={args.mode}",
              file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"ANDROID_EXPORT_GATE=FAIL format={args.format} mode={args.mode}",
              file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") in ("PASS", "DRY_RUN") else 1
    elif args.dry_run:
        print("ANDROID_EXPORT_DRY_RUN=1")
        print("COMMAND=" + " ".join(result["command"]))
    else:
        print(f"ANDROID_EXPORT_GATE=PASS format={result['format']} "
              f"mode={result['mode']} artifact={result['artifact']} "
              f"bytes={result['bytes']}")
        label = "APK_SIGNATURE_GATE" if result["format"] == "apk" else "AAB_SIGNATURE_GATE"
        print(f"{label}={result['signature']}")
        print(f"LOG={result['log']}")
        manifest = result["manifest"]
        print(f"MANIFEST_GATE={manifest['status'].replace(' ', '_')} package={manifest.get('package', '')} "
              f"versionCode={manifest.get('version_code', '')} minSdk={manifest.get('min_sdk', '')} "
              f"targetSdk={manifest.get('target_sdk', '')}")
        device = result["device"]
        print(f"DEVICE_GATE={device['status'].replace(' ', '_')} {device.get('reason') or device.get('log', '')}")
        print("INTERACTION_GATE=NOT_RUN PERFORMANCE_GATE=NOT_RUN")
        print(f"REPORT={result['report']}")
        if result["format"] == "aab":
            print("PLAY_CONSOLE_GATE=NOT_RUN local export is not Play acceptance")
    return 0 if result.get("status") in ("PASS", "DRY_RUN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
