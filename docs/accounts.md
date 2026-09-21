# Accounts — the mailbox and the calendar your agent may read

An account is something the agent reads **for you**: your inbox, your calendar.
It is not a channel (nothing arrives through it), and the rules are the
channel rules' mirror image:

- **Every read is a decision in the ledger.** `mail.read` and `calendar.read`
  are their own permission actions, grantable apart from everything else. A
  mission that reads your mail says so on its consent block, and the
  Permissions app can take it back.
- **The credential is yours, and it is in the vault.** A password or a
  sign-in's tokens never sit in config: config holds a reference, the bytes are
  encrypted in [the vault](vault.md), every read of them is a line in the
  diary, and no route, verb or tool returns them. The model sees the mail,
  never the password.
- **Reading never changes anything.** No message is ever marked read, moved or
  deleted; no event is ever created. There are no tools for it.
- **Sending is separate, and always asks.** `mail_send` is its own action
  (`mail.send`), risky, and confirms every time unless you wrote a grant for
  it. No mission grants it. A drafted reply is a draft on the Brief item, and
  *Send draft…* sends it as you, through the gate that asks.
- **Mail is written by other people.** Everything the tools return is marked
  untrusted, like a fetched web page: for the rest of that turn, anything that
  changes something asks first, whatever the autonomy level.

## Three doors, in the order you should try them

| Door | For | What you type |
|---|---|---|
| **Sign in with Google / Microsoft** | Gmail, Google Workspace, Outlook.com, Microsoft 365 | nothing — a consent page, and a grant you can revoke from your account |
| **Through an MCP server** | a mail or calendar MCP server you already run | which server |
| **An app password** | iCloud, Fastmail, any IMAP server; any ICS address or CalDAV server | the address, an app password |

One sign-in serves both accounts: you tick what it may read (mail, calendar,
and — separately, never by default — send), the consent page names exactly
that, and afterwards the card reads *signed in with Google as you@gmail.com
(mail, calendar)*. Mail is read over the Gmail API or Microsoft Graph, the
calendar over the Google Calendar API or Graph; the four tools (`mail_search`,
`mail_read`, `mail_send`, `calendar_events`) are the same whatever the door,
so every mission works unchanged.

### Sign in with Google / Microsoft

Settings → Accounts → **Sign in with Google** (or Microsoft). From a terminal
on a headless box:

```
bento mail signin google          # prints the consent URL — open it anywhere
bento mail signin google --send   # also ask to send (every message still asks)
bento mail show                   # "reads through: signed in with Google as …"
bento mail signout google
```

The consent page comes back to **this server** (`/api/accounts/oauth/callback/…`),
so a phone can finish a sign-in for a box in another room: the machine has to
be reachable at the address in Settings → System → *redirect base* (the same
setting the MCP Store's sign-ins use). The tokens land in your vault, are
refreshed silently, and *Sign out* revokes them and switches the accounts
that read through them **off** — never silently back to some old password.

**This install needs an OAuth client first.** Google and Microsoft issue an
OAuth client per *application*, and a self-hosted OS has no central
application — so the project ships none, for the same reason it ships no
signing key. The button is greyed with that sentence until an admin pastes a
client id in Settings → Accounts → **App registration**. Five minutes, once
per machine:

- **Google.** Google Cloud → APIs & Services → Credentials → *Create OAuth
  client*, type **Desktop app**. Enable the **Gmail API** and the **Google
  Calendar API** for the project. Paste the client id and the client secret
  (Google issues one for desktop clients and documents it as not secret; the
  OS still masks it). While the app is in *Testing*, add your own address
  under Audience → Test users — that is enough for a personal install.
- **Microsoft.** Microsoft Entra → App registrations → *New*: accounts in any
  organisational directory **and personal Microsoft accounts**; platform
  *Mobile and desktop*; the redirect URI shown on the card; *Allow public
  client flows* on. Paste the Application (client) ID. No secret — it is a
  public client with PKCE.

### Through an MCP server

If you already run a Gmail, Outlook or calendar MCP server, set the account's
*Reads through* to **Through an MCP server** and pick it. A mission that wants
mail then gets **that server's tools** instead of the built-in ones — the
flow's grant names them, and its instructions say so in one paragraph. The
built-in tools refuse in that mode rather than pretend to be the door. Because
a server's tool names are known only while it is connected, such a mission is
installed from the desktop (or with the server running).

### An app password (any provider)

Under *Another provider* on the card, or from a terminal:

```
bento mail set --preset icloud --username you@icloud.com --password <app password>
bento mail test
bento calendar set --preset fastmail --username you@fastmail.com --password <app password>
bento calendar test
```

The password goes into the vault as you press Save; config keeps
`vault:mail.password`. Presets carry the one sentence that matters: it is an
**app password**, never your login password, and where to make one.

## What "set up" means

The card and the Missions catalogue read the **last real probe**, never the
form: *Test* signs in and the card says what the server said (`signed in with
Google as you@gmail.com — 12 messages`, `2 events in the next 7 days (Work)`).
A mission that needs an account is greyed with the sentence that would fix it
until that probe has succeeded.

## The missions built on them

Triage my inbox, brief me before today's meetings, show me the week ahead,
tell me who I owe a reply to — see [missions.md](missions.md). They deliver
to [the Brief](brief.md).

## What is deliberately not here

- **No "record my browser session".** Signing into gmail.com in a browser the
  OS keeps, and reading the mailbox through its web page, works until the
  provider's bot check breaks it, cannot be audited per message, and is
  against most providers' terms. Sign in with Google gives the same "just sign
  in" with a grant that shows up in your account and can be revoked there.
- **No OAuth client of the project's own.** See above: a credential the
  project would have to keep on a build machine, and one that every install
  would share.
- **No sending by a mission.** Sending is yours, and asks every time.
