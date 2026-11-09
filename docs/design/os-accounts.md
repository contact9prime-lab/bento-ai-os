# Design: an OS user per Bento account (Linux and macOS)

*Status: designed, not built. On the [roadmap](../roadmap.md) under pillar D. November 2026.*

## Why

Today every Bento account, and every agent of every account, runs as one OS user: the person who
installed Bento. On the machine this was designed on, that user is in the `sudo` group and the
`docker` group, and membership of `docker` alone is the same as root (anything that can reach the
docker socket can start a container with `/` mounted).

What keeps accounts apart today is Bento itself:

- the bubblewrap jail (or `sandbox-exec` on macOS) blanks other homes, `/run` (so the docker
  socket and D-Bus are gone) and this OS's own data, and bwrap stops any program inside it from
  raising its privileges, so `sudo` cannot work in there;
- `agentos/protected.py` refuses keys, accounts, settings and code to every agent by path,
  whatever its grants, the admin's agents included;
- the file tools' tenant check refuses another account's home.

Those hold, and they are tested (see [How Bento's security is built and tested](../security-testing.md)).
But they are Bento's code. A bug in one of them, or a bwrap escape, lands as the desktop user, and
that user can become root. The owner's rule is that security should not depend on any one layer,
and that the admin's identity, which can use sudo, should never be the one that runs agent work.

## What was decided

- **The server stays as the desktop user.** It has to be in the desktop session to draw the SUI,
  drive the screen and change Wi-Fi. Moving it to a service user is a larger change, kept for later.
- **Agent work runs as `bento-<account>`.** Every process an agent starts (its shell, `run_python`,
  the Terminal, an agent CLI, a tool server) runs as that account's own OS user. The admin's
  account gets one too, and a machine with no accounts uses `bento-main`. These users have no
  sudo, no docker and no other groups, and cannot log in.
- **Each account signs its own CLIs in.** The machine's current Claude Code sign-in moves to the
  admin's account. Nobody else's agent can use or spend it.
- **Root needs an admin's typed yes.** Only a person signed in as a Bento admin, from a screen,
  re-entering their Bento password and then sudo's own password, every time. Bento never uses
  passwordless sudo for root, and refuses outright while an agent is acting. No tool, app, flow,
  peer or linked team can reach it.
- **Every root use is recorded and alerted.** A ledger row, and one alert per incident on every
  admin's screens and phone. An attempt from an agent is its own alert.
- **Pis and Zeros:** offered, off by default. They have one person and are set up zero-touch,
  which relies on passwordless sudo.

## Linux

- **Users.** `useradd --system`, shell `nologin`, primary group `bento-<account>`, plus
  `bento-agents` so one sudo rule can name them all. The mapping from Bento account to OS user is
  `/etc/bento/accounts.json`, owned by root, so neither the server nor an agent can change it.
- **What they own.** Only the account's agent area: its workspace, tool-server boxes, CLI sign-in
  folders, scratch and a spool folder. Mode 2770 with default ACLs giving the server read and
  write. The account's home itself (database, settings, vault, keys) stays the server's, 0700, so
  no agent user can read it even outside a jail. One account's agent user cannot read another's
  area at all. That is a second wall behind the jail's blanking.
- **Switching user, with no Bento code running as root.** A sudoers rule lets the server run one
  program, `/usr/local/libexec/bento-enter`, and only as the agent users, never as root:
  `<desktop user> ALL=(%bento-agents) NOPASSWD: /usr/local/libexec/bento-enter`.
  `bento-enter` is small, owned by root, copied out of the checkout at the root step. It reads the
  run's environment from a 0640 file in that account's spool, so secrets are never on a command
  line (`/proc/*/cmdline` is readable by every user). It checks where the file is and who owns it,
  deletes it, sets umask 007 and `no_new_privs`, then runs bwrap and nothing else.
- **One wrap point.** Both jail builders (`tools.bwrap_argv`, `executors._bwrap`) return a `bwrap`
  command, and the places that start them are few: the shell and Python tools, tool servers
  (`mcp_client.stdio_launch`), agent CLIs (`executors.jail_cli`/`jail_server`) and the Terminal.
  Each goes through one `osaccounts.wrap(argv, env, uid)`.
- **Fail closed.** With separation on, an account with no OS user yet (added after the root step)
  gets no shell, Terminal or CLI, with a sentence and a door to Settings → Users. Nothing ever
  falls back to the desktop user.
- **One door to root.** `privilege.run_root` replaces the separate sudo and pkexec calls in
  `session.py`, `components.py`, `appstore.py`, `screen.py`, `hostfirewall.py` and `integrity.py`.
  A test fails if sudo or pkexec appears anywhere else.
- **The watcher covers it.** The sudoers file, `bento-enter` and `accounts.json` are hashed like
  the other security files, and a change stops the agents. `osaccounts.check` makes sure each
  agent user still has no extra groups, isn't uid 0, can't log in and matches the mapping, and
  that each area keeps its owner and mode. Drift raises an alert and stops that account's agents.
  At start the server reads its own groups and says, on the Security card and in `bento doctor`,
  when it can become root (docker, sudo, lxd, libvirt, disk), with the command to remove docker.
- **The root step.** `bento accounts linux status|on|add <account>|off`, and a Linux accounts card
  in Settings → Users (loopback and admin only). `on` shows every command first, then makes the
  users, the groups, the sudoers file (checked with `visudo -c`), `bento-enter` and the mapping,
  sets owners, modes and ACLs, moves the CLI sign-in, and can run `bento integrity lock` in the
  same step, so the code is owned by root too. `off` gives everything back and deletes no data.
- **File tools stay in the server.** `read_file` and `write_file` run in the server process, held by
  the tenant check and `protected.py` as now. The uid wall covers every process an agent starts,
  and the docs will say exactly that.

## macOS

The same shape, with these differences, several of them harder:

- **Users** are made with `sysadminctl` or `dscl`, hidden (`IsHidden`, uid under 500), with a
  primary group that is not `staff`. Every ordinary macOS user is in `staff`, and files `staff` can
  read would otherwise be open to them. Groups with `dseditgroup`, ACLs with `chmod +a`.
- **sudo** is classic sudo, so the same sudoers rule works.
- **The jail** is `sandbox-exec` (deprecated by Apple but working). The profile already exists in
  `tools._sandbox_exec_profile`, and `bento-enter` runs it in place of bwrap.
- **Claude Code keeps its sign-in in the login Keychain, not in a file.** Each agent user needs a
  keychain and a sign-in of its own, and copying the admin's file doesn't apply. This is the part
  most likely to need a different answer.
- **Privacy prompts (TCC).** Files and Folders and Full Disk Access prompts belong to the person
  at the screen, and a hidden user can't answer them. What an agent user may reach has to be
  decided before it runs, not by a prompt in the middle of a run.
- **Root from the page** has no polkit. It uses an `osascript … with administrator privileges`
  prompt, where the person authenticates to macOS themselves, after the same Bento admin step.
- **The server** runs from launchd, not systemd.

## Open questions

- Whether sudo-rs (Ubuntu's default sudo since 25.10) supports `%group` in the runas list. If it
  doesn't, the root step writes the users by name and rewrites the rule when an account is added.
- Where Gemini CLI and Codex keep their sign-ins, per OS user, on both systems.
- How a person signs an account's CLI in: most likely from that account's own Terminal, which
  already runs in its jail and would then run as its OS user.

## How it will be proved

Nothing in this design is run on the owner's machine by an agent. It is proved in places that
can't reach that machine:

- containers with `--network none` and only the capabilities bwrap needs, in Ubuntu (sudo-rs) and
  Debian (classic sudo), running the real root step with two accounts. Each test checks that the
  commands run as `bento-<account>`; that `id` shows no sudo or docker; that `sudo` and `su` fail;
  that the other account's area, every home, `config.json` and `vault.key` are unreadable even
  with the jail's blanking taken away; that secrets arrive without appearing in a command line;
  that the Terminal works; that a CLI reads only its own sign-in; that files an agent writes are
  readable and writable by the server; and that `off` gives everything back;
- a macOS machine or VM for the macOS half;
- the full suite, inside the test jail described in the testing page, and CI on both Pythons.

The owner runs the root step on their own machine, from their own terminal.
