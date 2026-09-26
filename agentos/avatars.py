"""The crew's faces: one character per agent, the same one everywhere it appears.

Every agent on this machine — your agent, each specialist in Missions, and you —
has a small pixel-art character: a skin tone, a hair style and colour, glasses or
not, trousers, and a shirt in a colour of its own. This module is the ONE place a
character exists. It generates a recipe the first time an agent is seen, keeps it
in the person's own database, and paints it; the Crew scene, Chat, Logs, the
Missions roster, approval cards and `bento avatar` all show what it painted.

Why one painter on the server, rather than each surface drawing its own:

- **Consistency is the feature.** The same specialist has to be the same person on
  the stage, beside its message in Chat, on its line in Logs and on its card in
  Missions. Two painters (the page's and the terminal's) are two definitions of a
  face, and the one that drifts is whichever is not being demoed. So there is one
  recipe, stored, and one painter, here; the page receives PNGs and the terminal
  receives half-block characters from the same pixel grid.
- **A character is PERSISTED, not re-derived.** It is generated from a hash of the
  agent's key on first sight and then stored, so an edit sticks and so the colour a
  specialist was given does not move when a colleague is added. Shirt colours are
  handed out at generation so no two live agents share one — the rule the stage
  needs — and your agent always wears the teal the desktop is branded in.
- **Per person, not per space.** Rows live in the user's own database (accounts are
  isolated by directory), and nothing here reads `space_id`: switching project
  never changes who your colleagues look like.
- **A recipe is a closed set.** Every field is an index into a palette or one of a
  few names, validated here. The editor, the agent's `set_avatar` tool and the CLI
  can choose from the set and nothing else — no arbitrary colour, no string that
  reaches the painter unchecked.

Skin and hair are literal palettes, and that is the one deliberate exception to the
immersive look's "every colour from the theme" rule: they are properties of PEOPLE,
not of a theme, and a skin tone recoloured by a theme would be wrong in a way that
matters. The shirt carries the agent's colour.

Nothing here is loaded from anywhere: no tileset, no sprite sheet, no licensed art.
Every coordinate below is this file's own drawing on its own 16x26 grid.

Kept free of HTTP and asyncio, like brief.py and jobs.py: `bento avatar` reads and
edits the same rows with the server down.
"""
from __future__ import annotations

import colorsys
import functools
import hashlib
import json
import random
import secrets
import struct
import time
import zlib

W, H = 16, 26                       # one frame of one character
FRAMES = 4                          # standing, blinking, wave (left arm), wave (right arm)
FACE = (1, 0, 15, 14)               # x0, y0, x1, y1 (exclusive) — the head, for avatars

AGENT, ME = "@agent", "@me"

# ---- the palettes, each a closed set with names people can say ------------------
SKINS = [("porcelain", (252, 224, 203)), ("light", (240, 199, 164)), ("tan", (214, 163, 122)),
         ("brown", (166, 114, 78)), ("deep", (110, 73, 50))]
HAIRS = [("black", (40, 33, 38)), ("dark brown", (80, 53, 36)), ("brown", (124, 84, 52)),
         ("blonde", (222, 184, 112)), ("auburn", (152, 66, 42)), ("grey", (172, 172, 180)),
         # dyed — rarer at generation, always available to choose
         ("pink", (226, 114, 162)), ("blue", (96, 132, 222)), ("mint", (118, 196, 160))]
NATURAL_HAIR = 6
STYLES = ["short", "long", "bun", "curly", "spiky", "bald", "bob"]
PANTS = [("denim", (60, 78, 120)), ("charcoal", (56, 58, 68)), ("khaki", (150, 128, 92)),
         ("navy", (42, 50, 84)), ("brown", (96, 70, 52))]
# The shirt colours. Hue degrees, named. Your agent's is teal.
HUES = [("amber", 34), ("coral", 12), ("teal", 172), ("violet", 264),
        ("green", 96), ("rose", 330), ("sky", 202), ("gold", 48)]
AGENT_HUE = 172
# What they wear over it. Your agent is the one in the BLAZER — the lead of the team,
# the one who hands out the work — and a specialist never is unless somebody picks it.
# A closed set like the rest, so the lead's look is a choice anyone can make or undo,
# never a second kind of character.
OUTFITS = ["shirt", "blazer", "hoodie"]
AGENT_OUTFIT = "blazer"

