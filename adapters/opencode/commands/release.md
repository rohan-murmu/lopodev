---
description: Run the full release QA suite, build Linux and Android where supported, and prepare Gate F evidence.
agent: lopodev
---
Prepare the release candidate for `$ARGUMENTS`.

1. Delegate an independent QA run to `qa-release` with the acceptance table.
2. Require `artifacts/qa_report.json`, logs, a real screenshot, Linux export and
   bounded run, Android APK/AAB export if in scope, and every `NOT RUN` stated.
   Use `tools/godot/export_android.sh <godot_dir> --format aab --release` only
   with release signing and a Gradle/template-ready project.
3. Inspect the report and re-run any dubious result yourself.
4. Check `ASSET_LICENSES.md`, known limitations, and that no build artifact will
   be committed.
5. Present Gate F with the acceptance table and ask for explicit approval. Never
   approve on the user's behalf.
