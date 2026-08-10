"""Capture the documentation screenshots against a real, running machine.

Not mockups and not a staged fixture database: this drives a live server through
the actual flows — first-run onboarding, creating an account, signing out, signing
back in as somebody else — and photographs what happens. A screenshot in the docs
that was posed rather than produced is a screenshot that stops matching the
software the first time somebody changes a label.

Usage:
    packaging/dev/sui-testbed.sh  is for the session shell; this one only needs a
    server:

        AGENTOS_HOME=/tmp/shots bento serve --port 8899 &
        .venv/bin/python packaging/dev/capture-docs.py --port 8899 --out docs/screenshots

The home directory it points at is REBUILT by the caller, because the arc being
photographed starts at "nothing has been set up" and there is no way to get back
there without deleting things — which this script deliberately will not do to a
directory it was merely handed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CHROMIUM = "/opt/pw-browsers/chromium"


class Shooter:
    def __init__(self, page, out: Path):
        self.p, self.out, self.errors = page, out, []
        page.on("pageerror", lambda e: self.errors.append(f"PAGEERROR {e}"))
        page.on("console", lambda m: m.type == "error" and not _noise(m.text)
                and self.errors.append(f"CONSOLE {m.text}"))

    async def shot(self, name: str, clip=None, wait=900):
        await self.p.wait_for_timeout(wait)
        await self.p.screenshot(path=str(self.out / f"{name}.png"), clip=clip)
        print(f"  · {name}.png")

    async def close_windows(self):
        await self.p.evaluate(
            "[...WM.wins.values()].forEach(w=>closeWin(w));"
            "document.querySelectorAll('.dlg-scrim').forEach(e=>e.remove())")
        await self.p.wait_for_timeout(300)

    async def app(self, app_id: str, wait=1200):
        await self.close_windows()
        await self.p.evaluate(f"openApp('{app_id}')")
        await self.p.wait_for_timeout(wait)


def _noise(text: str) -> bool:
    return "404" in text or "favicon" in text


async def onboarding(s: Shooter, base: str):
    """The arc, photographed as somebody walks it."""
    print("onboarding")
    await s.p.goto(base, wait_until="networkidle")
    await s.p.wait_for_timeout(3000)
    if not await s.p.evaluate("!!document.querySelector('.wiz.ob')"):
        await s.p.evaluate("obShow({})")
    await s.shot("onboarding-1-name", wait=1400)

    await s.p.evaluate("OB.open='agent';obRender()")
    await s.shot("onboarding-2-agent")

    await s.p.evaluate("OB.open='schedule';obRender()")
    await s.shot("onboarding-3-schedule", wait=1600)

    await s.p.evaluate("OB.open='account';obRender()")
    await s.shot("onboarding-4-account", wait=1400)


async def make_account(s: Shooter):
    """Create the first account through the wizard — the real POST, the real
    adoption, the real sign-in."""
    print("first account")
    await s.p.fill("#ob-u-name", "ada")
    await s.p.fill("#ob-u-disp", "Ada Lovelace")
    await s.p.fill("#ob-u-pass", "hunter2hunter")
    await s.p.click("#ob-u-go")
    await s.p.wait_for_timeout(600)
    await s.shot("onboarding-5-account-consent", wait=400)
    await s.p.click(".dlg-ok")
    await s.p.wait_for_timeout(2200)
    await s.shot("onboarding-6-account-done")
    await s.p.evaluate("obClose()")
    await s.p.wait_for_timeout(600)


async def users_app(s: Shooter):
    print("users")
    # No shot of the one-account roster: `onboarding-6-account-done` already shows
    # that moment, and two near-identical pictures in one page is how a reader
    # starts skipping them.
    await s.app("users", wait=1600)

    # add an executor, so the roster shows both roles and the shared library has
    # somebody to share with
    await s.p.click(".usr-add > summary")
    await s.p.wait_for_timeout(400)
    await s.p.fill("#usr-name", "bob")
    await s.p.fill("#usr-display", "Bob Kahn")
    await s.p.fill("#usr-pass", "hunter2hunter")
    await s.shot("users-add", wait=500)
    await s.p.click("#usr-save")
    await s.p.wait_for_timeout(2000)
    await s.shot("users-two-accounts")


async def sharing(s: Shooter):
    print("sharing")
    await s.p.evaluate("""fetch('/api/subagents',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'market-watcher',
          soul:'You watch a market and report only what changed and why it matters.',
          tools:['fetch_url','save_report','recall']})})""")
    await s.p.wait_for_timeout(900)
    await s.p.evaluate("fabTab='agents'")
    await s.app("fabric", wait=1800)
    await s.shot("sharing-agent-share-button")
    await s.p.evaluate("() => { usersShare('agent','market-watcher') }")
    await s.p.wait_for_timeout(500)
    await s.shot("sharing-consent", wait=400)
    await s.p.click(".dlg-ok")
    await s.p.wait_for_timeout(1200)
    await s.app("users", wait=1600)
    await s.shot("sharing-library")


async def remote(s: Shooter):
    print("remote access")
    await s.close_windows()
    await s.p.evaluate("openApp('syssettings')")
    await s.p.wait_for_timeout(1200)
    await s.p.evaluate("sysTab(SYS_TABS.indexOf('Remote access'))")
    await s.p.wait_for_timeout(2500)
    await s.shot("remote-locked-by-accounts")


async def sign_out_in(s: Shooter, base: str):
    print("sign out, sign in")
    await s.close_windows()
    await s.p.click("#tray-power")
    await s.p.wait_for_timeout(500)
    await s.shot("power-menu-signed-in",
                 clip={"x": 1000, "y": 0, "width": 440, "height": 330}, wait=200)
    await s.p.evaluate("document.getElementById('powermenu').classList.remove('show')")
    await s.p.evaluate("() => { usersSignOut() }")
    await s.p.wait_for_timeout(500)
    await s.p.click(".dlg-ok")
    await s.p.wait_for_timeout(2200)
    await s.shot("login")

    await s.p.fill("#who", "bob")
    await s.p.fill("#pw", "hunter2hunter")
    await s.p.click("#go")
    await s.p.wait_for_timeout(4000)
    # bob is new: he gets his own arc, on a machine ada already set up
    await s.shot("second-user-onboarding")
    await s.p.evaluate("document.querySelectorAll('.wiz').forEach(e=>e.remove())")
    await s.app("users", wait=1600)
    await s.shot("users-executor-view")
    # The Agents tab, not Flows: the point is that ada's `market-watcher` is not
    # here. A Flows screenshot shows the seeded `daily-briefing` and reads as
    # "there is stuff", which is the opposite of what it is meant to prove.
    await s.p.evaluate("fabTab='agents'")
    await s.app("fabric", wait=1800)
    await s.shot("isolation-second-user-agents")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--out", default="docs/screenshots")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1440, "height": 900},
                                device_scale_factor=2)
        s = Shooter(page, out)
        await onboarding(s, base)
        await make_account(s)
        await users_app(s)
        await sharing(s)
        await remote(s)
        await sign_out_in(s, base)
        await b.close()

    if s.errors:
        print("\npage errors:")
        for e in dict.fromkeys(s.errors):
            print("  " + e)
        sys.exit(1)
    print("\nno page errors")


if __name__ == "__main__":
    asyncio.run(main())