FIELDS = ("skin", "hair", "style", "pants", "glasses", "blush", "hue", "outfit")


# ---- recipes -------------------------------------------------------------------------

def _seed(key: str, salt: int = 0) -> int:
    return int(hashlib.sha256(f"{key}|{salt}".encode()).hexdigest()[:12], 16)


def generate(key: str, taken: set | None = None, salt: int = 0) -> dict:
    """A new character for `key`. Deterministic for (key, salt), so the same agent
    comes back as the same person on a fresh machine; `salt` is what a reroll turns.

    `taken` is the set of shirt hues other live agents already wear. The first free
    one from where this key's hash points is used, so a row of eight is eight
    colours — the hash alone collided like birthdays, and two specialists in one
    colour is the opposite of what a colour per specialist is for.
    """
    taken = set(taken or ())
    seed = _seed(key, salt)
    R = random.Random(seed)
    rec = {"skin": R.randrange(len(SKINS)),
           "style": R.choice(STYLES),
           "hair": (NATURAL_HAIR + R.randrange(len(HAIRS) - NATURAL_HAIR)) if R.random() < .12
           else R.randrange(NATURAL_HAIR),
           "pants": R.randrange(len(PANTS)),
           "glasses": R.random() < .3,
           "blush": R.random() < .45}
    rec["outfit"] = AGENT_OUTFIT if key == AGENT else ("hoodie" if R.random() < .2 else "shirt")
    if key == AGENT:
        rec["hue"] = AGENT_HUE
    else:
        hues = [h for _, h in HUES]
        start = seed % len(hues)
        free = [hues[(start + k) % len(hues)] for k in range(len(hues))]
        pick = next((h for h in free if h not in taken and h != AGENT_HUE), None)
        rec["hue"] = pick if pick is not None else free[0]
    return rec


def _index(value, table: list, what: str) -> int:
    """A palette entry by index or by name, or a sentence naming the choices."""
    names = [n for n, _ in table]
    if isinstance(value, bool):
        raise ValueError(f"{what} must be one of: {', '.join(names)}")
    if isinstance(value, int):
        if 0 <= value < len(table):
            return value
    elif isinstance(value, str):
        # "dark-brown" and "dark_brown" are how a name gets typed on a command line
        v = " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())
        if v in names:
            return names.index(v)
        if v.isdigit() and int(v) < len(table):
            return int(v)
    raise ValueError(f"{what} must be one of: {', '.join(names)}")


