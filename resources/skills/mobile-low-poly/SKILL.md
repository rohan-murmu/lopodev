---
name: mobile-low-poly
description: Use when a Godot game targets Android or touch devices, needs mobile-safe UI, needs a low-poly mobile budget, or requires honest Android export and device validation.
license: MIT
---

# Mobile Low-Poly

Android is the verified mobile export path in this repository. iOS is not
validated here. A desktop pass is not mobile evidence.

## Baseline checks

```bash
tools/check_env.sh
tools/godot/check_android.sh
```

Required for Android export:

- Godot 4.6.1 Android templates installed.
- Android SDK with platform tools, build-tools, and `apksigner`.
- JDK 17.
- `[rendering] textures/vram_compression/import_etc2_astc=true` in
  `project.godot`. Without it the export fails while checking textures.
- A debug keystore, or allow Godot to create one on first debug export.

`tools/godot/export_android.sh <godot_dir> [--format apk|aab] [--release]`
sets an isolated `XDG_CONFIG_HOME` with the SDK/JDK paths so the repository does
not depend on global editor state. The same core is available as
`lopodev android-export` and `lopodev_android_export` over MCP.

AAB is release-only. Its preset must set `gradle_build/use_gradle_build=true`
and `gradle_build/export_format=1`. Release signing comes from
`GODOT_ANDROID_KEYSTORE_RELEASE_PATH/USER/PASSWORD` or Godot's credential/preset
fields. If the project has no Gradle build template, the exporter installs it,
creating `android/` in the project. Keep signing passwords and keystores out of
Git and logs.

## Mobile design budget

Start conservative and record measured numbers:

| Item | Initial budget |
|---|---:|
| Visible triangles | 60,000 |
| Draw calls | 80 |
| Texture dimension | 2048 px max |
| Materials per prop | 1 |
| UI touch target | 44x44 logical px min |
| Renderer | `gl_compatibility` |

These are starting limits, not measured device guarantees.

## Rendering and input

- Use `gl_compatibility` and the Mobile renderer only after checking template and
  shader support; `gl_compatibility` is the safe default on this toolchain.
- Prefer unshaded or simple lit materials; avoid per-frame material duplication.
- Use anchored `Control` layouts, containers, safe-area insets, and scalable
  fonts. Test landscape and portrait aspect ratios even if one is locked.
- Map touch actions explicitly in `project.godot`; do not require hover or right
  click. Keep gameplay information visible without a mouse.
- Pause/suspend handling must not corrupt game state.

## Acceptance and evidence

1. Android import and export exit 0; the APK/AAB exists, is above a plausible
   size, and contains its manifest.
2. APK signature is checked with `apksigner`; AAB signature with `jarsigner`.
   Missing tooling is `NOT RUN`, not a pass.
3. Record artifact size, package name, architectures, and capabilities.
4. Device/emulator launch and interaction are `NOT RUN` unless a device is
   actually connected and inspected.
5. Performance is `NOT RUN` without device profiling or a repeatable benchmark.
6. GPU compatibility is not inferred from desktop rendering.

Report the exact command, APK path, log path, device status, and every unverified
mobile claim.
