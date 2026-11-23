"""Our MCP client against REAL servers built with the installed SDK: one over stdio, one over
streamable HTTP through the network guard. Before this, nothing connected a server in the suite,
so mcp 2.x renaming its HTTP transport turned every machine's MCP off with every test passing."""
import asyncio
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from agentos import mcp_client

SERVER = textwrap.dedent('''
    import sys
    try:
        from mcp.server.mcpserver import MCPServer as Server      # mcp 2.x
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server          # mcp 1.x
    app = Server("sums")

    @app.tool()
    def add(a: int, b: int) -> str:
        """Add two numbers."""
        return f"{a} + {b} = {a + b}"

    @app.tool()
    def boom() -> str:
        """Always fails."""
        raise ValueError("the sums machine is broken")

    if sys.argv[1:] and sys.argv[1] == "http":
        port = int(sys.argv[2])
        try:
            app.run(transport="streamable-http", host="127.0.0.1", port=port)
        except TypeError:
            app.settings.host, app.settings.port = "127.0.0.1", port
            app.run(transport="streamable-http")
    else:
        app.run()
''')


async def _connect(conf: dict, timeout: float = 30) -> mcp_client.MCPManager:
    mgr = mcp_client.MCPManager({"mcp_servers": {}})
    srv = mcp_client.MCPServer("sums", conf)
    seen = asyncio.Event()

    async def changed(s):
        seen.set()
    srv.task = asyncio.create_task(srv._run(changed))
    await asyncio.wait_for(seen.wait(), timeout)
    mgr.servers["sums"] = srv
    return mgr


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_the_client_imports_on_the_installed_sdk():
    assert mcp_client.MCP_AVAILABLE, "the MCP SDK is installed and our client must load with it"


def test_a_stdio_server_connects_lists_and_answers(tmp_path):
    script = tmp_path / "sums.py"
    script.write_text(SERVER)

    async def go():
        mgr = await _connect({"transport": "stdio", "command": sys.executable, "args": str(script)})
        srv = mgr.servers["sums"]
        assert srv.status == "connected", srv.error
        assert sorted(t["name"] for t in srv.tools) == ["add", "boom"]
        add = next(t for t in srv.tools if t["name"] == "add")
        assert set(add["parameters"]["properties"]) == {"a", "b"}, "the input schema came through"
        out = await mgr.call("sums", "add", {"a": 2, "b": 3})
        bad = await mgr.call("sums", "boom", {})
        srv.close()
        return out, bad
    out, bad = asyncio.run(go())
    assert "2 + 3 = 5" in out
    # 2.x keeps a crash's message to itself ("Error executing tool boom"); 1.x passes it on
    assert bad.startswith("[error]") and ("broken" in bad or "boom" in bad), \
        "a tool's failure reads as a failure, not a result"


def test_an_http_server_connects_through_the_guard(tmp_path):
    script = tmp_path / "sums.py"
    script.write_text(SERVER)
    port = _free_port()
    p = subprocess.Popen([sys.executable, str(script), "http", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        async def go():
            mgr = await _connect({"transport": "http", "url": f"http://127.0.0.1:{port}/mcp"})
            srv = mgr.servers["sums"]
            assert srv.status == "connected", srv.error
            out = await mgr.call("sums", "add", {"a": 40, "b": 2})
            srv.close()
            return out
        assert "40 + 2 = 42" in asyncio.run(go())
    finally:
        p.terminate()
        p.wait(10)


def test_the_guard_refuses_a_metadata_address_on_the_sdks_own_client():
    from agentos import netguard

    async def go():
        try:
            import httpx2 as lib
            c = netguard.client2(local_ok=True, timeout=5)
        except ImportError:
            import httpx as lib
            c = netguard.client(local_ok=True, timeout=5)
        async with c:
            with pytest.raises(lib.TransportError) as e:
                await c.get("http://169.254.169.254/latest/meta-data/")
        return e.value
    err = asyncio.run(go())
    assert isinstance(err.__cause__, netguard.Refused) or isinstance(err, netguard.Refused), \
        "refused by the guard before any connection, not a timeout"


def test_oauth_hands_the_sdk_the_shape_it_asks_for():
    from agentos import mcp_oauth
    p = mcp_oauth.provider_for("notion", "https://mcp.example.com/mcp")
    assert p is not None
    import importlib.metadata as md
    if int(md.version("mcp").split(".")[0]) >= 2:
        assert mcp_oauth.AuthorizationCodeResult is not None, "2.x wants a result object back"


def test_a_finished_sign_in_hands_back_the_code_state_and_issuer(monkeypatch):
    """The callback route records what the provider sent; the SDK gets it in its own shape. 2.x
    checks the issuer (RFC 9207), so dropping `iss` would refuse a provider that sends it."""
    from agentos import mcp_oauth
    p = mcp_oauth.provider_for("notion", "https://mcp.example.com/mcp")
    ctx = getattr(p, "context", None)
    if ctx is None:
        pytest.skip("this SDK keeps its handlers elsewhere")

    async def go():
        await ctx.redirect_handler("https://auth.example.com/authorize?state=s1")
        waiting = asyncio.create_task(ctx.callback_handler())
        await asyncio.sleep(0)
        assert mcp_oauth.resolve("notion", "c0de", "s1", iss="https://auth.example.com")
        return await waiting
    monkeypatch.setattr(mcp_oauth, "_ui_probe", lambda: True)   # a screen is watching: no browser opened
    got = asyncio.run(go())
    if mcp_oauth.AuthorizationCodeResult is not None:
        assert (got.code, got.state, got.iss) == ("c0de", "s1", "https://auth.example.com")
    else:
        assert got == ("c0de", "s1")
