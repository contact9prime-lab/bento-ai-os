"""A phone sees a department at work: one Telegram message that the lead hands to Finance.

    .venv/bin/python packaging/dev/phone-steps-e2e/run.py WORKDIR

A real `bento serve` on a throwaway home with a company (the catalogue's Finance department:
finance-lead, bookkeeper, fin-analyst), the scripted brain in brain.py and a stand-in Telegram
here (AGENTOS_TELEGRAM_API) that keeps every message and every edit with its time. One message
goes in from the phone; the run checks what the phone received while the desk worked:

  - one "Steps" message, sent quietly, BEFORE the answer, and edited as the work went on
  - in it: the hand-over to Finance, the desk taking it, each person it gave a piece to and
    their steps, the head's sign-off, the auditor, the finish
  - the answer after it

Then it renders what the phone showed (mid-turn and at the end) as a chat transcript and
photographs it at 390 px and 1440x900 into WORKDIR/shots.
"""
import asyncio
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
HERE = Path(__file__).resolve().parent
PORT, BRAIN, TG = 8661, 9461, 9462
CHAT = 777

tg = FastAPI()
UPD: list = []
LOG: list = []          # every send and edit: {at, method, id, text, quiet}
MSGS: dict = {}         # message id -> its latest text
NEXT = [100]


@tg.api_route("/bot{token}/{method}", methods=["GET", "POST"])
async def api(token: str, method: str, req: Request):
    try:
        b = await req.json()
    except Exception:
        b = dict(req.query_params)
    if method == "getMe":
        return {"ok": True, "result": {"id": 1, "is_bot": True, "username": "bento_bot", "first_name": "Bento"}}
    if method == "getUpdates":
        off = int(b.get("offset") or 0)
        if off:
            UPD[:] = [u for u in UPD if u["update_id"] >= off]
        t0 = time.time()
        while time.time() - t0 < min(float(b.get("timeout") or 0), 2) and not UPD:
            await asyncio.sleep(0.2)
        return {"ok": True, "result": [u for u in UPD if u["update_id"] >= off]}
    if method == "sendMessage":
        NEXT[0] += 1
        mid = NEXT[0]
        MSGS[mid] = str(b.get("text") or "")
        LOG.append({"at": time.time(), "method": method, "id": mid, "text": MSGS[mid],
                    "quiet": bool(b.get("disable_notification"))})
        # an approval card: the person taps "Allow once", a moment later, as on a real phone
        for row in ((b.get("reply_markup") or {}).get("inline_keyboard") or []):
            for btn in row:
                if str(btn.get("callback_data") or "").startswith("ap:") and btn["callback_data"].endswith(":1"):
                    TAPS.append(btn["callback_data"])
                    threading.Timer(0.8, tap, args=(btn["callback_data"], mid)).start()
        return {"ok": True, "result": {"message_id": mid, "chat": {"id": CHAT}, "date": int(time.time())}}
    if method == "editMessageText":
        mid = int(b.get("message_id") or 0)
        if MSGS.get(mid) == b.get("text"):
            return {"ok": False, "description": "Bad Request: message is not modified"}
        MSGS[mid] = str(b.get("text") or "")
        LOG.append({"at": time.time(), "method": method, "id": mid, "text": MSGS[mid]})
        return {"ok": True, "result": {"message_id": mid}}
    return {"ok": True, "result": True}


TAPS: list = []


def tap(data, mid):
    NEXT[0] += 1
    UPD.append({"update_id": NEXT[0], "callback_query": {
        "id": str(NEXT[0]), "data": data, "from": {"id": CHAT, "is_bot": False, "first_name": "Piyush"},
        "message": {"message_id": mid, "chat": {"id": CHAT, "type": "private"}, "date": int(time.time())}}})


def say(text):
    NEXT[0] += 1
    UPD.append({"update_id": NEXT[0], "message": {
        "message_id": NEXT[0], "date": int(time.time()), "text": text,
        "from": {"id": CHAT, "is_bot": False, "first_name": "Piyush"},
        "chat": {"id": CHAT, "type": "private", "first_name": "Piyush"}}})


def setup(home: Path, env: dict):
    shutil.rmtree(home, ignore_errors=True)
    (home / "work").mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Aria", "setup_complete": True, "permissions_migrated": True,
        "default_model": "custom/fake-1", "workspace": str(home / "work"), "autonomy": "full",
        "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": CHAT, "status_messages": False},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "api_key": "", "models": ["fake-1"]}}}))
    # the company, and the owner's chat let in, before the server starts
    subprocess.run([PY, "-c", f"""
from agentos import company, config, tools
from agentos.memory import Store
cfg = config.load_config()
store = Store()
plan, _ = company.normalize(company.template_plan(['finance'], 'Acme'), [t['name'] for t in tools.TOOL_SCHEMAS])
company.apply(cfg, store, plan, {{'mail': False, 'calendar': False}})
config.save_config(cfg)
store.tg_upsert_chat({CHAT}, 'Piyush', '', 'private')
store.tg_set_allowed({CHAT}, 1, by='the run')
"""], env=env, cwd=ROOT, check=True)


