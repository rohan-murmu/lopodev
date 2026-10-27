---
name: game-qa
description: Use last, before reporting any milestone complete, to run import, content, runtime, graphical screenshot, and Linux export gates and to produce an evidence-backed report with PASS/FAIL/NOT RUN results.
license: MIT
---

# Game QA

Independently verify the project against the spec. QA does not trust generator
output, file existence, or headless checks for visual claims. Every reported
result must have a command, timestamp, and artifact path.

## Required inputs

- Godot project and `project.json` acceptance criteria.
- Asset validation reports and scene node map.
- Access to `DISPLAY=:0` for the visual gate (present on this host).
- Export templates matching the Godot engine version.

## Expected outputs

```text
projects/<slug>/artifacts/
  logs/<gate>_<timestamp>.log
  qa_report.json
  screenshots/<name>.png
projects/<slug>/docs/poc-report.md   # or final game report
```

The report must record each gate as exactly `PASS`, `FAIL`, or `NOT RUN`, with
the command, timestamp, and evidence path. Unrun gates stay `NOT RUN`.

## Workflow

1. Confirm the working tree and versions:
   ```bash
   tools/check_env.sh
   git status --short
   ```
2. **Generation/asset gate** - re-run the independent GLB validator. Do not
   trust the generator's own claim.
3. **Import gate**:
   ```bash
   source tools/env.sh
   "$GODOT" --headless --path projects/<slug>/godot --import
   ```
   Fail on non-zero exit or project-caused `ERROR:`/`SCRIPT ERROR:`.
4. **Content gate**:
   ```bash
   TARGET_NODE=<Node> TARGET_ANIM=<clip> \
     tools/godot/validate.sh projects/<slug>/godot
   ```
5. **Runtime gate**:
   ```bash
   TARGET_NODE=<Node> FRAMES=30 EXPECT_ROTATION=1 \
     tools/godot/smoke.sh projects/<slug>/godot
   ```
   This must process real frames and assert mechanics, not just load files.
6. **Visual gate**:
   ```bash
   tools/godot/screenshot.sh projects/<slug>/godot \
     projects/<slug>/artifacts/screenshots/<name>.png
   ```
   Inspect the image itself (open/read it). Verify it is non-blank, shows the
   expected asset, and matches the described camera/lighting. Record dimensions
   and a short observation.
7. **Build gate**:
   ```bash
   tools/godot/export_build.sh projects/<slug>/godot Linux \
     projects/<slug>/build/<name>.x86_64
   ```
   Verify the binary size, then run the exported binary headless for a bounded
   number of frames and check exit code 0.
8. **Android gate** (mobile scope only):
   ```bash
   tools/godot/check_android.sh
   tools/godot/export_android.sh projects/<slug>/godot --format apk
   # distribution:
   tools/godot/export_android.sh projects/<slug>/godot --format aab --release
   ```
   Verify the APK/AAB exists, has a plausible size, contains its manifest, and
   passes `apksigner`/`jarsigner` when available. AAB is release-only, requires
   a Gradle preset and `android_source.zip`, and may install the project-local
   Android build template. A device launch is a separate `NOT RUN` item unless a
   real device/emulator was connected and inspected.
9. Record each result with the deterministic report helper:
   ```bash
   python3 tools/qa_report.py record --project projects/<slug> \
     --name content --status PASS --command "<command>" --exit-code 0 \
     --evidence projects/<slug>/artifacts/logs/content.log
   python3 tools/qa_report.py record --project projects/<slug> \
     --name device --status "NOT RUN" --reason "no Android device connected"
   python3 tools/qa_report.py validate --project projects/<slug>
   ```
   A `PASS`/`FAIL` without a command and evidence path is rejected, as is a
   `NOT RUN` without a reason.
10. Write the human report and update the spec acceptance table with
    met/not met and evidence paths. Include known limitations, environment
    warnings, and anything not tested.
11. Commit evidence at a checkpoint only after reviewing `git status`/`git diff`.

## Validation procedures

| Gate | Pass condition |
|---|---|
| Generation | exit 0; expected files non-empty; hashes/paths recorded |
| Asset | GLB header/chunks/mesh/material/bounds/budget pass |
| Import | exit 0; no project-caused errors in log |
| Content | main scene instantiates; target node/mesh/material/animation found |
| Runtime | N frames processed; mechanic assertion passes; exit 0 |
| Visual | graphical launch; screenshot exists, non-blank, inspected |
| Build | release binary exists, size plausible, headless run exit 0 |
| Android | APK/AAB exists, plausible size, manifest and available signature checks; device/performance separate |

## Playability claim standard

Do not write "playable" unless all of the following are true in this session:

1. the game launches graphically on a real display;
2. the rendered screenshot/frames show the player, level, and expected assets;
3. the core input/mechanic was exercised and produced the expected state change;
4. the runtime test evidence and screenshot paths are recorded.

For a non-game PoC, use narrower language: "scene runs and renders the imported
asset".

## Failure recovery

- **Import errors** - capture full log; fix the project, not the log filter.
  Distinguish host/renderer warnings from project errors.
- **Content check cannot find node** - print the actual instantiated tree and
  correct the target name/path; never weaken the check to make it pass.
- **Runtime flake** - rerun with a fixed frame count and threshold assertions;
  record both runs if behavior differs.
- **Blank screenshot** - treat as FAIL. Check camera, lights, environment,
  viewport size, and whether the process was headless.
- **Export template missing** - verify `~/.local/share/godot/export_templates/
  4.6.1.stable`; install matching templates if absent. Do not switch engine
  versions silently.
- **Exported binary crashes** - run with console output, inspect the first error,
  and fix before claiming the build gate.
- **AAB export fails on build template** - the exporter installs
  `--install-android-build-template` when missing; verify `android_source.zip` in
  the matching template directory and allow the project-local `android/` output.
- **Android export fails on textures** - confirm
  `textures/vram_compression/import_etc2_astc=true` in `project.godot`, re-import,
  then retry. Do not disable texture validation.
- **No Android device** - export only; record device, interaction, and
  performance as `NOT RUN`. Do not infer them from a desktop run.
- **Interrupted session** - leave unrun gates as `NOT RUN`; provide the exact
  next command.

## Handoff

Deliver the final report with status, deliverables, gate table, acceptance
criteria results, known limitations, and one concrete next safe step. Never
convert `NOT RUN` or an inferred result into a pass.
