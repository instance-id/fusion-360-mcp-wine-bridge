---
name: fusion360
description: Control Autodesk Fusion 360 (running under Wine) via the local MCP-Link bridge. Create/edit/query CAD geometry, run Python inside Fusion, execute any Fusion API call.
argument-hint: "[what to do in Fusion]"
allowed-tools:
  - exec
triggers:
  - user
  - model
---

# Fusion 360 control

Fusion 360 runs under Wine. The `Fusion-360-MCP-Server` add-in inside Fusion
connects OUT to a local bridge (`mcp_link_server.py` on `127.0.0.1:8757`).
This MCP server's `fusion360` tool forwards calls to the add-in.

## Pre-flight check

Normally IDE spawns `fusion_stdio.py` (stdio MCP) → bridge lives for the
session and the add-in connects within ~60s of the bridge appearing.

If `fusion360` tool missing or calls error "add-in session gone"/timeout:

```bash
ss -tln | grep 8757           # bridge up?
ps aux | grep Fusion360.exe   # Fusion running?
```

- Fusion not running → tell user to start Fusion; tool works once add-in
  reconnects (≤60s after bridge + add-in both up).
- Bridge up but never registers → shim broken/missing. Fix:
  `cd /home/mosthated/_dev/fusion360/fusion_mcp && ./setup.sh`, then in
  Fusion: Utilities → Add-Ins → stop/start MCP-Link.
- No MCP tool at all AND need CLI fallback → run standalone bridge first:
  `PYTHONUNBUFFERED=1 nohup python3 /home/mosthated/_dev/fusion360/fusion_mcp/mcp_link_server.py > /tmp/mcp_link.log 2>&1 &`
  then `python3 fusion_cli.py --py 'print(app.version)'`.
  WARNING: port conflict — kill standalone before IDE spawns stdio server,
  or stdio will fail to bind 8757.

## Calling the tool

### A. execute_python (preferred for anything non-trivial)

```json
{"operation": "execute_python", "code": "<python>", "session_id": "x", "persistent": true}
```

Scope inside Fusion: `app`, `ui`, `design`, `adsk.core`, `adsk.fusion`,
`adsk.cam`, `mcp` (bridge), `fusion_context` (stored objects), plus persisted
per-`session_id` module globals. `print()` output comes back in `stdout`.

Example:

```python
import adsk.core, adsk.fusion
design = adsk.fusion.Design.cast(app.activeProduct)
root = design.rootComponent
sketch = root.sketches.add(root.xYConstructionPlane)
sketch.sketchCurves.sketchLines.addTwoPointRectangle(
    adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(5,3,0))
print(sketch.name)
```

### B. Generic API call (simple ops, no `operation` key)

```json
{"api_path": "rootComponent.sketches.add",
 "args": ["rootComponent.xYConstructionPlane"],
 "store_as": "sk1", "return_properties": ["name"]}
```

- Path roots: `app`, `ui`, `design`, `rootComponent`, `$stored_name`
- Construct objects: `{"type":"Point3D","x":0,"y":0,"z":0}`,
  `{"type":"Vector3D","x":1,"y":0,"z":0}`,
  `{"type":"ValueInput","expression":"2.5 cm"}`,
  `{"type":"ObjectCollection"}`
- `store_as` keeps result → reference later as `"$name.attr.method"`

### C. Other operations

`call_tool`, `save_script`, `load_script`, `list_scripts`, `delete_script`,
`get_api_documentation` (introspect API), `get_online_documentation`,
`get_best_practices`.

## Gotchas

- Units: API works in cm internally; use `ValueInput` expressions for user units.
- Active doc may be absent/empty → check `app.activeDocument` /
  `app.activeProduct` first; create a design if needed.
- Long ops: wrap mutations in a transaction for single undo
  (`design.timeline` / `app.executeTextCommand` variants) — see add-in
  `best_practices.md`.
- Calls route through Fusion's MAIN thread — Fusion must not be modal-blocked
  (open dialogs can stall calls).
- Reply cap: results come back as text; `return_properties` limits size on
  generic calls.
