# Troubleshooting

- `lopodev doctor`: reports executable availability and installed adapter files.
  Blender/Godot absence is not fatal to planning or state inspection.
- `lopodev install ...` refuses to replace existing files. Inspect them and
  merge manually; there is no forced overwrite option. In `opencode.json` it
  works key by key: `PRESERVED opencode.json:<key>` means your value differs
  from LopoDev's; edit or delete that key and rerun. Originals are backed up in
  `.lopodev/backups/`.
- `lopodev doctor` FAIL rows name the fix. Typical cases:
  - `skill-pack ... not installed` / `mcp ... is not installed`: `lopodev setup`.
    Behind a proxy, set `HTTPS_PROXY`; `uv`, `npm` and the skill downloader honor it.
  - `checksum mismatch`: the upstream archive changed; do not bypass it. Report
    it or re-pin following `CONTRIBUTING.md`.
  - `opencode skill discovery: missing ...`: the workspace was installed before
    `setup`; rerun `lopodev install opencode --project <ws>`.
  - `opencode mcp <server>: failed`: run `lopodev mcp-run <server>` in a terminal
    to see its error; `godot` needs Node.js, `blender` needs the venv from setup.
  - `blender addon socket NOT RUN`: open Blender; the addon starts its server
    (N panel > MCP for Blender > Start). Other agents keep working meanwhile.
- New tools or skills not visible in an open OpenCode session: sessions load
  configuration at start. Restart the session; `lopodev doctor` shows what a new
  session will see.
- `lopodev approval manual` refuses to change a user-defined `permission` block;
  remove it from `opencode.json` to let LopoDev manage the mode.
- Knowledge: `lopodev knowledge validate` lists invalid entries; a recipe that
  misbehaves in your project should be marked with `lopodev knowledge fail <id>
  --reason "<evidence>"` so it is no longer suggested.
- `.opencode/`, `.kilo/`, `.cursor/`, and `.agents/skills/` are generated.
  If an adapter is missing, run `lopodev install <target> --project <workspace>`
  before reopening the client.
- If OpenCode agents do not appear, reopen the project and run
  `opencode agent list` and `opencode debug config` from the project root.
- If Kilo does not show LopoDev, verify `.kilo/agents/lopodev.md` and restart or
  reload Kilo. Kilo discovers `skills.paths`; the installer links
  `.kilo/skills/<name>` and `.agents/skills/<name>` from `resources/skills/`.
- Cursor loads project rules in `.cursor/rules/*.mdc`; it does not offer the
  same primary-agent selector or guaranteed specialist delegation as OpenCode.
- For MCP, install the optional SDK, ensure `.lopodev/mcp-server.json` points at
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
- `APK metadata check failed: package ... != preset ...`: the APK was built from
  a different preset/package than expected; fix `export_presets.cfg`.
  `mobile.orientation ... ships 'portrait'`: align `window/handheld/orientation`
  (0 landscape, 1 portrait) with `project.json`.
- `DEVICE_GATE=NOT_RUN`: no device in `adb devices`. Connect one with USB
  debugging or start an emulator, then rerun with `--install-run`.
- Signature verification is `NOT RUN` when `apksigner`/`jarsigner` is absent.
  Do not convert that into a pass. See
  [`android-export.md`](android-export.md).
- Homebrew formula generation requires a published immutable archive, its
  computed SHA-256 and confirmed SPDX license. No placeholders are accepted.
