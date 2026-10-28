# Live mode: see the work happen

With live mode on (`auto`, the default when a display exists), LopoDev opens
its tools on screen while it works and closes them when it is done:

| Work | What you see |
|---|---|
| `lopodev assets derive` / `lopodev assets rig` | a Blender window: the source is imported, each edit step redraws and frames the changed part, then Blender saves, exports and closes |
| `lopodev live start blender` | Blender with the MCP add-on server running; agent MCP calls (`execute_blender_code`, viewport capture) happen in that window |
| `lopodev live start godot --project P` | the Godot editor on the project (it reloads files the agents change) |
| `lopodev live run godot --project P [--scene S] [--seconds N] [--screenshot F]` | the game in a window for N seconds, optionally saving a screenshot, then closed |
| `lopodev android-test --project P` | the Android emulator window with the game installed and launched |

```sh
lopodev live mode            # show: mode, display, active
lopodev live mode off        # headless (CI, remote sessions)
lopodev live status          # LopoDev-owned windows still open
lopodev live stop [all]      # close what LopoDev opened
```

## Ownership: never closing your windows

Every process LopoDev starts is recorded in `.lopodev/live/<tool>.json` with
its PID and the kernel start time. `stop` closes a process only when both
still match. A Blender, Godot or emulator you opened yourself, or a reused
PID, is never touched. If something is already running (for example a Blender
with its MCP server on port 9876, or an emulator), LopoDev reuses it and marks
it `owned: false`.

`LOPODEV_HEADLESS=1` or no display forces headless runs; tests use that.
