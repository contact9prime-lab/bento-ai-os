"""A drawing of what a blueprint shows: a free-licence one found on Wikimedia Commons, or one
drawn when the person asks for it.

Asked for after the blueprint learned to take things apart: "is it still going to show the
drawings as well, how each thing looks" (with a line-art turbofan cutaway), then "the use of
the image, building of the designs should be done further". A blueprint drawn from parts data
is boxes; it never looks like the engine. So the whole and each top-level part get a picture
of the real thing, and the page tints it in blueprint ink (the Look view).

Four rules:
- Found means Commons, and only under a licence that lets anyone show it (public domain, CC0,
  CC BY, CC BY-SA). The credit, the licence and the file's page travel with the picture, and
  every face shows them. A picture is never taken from an address a model wrote: the model
  only gives search words (`look_for`).
- Drawn is the person's tap (`draw`), never automatic, and is marked illustrative: a generated
  cutaway looks right and may not be.
- Nothing here is a capability: the result is display only, kept on the scene.
- No answer, no picture. A failed lookup is quiet (the Look view says nothing was found and
  offers Draw it), because a blueprint must never fail for want of a picture.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlencode, urlsplit

API = "https://commons.wikimedia.org/w/api.php"
UA = "BentoBlueprint/1.0"
# Wikimedia's robot policy (https://w.wiki/4wJS) asks a client to name a contact in its
# User-Agent and refuses some that don't. The contact is the person's choice (`stage.contact`:
# a web address or an email of theirs); nothing personal is sent unless they set it.
CAP = 2 * 1024 * 1024
TIMEOUT = 20.0
FREE = ("public domain", "pd", "cc0", "cc by", "cc-by", "cc by-sa", "cc-by-sa")
# words in a file's title that say it is a drawing of how a thing is built
GOOD = ("cutaway", "cut-away", "diagram", "schematic", "section", "cross-section", "layout",
        "anatomy", "exploded", "blueprint", "drawing", "scheme", "structure", "plan", "elevation")
MIN_W = 500
HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org")


def _plain(s: str, n: int) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


def free(licence: str) -> bool:
    lic = (licence or "").strip().lower()
    if re.search(r"\b(nc|nd)\b", lic) or "noncommercial" in lic or "fair use" in lic:
        return False
    return any(lic == f or lic.startswith(f + " ") or lic.startswith(f + "-") for f in FREE) \
        or lic.startswith("public domain")


def query(words: str) -> str:
    q = re.sub(r"[^\w\s\-'.]", " ", str(words or ""), flags=re.UNICODE)
    q = re.sub(r"\s+", " ", q).strip()[:90]
    return q


def search_url(words: str) -> str:
    return API + "?" + urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrlimit": 12, "gsrsearch": f"{words} filetype:drawing|bitmap",
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 1280,
        "iiextmetadatafilter": "LicenseShortName|Artist|Credit"})


def _clean_url(u: str) -> str:
    """Only Wikimedia's own image hosts, over https, without the tracking query."""
    p = urlsplit(str(u or ""))
    if p.scheme != "https" or (p.hostname or "") not in HOSTS:
        return ""
    return f"https://{p.hostname}{p.path}"


