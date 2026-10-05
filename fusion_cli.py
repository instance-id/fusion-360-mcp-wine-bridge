#!/usr/bin/env python3
"""CLI client for the local MCP-Link emulator -> Fusion 360 add-in.

Usage:
  python3 fusion_cli.py '<json arguments>'          # raw fusion360 tool args
  python3 fusion_cli.py --py '<python code>'        # execute_python shortcut
  python3 fusion_cli.py --api <api_path> [--args '<json list>'] [--store-as NAME]

Examples:
  python3 fusion_cli.py --py 'print(app.version)'
  python3 fusion_cli.py --api design.rootComponent.bRepBodies.count
  python3 fusion_cli.py '{"operation":"execute_python","code":"print(1+1)"}'
"""

import argparse
import http.client
import json
import queue
import sys
import threading
import uuid

HOST = "127.0.0.1"
PORT = 8757
AUTH = "Bearer fusion360-mcp-local-token"


def call_fusion(arguments: dict, timeout: float = 120.0):
    # Open SSE
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout + 30)
    conn.request("GET", "/sse", headers={
        "Accept": "text/event-stream",
        "Authorization": AUTH,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"SSE connect failed: {resp.status}")

    message_endpoint = None
    responses = queue.Queue()
    stop = threading.Event()

    def reader():
        event_type = None
        while not stop.is_set():
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", "ignore").strip()
            if line == "":
                event_type = None
            elif line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
                if event_type == "endpoint":
                    responses.put(("endpoint", data))
                else:
                    try:
                        responses.put(("msg", json.loads(data)))
                    except json.JSONDecodeError:
                        pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Wait for endpoint
    while True:
        kind, data = responses.get(timeout=timeout)
        if kind == "endpoint":
            message_endpoint = data
            break

    # Send tools/call
    req_id = str(uuid.uuid4())
    body = json.dumps({
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": "fusion360", "arguments": arguments},
    })
    post = http.client.HTTPConnection(HOST, PORT, timeout=30)
    post.request("POST", message_endpoint, body=body, headers={
        "Content-Type": "application/json",
        "Authorization": AUTH,
    })
    presp = post.getresponse()
    presp.read()
    post.close()
    if presp.status != 202:
        raise RuntimeError(f"POST failed: {presp.status}")

    # Wait for matching response
    while True:
        kind, data = responses.get(timeout=timeout)
        if kind == "msg" and isinstance(data, dict) and data.get("id") == req_id:
            stop.set()
            conn.close()
            return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_args", nargs="?", help="JSON arguments for fusion360 tool")
    ap.add_argument("--py", help="Python code to execute (execute_python)")
    ap.add_argument("--api", help="api_path for generic API call")
    ap.add_argument("--args", help="JSON list of args for --api")
    ap.add_argument("--store-as", dest="store_as", help="store_as name for --api")
    ap.add_argument("--session", default="fusion360mcp", help="session_id for --py")
    ap.add_argument("--timeout", type=float, default=120.0)
    a = ap.parse_args()

    if a.py:
        arguments = {"operation": "execute_python", "code": a.py,
                     "session_id": a.session, "persistent": True}
    elif a.api:
        arguments = {"api_path": a.api}
        if a.args:
            arguments["args"] = json.loads(a.args)
        if a.store_as:
            arguments["store_as"] = a.store_as
    elif a.json_args:
        arguments = json.loads(a.json_args)
    else:
        ap.error("provide --py, --api, or JSON args")

    resp = call_fusion(arguments, timeout=a.timeout)
    if "error" in resp:
        print(json.dumps(resp["error"], indent=2))
        sys.exit(1)
    result = resp.get("result", {})
    for item in result.get("content", []):
        if item.get("type") == "text":
            print(item["text"])
    if result.get("isError"):
        sys.exit(1)


if __name__ == "__main__":
    main()
