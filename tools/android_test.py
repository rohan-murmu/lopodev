#!/usr/bin/env python3
"""Run the finished game on an Android emulator and capture evidence.

  lopodev android-test --project projects/<slug> [--avd lopodev_api36] [--tap X,Y]
                       [--keep-running] [--headless-emulator] [--apk build/x.apk]

Steps:
1. Ensure the AVD exists. A missing `lopodev_api36` is created from the installed
   `system-images;android-36;*;x86_64` image; only ~/.android/avd/<name>* is written.
2. Start the emulator in a window (or reuse a running emulator) and wait for boot.
3. Export a debug APK (tools/godot/android_export.py), install it, and launch it.
4. Check that the process is alive after 10 s and that logcat has no crash for the
   package. Take a screenshot, which must not be blank. Tap (play button or
   screen center), take a second screenshot, and check that the screen changed.
5. Record a PASS/FAIL test as type `emulator` (gate E) with the report path.
   A physical device and performance stay NOT RUN.
6. Stop the emulator if LopoDev started it.

Exit 0 only on PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "godot"))

import android_export  # noqa: E402
import live_session  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AVD = "lopodev_api36"
EMULATOR_PORT = 5584  # fixed port -> known serial, distinct from a user's default 5554
CRASH_PATTERNS = ("FATAL EXCEPTION", "Fatal signal", "SCRIPT ERROR", "ERROR: ", "ANR in ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sdk_tool(env: dict, *candidates: str) -> str | None:
    sdk = android_export.android_sdk(env)
    for relative in candidates:
        path = sdk / relative
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def system_images(env: dict) -> list[str]:
    base = android_export.android_sdk(env) / "system-images"
    found = []
    for path in sorted(base.glob("android-*/*/x86_64")) + sorted(base.glob("android-*/*/arm64-v8a")):
        api, variant, abi = path.parts[-3:]
        found.append(f"system-images;{api};{variant};{abi}")
    return found


def sdk_env(env: dict) -> dict:
    """avdmanager/emulator locate images through the SDK root, not their own path."""
    sdk = str(android_export.android_sdk(env))
    extra = {"ANDROID_HOME": sdk, "ANDROID_SDK_ROOT": sdk}
    # avdmanager derives the SDK root from its own location (toolsdir/../..); a
    # nested cmdline-tools/latest/cmdline-tools layout makes it look in the wrong place.
    if (Path(sdk) / "cmdline-tools/latest/cmdline-tools/bin/avdmanager").is_file():
        extra["AVDMANAGER_OPTS"] = f"-Dcom.android.sdkmanager.toolsdir={sdk}/cmdline-tools/latest"
    return {**env, **extra}


def ensure_avd(name: str, env: dict, runner=subprocess.run) -> dict:
    env = sdk_env(env)
    avdmanager = sdk_tool(env, "cmdline-tools/latest/bin/avdmanager", "cmdline-tools/latest/cmdline-tools/bin/avdmanager",
                          "tools/bin/avdmanager")
    emulator = sdk_tool(env, "emulator/emulator")
    if not emulator:
        return {"status": "NOT RUN", "reason": "Android emulator not installed (sdkmanager \"emulator\")"}
    listed = runner([emulator, "-list-avds"], capture_output=True, text=True, timeout=60, check=False, env=env)
    if name in (listed.stdout or "").split():
        return {"status": "PASS", "avd": name, "created": False}
    images = system_images(env)
    if not images:
        return {"status": "NOT RUN", "reason": "no x86_64/arm64 system image installed (sdkmanager)"}
    if not avdmanager:
        return {"status": "NOT RUN", "reason": "avdmanager not found (install cmdline-tools)"}
    image = images[-1]
    print(f"CREATING AVD {name} from {image} (writes ~/.android/avd/{name}.avd and {name}.ini)", flush=True)
    result = runner([avdmanager, "create", "avd", "-n", name, "-k", image, "-d", "pixel_6"], input="no\n",
                    capture_output=True, text=True, timeout=300, check=False, env=env)
    if result.returncode != 0:
        return {"status": "FAIL", "reason": f"avdmanager failed: {(result.stderr or result.stdout)[-400:]}"}
    return {"status": "PASS", "avd": name, "created": True, "image": image}


def running_emulators(adb: str, env: dict, runner=subprocess.run) -> list[str]:
    listed = runner([adb, "devices"], capture_output=True, text=True, timeout=30, check=False, env=env)
    return [line.split()[0] for line in (listed.stdout or "").splitlines()[1:]
            if line.startswith("emulator-") and line.strip().endswith("device")]


def start_emulator(workspace: Path, avd: str, env: dict, headless: bool, runner=subprocess.run,
                   sleep=time.sleep, boot_timeout: float = 420) -> dict:
    adb = android_export.find_adb(env)
    emulator = sdk_tool(env, "emulator/emulator")
    if not adb or not emulator:
        return {"status": "NOT RUN", "reason": "adb or emulator missing"}
    serial = f"emulator-{EMULATOR_PORT}"
    existing = running_emulators(adb, env, runner)
    if existing and serial not in existing:
        return {"status": "PASS", "serial": existing[0], "owned": False, "reason": "reusing a running emulator"}
    owned = False
    if serial not in existing:
        command = [emulator, "-avd", avd, "-port", str(EMULATOR_PORT), "-no-snapshot-save", "-no-boot-anim",
                   "-gpu", "auto"] + (["-no-window"] if headless or not live_session.has_display() else [])
        record = live_session.launch(workspace, "emulator", command, sdk_env(env))
        record["serial"] = serial
        live_session.record_path(workspace, "emulator").write_text(json.dumps(record, indent=2) + "\n")
        owned = True
    deadline = time.time() + boot_timeout
    booted = False
    while time.time() < deadline:
        result = runner([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], capture_output=True,
                        text=True, timeout=30, check=False, env=env)
        if (result.stdout or "").strip() == "1":
            booted = True
            break
        sleep(3)
    if not booted:
        return {"status": "FAIL", "serial": serial, "owned": owned, "reason": f"no boot within {boot_timeout}s"}
    wake_screen(adb, serial, env, runner)
    return {"status": "PASS", "serial": serial, "owned": owned}


def wake_screen(adb: str, serial: str, env: dict, runner=subprocess.run) -> None:
    """A sleeping display or lock screen pauses the game and screenshots come out black."""
    for command in (["input", "keyevent", "KEYCODE_WAKEUP"], ["wm", "dismiss-keyguard"],
                    ["svc", "power", "stayon", "true"],
                    ["settings", "put", "system", "screen_off_timeout", "1800000"],
                    # the first-run "Viewing full screen" notice would swallow the test tap
                    ["settings", "put", "secure", "immersive_mode_confirmations", "confirmed"]):
        runner([adb, "-s", serial, "shell", *command], capture_output=True, timeout=30, check=False, env=env)


def foreground(adb: str, serial: str, env: dict, runner=subprocess.run) -> str:
    result = runner([adb, "-s", serial, "shell", "dumpsys", "activity", "activities"], capture_output=True,
                    text=True, timeout=30, check=False, env=env)
    line = next((l.strip() for l in (result.stdout or "").splitlines()
                 if "mResumedActivity" in l or "ResumedActivity:" in l), "")
    return line[:200]


# ---------------------------------------------------------------- screenshot analysis

def png_pixels(data: bytes) -> tuple[int, int, int, bytes]:
    """Decode an 8-bit RGB/RGBA PNG (what screencap writes) into raw rows."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    offset, idat, width = 8, b"", 0
    while offset < len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        chunk = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", chunk[:10])
            if depth != 8 or color not in (2, 6):
                raise ValueError(f"unsupported PNG depth/color {depth}/{color}")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat += chunk
        offset += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, previous, position = bytearray(), bytearray(stride), 0
    for _ in range(height):
        kind = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                estimate = left + up - corner
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        rows += line
        previous = line
    return width, height, channels, bytes(rows)


