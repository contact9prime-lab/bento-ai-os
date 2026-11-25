"""Train on what your devices said: readings and the alarms that followed, as examples.

Asked for as "we need to be able to train on the data of IoT as well, which is a big use
case". A hub already keeps what every sensor read (telemetry.py, per minute for 30 days) and
the diary of which alarms were raised and when they ended (devboard.episodes). Put together
they are labelled examples nobody had to write: a window of readings, and what was true at
its end. A small model trained on them reads a window and says `normal`, names the alarm
that is on, or names the one that is coming, on the hub or on a Pi, for nothing a call.

    Readings from Cold room B. 30 minutes to Tue 14:20, one every 5 minutes, oldest first.
    temperature (°C): 4.1 4.2 4.6 5.3 6.1 7.0. now 7, rising by 2.9
    door (1 = on): 0 0 1 1 1 1. on now, on for 4 of 6
                                                →  coming: Cold room B is too warm

It only reads: the readings store and the diary lines it is handed. Which machines an
account may use is the caller's to decide (the server hands it that account's board, the
same list Devices draws). Kept free of HTTP and asyncio, so `bento train devices` builds the
same dataset with the server down.

What it is not: a forecast model. It is a language model reading numbers as text, which
suits "is this pattern one I have seen before an alarm" and not arithmetic. With no alarm in
the record there is nothing to learn the answer from, so the windows come without answers
and a teacher can write them from an instruction.
"""

import time

WIDTH_MIN = 30          # how much of the past a window shows
POINTS = 6              # values per line in a window: one every WIDTH_MIN / POINTS minutes
STRIDE_MIN = 10         # a new window this often
HORIZON_MIN = 15        # an alarm raised within this long after a window is "coming"
MAX_DAYS = 30           # the per-minute summaries are kept this long
MAX_ITEMS = 8           # lines in one window: more is a prompt nobody could read either
MAX_ROWS = 4000
CARRY_S = 900           # a value stands until the next one, up to this long (a steady sensor
                        # is stored once every five minutes, so a gap is not a missing reading)
NORMAL_PER_ALARM = 1    # quiet windows kept per window that is not quiet. At three to one a small
                        # model learned to say "normal" to everything: 16 of 20, and no alarm found


def machines() -> dict:
    """What the readings store holds, per machine key: {key: {item: {first, last, n}}}."""
    from . import telemetry
    out: dict = {}
    for m, i, lo, hi, n in telemetry.db().execute(
            "SELECT m, i, min(b), max(b), sum(n) FROM minute GROUP BY m, i"):
        out.setdefault(m, {})[i] = {"first": lo * 60, "last": hi * 60 + 59, "n": int(n or 0)}
    return out


