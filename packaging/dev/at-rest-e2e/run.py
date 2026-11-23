"""The databases are encrypted at rest with the machine's key, end to end (agentos/dbcrypt.py).

    python packaging/dev/at-rest-e2e/run.py [WORK]

  1. A home as an older Bento left it: plain databases holding a memory and a chat.
  2. A real `bento serve` starts on it. Before it opens anything it encrypts them: the file no
     longer reads with plain SQLite, the secret's words are not in it, and the memory and the
     chat are still there through the API. The diary says what it did.
  3. `bento vault at-rest` and `bento doctor` say the same, Settings → System → Encryption shows
     it (photographed at 1440x900 and on a 390px phone).
  4. `bento backup` of that home, `bento restore` into a second, empty home, and a second server
     there: it opens what was restored, under the SECOND home's own key, which is a different key.
Prints FINDINGS (empty when it all held).
"""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, PORT2 = 8851, 8852
SECRET = "the Bluebird acquisition closes on Friday"
PW = "a backup passphrase for this run"
findings: list[str] = []


def env_for(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost")
    return env


def plain_home(home: Path):
    """What an older Bento left: plain SQLite, made with dbcrypt switched off."""
    code = f"""
import sqlite3
from agentos import dbcrypt
dbcrypt.connect = lambda db, *a, **k: sqlite3.connect(db, *a, **{{x: y for x, y in k.items() if x not in ("plain", "key")}})
dbcrypt.Row = sqlite3.Row
from agentos.memory import Store
s = Store({str(home / 'agentos.db')!r})
s.add_memory({SECRET!r})
cid = s.create_conversation("Bluebird plan")
s.add_message(cid, "user", "remind me about Bluebird")
s.add_message(cid, "assistant", {SECRET!r})
"""
    subprocess.run([PY, "-c", code], env=env_for(home), cwd=ROOT, check=True)


def serve(home: Path, port: int, log: Path):
    return subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(port), "--no-browser",
                             "--if-running", "fail"], env=env_for(home), cwd=ROOT,
                            stdout=open(log, "w"), stderr=subprocess.STDOUT)


def get(port: int, path: str):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10).read())


def wait_up(port: int, what: str):
    for _ in range(120):
        try:
            get(port, "/api/at-rest")
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"{what} did not start")


