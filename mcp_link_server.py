#!/usr/bin/env python3
"""Minimal MCP-Link server emulator for the Fusion 360 MCP add-in.

Implements just enough of the AuraFriday MCP-Link protocol:
  GET  /sse                          -> SSE stream; sends 'endpoint' event
  POST /messages/?session_id=X       -> JSON-RPC in; response pushed back over SSE

Tools:
  'remote'    -> used by add-ins to register themselves (operation=register)
  'fusion360' -> registered by the add-in; calls are forwarded over SSE as
                 {"reverse": {...}} and answered via tools/reply.

Run:  python3 mcp_link_server.py [--port 8757]
"""

import argparse
import json
import queue
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
AUTH = "Bearer fusion360-mcp-local-token"

# session_id -> {"queue": Queue, "kind": "addon"|"caller"|None}
sessions = {}
sessions_lock = threading.Lock()

# call_id -> (caller_session_id, original_request_id)
pending_reverse = {}
pending_lock = threading.Lock()

# tool_name -> {"sessions": set(), "description": str, "schema": dict}
registered_tools = {}

# Schema advertised for the fusion360 tool (its real arg shape, not the
# generic {command, parameters} envelope the add-in registers with).
FUSION360_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["execute_python", "call_tool", "save_script",
                     "load_script", "list_scripts", "delete_script",
                     "get_api_documentation", "get_online_documentation",
                     "get_best_practices"],
            "description": "Operation type. Omit for generic api_path call. "
                           "Most common: execute_python.",
        },
        "code": {
            "type": "string",
            "description": "Python source (operation=execute_python). Runs "
                           "inside Fusion with app, ui, design, adsk.core/"
                           "fusion/cam, mcp, fusion_context in scope. "
                           "print() output is returned.",
        },
        "session_id": {"type": "string",
                       "description": "Execution session; vars persist "
                                      "per-session across calls."},
        "persistent": {"type": "boolean"},
        "api_path": {
            "type": "string",
            "description": "Dotted Fusion API path for generic calls, e.g. "
                           "'rootComponent.sketches.add', "
                           "'$stored.someMethod', 'design.rootComponent...'",
        },
        "args": {"type": "array",
                 "description": "Positional args; construct objects via "
                                "{'type':'Point3D','x':..,'y':..,'z':..}, "
                                "'$name' refs stored objects"},
        "kwargs": {"type": "object"},
        "store_as": {"type": "string",
                     "description": "Store result for later $name reference"},
        "return_properties": {"type": "array",
                              "items": {"type": "string"}},
        "tool_name": {"type": "string",
                      "description": "For operation=call_tool"},
        "arguments": {"type": "object",
                      "description": "For operation=call_tool"},
    },
    "additionalProperties": True,
}


def sse_push(session_id: str, obj: dict) -> bool:
    with sessions_lock:
        sess = sessions.get(session_id)
    if not sess:
        return False
    sess["queue"].put(obj)
    return True


def rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_rpc(session_id: str, msg: dict):
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {}) or {}

    if method == "tools/reply":
        call_id = req_id
        with pending_lock:
            entry = pending_reverse.pop(call_id, None)
        if entry:
            caller_sid, orig_id = entry
            sse_push(caller_sid, rpc_result(orig_id, params.get("result")))
        return

    if method == "initialize":
        sse_push(session_id, rpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-link-emulator", "version": "0.1"},
        }))
        return

    if method == "tools/list":
        tools = [{
            "name": "remote",
            "description": "Remote tool registration and invocation",
            "inputSchema": {"type": "object", "properties": {
                "input": {"type": "object"}}},
        }]
        for name, entry in registered_tools.items():
            tools.append({
                "name": name,
                "description": entry["description"] or f"Remote tool: {name}",
                "inputSchema": entry["schema"] or {"type": "object"},
            })
        sse_push(session_id, rpc_result(req_id, {"tools": tools}))
        return

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}

        if name == "remote":
            inp = args.get("input", {}) or {}
            if inp.get("operation") == "register":
                tname = inp.get("tool_name", "unknown")
                entry = registered_tools.setdefault(tname, {
                    "sessions": set(), "description": "", "schema": None})
                entry["sessions"].add(session_id)
                entry["description"] = inp.get("description") or \
                    entry["description"]
                if tname == "fusion360":
                    entry["schema"] = FUSION360_SCHEMA
                else:
                    entry["schema"] = inp.get("parameters") or entry["schema"]
                with sessions_lock:
                    if session_id in sessions:
                        sessions[session_id]["kind"] = "addon"
                print(f"[+] tool registered: '{tname}' (session {session_id[:8]})")
                sse_push(session_id, rpc_result(req_id, {
                    "content": [{"type": "text",
                                 "text": f"Successfully registered tool '{tname}'"}],
                    "isError": False}))
            else:
                sse_push(session_id, rpc_result(req_id, {
                    "content": [{"type": "text", "text": "remote: ok"}]}))
            return

        if name in registered_tools:
            addon_sids = [s for s in registered_tools[name]["sessions"]
                          if s in sessions]
            call_id = str(req_id)
            with pending_lock:
                pending_reverse[call_id] = (session_id, req_id)
            pushed = 0
            for addon_sid in addon_sids:
                print(f"[<] reverse -> '{name}' call_id={call_id[:8]} "
                      f"on session {addon_sid[:8]}")
                if sse_push(addon_sid, {"reverse": {
                        "tool": name,
                        "call_id": call_id,
                        "input": {"params": {"name": name, "arguments": args}},
                }}):
                    pushed += 1
            if not pushed:
                with pending_lock:
                    pending_reverse.pop(call_id, None)
                sse_push(session_id, rpc_error(req_id, -32000,
                                               f"add-in session for '{name}' gone"))
            return

        sse_push(session_id, rpc_result(req_id, {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True}))
        return

    # notifications (no id) and anything else: ack quietly
    if req_id is not None:
        sse_push(session_id, rpc_result(req_id, {}))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # quiet

    def _check_auth(self):
        return self.headers.get("Authorization") == AUTH

    def do_GET(self):
        if self.path.split("?")[0] != "/sse":
            self.send_error(404)
            return
        if not self._check_auth():
            self.send_error(401)
            return

        sid = uuid.uuid4().hex
        q = queue.Queue()
        with sessions_lock:
            sessions[sid] = {"queue": q, "kind": None}

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            ep = f"/messages/?session_id={sid}"
            self.wfile.write(f"event: endpoint\ndata: {ep}\n\n".encode())
            self.wfile.flush()
            print(f"[~] SSE client connected: {sid[:8]}")

            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with sessions_lock:
                sessions.pop(sid, None)
            for t, entry in list(registered_tools.items()):
                if sid in entry["sessions"]:
                    entry["sessions"].discard(sid)
                    print(f"[-] addon session ended for tool '{t}'")
            print(f"[~] SSE client disconnected: {sid[:8]}")

    def do_POST(self):
        if not self.path.startswith("/messages/"):
            self.send_error(404)
            return
        if not self._check_auth():
            self.send_error(401)
            return

        qs = dict(p.split("=", 1) for p in
                  self.path.split("?", 1)[1].split("&") if "=" in p) \
            if "?" in self.path else {}
        sid = qs.get("session_id")

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return
        print(f"[>] POST sid={str(sid)[:8]} method={msg.get('method')} "
              f"id={msg.get('id')} name={msg.get('params', {}).get('name')}")
        threading.Thread(target=handle_rpc, args=(sid, msg), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8757)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((HOST, args.port), Handler)
    srv.daemon_threads = True
    print(f"MCP-Link emulator listening on http://{HOST}:{args.port}/sse")
    srv.serve_forever()


if __name__ == "__main__":
    main()
