# Coding-agent integrations

LopoDev keeps project planning, skills, pipeline state, validation scripts, and
evidence as shared files. Native adapters provide each agent's entry point;
they do not make one platform's delegation features appear in another.

| Agent | Integration level | Entry point | Platform-specific limitation |
|---|---|---|---|
| OpenCode | Native/reference | `.opencode/agents`, `commands`, `skills`; `opencode.json` | Full native primary agent, task delegation and slash commands |
| Kilo Code | Native primary + specialist subagents + shared skills | `.kilo/agents/*.md`, `.kilo/skills/`, `.agents/skills/` | Uses Kilo's Task tool and permissions; contracts are adapter instructions, not OpenCode internals |
| Cursor | Project rule + specialist subagents + shared skills | `.cursor/rules/lopodev.mdc`, `.cursor/agents/*.md`, `.agents/skills/` | Rule guides the selected primary; specialist selection/delegation follows Cursor's Task tool, not OpenCode slash commands |
| Other MCP clients | Workflow and Android export tools | `tools/mcp_server.py` | MCP exposes bounded tools, not the LopoDev system prompt, autonomous workflow, or native specialist orchestration |

Kilo adapter format follows current [Kilo custom agents](https://kilocode.ai/docs/customize/custom-modes),
[custom subagents](https://kilocode.ai/docs/customize/custom-subagents), and
[Agent Skills](https://kilocode.ai/docs/customize/skills) documentation.
Cursor follows its current [project rules and AGENTS.md](https://cursor.com/docs/context/rules),
[subagent](https://cursor.com/docs/agent/subagents), and
[Agent Skills](https://cursor.com/docs/context/skills) documentation. Always
check your installed application version because these platform formats evolve.

## Engine and code integrations

`lopodev setup` installs pinned [MCP for Blender](https://github.com/ahujasid/mcp-for-blender),
[Godot MCP](https://github.com/Coding-Solo/godot-mcp) and [Code Map](https://github.com/JordanCoin/codemap)
(versions in `resources/integrations.json`); `lopodev install opencode` registers
them as `lopodev mcp-run <server>`. Tools are disabled globally and enabled per
agent: Blender for modeling/animation/level-design (paid `generate_*` and
telemetry tools denied), Godot for gameplay/ui/level-design/qa/optimization,
Code Map for the lead and code-editing specialists. Agents still edit files and
run deterministic scripts directly; MCP output is observation, never gate proof.

Kilo and Cursor receive the vendored skills through `.kilo/skills` and
`.agents/skills`; register the MCP servers in their own settings with the same
`lopodev mcp-run <server>` command. The LopoDev MCP server (`lopodev install mcp`)
adds task briefs and knowledge search to any MCP client.

## Install in the current project

Run from a LopoDev workspace or pass `--project`:

```sh
lopodev install opencode --dry-run
lopodev install opencode
lopodev install kilo
lopodev install cursor
lopodev install mcp
lopodev uninstall cursor --dry-run
```

Installations are project-level and idempotent. They refuse to overwrite existing
adapter paths/configuration. Canonical skills live once in `resources/skills/`;
Kilo links them into `.kilo/skills/`, and Kilo and Cursor also receive the
Agent Skills-compatible `.agents/skills/` view. No instruction copy is
maintained. OpenCode gets a generated `.opencode/` directory whose `agents` and
`commands` link to `adapters/opencode/` and whose `skills` link to
`resources/skills/`. The Kilo and Cursor specialist files are thin platform
wrappers that direct agents to the shared role constraints in `AGENTS.md` and
the relevant skill.

`lopodev uninstall <target>` removes only adapter files recorded in
`.lopodev/managed-files.json` whose content/link target still matches the
installed baseline. Shared files are retained until their last LopoDev adapter
owner is uninstalled; edited or untracked files are left in place.

The MCP install creates `.lopodev/mcp-server.json` as a client-neutral
registration example. It does not edit OpenCode, Kilo, Cursor, Claude, or any
other client configuration. Merge the server entry into the selected client's
MCP configuration and restart/reload the client.
