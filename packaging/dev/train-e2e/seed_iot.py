"""Seed a throwaway home with two days of a cold room's readings and its alarms.

    AGENTOS_HOME=/tmp/x python packaging/dev/train-e2e/seed_iot.py

For the Train live run's device step. The history is made up and says so: a sensor node the
hub holds ("Cold room B": a temperature and a door contact, on an address nothing answers),
a reading a minute for two days through telemetry.store (the door a Pi's samples come in by),
and the alarm lines the board would have written. A door left open warms the room a quarter
of a degree a minute; past 8 °C the alarm is raised, and cleared when it is back under. Short
openings that never reach 8 °C are in there too, so "door open" alone is not the answer.
"""
import json
import random
import time

from agentos import config as cfgmod
from agentos import espnodes, teamlink, telemetry
from agentos.memory import Store

TEMP, DOOR = "esp.coldroom.sensor.temperature", "esp.coldroom.binary_sensor.door"
ALARM = "Cold room B is too warm"


def main() -> dict:
    rng = random.Random(11)
    cfg = cfgmod.load_config()
    label = teamlink.machine_name(cfg)
    espnodes._path().write_text(json.dumps({"nodes": [{
        "name": "coldroom", "host": "127.0.0.1", "port": 9, "title": "Cold room B",
        "entities": [{"domain": "sensor", "name": "Temperature", "slug": "temperature", "unit": "°C"},
                     {"domain": "binary_sensor", "name": "Door", "slug": "door"}]}]}))
    now = time.time()
    start = now - 2 * 86400 + 120
    minutes = int((now - start) // 60) - 2
    opens = {}                                   # minute the door opens -> how long it stays open
    m = 40
    while m < minutes - 60:
        opens[m] = rng.choice([2, 3, 4, 26, 30, 34, 28])   # a quick visit, or left open
        m += rng.randint(70, 150)
    temp, open_left, rows, raised, alarms = 4.0, 0, [], None, []
    for k in range(minutes):
        ts = start + k * 60
        if k in opens:
            open_left = opens[k]
        door = 1 if open_left > 0 else 0
        open_left -= 1
        temp += (0.26 if door else (4.0 - temp) * 0.12) + rng.uniform(-0.05, 0.05)
        rows.append((ts, TEMP, round(temp, 2)))
        rows.append((ts + 1, DOOR, door))
        if temp > 8 and raised is None:
            raised = ts
        elif temp <= 8 and raised is not None:
            alarms.append((raised, ts))
            raised = None
    seq = 0
    for i in range(0, len(rows), 1200):
        batch = []
        for ts, item, v in rows[i:i + 1200]:
            seq += 1
            batch.append([seq, ts, item, v])
        telemetry.store(telemetry.HERE_KEY, {"rows": batch, "now": time.time(), "boot": "seed", "seq": seq})
    st = Store(cfgmod.DB_PATH)
    for n, (a, b) in enumerate(alarms):
        for at, ev, text in ((a, "alarm", f"Alarm on {label}: {ALARM}"), (b, "cleared", f"Cleared on {label}: {ALARM}")):
            mark = f"seed-{n}-{ev}"
            st.log("device", text, {"event": ev, "link": label, "alarm": "coldroom-warm", "level": "alarm",
                                    "item": TEMP, "source": "alarm", "whose": "", "seed": mark})
            # the diary stamps a line with now; these happened when the readings say they did
            st.db.execute("UPDATE logs SET created_at=? WHERE kind='device' AND meta LIKE ?", (at, f'%"{mark}"%'))
    st.db.commit()
    return {"machine": label, "readings": len(rows), "alarms": len(alarms), "long": sum(1 for v in opens.values() if v > 10),
            "short": sum(1 for v in opens.values() if v <= 10)}


if __name__ == "__main__":
    print(json.dumps(main()))
