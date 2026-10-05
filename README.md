# fusion_mcp — Fusion 360 (Wine) ↔ LLM bridge

Talk to the [AuraFriday Fusion-360-MCP-Server](https://github.com/AuraFriday/Fusion-360-MCP-Server)
add-in running inside Fusion 360 under Wine — no Windows, no AuraFriday
MCP-Link install needed.

## Why

The add-in's docs assume the AuraFriday `mcp-link-server` native binary, which
ships as a Chrome native-messaging shim (`com.aurafriday.shim.json` → exe that
emits the real server URL + Bearer token). On Linux/Wine that shim doesn't
exist, so the add-in never connects. This repo fakes both halves:

```
LLM ──MCP/SSE──▶ mcp_link_server.py (127.0.0.1:8757)
                            ▲  GET /sse (reverse-call channel)
                            │  POST /messages/ (requests + replies)
Fusion (wine) add-in ───────┘
        ▲ reads manifest + runs shim.exe at startup
C:\AuraFriday\shim.exe  (prints {"mcpServers":{"local":{"url":"http://127.0.0.1:8757/sse",...}}})
```

Wine shares host loopback → `127.0.0.1:8757` is reachable from inside Fusion.

## Files

| File | Role |
|---|---|
| `fusion_stdio.py` | All-in-one stdio MCP server: embeds the emulator, spawned/killed by the IDE per session |
| `mcp_link_server.py` | Standalone emulator (SSE+POST bridge) — for CLI use or other MCP clients |
| `fusion_cli.py` | CLI client for standalone server: `--py`, `--api`, or raw JSON args |
| `setup.sh` | Installs shim.exe + manifest into a wineprefix (cross-PC setup) |
| `shim/shim.c` | Fake native-messaging shim source (mingw) |
| `shim/shim.exe` | → copied to `C:\AuraFriday\shim.exe` in wineprefix |
| `shim/com.aurafriday.shim.json` | manifest → `%LOCALAPPDATA%\AuraFriday\` |
| `.<ide_config_dir>/mcp_config.json` | Registers `fusion360` stdio MCP server for IDE |
| `.<ide_config_dir>/skills/fusion360/SKILL.md` | Agent skill: usage, formats, gotchas |

## Lifecycle modes

**IDE-managed (default)** — `.<ide_config_dir>/mcp_config.json` points at
`fusion_stdio.py`. IDE spawns it per session → bridge (port 8757) lives only
while a chat session runs; add-in connects to it automatically. Session ends →
process exits → port freed.

**Standalone** — for `fusion_cli.py` or other MCP clients (SSE at
`http://127.0.0.1:8757/sse`, header `Authorization: Bearer fusion360-mcp-local-token`):

```bash
PYTHONUNBUFFERED=1 python3 mcp_link_server.py
```

Only one mode at a time — both bind 8757. If `fusion_stdio.py` exits with
"Address already in use", kill the standalone server first.

## Setup on a new machine

```bash
./setup.sh [WINEPREFIX]   # default ~/.autodesk_fusion/wineprefixes/default
```

Builds `shim.exe` (needs `x86_64-w64-mingw32-gcc`, or reuse committed exe) and
installs shim + manifest. Then edit `.<ide_config_dir>/mcp_config.json` arg path if repo
location differs. Add-in lives in
`C:\users\<user>\Downloads\Fusion-360-MCP-Server\` — copy the AuraFriday add-in
there and enable it in Fusion (Utilities → Add-Ins).

## Use

IDE MCP tool `fusion360` (auto), or CLI (standalone mode only):

```bash
python3 fusion_cli.py --py 'print(app.version)'
python3 fusion_cli.py --api design.rootComponent.bRepBodies.count
python3 fusion_cli.py '{"operation":"execute_python","code":"..."}'
```

## Protocol notes (for hacking)

- `GET /sse` + `Authorization: Bearer fusion360-mcp-local-token` → `event: endpoint`
  with `data: /messages/?session_id=X`, then JSON-RPC messages as `data:` lines.
- `POST /messages/?session_id=X` → 202; response pushed over SSE matching `id`.
- Register: `tools/call` `remote` `{input:{operation:"register", tool_name,...}}`.
- Reverse call → `data: {"reverse":{"tool":"fusion360","call_id":..,"input":{"params":{"arguments":{..}}}}}`;
  add-in replies `tools/reply` id=call_id, `params.result` = handler result.
- Handler arg shape: `arguments.operation` routes (`execute_python`, `call_tool`,
  `save_script`, `load_script`, `list_scripts`, `delete_script`,
  `get_api_documentation`, `get_online_documentation`, `get_best_practices`);
  no `operation` → generic `{api_path,args,kwargs,store_as,return_properties}`.

## Troubleshooting

| Symptom | Check |
|---|---|
| No `fusion360` tool | bridge logs: stderr of `fusion_stdio.py` (IDE MCP log) or `/tmp/mcp_link.log` (standalone) → want `tool registered: 'fusion360'` |
| Never registers | manifest/exe present? `run ./setup.sh`; test shim: `WINEPREFIX=... $HOME/fusion-wine-build/bin/wine 'C:\AuraFriday\shim.exe'` → framed JSON |
| Call hangs | Fusion modal dialog open? look for `reverse ->` + `tools/reply` pair in bridge log |
| Port busy | `kill $(ss -tlnp \| grep 8757 \| grep -oP 'pid=\K[0-9]+')` |

Port/token constants: `mcp_link_server.py` (HOST/AUTH), `shim.c` (embedded JSON),
`fusion_cli.py` — keep in sync if changed.