def transcript(items: list, title: str) -> str:
    rows = []
    for it in items:
        cls = "me" if it["who"] == "me" else ("steps" if it["text"].startswith(("⚙", "✓ Steps")) else "bot")
        rows.append(f'<div class="b {cls}">{html.escape(it["text"])}'
                    f'<span class="t">{it["when"]}</span></div>')
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:light}}body{{margin:0;background:#d9e7d0;font:15px/1.4 -apple-system,system-ui,sans-serif}}
header{{background:#517da2;color:#fff;padding:14px 16px;font-weight:600}}header small{{display:block;font-weight:400;opacity:.8}}
main{{max-width:560px;margin:0 auto;padding:12px 10px 40px;display:flex;flex-direction:column;gap:8px}}
.b{{white-space:pre-wrap;padding:8px 10px 18px;border-radius:12px;max-width:86%;position:relative;box-shadow:0 1px 1px rgba(0,0,0,.12)}}
.me{{align-self:flex-end;background:#effdde}}.bot{{align-self:flex-start;background:#fff}}
.steps{{align-self:flex-start;background:#fff;font-size:13.5px;border-left:3px solid #517da2}}
.t{{position:absolute;right:8px;bottom:3px;font-size:11px;color:#8a9aa9}}
</style><header>Bento <small>{html.escape(title)}</small></header><main>{''.join(rows)}</main>"""


async def shoot(pages: dict, out: Path):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for name, path in pages.items():
            for tag, vp, scale in (("phone", {"width": 390, "height": 844}, 2), ("wide", {"width": 1440, "height": 900}, 1)):
                c = await b.new_context(viewport=vp, device_scale_factor=scale)
                p = await c.new_page()
                await p.goto(path.as_uri())
                await p.screenshot(path=str(out / f"{tag}-{name}.png"), full_page=True)
                await c.close()
        await b.close()


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/phone-steps-e2e")
    home, shots = work / "home", work / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=lambda: uvicorn.run(tg, host="127.0.0.1", port=TG, log_level="warning"),
                     daemon=True).start()
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}")
    setup(home, env)
    brain = subprocess.Popen([PY, str(HERE / "brain.py"), str(BRAIN)], env=env,
                             stdout=open(work / "brain.log", "w"), stderr=subprocess.STDOUT)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                            "--if-running", "fail"], env=env, cwd=ROOT,
                           stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad = []
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/platform", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        time.sleep(4)                        # the bridge's first poll
        asked = "Get Finance on it: how long is our cash runway this quarter, and how do we stretch it?"
        t0 = time.time()
        say(asked)
        answer = None
        while time.time() - t0 < 240:
            answer = next((e for e in LOG if e["method"] == "sendMessage"
                           and e["text"].startswith("Finance is done")), None)
            if answer:
                break
            time.sleep(0.5)
        time.sleep(2)
        steps_id = next((e["id"] for e in LOG if e["text"].startswith("⚙ Steps")), None)
        for e in LOG:
            print(f"+{e['at'] - t0:5.1f}s {e['method']:<15} #{e['id']} {e['text'][:90]!r}")
        print(f"approvals tapped: {len(TAPS)}")
        if not answer:
            bad.append("no answer arrived")
        if not steps_id:
            bad.append("no Steps message was sent")
        else:
            first = next(e for e in LOG if e["id"] == steps_id)
            edits = [e for e in LOG if e["id"] == steps_id and e["method"] == "editMessageText"]
            if not first["quiet"]:
                bad.append("the Steps message buzzed the phone")
            if answer and first["at"] > answer["at"]:
                bad.append("the steps came after the answer")
            if len(edits) < 2:
                bad.append(f"the Steps message was edited {len(edits)} times while the desk worked")
            final = MSGS[steps_id]
            for need in ("▦ To Finance", "▦ Finance desk took it", "↳ @fin-analyst", "↳ @bookkeeper",
                         "✓ @fin-analyst finished", "@finance-lead", "⚑ The auditor passed it", "▦ Finance desk finished"):
                if need not in final:
                    bad.append(f"the steps never said {need!r}")
            if not final.startswith("✓ Steps"):
                bad.append("the Steps message was not marked finished")
            # what the phone showed mid-turn: the steps message as it was half way through
            mid_text = next((e["text"] for e in edits if "↳ @bookkeeper" in e["text"]), first["text"])
            hhmm = lambda t: time.strftime("%H:%M", time.localtime(t))      # noqa: E731
            mid = [{"who": "me", "text": asked, "when": hhmm(t0)},
                   {"who": "bot", "text": mid_text, "when": hhmm(first["at"])}]
            end = [{"who": "me", "text": asked, "when": hhmm(t0)},
                   {"who": "bot", "text": final, "when": hhmm(first["at"])}]
            if answer:
                end.append({"who": "bot", "text": answer["text"], "when": hhmm(answer["at"])})
            pages = {}
            for name, items, title in (("while-it-works", mid, "while Finance works"),
                                       ("answered", end, "the answer, after the steps")):
                p = work / f"{name}.html"
                p.write_text(transcript(items, title))
                pages[name] = p
            asyncio.run(shoot(pages, shots))
            (work / "telegram-log.json").write_text(json.dumps(LOG, indent=1, ensure_ascii=False))
    finally:
        for p in (srv, brain):
            p.terminate()
    print("FINDINGS:", json.dumps(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
