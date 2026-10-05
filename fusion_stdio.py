#!/usr/bin/env python3
"""All-in-one stdio MCP server for the Fusion 360 add-in.

Spawned by the IDE as an MCP server (stdio transport, newline-delimited
JSON-RPC). On start it brings up the MCP-Link emulator HTTP bridge on
127.0.0.1:8757 in a background thread — the Fusion add-in connects to it
and registers the 'fusion360' tool. When the IDE session ends, this process
exits and the port is freed; the add-in reconnects on the next session.

Reuses mcp_link_server's handler + session tables: this process registers a
synthetic 'stdio' caller session and forwards MCP calls through handle_rpc,
so behavior is identical to the standalone server + fusion_cli.py path.

Config (.<ide_config_dir>/mcp_config.json):
  {"mcpServers":{"fusion360":{"command":"python3","args":["/abs/path/fusion_stdio.py"]}}}
"""

import json
import queue
import sys
import threading
from http.server import ThreadingHTTPServer

import mcp_link_server as link

STDIO_SID = "stdio-local"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    # Bridge for the add-in (dies with this process)
    srv = ThreadingHTTPServer((link.HOST, 8757), link.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"bridge on http://{link.HOST}:8757/sse")

    # Synthetic caller session: handle_rpc pushes our responses here
    outbox = queue.Queue()
    link.sessions[STDIO_SID] = {"queue": outbox, "kind": "caller"}

    def forwarder():
        while True:
            send(outbox.get())

    threading.Thread(target=forwarder, daemon=True).start()

    # stdio JSON-RPC loop (newline-delimited per MCP spec)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:
            continue  # notification
        threading.Thread(target=link.handle_rpc, args=(STDIO_SID, msg),
                         daemon=True).start()

    # stdin closed -> IDE ended session; exit kills the bridge thread
    log("stdin closed, shutting down")


if __name__ == "__main__":
    main()
