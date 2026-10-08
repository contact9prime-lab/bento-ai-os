"""Put Bento in the cloud: the ways to get a cloud machine, in the order a beginner should try them.

Asked for as "deploy it quickly to the cloud … really quick and noob for anyone, so sso
and done". Cloud standby (standby.py) already knew what to do WITH a cloud machine, and
its docs began "You need Bento running on a cloud machine" with no word on how to get one.

The one-click road is Render's FREE plan (asked for next: "deploy the agent in the cloud
free and make it work"), and it is chosen for three reasons:

  * Its free plan needs no card, and it keeps running if something visits it. Its disk is
    wiped on every restart, so the home is kept sealed in a storage bucket the person owns
    (keep.py: Backblaze B2's 10 GB free, or any S3-compatible storage), and a visit every
    ten minutes keeps it awake. A host with no free plan, or one whose free machine sleeps
    for good, is not the one-click road.
  * Its button reads a file in the repo (`render.yaml`), so the disk, the health check and
    the password prompt are declared once, here, and nobody fills in a form of ten fields.
  * Sign-in is GitHub, GitLab or Google, and the password is asked for ON the deploy page
    (`sync: false`), so the first thing on the new machine is a lock that is already set.

Everything else is a few commands for people who have a terminal open anyway. Each option
says what it costs and whether it keeps your data, because "free" that forgets everything
on the first restart is the most expensive kind.

Kept free of HTTP and asyncio, like jobs.py: `bento cloud` prints the same list with the
server down, and the Settings card and docs read the same words.
"""
from __future__ import annotations

import secrets

from . import keep

#: The image's own entrypoint reads these. Kept here so the docs, the card and the
#: blueprint name one variable.
PASSPHRASE_ENV = "AGENTOS_PASSPHRASE"
#: The open path a host can poll without signing in (REMOTE_OPEN_PATHS has it).
HEALTH_PATH = "/login"

_WORDS = ("amber", "basil", "cedar", "delta", "ember", "fjord", "garnet", "harbor",
          "indigo", "juniper", "kelp", "lumen", "maple", "nectar", "onyx", "pepper",
          "quartz", "raven", "saffron", "tundra", "umber", "velvet", "willow", "zephyr")


def repo(cfg: dict | None = None) -> str:
    """owner/name of the repository this machine updates from (a fork deploys itself)."""
    try:
        from . import updates
        return updates.repo_of(cfg or {})
    except Exception:
        return "contact9prime-lab/bento-ai-os"


def suggest_passphrase() -> str:
    """Four words and two digits: long enough to be safe on the internet, short enough
    to type on a phone. Made fresh each time and never stored."""
    pick = [secrets.choice(_WORDS) for _ in range(4)]
    return "-".join(pick) + f"-{secrets.randbelow(90) + 10}"