def pick(answer: dict, words: str) -> dict | None:
    """The best free drawing in a Commons search answer, read field by field."""
    pages = ((answer or {}).get("query") or {}).get("pages") or {}
    best, best_score = None, -1e9
    want = {w for w in query(words).lower().split() if len(w) > 2}
    for p in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(p, dict):
            continue
        ii = (p.get("imageinfo") or [{}])[0] if isinstance(p.get("imageinfo"), list) else {}
        meta = ii.get("extmetadata") or {}
        lic = _plain((meta.get("LicenseShortName") or {}).get("value"), 40)
        if not free(lic):
            continue
        url = _clean_url(ii.get("thumburl") or ii.get("url"))
        page = str(ii.get("descriptionurl") or "")
        if not url or not page.startswith("https://commons.wikimedia.org/"):
            continue
        w = int(ii.get("width") or 0)
        if w and w < MIN_W and not str(ii.get("mime") or "").endswith("svg+xml"):
            continue
        title = _plain(str(p.get("title") or "").removeprefix("File:"), 120)
        tl = title.lower()
        score = 3 * sum(1 for g in GOOD if g in tl) + 2 * sum(1 for x in want if x in tl)
        score += 2 if str(ii.get("mime") or "").endswith("svg+xml") else 0
        score -= int(p.get("index") or 0) * 0.3          # Commons' own order breaks ties
        if score > best_score:
            best_score = score
            credit = _plain((meta.get("Artist") or {}).get("value"), 120) \
                or _plain((meta.get("Credit") or {}).get("value"), 120) or "Wikimedia Commons"
            best = {"url": url, "page": page[:400], "title": title, "credit": credit,
                    "licence": lic, "made": "found"}
    return best


def user_agent(contact: str = "") -> str:
    c = re.sub(r"[^\w@.:/+\-]", "", str(contact or ""))[:120]
    return f"{UA} ({c})" if c else UA


async def find(words: str, contact: str = "") -> dict | None:
    """A free drawing for these words, or None (offline, refused, nothing free, nothing matched)."""
    from . import netguard
    q = query(words)
    if not q:
        return None
    try:
        status, _ct, body = await netguard.read_capped(search_url(q), CAP, timeout=TIMEOUT,
                                                       headers={"User-Agent": user_agent(contact)})
        if status != 200:
            return None
        return pick(json.loads(body.decode("utf-8", "replace")), q)
    except Exception:
        return None


def words_for(scene: dict, part: dict | None = None) -> str:
    """What to search for: the brain's own words when it gave some, else the names."""
    if part is not None:
        return part.get("look_for") or f"{scene.get('subject') or ''} {part.get('name') or ''} diagram"
    return scene.get("look_for") or f"{scene.get('subject') or scene.get('title') or ''} cutaway diagram"


def draw_prompt(scene: dict, part: dict | None = None) -> str:
    what = part["name"] + " of " + (scene.get("subject") or "") if part else \
        (scene.get("subject") or scene.get("title") or "")
    return (f"Technical blueprint cutaway illustration of {what}: fine white line art on a deep "
            f"navy background, engineering drawing style, sectioned to show the inside, clean, "
            f"no text, no labels, no watermark")


IMG_CAP = 3 * 1024 * 1024
IMG_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


async def keep(store, pic: dict, contact: str = "") -> dict:
    """Download a found picture once and keep it as an asset, so the page, a phone's photographs
    and an offline machine all read this copy rather than asking Wikimedia every time. The
    credit and page stay with it. On any failure the picture keeps its Commons address."""
    from . import assets as assetmod, netguard
    if not pic or pic.get("asset") or not _clean_url(pic.get("url")):
        return pic
    try:
        status, ct, body = await netguard.read_capped(pic["url"], IMG_CAP, timeout=TIMEOUT,
                                                      headers={"User-Agent": user_agent(contact)})
        mime = (ct or "").split(";")[0].strip().lower()
        if status != 200 or mime not in IMG_TYPES or not body:
            return pic
        row = await assetmod.put_bytes(store, body, name="drawing" + {"image/png": ".png", "image/jpeg": ".jpg",
                                       "image/gif": ".gif", "image/webp": ".webp"}[mime], mime=mime,
                                       title=pic.get("title") or "drawing", origin_url=pic.get("page") or "",
                                       source=f"Wikimedia Commons · {pic.get('credit')} · {pic.get('licence')}")
    except Exception:
        return pic
    if not row:
        return pic
    return {**pic, "asset": row["id"], "url": f"/api/assets/{row['id']}/file", "remote": pic["url"]}
