# How Bento's security is built and tested

This page says what protects a Bento machine, which code does it, and how each part was tested. It also
says what has not been tested yet. [Security & threat model](security.md) explains the design; this page is
the evidence.

## The rules it is held to

The owner set four rules, and every change below is checked against them:

1. **No AI overrules security.** No model, at any autonomy level, can change a security setting, a grant,
   the gate or the sandbox.
2. **No AI touches the security files.** The gate's code, the keys, the accounts and the settings are out of
   every agent's reach.
3. **A change is noticed.** If a security file changes, a watcher sees it, says so on every screen and stops
   the agents.
4. **An attack is flagged.** Failed sign-ins, forged tokens and refused steps are recorded and raise an alert.
   The AI is told so it can warn you, but it decides nothing.

## How it was tested

**An audit first.** Nine review areas covered the whole codebase: about 112,000 lines, 136 modules and 587
routes. Each finding was checked by a second reviewer that hadn't written it, and most were proved with a
small script against a copy of the code. That found 97 issues, 12 of them critical.

**A fix for each finding, with a test that fails on the old code.** Every fix comes with a test that describes
what must stay true. Each new test was run against the code from before the fix, to show it fails there, and
against the fix, to show it passes. A test written only against the new code proves nothing about the hole.

**The whole suite after every merge.** The full suite runs on the combined code after each group of fixes is
merged. The latest run is at the end of this page.

**Real runs, not only tests.** Some things only show up for real:

- A real Claude Code turn ran in the jail, on a copy of a real machine's data with Bash turned on. It could
  not read the settings, the session key or `~/.ssh`. It could not write `policy.py`. Its call to Bento's own
  API was refused, and that raised a security alert. Ordinary work in the workspace worked.
- A resumed session remembered the previous turn from inside the jail. A task handed to a department through
  the team door ran its desk, its review and its audit.
- A file in the code tree was changed while the server ran. Within a minute the agents stopped, a new turn
  was refused, and the alert named the file. A process started by Bento could not clear the hold.
- All 46 desktop apps were opened in a real Chrome under the new content security policy, with no false
  refusals. Script planted in a theme, a report and an app page did not run on the desktop.
- Throwaway servers were run with accounts, to check a non-admin is refused at the machine's routes, and
  with DNS rebinding and a jailed shell, which were refused.

## Running the security tests safely

Bento controls the machine it runs on: networking, power, the screen. A test server on a throwaway home is
still on the real machine. So the tests run inside a bubblewrap jail where `/run` is empty: there is no
system or session D-Bus, so nothing a test does can reach NetworkManager, logind or systemd. Your homes are
read-only in there. Check the jail works before you trust it:

```sh
bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /run --tmpfs /tmp \
  gdbus call --system --dest org.freedesktop.NetworkManager \
  --object-path /org/freedesktop/NetworkManager \
  --method org.freedesktop.DBus.Properties.Get org.freedesktop.NetworkManager NetworkingEnabled
# expected: "Could not connect". If it answers, the jail is not doing its job.
```

Give the test run a throwaway `HOME` and `AGENTOS_HOME` too. The suite opens `AGENTOS_HOME` when it is
imported, so without that it writes your real database. Never test a route that changes the machine as an
admin. Test that a non-admin is refused, or replace the program it runs.

## The layers, and the tests that hold each one

