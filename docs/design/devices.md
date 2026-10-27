# Devices: the hub is the Pi's nervous system

Status: discovery is built in 0.7.0, readings and the 90-day view in 0.7.1. The rest is the plan, in the order it will be built.

## What was asked

> The hub is the central nervous system for the Pi. Using the Pi we build the functionality on
> the Pi, which has two MCPs, get and set, the underlying functionality of the Pi. The getters and
> setters get values from the Pi and set values on the Pi, and the hub is responsible for doing so
> and executing the code, because Pis are Zeros. The complete hardware understanding of the Pi is
> the profile of the Pi: camera, sensors and so on. It has to be discovered every day, and the full
> inventory is with the hub. The hub can only use sensors where permission was granted, at the
> tool level or the agent level.

And:

- getters and setters stream between the Pi and the hub, encrypted, with the AI's request going
  along with them;
- the hub stores the readings under retention rules, next to the inventory, and can also read
  live through the getters and setters;
- a Pi's profile with its permissions can be saved as a provisioning profile, distributed to
  other Pis, and updated from the hub;
- installing anything on a Pi is rare and needs permission. Once one Pi needs it, the others on
  the profile get it too, but only at provisioning or when the profile is distributed;
- everything is logged on the Pi and on the hub, and nothing slips past the gate;
- in Devices, a sensor can be opened to see its readings over the last 90 days.

Decisions made:

1. A Pi can only use sensors it has been permitted. Something discovered but never tested and
   built with Bento can't be controlled, even though it's listed.
2. Every set is asked. If the person asks from the Pi itself, the approval goes to Telegram when
   it's connected, and to the hub otherwise, so it's checked twice.
3. Retention: numeric readings 90 days, images 7 days.

## The pieces

```
  Pi (a Zero)                                     Hub
  ───────────                                     ───
  hardware.py   discovery (reads only)   ───►     inventory: board + items, each <pi>/<id>
  pi-get        fixed, reviewed reader   ◄──┐     PDP: device.get / device.set per item
  pi-set        fixed, reviewed setter   ◄──┤     ledger, diary, Devices → Events
  triggers      rules from the profile      │     readings store (telemetry.db), retention
  ring buffer   while the hub is away       │     agents' tools: device_read, device_set,
                                            │                    device_history
  one link, Pi-dialled, mTLS, kept open ────┘     provisioning profiles, signed
```

The Pi runs no logic of its own. It runs a small, fixed program that reads and sets only what
its signed profile lists. Everything that decides anything (the agent, custom code, permissions,
stored readings) is on the hub.

## Step 1: discovery (built, 0.7.0)

