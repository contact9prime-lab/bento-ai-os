# The vault — where a secret lives, and the only door to it

A password to your mailbox, or the refresh token a sign-in with Google handed
over, used to sit in `config.json` in clear — masked on the one route that
shows config, and nowhere else. Masking a value on the way out is a promise
the next code path has to remember to keep. Storing it somewhere else is not.

So config holds a **reference** — `vault:mail.password` — and the bytes live
in the vault: encrypted (AES-256-GCM) in a 0600 file in your own home
(`~/.agentos/vault.json`, or your user directory on a machine with accounts).

## Who can read it

- **The system, for the job it needs the secret for** — opening the mailbox,
  refreshing a sign-in. Each read is one line in the operator diary saying
  which secret and for what (`read mail.password for mail`).
- **You** — in the sense that it is your file, in your home, keyed by your
  session. There is deliberately no route, verb or tool that prints a value:
  `bento vault` lists names and says what protects them, and stops there.
- **Never the model.** Tools use secrets internally; nothing hands one into a
  turn. The agent sees the mail, not the password.

## What protects it, in the card's own words

The key is not kept next to the lock when it can be elsewhere:

- **A desktop with a keyring** (Secret Service via `secret-tool` on Linux, the
  keychain on macOS): the key sits there, and the file on disk is bytes nobody
  can read without your session. The card says *Encrypted; the key is in this
  machine's keyring*.
- **A headless box** (a Pi, a server): the key is a 0600 file beside the vault.
  The card says *protected by file permissions on this machine, which is all a
  headless box can offer* — because a vault that claimed more would be worse
  than the clear-text file it replaced; somebody would believe it.

The mechanism is decided once, when the first secret is stored, and recorded
in the vault. If the keyring is unreachable later (a desktop session that is
not there), the vault is **locked** and says so — it never mints a fresh key
and quietly fails to decrypt everything it held.

## From a terminal

```
bento vault              # what protects it, how many secrets, their names
bento vault list
bento vault forget oauth.google
```

## What moved

An install that had a mail or calendar password in config gets it moved into
the vault the first time the server starts (or the first time that person's
config is loaded, on a machine with accounts); config is left holding the
reference. Provider API keys and the Telegram token are the **machine's**
(`docs/users.md` says why) and stay where they were — masked, as before.