def _flag(value, what: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("yes", "true", "on", "1", "no", "false", "off", "0"):
        return value.strip().lower() in ("yes", "true", "on", "1")
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{what} is yes or no")


def validate(patch: dict) -> dict:
    """The only way a change reaches a recipe. Unknown fields and values outside the
    set are refused with a sentence that says what IS allowed — the agent reads this
    as its tool result and can correct itself."""
    if not isinstance(patch, dict) or not patch:
        raise ValueError(f"say what to change: {', '.join(FIELDS)}")
    out = {}
    for k, v in patch.items():
        if k == "skin":
            out[k] = _index(v, SKINS, "skin")
        elif k == "hair":
            out[k] = _index(v, HAIRS, "hair")
        elif k == "pants":
            out[k] = _index(v, PANTS, "pants")
        elif k == "style":
            s = str(v).strip().lower()
            if s not in STYLES:
                raise ValueError(f"style must be one of: {', '.join(STYLES)}")
            out[k] = s
        elif k in ("glasses", "blush"):
            out[k] = _flag(v, k)
        elif k == "outfit":
            o = str(v).strip().lower()
            if o not in OUTFITS:
                raise ValueError(f"outfit must be one of: {', '.join(OUTFITS)}")
            out[k] = o
        elif k in ("hue", "shirt"):
            names = {n: h for n, h in HUES}
            hues = list(names.values())
            if isinstance(v, str) and v.strip().lower() in names:
                out["hue"] = names[v.strip().lower()]
            elif isinstance(v, int) and not isinstance(v, bool) and v in hues:
                out["hue"] = v
            else:
                raise ValueError(f"shirt must be one of: {', '.join(names)}")
        else:
            raise ValueError(f"'{k}' is not part of a character — use: "
                             f"{', '.join(f for f in FIELDS if f != 'hue')}, shirt")
    return out


def clean(rec: dict) -> dict:
    """A stored recipe made safe to paint: anything missing or out of range falls
    back to a sane value rather than failing to draw a face."""
    rec = dict(rec or {})
    out = {"skin": rec.get("skin", 1), "hair": rec.get("hair", 0), "style": rec.get("style", "short"),
           "pants": rec.get("pants", 0), "glasses": bool(rec.get("glasses")),
           "blush": bool(rec.get("blush")), "hue": rec.get("hue", AGENT_HUE),
           "outfit": rec.get("outfit", "shirt")}
    try:
        return {**out, **validate(out)}
    except ValueError:
        return {"skin": 1, "hair": 0, "style": "short", "pants": 0,
                "glasses": False, "blush": False, "hue": AGENT_HUE, "outfit": "shirt"}


def describe(rec: dict) -> str:
    """The character in words — the alt text on every image, and what the terminal
    prints when it cannot draw colour."""
    r = clean(rec)
    hair = HAIRS[r["hair"]][0]
    style = {"short": "short", "long": "long", "bun": "a bun of", "curly": "curly",
             "spiky": "spiky", "bald": "bald with", "bob": "a bob of"}[r["style"]]
    shirt = next((n for n, h in HUES if h == r["hue"]), "")
    bits = [f"{SKINS[r['skin']][0]} skin", f"{style} {hair} hair".replace("bald with ", "bald, a little ")]
    if r["glasses"]:
        bits.append("glasses")
    top = {"shirt": "shirt", "blazer": "blazer over a white shirt and tie",
           "hoodie": "hoodie"}[r["outfit"]]
    bits.append(f"{'an' if shirt[:1] in 'aeiou' else 'a'} {shirt} {top}")
    bits.append(f"{PANTS[r['pants']][0]} trousers")
    return ", ".join(bits)


# ---- who has a character --------------------------------------------------------------

def principals(store, cfg: dict) -> list[dict]:
    """Everybody who gets a face: your agent, you, and every specialist that exists.
    A character is never invented for somebody who is not there."""
    out = [{"key": AGENT, "label": (cfg or {}).get("agent_name") or "Aria", "kind": "agent"},
           {"key": ME, "label": "you", "kind": "me"}]
    try:
        for s in store.list_subagents():
            if s.get("name"):
                out.append({"key": s["name"], "label": s["name"], "kind": "specialist"})
    except Exception:
        pass
    return out


def ensure(store, cfg: dict) -> list[dict]:
    """Every principal with its character, generating and storing any that are new.

    Called whenever the roster is read, so a specialist created by any door — the
    editor, the agent's own `create_subagent`, a forked bundle — has a face the first
    time anything looks, without each of those doors having to remember to make one.
    """
    people = principals(store, cfg)
    rows = {r["key"]: r for r in store.avatar_all()}
    # Your agent and you are generated with a salt of THIS install's own. Unsalted, the
    # hash of '@agent' is the same on every machine, so every Bento's agent was the same
    # person — invisible alone, and the whole problem once two teams are linked and
    # their leads stand side by side. A default nobody touched is re-drawn once, in the
    # same colour and outfit; one somebody edited no longer matches and is left alone.
    for key in (AGENT, ME):
        row = rows.get(key)
        if row and _is_untouched_default(key, row.get("recipe") or {}):
            fresh = generate(key, salt=secrets.randbelow(1 << 24) + 1)
            keep = {k: row["recipe"][k] for k in ("hue", "outfit") if k in row["recipe"]}
            store.avatar_put(key, {**fresh, **keep})
            rows[key] = store.avatar_get(key)
    # Your agent's character was stored before it had an outfit. It is the lead, so
    # it is put in the blazer ONCE — the key is missing, which is how this knows
    # nobody chose otherwise; a person who later picks a shirt keeps the shirt.
    row = rows.get(AGENT)
    if row and "outfit" not in (row.get("recipe") or {}):
        store.avatar_put(AGENT, {**row["recipe"], "outfit": AGENT_OUTFIT})
        rows[AGENT] = store.avatar_get(AGENT)
    taken = {rows[p["key"]]["recipe"].get("hue") for p in people if p["key"] in rows}
    for p in people:
        if p["key"] not in rows:
            rec = generate(p["key"], taken,
                           salt=secrets.randbelow(1 << 24) + 1 if p["key"] in (AGENT, ME) else 0)
            taken.add(rec["hue"])
            store.avatar_put(p["key"], rec)
            rows[p["key"]] = store.avatar_get(p["key"])
    for p in people:
        row = rows[p["key"]]
        p["recipe"] = clean(row["recipe"])
        p["v"] = int((row.get("updated_at") or 0) * 1000)
        p["about"] = describe(p["recipe"])
    return people


_LOOK = ("skin", "hair", "style", "pants", "glasses", "blush")


def _is_untouched_default(key: str, rec: dict) -> bool:
    base = generate(key)
    return all(rec.get(k) == base.get(k) for k in _LOOK)


def recipe_for(store, key: str) -> dict:
    """The stored character, or — for a key nobody has stored — the one it WOULD be
    generated as, without storing it. A log line from a principal that no longer
    exists still gets a stable face, and the table does not grow for it."""
    row = store.avatar_get(key) if key else None
    return clean(row["recipe"]) if row else clean(generate(key or "?"))


def is_known(store, cfg: dict, key: str) -> bool:
    return any(p["key"] == key for p in principals(store, cfg))


def update(store, cfg: dict, key: str, patch: dict) -> dict:
    """Change part of a character. Refuses a key that is nobody on this machine."""
    if not is_known(store, cfg, key):
        raise KeyError(key)
    ensure(store, cfg)
    rec = {**recipe_for(store, key), **validate(patch)}
    store.avatar_put(key, rec)
    return clean(rec)


def reroll(store, cfg: dict, key: str) -> dict:
    """A new look, SAME colour and outfit: the shirt is how the stage and the chat tell
    this specialist from the others, and a reroll that moved it would reshuffle everyone."""
    if not is_known(store, cfg, key):
        raise KeyError(key)
    ensure(store, cfg)
    cur = recipe_for(store, key)
    rec = generate(key, salt=int(time.time() * 1000) & 0xFFFFFF)
    rec["hue"] = cur["hue"]
    rec["outfit"] = cur["outfit"]           # a new face, never a demotion: the lead stays the lead
    store.avatar_put(key, rec)
    return clean(rec)


# ---- the painter -------------------------------------------------------------------------

def _hsl(h: float, s: float, l: float) -> tuple:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def _tone(c: tuple, m: float) -> tuple:
    return tuple(min(255, round(v * m)) for v in c)


def _lum(c) -> float:
    """Perceived brightness, 0-255 (Rec. 601 weights) — enough to tell light from deep."""
    return .299 * c[0] + .587 * c[1] + .114 * c[2]

def paint(rec: dict, frame: int = 0) -> bytearray:
    """One frame of one character as RGBA bytes, W x H. Frames: 0 standing, 1
    blinking, 2 and 3 the two halves of a working wave (one arm up, then the other)."""
    r = clean(rec)
    buf = bytearray(W * H * 4)

    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H:
            i = (y * W + x) * 4
            buf[i:i + 4] = bytes((c[0], c[1], c[2], 255))

    def clr(x, y):
        if 0 <= x < W and 0 <= y < H:
            buf[(y * W + x) * 4 + 3] = 0

    def box(x0, y0, x1, y1, c):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                put(x, y, c)

    sk = SKINS[r["skin"]][1]
    skH, skS = _tone(sk, 1.07), _tone(sk, .8)
    # A mouth is a LIP colour — warmer and redder than the face — never a darker
    # skin: skin at 55% brightness is grey-brown, and two pixels of it under a nose
    # read as a goatee on every light-skinned figure in a row.
    mouth = (round(sk[0] * .78), round(sk[1] * .42), round(sk[2] * .42))
    sh = _hsl(r["hue"], .60, .52)
    if r["outfit"] == "blazer":
        # a jacket is DEEPER than a shirt in the same colour; at shirt brightness the
        # first cut read as a shirt with a stain on it
        sh = _hsl(r["hue"], .52, .34)
    shH, shS = _tone(sh, 1.3), _tone(sh, .7)
    pa = PANTS[r["pants"]][1]
    paS = _tone(pa, .72)
    hr = HAIRS[r["hair"]][1]
    hrH, hrS = _tone(hr, 1.35), _tone(hr, .7)
    # the outline: a deep shade of the character's own shirt colour, never one
    # shared black — eight characters sharing one ink look printed, not drawn
    ln = _hsl(r["hue"], .28, .13)

    # legs, belt and shoes
    box(5, 19, 7, 22, pa); box(8, 19, 10, 22, pa); box(5, 19, 10, 19, paS)
    box(7, 20, 7, 22, paS); box(10, 20, 10, 22, paS)
    box(4, 23, 7, 24, ln); box(8, 23, 11, 24, ln)
    put(5, 23, _tone(ln, 2.2)); put(9, 23, _tone(ln, 2.2))
    # torso: a lit left edge, a shaded right one, a collar
    box(4, 13, 11, 18, sh); box(5, 14, 5, 17, shH); box(11, 14, 11, 18, shS); box(4, 18, 11, 18, shS)
    box(6, 13, 9, 13, shH); put(7, 13, skS); put(8, 13, skS)
    box(7, 12, 8, 12, skS)                                  # neck
    outfit = r["outfit"]
    if outfit == "blazer":
        # the lead: a jacket in their colour, open over a white shirt, a tie in the
        # complementary colour so it reads against the jacket, and one gold pin. The
        # face crop ends at the collar, so every chat bubble shows who leads.
        white, gold = (242, 244, 248), (240, 194, 72)
        tie = _hsl((r["hue"] + 180) % 360, .62, .46)
        box(6, 13, 9, 13, white)
        put(6, 14, white); put(9, 14, white); put(7, 14, tie); put(8, 14, tie)
        put(6, 15, shH); put(9, 15, shS); put(7, 15, tie); put(8, 15, tie)
        put(7, 16, tie); put(8, 16, _tone(tie, .7))
        put(10, 14, gold)
        put(8, 18, _tone(sh, 1.6))                          # a button
    elif outfit == "hoodie":
        # a hood folded behind the neck and two drawstrings
        box(5, 12, 6, 12, shS); box(9, 12, 10, 12, shS); box(6, 13, 9, 13, shS)
        put(7, 13, skS); put(8, 13, skS)
        put(6, 14, (236, 236, 240)); put(6, 15, (236, 236, 240))
        put(9, 14, (236, 236, 240)); put(9, 15, (236, 236, 240))
        box(5, 17, 10, 17, shS)                              # the pocket seam

    def arm_down(x0):
        box(x0, 13, x0 + 1, 16, sh)
        put(x0 + (0 if x0 < 8 else 1), 14, shH if x0 < 8 else shS)
        box(x0, 17, x0 + 1, 17, sk)                         # the hand

    def arm_up(x0):
        box(x0, 9, x0 + 1, 13, sh)
        box(x0, 8, x0 + 1, 8, sk)                           # the hand, raised

    if frame == 2:
        arm_up(2); arm_down(12)
    elif frame == 3:
        arm_down(2); arm_up(12)
    else:
        arm_down(2); arm_down(12)

    # head: rounded, lit from the left, with ears; the jaw shade stops short of the
    # sides, because a full-width row read as a beard on darker skin
    box(4, 3, 11, 11, sk)
    for x, y in ((4, 3), (11, 3), (4, 11), (11, 11)):
        clr(x, y)
    box(5, 5, 5, 9, skH); box(11, 4, 11, 10, skS); box(6, 11, 9, 11, skS)
    put(3, 7, sk); put(3, 8, skS); put(12, 7, sk); put(12, 8, skS)

    # the face: two eyes (never one mark in the middle — that is what made the very
    # first version of these read as frightening), a mouth that opens while working
    # The eye ink is chosen against the SKIN. The outline shade sits at 13% lightness,
    # which is plenty on porcelain and nearly nothing on deep skin: the first deep-
    # skinned character came out with eyes you had to know were there. On the darker
    # skins the eye is near-black with one lit pixel, which is how a pixel eye reads
    # as looking back at you rather than as a hole.
    deep = _lum(sk) < 130
    eye = (16, 12, 18) if deep else ln
    if frame == 1:
        put(6, 8, eye); put(9, 8, eye)
    else:
        put(6, 7, eye); put(6, 8, eye); put(9, 7, eye); put(9, 8, eye)
        if deep and not r["glasses"]:
            put(6, 7, (236, 232, 228)); put(9, 7, (236, 232, 228))
    if frame >= 2:
        box(7, 10, 8, 10, ln)
    else:
        put(7, 10, mouth); put(8, 10, mouth)
    if r["blush"]:
        put(5, 9, (232, 136, 136)); put(10, 9, (232, 136, 136))
    # Glasses: a rim over each eye and a pale lens beside it. A full frame drawn in
    # the line colour, beside a one-pixel eye, filled the whole eye band — and a
    # dark-skinned character in glasses came out with no face at all.
    if r["glasses"]:
        lens = (214, 226, 236)
        box(5, 6, 7, 6, ln); box(8, 6, 10, 6, ln)
        for x in (5, 7, 8, 10):
            put(x, 7, lens)

    # hair, by style
    def cap():
        box(4, 2, 11, 4, hr); clr(4, 2); clr(11, 2)
        put(4, 5, hr); put(11, 5, hr); box(6, 2, 8, 2, hrH); put(10, 4, hrS)

    st = r["style"]
    if st == "short":
        cap()
    elif st == "long":
        cap(); box(3, 4, 4, 13, hr); box(11, 4, 12, 13, hr)
        box(3, 12, 3, 13, hrS); box(12, 12, 12, 13, hrS)
    elif st == "bob":
        cap(); box(3, 4, 4, 10, hr); box(11, 4, 12, 10, hr); box(5, 4, 10, 4, hr)
        box(3, 10, 4, 10, hrS); box(11, 10, 12, 10, hrS)
    elif st == "bun":
        cap(); box(6, 1, 9, 2, hr); put(7, 1, hrH)
    elif st == "curly":
        box(3, 2, 12, 4, hr); clr(3, 2); clr(12, 2)
        for x in (4, 7, 10):
            put(x, 1, hr); put(x + 1, 1, hr)
        box(3, 5, 3, 7, hr); box(12, 5, 12, 7, hr)
        for x in (5, 8, 11):
            put(x, 3, hrH)
    elif st == "spiky":
        box(4, 3, 11, 4, hr)
        for x in (4, 6, 8, 10):
            put(x, 2, hr); put(x + 1, 1, hr)
        put(5, 1, hrH); put(9, 1, hrH); put(4, 5, hr); put(11, 5, hr)
    elif st == "bald":
        box(4, 6, 4, 8, hr); box(11, 6, 11, 8, hr)
        put(6, 4, _tone(sk, 1.18)); put(7, 4, _tone(sk, 1.18))

    # THE OUTLINE: every empty pixel touching the character becomes the line colour.
    # One pass over the finished figure, so a new hair style needs no outline of its
    # own and cannot forget one.
    alpha = [buf[i * 4 + 3] for i in range(W * H)]
    for y in range(H):
        for x in range(W):
            if alpha[y * W + x]:
                continue
            if ((x > 0 and alpha[y * W + x - 1]) or (x < W - 1 and alpha[y * W + x + 1])
                    or (y > 0 and alpha[(y - 1) * W + x]) or (y < H - 1 and alpha[(y + 1) * W + x])):
                put(x, y, ln)
    return buf


def image(rec: dict, frame: int = 0, crop: str = "", sheet: bool = False,
          scale: int = 1) -> tuple[int, int, bytes]:
    """(width, height, rgba) — a frame, the face crop, or all frames side by side,
    scaled up by a whole number (nearest neighbour: it is pixel art)."""
    if sheet:
        frames = [paint(rec, f) for f in range(FRAMES)]
        w, h = W * FRAMES, H
        rows = bytearray()
        for y in range(H):
            for fb in frames:
                rows += fb[y * W * 4:(y + 1) * W * 4]
        px = bytes(rows)
    else:
        px = bytes(paint(rec, max(0, min(FRAMES - 1, int(frame)))))
        w, h = W, H
        if crop == "face":
            x0, y0, x1, y1 = FACE
            px = b"".join(px[(y * W + x0) * 4:(y * W + x1) * 4] for y in range(y0, y1))
            w, h = x1 - x0, y1 - y0
    scale = max(1, min(12, int(scale or 1)))
    if scale > 1:
        out = bytearray()
        for y in range(h):
            line = bytearray()
            for x in range(w):
                line += px[(y * w + x) * 4:(y * w + x) * 4 + 4] * scale
            out += bytes(line) * scale
        px, w, h = bytes(out), w * scale, h * scale
    return w, h, px


def png(w: int, h: int, rgba: bytes) -> bytes:
    """A PNG from RGBA bytes, with nothing but the standard library."""
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


@functools.lru_cache(maxsize=512)
def _png_cached(recipe_json: str, frame: int, crop: str, sheet: bool, scale: int) -> bytes:
    w, h, px = image(json.loads(recipe_json), frame=frame, crop=crop, sheet=sheet, scale=scale)
    return png(w, h, px)


def png_of(rec: dict, frame: int = 0, crop: str = "", sheet: bool = False, scale: int = 1) -> bytes:
    """A character as PNG bytes. Cached on the RECIPE, not on the key: an edit is a
    new recipe and so a new entry, and nothing has to remember to invalidate."""
    return _png_cached(as_json(rec), max(0, min(FRAMES - 1, int(frame or 0))),
                       "face" if crop == "face" else "", bool(sheet), max(1, min(12, int(scale or 1))))


def terminal(rec: dict, crop: str = "", frame: int = 0) -> list[str]:
    """The same pixels, for a terminal: two pixel rows per line with the upper-half
    block, foreground the top pixel and background the bottom one. It is the TUI's
    face of this feature — the grid is the one the page's PNG is made from, so the
    character on an SSH session is the same person as the one on the desktop."""
    w, h, px = image(rec, frame=frame, crop=crop)
    lines = []
    for y in range(0, h, 2):
        s = ""
        for x in range(w):
            top = px[(y * w + x) * 4:(y * w + x) * 4 + 4]
            bot = px[((y + 1) * w + x) * 4:((y + 1) * w + x) * 4 + 4] if y + 1 < h else b"\0\0\0\0"
            if top[3] and bot[3]:
                s += f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m\x1b[48;2;{bot[0]};{bot[1]};{bot[2]}m▀\x1b[0m"
            elif top[3]:
                s += f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m▀\x1b[0m"
            elif bot[3]:
                s += f"\x1b[38;2;{bot[0]};{bot[1]};{bot[2]}m▄\x1b[0m"
            else:
                s += " "
        lines.append(s.rstrip() if not s.strip() else s)
    return lines


# ---- designing one from a description -------------------------------------------------
#
# "A calm senior engineer with a grey bun and glasses, in a navy blazer" -> a recipe.
# The model picks, the closed set decides: every field it returns goes through
# validate() one at a time, so a wrong one is dropped and named rather than failing the
# whole design, and nothing outside the palettes can ever be painted. With no model to
# ask, `from_words` matches the palette's own names in what was typed — and the result
# SAYS it matched words, because "designed by AI" when it was not would be a lie.

DESIGN_FIELDS = ("skin", "hair", "style", "shirt", "outfit", "pants", "glasses", "blush")
_SYNONYMS = {"purple": "violet", "blue": "sky", "yellow": "gold", "orange": "amber",
             "red": "coral", "pink": "rose", "navy": "sky", "suit": "blazer", "jacket": "blazer",
             "hood": "hoodie", "sweatshirt": "hoodie", "tee": "shirt", "t-shirt": "shirt",
             "jeans": "denim", "gray": "grey", "silver": "grey", "white": "grey", "blond": "blonde", "ginger": "auburn",
             "brunette": "dark brown", "spectacles": "glasses", "specs": "glasses",
             "ponytail": "bun", "afro": "curly", "shaved": "bald", "rosy": "blush"}


def design_prompt(description: str, who: str = "") -> tuple[str, str]:
    """(system, prompt) for a model: the whole palette, and JSON only."""
    pal = palette()
    system = ("You design small pixel-art characters by choosing from FIXED options. Answer "
              "ONLY with one compact JSON object and no prose. Use only the values listed; "
              "leave out any field the description does not suggest.")
    prompt = (f"Design {who or 'this character'} from this description:\n\"{description}\"\n\n"
              f"Fields and their ONLY allowed values:\n"
              f"- skin: {', '.join(x['name'] for x in pal['skin'])}\n"
              f"- hair (colour): {', '.join(x['name'] for x in pal['hair'])}\n"
              f"- style (hair): {', '.join(pal['style'])}\n"
              f"- shirt (the colour they wear): {', '.join(x['name'] for x in pal['shirt'])}\n"
              f"- outfit: {', '.join(pal['outfit'])} (blazer = the lead, the one in charge)\n"
              f"- pants: {', '.join(x['name'] for x in pal['pants'])}\n"
              f"- glasses: true or false\n- blush: true or false\n"
              f'Also add "note": one short sentence on the look you chose.\n'
              f'Example: {{"hair": "grey", "style": "bun", "glasses": true, "outfit": "blazer", '
              f'"shirt": "violet", "note": "a calm lead with a grey bun"}}')
    return system, prompt


def read_design(raw: str) -> tuple[dict, list, str]:
    """A model's answer -> (patch, dropped, note). Each field is validated ALONE, so one
    invented value costs that field, not the design."""
    import re as _re
    m = _re.search(r"\{.*\}", raw or "", _re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    patch, dropped = {}, []
    for k in DESIGN_FIELDS:
        if k not in d or d[k] in (None, ""):
            continue
        v = d[k]
        if isinstance(v, str):
            v = _SYNONYMS.get(v.strip().lower(), v)
        try:
            patch.update(validate({k: v}))
        except ValueError:
            dropped.append(f"{k}={str(d[k])[:20]}")
    note = str(d.get("note") or "")[:140] if isinstance(d, dict) else ""
    return patch, dropped, note


def from_words(description: str) -> dict:
    """The palette's own names, found in what was typed. Crude on purpose: it only
    ever picks something that was literally said (or a common synonym of it)."""
    import re as _re
    t = " " + _re.sub(r"[^a-z\- ]", " ", (description or "").lower()) + " "
    for a, b in _SYNONYMS.items():
        t = t.replace(f" {a} ", f" {b} ")
    words = t.split()
    patch: dict = {}

    def near(i, nouns):          # "<value> hair" / "<value> skin" / "<value> shirt"
        return i + 1 < len(words) and words[i + 1] in nouns

    names2 = {n: n for n, _ in HAIRS}
    for i, w in enumerate(words):
        two = f"{w} {words[i + 1]}" if i + 1 < len(words) else ""
        if two in names2 and i + 2 < len(words) and words[i + 2] in ("hair", "haired"):
            patch["hair"] = two
        elif w in names2 and near(i, ("hair", "haired", "bun", "bob", "curls")):
            patch.setdefault("hair", w)
        if w in {n for n, _ in SKINS} and near(i, ("skin", "skinned")):
            patch["skin"] = w
        if w in {n for n, _ in HUES} and near(i, ("shirt", "blazer", "hoodie", "top", "jumper")):
            patch["shirt"] = w
        if w in {n for n, _ in PANTS} and near(i, ("trousers", "pants", "slacks")):
            patch["pants"] = w
    if "denim" in words:
        patch.setdefault("pants", "denim")
    for st in STYLES:
        if st in words:
            patch.setdefault("style", st)
    for o in OUTFITS:
        if o in words:
            patch["outfit"] = o
    if "glasses" in words:
        patch["glasses"] = not _re.search(r"\b(no|without)\s+glasses", t)
    if "blush" in words:
        patch["blush"] = True
    if "shirt" not in patch:     # a bare colour word is the shirt ("in violet")
        for n, _ in HUES:
            if n in words:
                patch["shirt"] = n
                break
    out = {}
    for k, v in patch.items():
        try:
            out.update(validate({k: v}))
        except ValueError:
            pass
    return out


def palette() -> dict:
    """What the editor offers — the same closed sets validate() accepts."""
    return {"skin": [{"i": i, "name": n, "rgb": list(c)} for i, (n, c) in enumerate(SKINS)],
            "hair": [{"i": i, "name": n, "rgb": list(c)} for i, (n, c) in enumerate(HAIRS)],
            "pants": [{"i": i, "name": n, "rgb": list(c)} for i, (n, c) in enumerate(PANTS)],
            "style": list(STYLES),
            "outfit": list(OUTFITS),
            "shirt": [{"name": n, "hue": h, "rgb": list(_hsl(h, .60, .52))} for n, h in HUES]}


def as_json(rec: dict) -> str:
    return json.dumps(clean(rec), sort_keys=True)
