"""A stand-in MCP server for the Zero-per-account run: one tool, `pantry_list`, so the run can
see whose integrations answered a Zero. Started over stdio by the hub's MCP manager.

    python pantry_mcp.py
"""
from mcp.server.fastmcp import FastMCP

app = FastMCP("pantry")


@app.tool()
def pantry_list() -> str:
    """What is in the pantry."""
    return "eggs, rice, lentils, spinach"


if __name__ == "__main__":
    app.run()