`agentos/hardware.py`. The Pi lists what it has; the hub keeps it on the Pi's inventory row
(`inventory.json`, under the row's MAC) and Devices shows it. Every item has an id that is stable
on that machine, and `<machine>/<id>` is its inventory name: `raspberrypi/cpu.temp`,
`raspberrypi/gpio.17`, `raspberrypi/i2c.1.0x48`, `raspberrypi/camera.0`.

- Read once a day, at first sight, and within a minute of a change: the hello carries
  `hardware.quick()`, a hash of directory listings only, and a different hash makes the hub ask
  for the whole thing (`ties.hardware_due`).
- Discovery only reads. No bus scan (a probe that writes to a bus can upset a device), no camera
  opened, no pin set, nothing installed.
- The Pi answers only its own hub (`hardware.answer` → `zero.is_my_hub`). The hub reads what
  arrives field by field (`hardware.clean`).
- What changed (`hardware.diff`) is an event: found, gone, power. A reading is never a change.
- Both machines write a diary line and a `device.hardware` ledger row for each read.

What the first real Pi showed (a Pi 3 B+ on trixie): ten `/dev/video` nodes and no camera (they
are the codec and the image processor), 28 header pins all inputs, the HDMI I2C bus only (the
user I2C bus was off), and `throttled=0x50005`, under-voltage and throttled right now. That last
one is the kind of thing this is for.

## Step 2: one link, kept open

Today every request is its own connection, and the hub has to dial the Pi, whose address keeps
changing (the whole of `teamlink.relocate` exists for that). The link becomes one mTLS connection
that the Pi dials and keeps open:

- messages in both directions, numbered, so a reply finds its request and a stream its
  subscriber;
- the hub's requests to the Pi travel down the Pi's own connection, so the Pi's address, NAT and
  firewall stop mattering;
- a heartbeat every 20 seconds; reconnect with backoff (1, 2, 4 … 60 s);
- the first message says what each side supports (`caps`), so a missing feature is known up
  front, not found by an "unknown request" error;
- chat replies stream as they're written, so the kiosk speaks from the first sentence.

The old dial-out path stays for a Pi on an older version.

## Step 3: get and set

Two MCP servers on the Pi, `pi-get` and `pi-set`, part of Bento and fixed. Each tool is one item
in the inventory that the profile has made usable: `cpu.temp.read`, `gpio.17.read`,
`gpio.17.write`, `camera.0.snapshot`. An item that was discovered but isn't in the profile has no
tool at all.

On the hub each tool is `device.get` or `device.set` on the resource `device:<machine id>/<item
id>`, decided by the PDP like every other action:

- a grant can name a tool or app, or an agent (the lead, a specialist), which are the two levels
  that were asked for;
- no grant, no call. An item outside the inventory doesn't exist;
- `device.set` is in `ALWAYS_ASK`. A grant can let a get run silently; a set is asked every time;
- a set asked for at the Pi itself (somebody at its screen) goes to the owner's Telegram when it's
  connected, and to the hub's screens otherwise. Two checks: the person at the Pi, and the owner;
- every request to the Pi carries who asked, the reason in the agent's own words
  (`policy.said()`), and the hub's ledger row id. The Pi checks that the request comes from its
  hub and is in its signed profile, writes its own ledger row, and only then reads or sets.

The Pi's check means a hub that has been tricked still can't reach past the profile.

## Step 4: readings, triggers and the 90-day view

### How often a Pi reports

There are three kinds of report, and each has its own pace:

| Report | What | When |
|---|---|---|
| Inventory | what the Pi has (step 1) | daily, at first sight, and within a minute of a change |
| Heartbeat | alive, load, memory, CPU temperature, power flags, Wi-Fi signal | every 60 s, in the hello |
| Readings | the values of the sensors the profile names | sampled at the item's `sample` rate, sent in batches every `report` seconds |

Defaults, which each profile can change per item:

| Item | Sample | Report |
|---|---|---|
| temperatures, power, Wi-Fi | 10 s | 60 s |
| a 1-Wire or I2C sensor | 30 s | 60 s |
| a GPIO input | on each edge (interrupt), 50 ms debounce | at once |
| a camera | never on its own: on demand, or on a trigger | at once |

Sampling often and sending in batches keeps the radio and the SD card quiet. A batch carries,
per item, the samples or, when there are many, min, max, mean and last for each minute.

### Triggers: the Pi sends at once when something happens

A trigger is a rule in the profile, evaluated on the Pi (edge compute), so a Pi can act on what
it sees without waiting for the next batch:

- `above` / `below` a threshold, with hysteresis (fires at 70 °C, re-arms under 65 °C);
- `change` by more than a step, or any edge on a GPIO input;
- `rate`: rising or falling faster than a step per minute;
- `missing`: a sensor that stopped answering;
- the system's own: under-voltage, something plugged in or out, a reboot.

Each trigger has a cooldown, so a flapping pin is one event and a count, not a flood. An event
carries the reading, the rule and the time on the Pi. Events skip the batch, and while the hub is
away they are kept ahead of plain readings.

On the hub, an event is a line in Devices → Events, a ledger row, and a flow trigger
(`device_event`, beside `os_event`), so a mission can start on "the freezer is above −10 °C".

Messages are already shaped as a topic (`device/<machine>/<item>`) and a payload. When the
volume calls for a bus (MQTT, RabbitMQ or Kafka), the bus replaces the transport and nothing else.

### When the hub is away

The Pi keeps a ring buffer in memory per item (an hour at the default pace), written to disk
every few minutes rather than per sample, to spare the SD card. On reconnect it sends events
first, then readings oldest first. When the buffer is full it keeps per-minute summaries rather
than dropping minutes.

### Storage and retention

Readings go to `telemetry.db` beside the person's database, not inside it, so they can't bloat
the agent's database. One row per item per sample, filed under the Pi's section (its space).
Retention is per item, from the profile, enforced daily like `Store.prune`:

- numeric: raw for 7 days, per-minute for 30, per-hour to 90, then gone;
- images: 7 days;
- events: 90 days.

### Built in 0.7.1

The first cut rides the hello the hub already sends every minute, not the kept-open link (step 2):
the hello asks `readings_since` {boot, seq} and the Zero answers with what is newer
(`telemetry.Buffer`, `SEND_MAX` a time). Every item is sampled every 10 s and pins on a change;
per-item `sample`, `report` and triggers come with profiles. The buffer is in memory only for now.
Readings are kept per machine in the machine's home (`telemetry.db`), like the inventory, rather
than per account.

### The 90-day view

In Devices → Hardware every item with readings opens a chart: the last day, week, 30 days or 90
days, at the resolution that is stored for that range, with its events marked on the line and
min, max and mean for the range. The chart reads `/api/devices/readings?item=<machine>/<id>&range=`,
which `device_history` (the agents' tool) and `bento network readings` read too, so the three
can't disagree.

## Step 5: provisioning profiles

A profile is what a Pi is built to be, baked from one that works:

- the hardware it expects (by kind and id), and which items are usable (step 3);
- each item's sample, report and trigger rules (step 4), and retention;
- the permissions, as a description: the hub writes the real grants for each Pi it applies them
  to, as agent bundles already do;
- the system installs it needs (below);
- custom getters: small scripts for a sensor Bento doesn't know, written and tested on the hub,
  carried signed, run by `pi-get` and never by a shell.

A profile is versioned and signed by the hub's key. Distributing a new version shows what changes
first, then each Pi on it reconciles: it reports what it has, the hub answers with what it should
have, the Pi applies the difference and reports back. Devices shows each Pi as on this version,
updating, or failed and why. A Pi that doesn't match the hardware a profile expects is refused
that profile in a sentence.

## Installs on a Pi

An install happens only at provisioning or when a profile is distributed, never from a chat. A
Pi under development that needs one (`libuv`, say) proposes a profile change; a person on the hub
approves it; it's applied to that Pi and added to the profile, so the others follow on the next
distribution.

A Pi's sudo wants a password, and nobody types one after provisioning. So provisioning (where the
password is already in hand) installs one narrow root helper with a sudoers rule for it alone. It
accepts only plans signed by the hub, only from a closed list (apt package names, enabling I2C,
SPI, the camera or 1-Wire), and nothing else. Each run is a ledger row on both sides.

## Everything is logged on both sides

Every read, set, trigger, install and profile change is a ledger row on the Pi and on the hub, and
a line in each diary. The Pi's rows are its own record, so what happened on the Pi can be checked
on the Pi even if the hub's record is lost.

## Order of work

1. Discovery (0.7.0).
2. The link kept open, with `caps` and streamed chat.
3. Readings, `telemetry.db`, retention and the 90-day view in Devices (0.7.1). They ride the hello
   and need no new permission, because the hub already reads these numbers.
4. `pi-get` / `pi-set`, the two actions, set asked every time (Telegram from the Pi), and the
   agents' tools.
5. Triggers on the Pi and the `device_event` flow trigger.
6. Provisioning profiles, signed, with installs through the root helper.
