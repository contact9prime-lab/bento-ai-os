"""The terminal is a door like the desktop, and on a machine with accounts it asks who you are.

Reported with a screenshot: the TUI on a machine with accounts read "Aria · no model"
and every tab was empty. The server refuses any call or socket without a signed
cookie once there are accounts — loopback included, on purpose (server._authed) —
and the TUI sent none. So: sign in first, carry the cookie on every call AND the
chat socket, show THIS person's agent, sign out with Ctrl+O. And the things asked
for on the desktop are reachable here too: the Office (roll call, Snap, Describe
it) and starting over (walk through again / factory reset).
"""
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
ROOT = Path(__file__).parent.parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture()
def server_with_an_account(tmp_path):
    home = tmp_path / "home"
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0"}
    setup = ("from agentos import users, config as c\n"
             "cfg=c.load_config(); cfg['setup_complete']=True; c.save_config(cfg)\n"
             "a=users.create('ada','hunter2hunter',role='admin')\n"
             "uc=users.cfg_for(a['id']); uc['agent_name']='Nova'; uc['default_model']='openai/gpt-x'\n"
             "users.save_user_cfg(a['id'],uc)\n")
    subprocess.run([sys.executable, "-c", setup], env=env, cwd=ROOT, check=True, timeout=60)
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "agentos", "serve", "--port", str(port), "--no-browser"],
                            env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    for _ in range(120):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/users/who", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    try:
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def test_the_tui_signs_in_shows_your_agent_and_signs_out(server_with_an_account):
    from textual.widgets import Input, Static
    from agentos.tui_app import AgentTUI, SignInScreen

    async def walk():
        app = AgentTUI(server_with_an_account, {"agent_name": "Aria"})
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(150):
                await pilot.pause(0.1)
                if isinstance(app.screen, SignInScreen):
                    break
            assert isinstance(app.screen, SignInScreen), "accounts: nothing loads before a sign-in"
            app.screen.query_one("#si-name", Input).value = "ada"
            app.screen.query_one("#si-pw", Input).value = "wrong-password-1"
            await pilot.click("#si-go")
            for i in range(150):
                await pilot.pause(0.1)
                if isinstance(app.screen, SignInScreen) and "do not match" in str(
                        app.screen.query_one("#si-error", Static).render()):
                    break
            assert "do not match" in str(app.screen.query_one("#si-error", Static).render()), (i, type(app.screen))
            app.screen.query_one("#si-name", Input).value = "ada"
            app.screen.query_one("#si-pw", Input).value = "hunter2hunter"
            await pilot.click("#si-go")
            for _ in range(150):
                await pilot.pause(0.1)
                if "Nova" in (app.sub_title or ""):
                    break
            assert app.sub_title.startswith("Nova · openai/gpt-x") and "ada" in app.sub_title, app.sub_title
            assert app.token, "the signed cookie is held for the session"
            for _ in range(150):
                await pilot.pause(0.1)
                if "Right now" in str(app.query_one("#office-body", Static).render()):
                    break
            body = str(app.query_one("#office-body", Static).render())
            assert "Right now" in body and "Nova" in body, "the Office tab reads THIS person's office"
            await pilot.press("o")               # the Office tab: the button is in it
            await pilot.pause(0.3)
            await pilot.click("#office-snap")
            for _ in range(150):
                await pilot.pause(0.1)
                if "not set up" in str(app.query_one("#office-status", Static).render()):
                    break
            assert "Telegram is not set up" in str(app.query_one("#office-status", Static).render())
            await pilot.press("ctrl+o")
            for _ in range(150):
                await pilot.pause(0.1)
                if isinstance(app.screen, SignInScreen):
                    break
            assert isinstance(app.screen, SignInScreen) and not app.token
    asyncio.run(walk())


def test_every_door_carries_the_cookie():
    tui = (ROOT / "agentos/tui_app.py").read_text()
    assert "cookies=self._cookies()" in tui and "additional_headers=hdrs" in tui
    assert '"/api/users/login"' in tui and '"/api/users/logout"' in tui
    assert "check_action" in tui, "no Sign out key on a machine with nobody to sign out as"
    for route in ("/api/office/rollcall", "/api/office/snap", "/api/office/design",
                  "/api/onboarding/restart", "/api/setup/reset"):
        assert route in tui, f"{route} is a desktop feature the terminal must reach"
    cli = (ROOT / "agentos/clitui.py").read_text()
    assert '"/api/users/login"' in cli and "additional_headers=hdrs" in cli, "the fallback REPL too"


def test_reset_from_a_terminal_refuses_what_it_must(tmp_path):
    home = tmp_path / "h"
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0"}
    r = subprocess.run([sys.executable, "-m", "agentos", "reset", "--port", str(_free_port())],
                       env=env, cwd=ROOT, input="reset everything\n", capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "no --yes on purpose" in r.stderr, "no terminal: refused, whatever was piped"
    src = (ROOT / "agentos/__main__.py").read_text()
    assert "_server_answers(port)" in src.split("def _reset_cli(")[1].split("\ndef ")[0], \
        "a running server would write its config back over the wipe"
    assert '"--again"' in src, "walking setup again is a flag on setup, and never a wipe"
    js = (ROOT / "agentos/ui/src/js/14-docs-setup.js").read_text()
    fr = js.split("async function factoryReset(")[1].split("\n}")[0]
    assert "if(!r.ok)" in fr, "a refused reset must not reload as if it had worked"
