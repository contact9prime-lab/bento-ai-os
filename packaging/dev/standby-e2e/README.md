# Cloud standby, end to end

`run.sh` pairs a laptop (this checkout, run as a process with its own `$HOME`) with a cloud
(the real Docker image: entrypoint, `/data`, passphrase, restart by re-exec). Both use a fake
OpenAI-compatible provider and a fake Telegram (`fakes.py`), so every chat, schedule and phone
message has a place to go and a record of which machine answered.

| Phase | What happens |
|---|---|
| `p0_setup` | The laptop gets a life: a provider, a vault secret, memories, facts, a skill, an agent, a one-minute schedule, a folder-watch mission, a chat, a Telegram chat, a workspace file. A fresh cloud container starts. |
| `p1_pair` | Pairing with a one-time code; the cloud's quiet mode seen from the network, signed in and not. |
| `p2_takeover`, `p2b` | The laptop dies. The cloud takes over; every table, the vault, the workspace, the mission's folder, chat, Telegram and the schedule are checked there. |
| `p3_back` | The laptop starts again and takes the work back before anything runs. |
| `p4_move` | Move to the cloud on purpose, and back. |
| `p5_sleep` | The laptop process is frozen past the grace (a closed lid), then woken. |
| `p6_split` | The network splits and both sides work; the laptop keeps its own, the cloud's copy waits, and "use the cloud's copy" switches to it. |
| `p7_restarts` | The container restarts while it is the one working; the laptop starts with the cloud refused, then a black hole. |
| `p8_accounts` | A laptop with two accounts moves to a fresh cloud: each person signs in there and sees only their own work. |

The phases build on each other, so run them in order. The first full run of this found five
bugs, each now pinned by a test: the workspace nested inside an empty folder on restore, a
mission's folder not rewritten for the new machine, the cloud answering from its empty home
for the second before its swap, a new chat's row landing in the machine's database on a
machine with accounts, and the container id shown as the cloud's name.
