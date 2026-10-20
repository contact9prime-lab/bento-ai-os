# A Zero: one line on a Pi, run from your hub

A Zero is a small machine (a Pi Zero, any Raspberry Pi, an old laptop) that you set up by
pasting one line. It installs Bento in Light mode, joins your Tailscale network if you want it
to, finds your main machine (the **hub**) and is set up from there with nobody at it. After
that, what you ask it is worked on by the hub's team, and any file they make comes back to it.

![Settings → Team & Communications on the hub: the one line, and the standard setup](screenshots/zero-make-a-zero.png)

## Make one

1. On the hub, open *Settings → Team & Communications → New machines → Make a Zero*.
2. If the Zero won't be on the same network as the hub, paste a Tailscale auth key
   ([make one here](https://login.tailscale.com/admin/settings/keys)). Leave it empty when they
   share a network.
3. Press **Show the line**, then **Copy**, and paste it on the Pi:

```sh
curl -fsSL https://raw.githubusercontent.com/<you>/bento-ai-os/master/install.sh \
  | sh -s -- --zero --enroll=bento-enroll-1.… --hub=100.101.102.103,192.168.1.4 \
             --tailscale-key=tskey-auth-…
```

That's all. A minute or two later the Pi is on the hub's list as *set up*, and you get a
toast saying it was heard over Tailscale or on your network.

From a terminal on the hub, the same thing:

```sh
bento pool zero                                  # the line, with this hub's addresses
bento pool zero --tailscale-key tskey-auth-… 100.101.102.103
bento pool standard                              # what every machine set up from here gets
bento pool standard set profile.json             # change it
bento pool hub 100.101.102.103                   # on a Zero: where to announce itself
```

![bento pool zero and bento pool standard on the hub](screenshots/zero-terminal.png)

## What the line does on the Pi

- Installs Bento in Light mode and asks nothing. `--zero` answers every question for this one
  install; it doesn't install the optional extras.
- With a Tailscale key, installs Tailscale and joins your tailnet as `bento-<hostname>`. The key
  is used once there. The hub puts it in the line and doesn't keep it anywhere.
- Writes the hub's addresses (`bento pool hub`), keeps the hub's automatic enrolment key, and
  starts Bento waiting to be set up.

## How the hub hears it

A waiting machine announces itself on its own network. Tailscale carries no broadcasts, so a
Zero also sends its announcement straight to each hub address in the line. The hub writes down
which way it arrived, read from the address the announcement came from: *over Tailscale* for an
address in Tailscale's range, *on your network* otherwise.

The Zero carries the hub's automatic key, so the hub sets it up the moment it hears it: no code
to type, no button to press. That is still a ledger row on both machines and a toast on the
hub.

## The standard setup

Every machine set up from the hub gets the same setup, with no questions:

| | |
|---|---|
| Where work runs | *on this hub* (the default for a Zero) or *on the machine* |
| Light mode, kiosk, agent's name | as you set them |
| Its agents | copies of the hub's agents you add, each with its executor |

Add one of your agents under **Its agents** and every machine set up from here gets a copy.
Only the tools a company department may have travel with it (no shell, push or send), and its
executor is copied by value. A key's own setup, and what you choose when enabling by hand, go on
top of the standard one.

## When the hub does the work

With *work runs on this hub*, the Zero keeps no agents of its own (beyond the ones the standard
setup gives it) and thinks with the hub's brain. Its lead hands anything more than a short answer
to the hub's lead, and the hub's team works it.

![On the Zero: the task went to the hub, and the file came back](screenshots/zero-file-came-back.png)

Files come back with the answer. Anything the hub's answer names by its full path, inside the
hub's workspace, travels back and lands in the Zero's workspace under `from-<hub>/`. Up to 8
files, 1.5 MB each and 2.5 MB in all; what's too big is named in the answer and stays on the
hub. Each time, the hub writes a `link.files` row.

## What keeps it safe

- **The hub only hears a Zero, it never trusts one.** An announcement is a stranger's words,
  read field by field. A Zero is set up automatically only if it proves it holds the hub's key,
  and the hub proves it back.
- **A task from a Zero is untrusted on the hub,** as every linked team's question is. The
  hand-over to the hub's specialists carries that mark, so a step that changes something waits
  for a person.
- **Two things are decided ahead of time, when the hub sets the Zero up:** the hub's lead may
  hand the Zero's task to its own specialists or departments, and any of the hub's agents may
  write files into one folder for that Zero (`<workspace>/for-<zero>/`). A report through
  *save report* needs nothing. Both rows are in *Permissions*, and removing the link removes
  them. A page the agent also read, a hidden file, or a path outside that folder still needs a
  person.
- **Files go back only to a machine the hub set up to run its work there.** Any other linked
  team gets words only.
- **The Tailscale key is never stored by Bento.** It's in the line you copy and nowhere else.

## The three faces

- **Desktop:** *Settings → Team & Communications → New machines*: Make a Zero, Standard setup,
  Its agents, and a *via* label on each machine heard.
- **Terminal:** `bento pool zero`, `bento pool standard`, `bento pool hub`, and `bento link`
  shows the standing folder for each Zero.
- **Session UI:** the same Settings page; nothing here touches the compositor.

## What was tested, and what wasn't

- `tests/test_zero.py`: where a machine was heard, the line (the Tailscale key is never written
  to disk), the standard setup as a closed set, the Zero's side after a claim, the hub's
  standing folder against `..`, hidden files and mixed untrusted content, files capped both
  ways, and a whole task from a Zero on the hub at the default autonomy level.
- `packaging/dev/provision-e2e/zero_run.py`: a hub and a Zero as real `bento serve` processes.
  The Zero's own broadcast goes nowhere, so the hub hears it only through the address in the
  line. It is set up by the key with the standard setup (one agent with its own executor), and a
  task typed on the Zero comes back with the file the hub's writer made.

Not tested: a real tailnet. The run can't give a process a `100.x` address, so *over Tailscale*
is covered by the unit tests on the address ranges, and the run's Zero is heard *on your
network*. Tailscale's own installer and `tailscale up` were not run.