def options(cfg: dict | None = None) -> list[dict]:
    """Every way to get a cloud Bento, easiest first. Each has a one-line `how`, the
    `steps`, what it `costs` and whether it `keeps` your data across restarts."""
    r = repo(cfg)
    gh = f"https://github.com/{r}"
    return [
        {"id": "render", "title": "Render", "kind": "button", "recommended": True,
         "url": f"https://render.com/deploy?repo={gh}",
         "how": "Free. Make a free storage bucket, sign in to Render, choose a password, press Deploy.",
         "storage": keep.PROVIDERS,
         "steps": ["Make a free storage bucket for its memory: Backblaze B2 gives 10 GB free with "
                   "no card. Make a private bucket and a key that can read and write only that bucket.",
                   "Press Deploy on Render and sign in with GitHub, GitLab or Google.",
                   f"Type a password in {PASSPHRASE_ENV}. Fill in {keep.ENV_ENDPOINT}, {keep.ENV_BUCKET}, "
                   f"{keep.ENV_KEY_ID} and {keep.ENV_SECRET} from your bucket.",
                   "Press Deploy Blueprint and wait about five minutes for the first build.",
                   "Open the address Render gives you (https://bento-….onrender.com) and sign in with that password."],
         "costs": "Free. Render's free plan has 512 MB and a slow processor, which is enough. Its "
                  "disk is wiped on every restart, so the memory is kept sealed with your password "
                  "in your own storage bucket, and a visit every ten minutes keeps it awake.",
         "keeps": True, "https": True, "free": True},
        {"id": "render-paid", "title": "Render with its own disk", "kind": "steps", "recommended": False,
         "url": "",
         "how": "The same deploy, moved to a paid plan that never sleeps and has its own disk.",
         "steps": ["Deploy with the button above.",
                   "In Render, open the service → Settings → Instance Type and choose Starter.",
                   "Open Disks → Add Disk, mount path /data, 1 GB.",
                   f"Remove the four BENTO_STORAGE_ settings, {keep.ENV_EPHEMERAL} and {keep.ENV_AWAKE} "
                   "if you no longer want the copy in your bucket."],
         "costs": "About $7 a month for the server, plus about $0.25 a month for the 1 GB disk.",
         "keeps": True, "https": True, "free": False},
        {"id": "fly", "title": "Fly.io", "kind": "commands", "recommended": False,
         "url": "https://fly.io/docs/flyctl/install/",
         "how": "Four commands in a terminal, with HTTPS and a disk.",
         "steps": [f"git clone {gh}.git && cd {r.split('/')[-1]}",
                   "fly launch --copy-config --no-deploy",
                   f"fly secrets set {PASSPHRASE_ENV}='<your password>'",
                   "fly deploy --volume-initial-size 1"],
         "costs": "About $3 a month for a 512 MB machine, plus $0.15 a month per GB of disk.",
         "keeps": True, "https": True, "free": False},
        {"id": "server", "title": "Your own server", "kind": "commands", "recommended": False,
         "url": "",
         "how": "Any Linux server you can reach (Hetzner, DigitalOcean, Lightsail).",
         "steps": [f"curl -fsSL https://raw.githubusercontent.com/{r}/master/install.sh | "
                   "sh -s -- --yes --passphrase='<your password>'",
                   "Put HTTPS in front before you use it over the internet: Caddy, a "
                   "Cloudflare Tunnel or Tailscale."],
         "costs": "Whatever the server costs, often $4 to $6 a month. Google Cloud's e2-micro and "
                  "Oracle's Always Free machines cost nothing but ask for a card to sign up.",
         "keeps": True, "https": False, "free": False},
    ]


#: Hosts people ask about that are deliberately not offered, and why. Said out loud so
#: the absence reads as a decision, not an oversight.
NOT_OFFERED = {
    "Railway": "no free plan, only a trial, and its deploy button cannot add a disk.",
    "Koyeb": "its free machine sleeps after an hour without visitors, and now asks for a card.",
    "Hugging Face Spaces": "free machines sleep after two days and their Docker apps may need a paid plan.",
    "DigitalOcean App Platform": "no free plan for a server, and no disk.",
    "Google Cloud Run": "no disk, so every restart forgets everything.",
}


def after() -> list[str]:
    """What to do once the cloud Bento is up: the two moves this OS already has."""
    return ["Use it as a standby: on the cloud Bento press Show a code under Settings → "
            "System → Cloud standby, then pair from this machine.",
            "Or move this machine there: Settings → System → Backup here, then Restore "
            "from a backup on the cloud Bento."]


def text(cfg: dict | None = None) -> str:
    """The whole list for a terminal (`bento cloud`)."""
    out = ["Put Bento in the cloud", ""]
    for i, o in enumerate(options(cfg), 1):
        tag = " (easiest)" if o["recommended"] else ""
        out.append(f"{i}. {o['title']}{tag}: {o['how']}")
        if o["kind"] == "button":
            out.append(f"   Open: {o['url']}")
        if o.get("storage"):
            out.append("   Storage for its memory (any S3-compatible service works):")
            for p in o["storage"]:
                if p.get("signup"):
                    out.append(f"     {p['name']}: {p['free']}. {p['card']} {p['signup']}")
        for s in o["steps"]:
            out.append(f"   - {s}")
        out.append(f"   Cost: {o['costs']}")
        if not o["https"]:
            out.append("   No HTTPS of its own.")
        out.append("")
    out.append("Not offered:")
    out += [f"  {k}: {v}" for k, v in NOT_OFFERED.items()]
    out.append("")
    out.append("Once it is up:")
    out += [f"  {s}" for s in after()]
    out.append("")
    out.append(f"A password you could use: {suggest_passphrase()}")
    return "\n".join(out)
