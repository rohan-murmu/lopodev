# Troubleshooting

- `loopdev doctor`: reports executable availability and installed adapter files.
  Blender/Godot absence is not fatal to planning or state inspection.
- `loopdev install ...` refuses to replace existing files. Inspect them and
  merge manually; there is no forced overwrite option.
- If OpenCode agents do not appear, reopen the project and run
  `opencode agent list` and `opencode debug config` from the project root.
- If Kilo does not show LoopDev, verify `.kilo/agents/loopdev.md` and restart or
  reload Kilo. Check that linked `.agents/skills/<name>/SKILL.md` targets exist.
- Cursor loads project rules in `.cursor/rules/*.mdc`; it does not offer the
  same primary-agent selector or guaranteed specialist delegation as OpenCode.
- For MCP, install the optional SDK, ensure `.loopdev/mcp-server.json` points at
  the correct workspace, merge its entry into the client config, then restart
  the client. Stderr contains startup errors; stdout is reserved for MCP.
- Godot failure: set `GODOT=/absolute/path/to/godot`; check version and project
  path. Blender modeling requires `BLENDER` or a discoverable executable.
- Android export failure: run `tools/godot/check_android.sh` first. Confirm the
  matching templates, Android SDK, JDK 17, `apksigner`, debug keystore, and
  `textures/vram_compression/import_etc2_astc=true`.
- AAB export requires a Gradle preset (`gradle_build/use_gradle_build=true`,
  `gradle_build/export_format=1`), release signing, and `android_source.zip`.
  The exporter installs the project-local Android build template if it is
  missing. AAB is not accepted by a device without a store/install path.
- Signature verification is `NOT RUN` when `apksigner`/`jarsigner` is absent.
  Do not convert that into a pass. See
  [`android-export.md`](android-export.md).
- Homebrew formula generation requires a published immutable archive, its
  computed SHA-256 and confirmed SPDX license. No placeholders are accepted.
