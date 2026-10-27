# LopoDev MCP server

The optional local stdio server exposes bounded project workflow operations:

- `lopodev_status`: gate and task summary.
- `lopodev_next`: next task whose dependencies are verified.
- `lopodev_validate`: `project.json` and pipeline state validation.
- `lopodev_context`: bounded spec/license excerpts and status.
- `lopodev_checkpoint`: save a short recovery note under the existing state and
  event log.
- `lopodev_android_export`: validate and export a Godot Android APK or release
  AAB through the shared deterministic exporter.

The former `loopdev_*` tool names are registered as deprecated aliases for one
release; new clients should use `lopodev_*`.

It does not expose arbitrary shell/filesystem access, approve gates, publish, or
deploy. The Android export tool is the one explicit operation that invokes Godot;
it is scoped to the project `godot_dir` and rejects output paths outside the
configured workspace. Native agents still supply the decision-making workflow
and specialist delegation. MCP tools do not turn a model into the LopoDev
orchestrator automatically.

## Setup

Python 3.12+ is used by the existing tools. Install the official Python MCP SDK
only if this interface is needed:

```sh
python3 -m pip install 'mcp>=2,<3'
lopodev install mcp --project /path/to/workspace
```

Use the same Python environment for both commands. If you want an isolated SDK
environment (recommended for Homebrew-managed Python), create a venv and pass its
Python explicitly:

```sh
python3 -m venv /path/to/workspace/.lopodev/mcp-venv
/path/to/workspace/.lopodev/mcp-venv/bin/python -m pip install 'mcp>=2,<3'
lopodev install mcp --project /path/to/workspace \
  --python /path/to/workspace/.lopodev/mcp-venv/bin/python
```

The generated `.lopodev/mcp-server.json` provides a stdio registration command
scoped to the selected workspace. It does not install dependencies or edit a
client config. For a direct registration, use:

```json
{
  "mcpServers": {
    "lopodev": {
      "command": "python3",
      "args": ["/absolute/path/to/tools/mcp_server.py", "--root", "/absolute/workspace"]
    }
  }
}
```

Pass an absolute workspace root. Tools accept only a lowercase snake_case slug
under `<root>/projects/`; path escapes are rejected. Stdio protocol output stays
on stdout, and diagnostics go to stderr. Pipeline updates use the same lock as
the state CLI. MCP checkpointing is deliberately non-approving and bounded.

`lopodev_android_export` accepts `format=apk|aab`, `mode=debug|release`,
`preset`, `output`, and `godot`. AAB is release-only. An explicit `godot`
executable must be inside the workspace or LopoDev checkout; otherwise omit it
and configure `GODOT` for the server. It returns the artifact, size, log paths,
signature status, and `device_gate: NOT RUN` unless a device was separately
tested. See [`android-export.md`](android-export.md).