def image_stats(path: Path, step: int = 8) -> dict:
    width, height, channels, rows = png_pixels(path.read_bytes())
    samples = [rows[(y * width + x) * channels:(y * width + x) * channels + 3]
               for y in range(0, height, step) for x in range(0, width, step)]
    colors = {bytes(s) for s in samples}
    luminance = [0.299 * s[0] + 0.587 * s[1] + 0.114 * s[2] for s in samples]
    mean = sum(luminance) / len(luminance)
    spread = (sum((v - mean) ** 2 for v in luminance) / len(luminance)) ** 0.5
    return {"width": width, "height": height, "distinct_colors": len(colors), "luma_stddev": round(spread, 2),
            "blank": len(colors) < 4 or spread < 2.0, "samples": samples}


def changed_fraction(a: dict, b: dict) -> float:
    if len(a["samples"]) != len(b["samples"]):
        return 1.0
    differ = sum(1 for x, y in zip(a["samples"], b["samples"]) if sum(abs(p - q) for p, q in zip(x, y)) > 30)
    return differ / max(1, len(a["samples"]))


def screencap(adb: str, serial: str, path: Path, env: dict, runner=subprocess.run) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = runner([adb, "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=60,
                    check=False, env=env)
    path.write_bytes(result.stdout or b"")
    return path


def play_tap(spec: dict, width: int, height: int) -> tuple[int, int, str]:
    """Where to tap to start playing: center, slightly low (menus stack Play first)."""
    if (spec.get("navigation") or {}).get("entry") and any(
            "play" in (s.get("controls") or []) for s in spec.get("screens", [])):
        return width // 2, int(height * 0.45), "main menu play button (estimated position: center)"
    return width // 2, height // 2, "screen center"


# ---------------------------------------------------------------- main flow

def run(project: Path, avd: str = DEFAULT_AVD, tap: tuple[int, int] | None = None, keep: bool = False,
        headless: bool = False, apk: Path | None = None, env: dict | None = None,
        runner=subprocess.run, sleep=time.sleep) -> dict:
    env = dict(os.environ if env is None else env)
    spec = json.loads((project / "project.json").read_text(encoding="utf-8"))
    workspace = project.resolve().parent.parent
    godot_dir = live_session.project_godot_dir(project)
    stamp = utc_stamp()
    out = project / "artifacts/android"
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"status": "FAIL", "type": "emulator", "avd": avd, "started": stamp,
                    "device_gate": "NOT RUN (emulator only)", "performance_gate": "NOT RUN"}

    def done(status: str, **fields) -> dict:
        report.update(status=status, **fields)
        path = out / f"emulator_{stamp}.json"
        path.write_text(json.dumps({k: v for k, v in report.items()}, indent=2) + "\n", encoding="utf-8")
        report["report"] = str(path)
        if (project / "pipeline_state.json").is_file():
            subprocess.run([sys.executable, str(ROOT / "tools/pipeline_state.py"), "record-test", "--project",
                            str(project), "--gate", "E", "--name", "android emulator smoke",
                            "--status", "PASS" if status == "PASS" else ("NOT RUN" if status == "NOT RUN" else "FAIL"),
                            "--command", "lopodev android-test", "--evidence", str(path),
                            "--details", fields.get("reason", "") or "emulator only; device and performance NOT RUN"],
                           capture_output=True, check=False)
        if report.get("emulator", {}).get("owned") and not keep:
            report["stopped"] = live_session.stop(workspace, "emulator")["status"]
        return report

    avd_result = ensure_avd(avd, env, runner)
    report["avd_setup"] = avd_result
    if avd_result["status"] != "PASS":
        return done(avd_result["status"], reason=avd_result.get("reason"))
    emulator = start_emulator(workspace, avd, env, headless, runner, sleep)
    report["emulator"] = emulator
    if emulator["status"] != "PASS":
        return done(emulator["status"], reason=emulator.get("reason"))
    serial = emulator["serial"]
    adb = android_export.find_adb(env)
    env["ANDROID_SERIAL"] = serial
    if apk is None:
        try:
            export = android_export.export_project(str(godot_dir), "apk", "debug", env=env, install_run=True,
                                                   runner=runner)
        except android_export.ExportError as exc:
            return done("FAIL", reason=f"export failed: {exc}")
        report["export"] = {k: export.get(k) for k in ("artifact", "bytes", "package_name", "report")}
        device = export["device"]
        package = export.get("package_name")
    else:
        package = android_export.apk_metadata(apk, {}, env, out / f"badging_{stamp}.log", runner).get("package")
        device = android_export.device_gate(apk, package, env, out / f"install_{stamp}.log", runner)
    report["launch"] = device
    if device["status"] != "PASS":
        return done("FAIL", reason=f"install/launch failed: {device.get('step') or device.get('reason')}")
    sleep(10)
    alive = runner([adb, "-s", serial, "shell", "pidof", package], capture_output=True, text=True, timeout=30,
                   check=False, env=env)
    logcat = runner([adb, "-s", serial, "logcat", "-d", "-t", "1500"], capture_output=True, text=True,
                    timeout=60, check=False, env=env)
    log_path = out / f"logcat_{stamp}.txt"
    log_path.write_text(logcat.stdout or "", encoding="utf-8")
    godot_lines = [line for line in (logcat.stdout or "").splitlines() if "godot" in line.lower()
                   or (package and package in line)]
    crashes = [line for line in godot_lines if any(p in line for p in CRASH_PATTERNS)]
    report["alive_after_10s"] = bool((alive.stdout or "").strip())
    report["logcat"] = {"path": str(log_path), "crash_lines": crashes[:20]}
    wake_screen(adb, serial, env, runner)
    sleep(2)
    report["foreground"] = foreground(adb, serial, env, runner)
    first = screencap(adb, serial, out / f"emulator_{stamp}_start.png", env, runner)
    try:
        before = image_stats(first)
    except (ValueError, zlib.error, struct.error) as exc:
        return done("FAIL", reason=f"screenshot unreadable: {exc}")
    x, y, how = (tap[0], tap[1], "requested position") if tap else play_tap(spec, before["width"], before["height"])
    runner([adb, "-s", serial, "shell", "input", "tap", str(x), str(y)], capture_output=True, timeout=30,
           check=False, env=env)
    sleep(3)
    second = screencap(adb, serial, out / f"emulator_{stamp}_after_tap.png", env, runner)
    after = image_stats(second)
    change = changed_fraction(before, after)
    report["screens"] = {"start": str(first), "after_tap": str(second), "tap": [x, y], "tap_target": how,
                         "start_blank": before["blank"], "after_blank": after["blank"],
                         "changed_fraction": round(change, 4)}
    problems = []
    if not report["alive_after_10s"]:
        problems.append("app process not running after 10 s")
    if crashes:
        problems.append(f"{len(crashes)} crash/error lines in logcat")
    if before["blank"]:
        in_front = bool(package) and package in report["foreground"]
        problems.append("first screenshot is blank" + ("" if in_front else
                        f" (game not in the foreground: {report['foreground'] or 'unknown'})"))
    if change < 0.01:
        problems.append("tap did not change the screen (interaction not proven)")
    return done("PASS" if not problems else "FAIL", reason="; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lopodev android-test", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--avd", default=DEFAULT_AVD)
    parser.add_argument("--tap", help="X,Y in device pixels (default: estimated play button)")
    parser.add_argument("--apk", type=Path, help="test an existing APK instead of exporting")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--headless-emulator", action="store_true", help="no emulator window")
    args = parser.parse_args(argv)
    tap = tuple(int(v) for v in args.tap.split(",")) if args.tap else None
    report = run(args.project.resolve(), args.avd, tap, args.keep_running, args.headless_emulator, args.apk)
    for key in ("avd_setup", "emulator", "launch", "screens", "logcat"):
        if key in report:
            print(f"{key.upper()} {json.dumps(report[key])[:400]}")
    print(f"ANDROID_EMULATOR_TEST={report['status']} {report.get('reason') or ''} report={report.get('report')}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