| Layer | What it stops | Code | Tests |
|---|---|---|---|
| Host check | A web page that renames itself to `127.0.0.1` driving your Bento (DNS rebinding) | `remote.host_allowed` | `test_perimeter.py` |
| Real loopback only | Turning remote access off and leaving the network let in | `server._authed` | `test_perimeter.py` |
| Process check | Code Bento started (an agent's shell, a CLI, a tool server) using your access over loopback | `agentos/peercheck.py` | `test_peercheck.py`, `test_perimeter.py` |
| Sessions | A copied cookie after sign-out, a password change or a role change; guessing another account's password | `users.py`, `remote.py` | `test_perimeter.py` |
| Machine routes | A non-admin using machine-wide controls | `agentos/machineroutes.py` | `test_machine_routes.py` |
| Account walls | A non-admin's workspace, files, tool servers or sign-ins reaching another account | `users.workspace_problem`, `mcp_client.stdio_launch` | `test_account_reach.py`, `test_mcp_accounts.py` |
| Sockets | A socket message acting as another account, or stopping or steering their work | `server` `/ws` handler | `test_ws_owner.py` |
| The page | Outside text running as script on the desktop: themes, files, app pages, names in menus | CSP in `server.security_headers`, `esc`/`jsq` | `test_web_headers.py`, `test_theme_shell_sandbox.py`, `test_ui_handlers.py`, `test_app_origin.py` |
| The gate's inputs | A shell line that looks read-only and writes or runs; a tool that wasn't offered; a model naming its own space; one "always" covering a whole program | `policy.py`, `tools.shell_parse` | `test_gate_inputs.py` |
| No AI control | A model changing security settings, the gate's code, its soul or the theme of every browser | `configure_agentos`, `develop_agentos`, `ALWAYS_ASK` | `test_tools_cannot_reach_security.py` |
| Protected files | Any agent reading keys and accounts or writing settings and code, whatever its grants | `agentos/protected.py` | `test_protected.py`, `test_jail.py` |
| The jail | A jailed command seeing other homes, the server's keys, other processes or the session bus | `tools.bwrap_argv` | `test_jail.py` |
| Agent CLIs | Prompt text read as a flag; a folder's settings running a hook; a CLI's shell outside a jail | `executors.jail_cli`, `prompt_of` | `test_cli_jail.py` |
| Fetches | An agent or app reaching this machine, the LAN or cloud metadata | `agentos/netguard.py` | `test_net_guard.py` |
| File opens | A link swapped between the check and the read | `agentos/safeopen.py` | `test_jail.py` |
| Time travel | A forged checkpoint writing anywhere | `timetravel.py` | `test_timetravel.py` |
| Watcher | A change to the code or a security file going unnoticed, or an agent clearing the hold | `agentos/integrity.py` | `test_integrity.py` |
| Ledger | Rewriting or deleting ledger rows without it showing | `memory.verify_chain` | `test_integrity.py` |
| Signed updates | An update that isn't signed by your key being taken as verified | `updates.SIGNING_KEYS` | `test_integrity.py` |
| Security record | An attack leaving no trace; an alert flood; an attacker's words reaching a model | `agentos/secevents.py` | `test_secevents.py` |
| Other machines | A Zero, a linked team, a community member or a cloud standby reaching past what it was given | `teamlink`, `pool`, `provision`, `zero`, `standby` | `test_zero_boundaries.py`, `test_pool.py`, `test_provision.py`, `test_standby.py`, `test_teamlink_request.py` |
| Devices | A password sent to a machine nobody checked; network names carrying terminal escapes | `remoteinstall.require_pin`, `netscan` | `test_device_install.py`, `test_network.py` |

The security tests are in 20 new test files with about 500 tests between them, plus tests added to files
that already existed.

## What is not proved yet

These are open, and nothing above should be read as covering them:

- **Same-user code outside the jail.** A process running as your user, outside Bento's jail, can edit
  files. The watcher notices; only `bento integrity lock` (the code owned by root) stops it, and that
  command has not yet been run on a real machine.
- **Signed updates need your key.** `SIGNING_KEYS` ships empty. Until you make a key and pin it, updates say
  "unsigned" and are not verified.
- **A community with no vote.** A community member that's been broken into can lead while the real leader
  is away. Leadership is checked against a signature from the machine that founded the community, but there
  is no quorum.
- **Not run on:** Gemini CLI and Codex, which follow their documented flags; macOS, where the jail profile is
  untested; a real `sshd`, which was a stand-in; a real WebKitGTK session for the desktop host bridge.
- **The network stays open in the jail,** so an agent's command can still reach the internet and abstract
  sockets. The process check is what keeps it from acting as you on loopback.
- **A second independent attempt to break the fixes** on the combined code is not finished. When it is, its
  results go here.

## Latest full run

The full suite on the combined fixes, run inside the jail described above, on 2026-11-09:

| | Tests |
|---|---|
| Passed | 5,886 |
| Failed | 4 |
| Skipped | 114 |

The four that failed and most of the skips are tests that need what the jail takes away on purpose: a real
Chrome sandbox, a real D-Bus, or a bubblewrap jail of their own, which can't start inside another one. The
same code run outside that jail earlier passed 5,966 tests, with 19 skipped and 10 failures that were in
`test_ochost.py` and failed on `master` too. CI runs the suite on Linux without the outer jail, so those
tests run there.

No command that changes the machine was run during either run: the stand-ins for `nmcli`, `systemctl` and
the others recorded only status reads.