def grid(key: str, items: list[str], start: float, end: float) -> dict:
    """{item: {minute: mean}} between two times, from the per-minute summaries."""
    from . import telemetry
    if not items:
        return {}
    marks = ",".join("?" * len(items))
    out: dict = {i: {} for i in items}
    for i, b, total, n in telemetry.db().execute(
            f"SELECT i, b, sum, n FROM minute WHERE m=? AND i IN ({marks}) AND b>=? AND b<=?",
            (key, *items, int(start // 60), int(end // 60))):
        if n:
            out[i][int(b)] = total / n
    return out


def _at(series: dict, minute: int):
    """The value standing at a minute: its own, or the last one before it within CARRY_S."""
    for back in range(0, CARRY_S // 60 + 1):
        v = series.get(minute - back)
        if v is not None:
            return v
    return None


def _num(v) -> str:
    if v is None:
        return "-"
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")


def render(label: str, end: float, lines: list[tuple], width: int = WIDTH_MIN, points: int = POINTS) -> str:
    """One window as the text a model reads. `lines` is [(name, unit, onoff, [values])]."""
    when = time.strftime("%a %H:%M", time.localtime(end))
    head = (f"Readings from {label}. {width} minutes to {when}, one every {width // points} minutes, "
            "oldest first.")
    body = []
    for name, unit, onoff, values in lines:
        tag = " (1 = on)" if onoff else f" ({unit})" if unit else ""
        body.append(f"{name}{tag}: " + " ".join(_num(v) for v in values) + _summary(values, onoff))
    return head + "\n" + "\n".join(body)


def _summary(values: list, onoff: bool) -> str:
    """The same line said the way a person would glance at it: where it is now and how far it
    moved, or how much of the window a contact was on. Worked out from the window alone, no
    threshold of ours in it. A 135M model shown only the six numbers fitted nothing, not even
    its own training examples."""
    seen = [v for v in values if v is not None]
    if not seen:
        return ""
    if onoff:
        on = sum(1 for v in seen if v >= 0.5)
        return f". {'on' if seen[-1] >= 0.5 else 'off'} now, on for {on} of {len(seen)}"
    move = seen[-1] - seen[0]
    way = "steady" if abs(move) < max(0.05 * abs(seen[0]), 0.2) else "rising" if move > 0 else "falling"
    return f". now {_num(seen[-1])}, {way}" + ("" if way == "steady" else f" by {_num(abs(move))}")


def answer(end: float, episodes: list[dict], horizon_s: float) -> str:
    """What was true at a window's end, from the alarm record: the alarm that was on, the one
    raised within the horizon after it, or `normal`. On beats coming."""
    coming = ""
    for e in episodes:
        since, ended = float(e.get("since") or 0), e.get("ended")
        if since <= end and (ended is None or float(ended) > end):
            return "alarm: " + str(e.get("text") or e.get("id") or "an alarm")
        if end < since <= end + horizon_s and not coming:
            coming = "coming: " + str(e.get("text") or e.get("id") or "an alarm")
    return coming or "normal"


def task_for(label: str, kinds: list[str]) -> str:
    said = ", ".join(sorted(set(kinds))) or "the alarm"
    return (f"You watch readings from {label}. Answer `normal`, or name what is wrong: "
            f"`alarm: …` when it is on now, `coming: …` when the readings show it is about to be. "
            f"The alarms you know: {said}.")


def build(key: str, label: str, things: list[dict], episodes: list[dict], items: list[str] | None = None,
          days: float = 7, width: int = WIDTH_MIN, stride: int = STRIDE_MIN, horizon: int = HORIZON_MIN,
          now: float | None = None) -> tuple[list[dict], dict]:
    """Examples from one machine's record. `things` is that machine's items as Devices names
    them ([{id, name, unit, onoff}]); `episodes` are ITS alarms (devboard.episodes, ended and
    open together). Returns (rows, how): `how` says what was read, how many windows had an
    alarm, and why the answers are empty when they are."""
    now = now or time.time()
    days = min(max(float(days or 7), 0.05), MAX_DAYS)
    width = min(max(int(width or WIDTH_MIN), POINTS), 240)
    stride = min(max(int(stride or STRIDE_MIN), 1), 240)
    horizon = min(max(int(horizon or HORIZON_MIN), 0), 240)
    have = machines().get(key, {})
    named = {t["id"]: t for t in things if isinstance(t, dict) and t.get("id")}
    chosen = [i for i in (items or list(named) or list(have)) if i in have][:MAX_ITEMS]
    how = {"machine": label, "items": chosen, "days": round(days, 2), "width": width, "horizon": horizon,
           "windows": 0, "alarms": 0, "coming": 0, "normal": 0, "kept": 0, "note": ""}
    if not chosen:
        how["note"] = "That machine has no readings kept yet."
        return [], how
    start = max(now - days * 86400, min(have[i]["first"] for i in chosen))
    g = grid(key, chosen, start - CARRY_S, now)
    step = max(1, width // POINTS)
    eps = [e for e in episodes if isinstance(e, dict)]
    loud, quiet = [], []
    first_min, last_min = int(start // 60) + width, int(now // 60)
    for m in range(first_min, last_min + 1, stride):
        lines, seen, total = [], 0, 0
        for i in chosen:
            vals = [_at(g[i], m - width + step * (k + 1)) for k in range(POINTS)]
            seen += sum(1 for v in vals if v is not None)
            total += POINTS
            t = named.get(i, {})
            lines.append((str(t.get("name") or i), str(t.get("unit") or ""), bool(t.get("onoff")), vals))
        if seen * 2 < total:            # a machine that was off: nothing to read in this window
            continue
        end = m * 60 + 59
        ans = answer(end, eps, horizon * 60)
        row = {"prompt": render(label, end, lines, width), "response": ans}
        (quiet if ans == "normal" else loud).append(row)
        how["windows"] += 1
        how["alarms" if ans.startswith("alarm") else "coming" if ans.startswith("coming") else "normal"] += 1
    if not loud:
        # nothing to learn an answer from: hand the windows over without one, evenly spread
        rows = _spread(quiet, min(len(quiet), 400))
        for r in rows:
            r["response"] = ""
        how["kept"] = len(rows)
        how["note"] = ("No alarm was raised on that machine in that time, so these windows have no answers. "
                       "A teacher can answer them from your instruction, or add an alarm rule in Devices and "
                       "come back when it has fired.")
        return rows, how
    rows = loud[-MAX_ROWS // 2:] + _spread(quiet, min(len(quiet), max(20, NORMAL_PER_ALARM * len(loud)), MAX_ROWS // 2))
    seen, out = set(), []
    for r in rows:                      # a steady machine repeats itself: the same window once
        k = r["prompt"].split("\n", 1)[1] + "|" + r["response"]
        if k not in seen:
            seen.add(k)
            out.append(r)
    how["kept"] = len(out)
    return out, how


def _spread(rows: list[dict], n: int) -> list[dict]:
    """`n` of the rows, evenly across the whole time rather than the first or the last."""
    if n <= 0 or not rows:
        return []
    if n >= len(rows):
        return list(rows)
    return [rows[int(k * len(rows) / n)] for k in range(n)]


def words(how: dict) -> str:
    """What was made, in a sentence, for every face."""
    if not how.get("kept"):
        return how.get("note") or "Nothing could be read."
    if how.get("note"):
        return f"{how['kept']} windows of {how['machine']}'s readings. " + how["note"]
    return (f"{how['kept']} examples from {how['machine']}: {how['alarms']} windows with an alarm on, "
            f"{how['coming']} with one coming within {how['horizon']} minutes, and quiet ones between "
            f"(of {how['windows']} windows over {how['days']:g} {'day' if how['days'] == 1 else 'days'}).")
