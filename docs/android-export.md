# Android APK and AAB export

LopoDev uses one deterministic exporter for Android artifacts:

```text
tools/godot/android_export.py
  -> tools/godot/export_android.sh       compatibility wrapper
  -> lopodev android-export              CLI
  -> lopodev_android_export              optional MCP tool
```

Do not add a second format-specific exporter. If the Android workflow changes,
change the Python core and its tests.

## Prerequisites

```bash
tools/godot/check_android.sh
```

Required:

- Godot 4.6.1 with matching Android export templates under
  `~/.local/share/godot/export_templates/4.6.1.stable`, or set
  `GODOT_TEMPLATES`.
- Android SDK with platform tools, build-tools, `apksigner`, and JDK 17.
- `[rendering] textures/vram_compression/import_etc2_astc=true` in
  `project.godot`.
- An Android preset in `export_presets.cfg` with a non-empty
  `package/unique_name`.
- A debug keystore for debug APKs. Godot's default is
  `~/.local/share/godot/keystores/debug.keystore`.

`tools/godot/check_android.sh` reports export readiness separately from device
readiness. A missing device does not block an export, but it does keep device,
interaction, and performance gates at `NOT RUN`.

## APK

Debug:

```bash
tools/godot/export_android.sh projects/<slug>/godot
# or
lopodev android-export projects/<slug>/godot --format apk --mode debug
```

Release APK:

```bash
tools/godot/export_android.sh projects/<slug>/godot --release
```

The default artifact is `projects/<slug>/build/<slug>_debug.apk` for debug and
`projects/<slug>/build/<slug>.apk` for release. Override it with `--out`.

## AAB

AAB is a release-only distribution format. Godot must use its Gradle Android
build and export format `Android App Bundle`:

```ini
[preset.1.options]
gradle_build/use_gradle_build=true
gradle_build/export_format=1
```

Then export:

```bash
GODOT_ANDROID_KEYSTORE_RELEASE_PATH=/absolute/release.keystore \
GODOT_ANDROID_KEYSTORE_RELEASE_USER=release-user \
GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD='***' \
tools/godot/export_android.sh projects/<slug>/godot --format aab --release
```

Release signing may instead be stored by Godot in
`.godot/export_credentials.cfg` or in `export_presets.cfg`. The exporter reads
all three locations, but never prints the password. Keep keystores and
credentials out of Git.

If the project has no installed Gradle build template, the exporter passes
`--install-android-build-template` to Godot, which requires the matching
`android_source.zip` export template. That creates or updates the project-local
`android/` build directory. Commit it only if your project intentionally tracks
custom Gradle changes; otherwise keep it generated.

The legacy `ANDROID_KEYSTORE_RELEASE_*` environment names are accepted as
aliases for the Godot-named variables.

## What is verified

A successful command records:

| Check | Meaning |
|---|---|
| Project/preset validation | `project.godot`, Android platform, preset name, Gradle/format settings |
| Texture setting | ETC2/ASTC import setting present |
| Capability check | SDK, JDK, templates, `apksigner`, debug keystore |
| Import gate | `godot --headless --import` exits 0 without project `ERROR:` lines |
| Export gate | Godot exits 0 and the artifact exists |
| Artifact gate | Artifact is a zip above the minimum size and contains the APK/AAB manifest |
| Signature gate | `apksigner` for APK or `jarsigner` for AAB, when available |

Rendered output, installation, launch, touch input, GPU compatibility, and
performance are not proven by an export. They remain `NOT RUN` until checked on
a real device or emulator. A locally signed AAB is not Play Console acceptance.

## Evidence

Logs are written under `projects/<slug>/artifacts/logs/`:

- `android_capability_<timestamp>.log`
- `android_import_<timestamp>.log`
- `android_export_<format>_<mode>_<timestamp>.log`
- `android_signature_<timestamp>.log`

The CLI also prints machine-readable gate lines:

```text
ANDROID_EXPORT_GATE=PASS format=apk mode=debug artifact=... bytes=...
APK_SIGNATURE_GATE=PASS        # or AAB_SIGNATURE_GATE for AAB
LOG=...
DEVICE_GATE=NOT_RUN ...
```

Use `--json` for structured output and `--dry-run` to validate the project and
print the exact Godot command without exporting. JSON results include the
artifact size, package name, version code/name, ABI list, Gradle-build flag,
signature status, and log paths.

## MCP

```text
lopodev_android_export(
  slug: str,
  format: "apk" | "aab" = "apk",
  mode: "debug" | "release" = "debug",
  preset: str = "Android",
  output: str = "",
  godot: str = ""
)
```

The MCP tool resolves `project.json.godot_dir` or
`projects/<slug>/godot`, rejects paths outside the configured workspace, and
returns the same structured result as the CLI. An explicit `godot` executable
must also stay inside the workspace or LopoDev checkout; omit it to use the
server's `GODOT` or pinned build. It can execute Godot because export is its
explicit purpose; other MCP tools remain bounded state/spec operations.

## Common failures

- `Android build template not installed` - the exporter installs it
  automatically for AAB. If installation fails, check `android_source.zip` in
  the matching template directory.
- `preset ... configured for APK/AAB` - use a dedicated preset or change the
  Godot Gradle export format. The exporter never edits `export_presets.cfg`.
- `release signing is incomplete` - configure all three release fields.
- `No project icon specified` - Godot may log this while still exporting. Add an
  icon before release; do not treat the warning as a successful visual check.
- `APK signature verification failed` - check the debug/release keystore and
  signing configuration.
- `device gate NOT RUN` - connect and authorize a device or start an emulator;
  then install, launch, and inspect it manually.