def bento(home: Path, *args, stdin: str = "") -> str:
    r = subprocess.run([PY, "-m", "agentos", *args], env=env_for(home), cwd=ROOT, input=stdin,
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


async def shoot(port: int, shots: Path):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        br = await pw.chromium.launch()
        for name, ctx in (("wide", {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2}),
                          ("phone", {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                                     "is_mobile": True, "has_touch": True})):
            c = await br.new_context(**ctx)
            p = await c.new_page()
            await p.goto(f"http://127.0.0.1:{port}/")
            await p.wait_for_function("()=>typeof openApp==='function'", timeout=40000)
            await p.wait_for_timeout(1500)
            await p.evaluate("()=>{SETTAB='system';localStorage.setItem('settab','system');"
                             "localStorage.setItem('setsub.system','Encryption');openApp('settings')}")
            await p.wait_for_selector("#ar-box .ar-row", timeout=20000)
            await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                             "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
            await p.wait_for_timeout(800)
            await p.evaluate("()=>{const e=document.getElementById('ar-box');e&&e.scrollIntoView({block:'center'})}")
            await p.wait_for_timeout(500)
            await p.screenshot(path=str(shots / f"{name}-at-rest.png"))
            await c.close()
        await br.close()


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/at-rest-e2e")
    shutil.rmtree(work, ignore_errors=True)
    home, home2, shots = work / "home", work / "home2", work / "shots"
    for d in (home, home2, shots):
        d.mkdir(parents=True)
    for h, port in ((home, PORT), (home2, PORT2)):
        (h / "config.json").write_text(json.dumps({"agent_name": "Bento", "setup_complete": True,
                                                   "permissions_migrated": True, "port": port,
                                                   "workspace": str(h / "work")}))
    plain_home(home)
    db = home / "agentos.db"
    print("before:", "plain" if db.read_bytes()[:16] == b"SQLite format 3\x00" else "encrypted",
          "| secret readable in the file:", SECRET.encode() in db.read_bytes())
    srv = serve(home, PORT, work / "server.log")
    srv2 = None
    try:
        t0 = time.monotonic()
        wait_up(PORT, "the server")
        print(f"server up in {time.monotonic() - t0:.1f}s")
        raw = db.read_bytes()
        if raw[:16] == b"SQLite format 3\x00":
            findings.append("agentos.db is still plain after the server started")
        if b"Bluebird" in raw:
            findings.append("the secret's words are still readable in agentos.db")
        try:
            sqlite3.connect(db).execute("select count(*) from memories").fetchone()
            findings.append("plain sqlite3 could still read agentos.db")
        except sqlite3.DatabaseError as e:
            print("plain sqlite3 now says:", e)
        mems = get(PORT, "/api/memories")
        mems = mems.get("memories", mems) if isinstance(mems, dict) else mems
        if not any(SECRET in json.dumps(m) for m in mems):
            findings.append("the memory didn't survive the conversion")
        convs = get(PORT, "/api/conversations")
        convs = convs.get("conversations", convs) if isinstance(convs, dict) else convs
        if not any("Bluebird" in (c.get("title") or "") for c in convs):
            findings.append("the chat didn't survive the conversion")
        at = get(PORT, "/api/at-rest")
        print("/api/at-rest:", json.dumps(at["db"]["line"]), "|", at["disk"]["state"])
        if at["db"]["state"] != "encrypted":
            findings.append(f"at-rest says {at['db']['state']}")
        logs = get(PORT, "/api/logs?limit=200")
        logs = logs.get("logs", logs) if isinstance(logs, dict) else logs
        said = [l for l in logs if "with this machine's key" in json.dumps(l)]
        print("diary:", said[0]["message"] if said else "(nothing)")
        if not said:
            findings.append("the diary doesn't say the databases were encrypted")
        print("\n$ bento vault at-rest\n" + bento(home, "vault", "at-rest"))
        doc = bento(home, "doctor")
        print("$ bento doctor   (the at-rest lines)\n" + "\n".join(
            ln for ln in doc.splitlines() if "databases:" in ln or "disk:" in ln))
        asyncio.run(shoot(PORT, shots))
        (work / "pw.txt").write_text(PW)
        out = bento(home, "backup", str(work / "machine.bento"), "--no-workspace", "--passphrase-file", str(work / "pw.txt"))
        print("\n$ bento backup …\n" + out.strip().splitlines()[-1] if out.strip() else out)
    finally:
        srv.terminate()
        srv.wait(10)
    out = bento(home2, "restore", str(work / "machine.bento"), "--yes", "--passphrase-file", str(work / "pw.txt"))
    print("$ bento restore … (into an empty second home)\n" + "\n".join(out.strip().splitlines()[-3:]))
    db2 = home2 / "agentos.db"
    restored_plain = db2.read_bytes()[:16] == b"SQLite format 3\x00"
    print("restored file, before any server:", "plain" if restored_plain else "encrypted")
    if restored_plain:
        findings.append("a restore left the databases plain on disk until the next start")
    srv2 = serve(home2, PORT2, work / "server2.log")
    try:
        wait_up(PORT2, "the second server")
        if db2.read_bytes()[:16] == b"SQLite format 3\x00":
            findings.append("the restored database is still plain after the second server started")
        mems = get(PORT2, "/api/memories")
        mems = mems.get("memories", mems) if isinstance(mems, dict) else mems
        if not any(SECRET in json.dumps(m) for m in mems):
            findings.append("the memory didn't come across in the backup")
        k1 = (home / "away.key").read_text().strip() if (home / "away.key").exists() else ""
        k2 = (home2 / "away.key").read_text().strip() if (home2 / "away.key").exists() else ""
        print("second home's key is", "the same as the first's (it came with the backup)" if k1 == k2
              else "its own")
    finally:
        srv2.terminate()
        srv2.wait(10)
    print("\nFINDINGS:", findings)


if __name__ == "__main__":
    main()
