"""A stand-in MCP server for the Zero-per-account run: one tool, `pantry_list`, so the run can
see whose integrations answered a Zero. Started over stdio by the hub's MCP manager.

    python3 pantry_mcp.py

Stdlib only, and run with a SYSTEM Python passed as `-c` source: an account's stdio server runs
in that account's jail (mcp_client.stdio_launch), which hides every home. A checkout under
/home, its venv and this file are not there inside it, so the run hands the jail a program and a
source it can see, as an admin-installed server would be.
"""
import json
import sys

TOOL = {"name": "pantry_list", "description": "What is in the pantry.",
        "inputSchema": {"type": "object", "properties": {}}}


def answer(msg: dict):
    method = msg.get("method")
    if method == "initialize":
        return {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2025-06-18",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "pantry", "version": "1"}}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        return {"content": [{"type": "text", "text": "eggs, rice, lentils, spinach"}], "isError": False}
    if method == "ping":
        return {}
    return None


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue                      # a notification
        got = answer(msg)
        out = ({"jsonrpc": "2.0", "id": msg["id"], "result": got} if got is not None else
               {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no such method"}})
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
