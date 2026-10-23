# Environment Audit

Audit date: 2026-10-23 (host time)
Repository: `/media/rohan/D5/MyProjects/automated-game-dev-agent`
Repository state at audit: empty directory, not a Git repository.

## Host

| Item | Actual value | Evidence |
|---|---|---|
| OS | Ubuntu (kernel `6.8.0-139-generic`), x86_64 | `uname -a` |
| Desktop session | X11, `DISPLAY=:0` | `$DISPLAY`, `$XDG_SESSION_TYPE` |
| GPU | NVIDIA GeForce GTX 1650, 4 GB VRAM, driver 580.178.04 | `glxinfo -B` |
| OpenGL | 4.6.0 NVIDIA (compatibility profile available) | `glxinfo -B` |
| Memory / disk | 29 GiB RAM; 381 GiB free on `/media/rohan/D5` | `free -h`, `df -h` |

## Required toolchain

| Tool | Version | Path | Status |
|---|---|---|---|
| Blender | 5.2.2 LTS (build 2026-09-15) | `/snap/bin/blender` (classic snap) | Installed and headless-verified |
| Blender Python | CPython 3.13.13 | inside Blender | Verified |
| glTF exporter | `io_scene_gltf2` bundled; Draco and MeshOptimizer bridges available | inside Blender | Verified |
| Godot | 4.6.1 stable (`14d19694e`) | `.tools/godot/Godot_v4.6.1-stable_linux.x86_64` | Installed locally from existing download |
| Godot export templates | `4.6.1.stable` | `~/.local/share/godot/export_templates/4.6.1.stable` | Installed; Linux release template present |
| System Python | 3.12.3 | `/usr/bin/python3` | Installed |
| Git | 2.43.0 | `/usr/bin/git` | Installed |
| ImageMagick | `import`, `convert`, `identify` | `/usr/bin` | Installed |
| FFmpeg | present | `/usr/bin/ffmpeg` | Installed |
| Node / npm / npx | 25.1.0 / bundled | nvm paths | Installed |

Godot 4.6.1 was already present in `~/Downloads` together with matching export
templates. It is MIT-licensed; no paid license or account is required. It is
installed under the gitignored `.tools/` directory so every project command can
use a pinned version.

## Missing or non-default dependencies

| Dependency | Status | Decision |
|---|---|---|
| `godot` on `PATH` | Missing | Use the pinned local binary through `tools/env.sh`; no system install required. |
| `jq` | Missing | Use Python's `json` module instead. No dependency added. |
| `gltf-transform` | Missing | Not required; GBV/GLB checks use `tools/blender/validate_asset.py`. |
| `xvfb-run` | Missing | Not required; a real X11 display is available for graphical verification. |
| System-wide Blender Python packages | N/A | Blender scripts use only `bpy`, `bmesh`, and the standard library. |

## Verified execution paths

### Blender

```bash
blender -b --factory-startup --python tools/blender/make_prop.py -- \
  --kind crate --out-dir projects/prop_poc
```

- `--background` / `-b` works headless.
- `bpy.ops.wm.read_factory_settings(use_empty=True)` gives deterministic scenes.
- `bpy.ops.export_scene.gltf(filepath=..., export_format='GLB', ...)` verified by
  producing a valid 1,984-byte GLB from a test cube.
- API defaults were inspected rather than assumed. Relevant exporter properties
  in Blender 5.2.2 include `export_format`, `use_selection`, `export_animations`
  (default `True`), `export_animation_mode` (default `ACTIONS`), `export_yup`
  (default `True`), and `export_apply` (default `False`).

### Godot

```bash
GODOT=.tools/godot/Godot_v4.6.1-stable_linux.x86_64
"$GODOT" --headless --path <project> --import
"$GODOT" --headless --path <project> --quit-after 5
"$GODOT" --headless --path <project> --script res://.pipeline/validate_project.gd
"$GODOT" --headless --path <project> --export-release "Linux" build/game.x86_64
```

All five paths were exercised in a throwaway probe project:

- import exit code 0 and `.godot/imported` populated;
- scene run exit code 0;
- Linux release export produced a 71 MB self-contained executable;
- the exported executable ran with `--headless --quit-after 5`, exit code 0;
- graphical launch used the X11 display with the OpenGL compatibility renderer;
- `get_viewport().get_texture().get_image().save_png()` produced a real
  640x360 screenshot, confirming rendered output is inspectable.

Renderer choice: `gl_compatibility` (OpenGL 3.3) is used because it was verified
with this NVIDIA/X11 setup. Forward+ (Vulkan) is not required for low-poly work.

### Known environment warnings

- Godot emits `xkbcommon` errors about `iso8859-1/Compose` on this host. They
  are host locale warnings, not project errors; rendering and exit codes are
  unaffected.
- Blender is a classic-confined snap. It can read/write project paths under
  `/media/rohan/D5`, verified during the probe.

## Cost, licensing, and inference constraints

- All chosen tools are free/open source: Blender (GPL), Godot (MIT), Python,
  Git, ImageMagick, FFmpeg.
- The pipeline makes no paid API calls. It uses only local Blender/Godot/Python
  execution.
- AI inference is provided by the already-configured OpenCode model. This plan
  does not assume unlimited or unmetered inference: work is split into small,
  resumable milestones, and no script loops on model calls.
- PoC assets are generated procedurally in this repository, so no third-party
  asset license is introduced. Future imported assets must carry a license and
  attribution entry in `projects/<slug>/ASSET_LICENSES.md`.

## Environment verdict

Ready for the first deliverable. The only non-default requirement is using the
pinned local Godot binary and its already-installed 4.6.1 templates.

## Second-draft verification (2026-10-23)

The OpenGame second draft was verified against the same host after adding
project agents, commands, state extensions, event logging, adoption, QA report,
Android wrappers, and a blank-image check.

| Check | Command | Result |
|---|---|---|
| Unit tests | `python3 -m unittest discover -s tools/tests -v` | PASS, 30 tests |
| OpenCode config | `opencode debug config` | `default_agent=opengame`, 9 agents, 12 commands |
| Agent discovery | `opencode agent list` | primary + 8 specialists discovered |
| Android capability | `tools/godot/check_android.sh` | SDK/templates/JDK/keystore present; 0 devices |
| Android export | `tools/godot/export_android.sh projects/sky_runner/godot` | PASS, 27,472,284-byte debug APK |
| New workspace | `tools/install_opengame.sh` + bootstrap | PASS, scaffold imported and rendered |
| Scaffold screenshot | `tools/godot/screenshot.sh` | PASS, 1280x720, stddev 0.0367, inspected |
| Crystal state | `tools/verify_opengame.sh --crystal ...` | PASS |
| Crystal content/runtime/gameplay/visual | `tools/verify_opengame.sh --crystal ... --full` | PASS |
| Crystal build | `tools/godot/export_build.sh ...` | PASS, 71,110,432 bytes |
| Crystal binary hash | `sha256sum ...` | `334409f5...3824b4`, unchanged |

The crystal visual artifact is
`projects/crystal_test/artifacts/screenshots/verify_opengame.png` outside this
repository. It was inspected: the drone, arena, three crystals, HUD counter, and
controls are visible.

A live routing smoke test ran `opencode run --agent opengame` and delegated a
read-only README inspection to `game-design` through the native `task` tool. The
subagent returned the title and 12 commands; the lead independently verified the
count. No files were modified. Evidence:
`/tmp/opencode/live_delegation.jsonl`.

Remaining `NOT RUN`: real Android device launch, Android interaction, Android
performance, and iOS.
