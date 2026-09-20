# Accounts — the mailbox and the calendar your agent may read

An account is something the agent reads **for you**: your inbox, your calendar.
It is not a channel (nothing arrives through it), and the rules are the
channel rules' mirror image:

- **Every read is a decision in the ledger.** `mail.read` and `calendar.read`
  are their own permission actions, grantable apart from everything else. A
  mission that reads your mail says so on its consent block, and the
  Permissions app can take it back.
- **The credential is yours.** `mail` and `calendar` are per-person settings on
  a machine with accounts, masked on every read of config, and never handed to
  the model. The tools are the only way in.
- **Reading never changes anything.** No message is ever marked read, moved or
  deleted; no event is ever created. There are no tools for it.
- **Sending is separate, and always asks.** `mail_send` is its own action
  (`mail.send`), risky, and confirms every time unless you wrote a grant for
  it. No mission grants it. A drafted reply is a draft in the report.
- **Mail is written by other people.** Everything the tools return is marked
  untrusted, like a fetched web page: for the rest of that turn, anything that
  changes something asks first, whatever the autonomy level.

## Setting up mail

Settings → Accounts → Mail, or from a terminal:

```
bento mail set --preset gmail --username you@gmail.com --password <app password>
bento mail test
bento mail search --unread --days 1
```

| Provider | What to enter |
|---|---|
| **Gmail / Google Workspace** | An **app password** (myaccount.google.com → Security → 2-Step Verification → App passwords), not your Google password. IMAP must be on in Gmail settings. |
| **Outlook / Microsoft 365** | Personal: an app password from account.microsoft.com → Security. Work accounts often have basic IMAP disabled by the admin. |
| **iCloud** | An app-specific password from appleid.apple.com. The user name is the full iCloud address. |
| **Fastmail** | An app password with Mail access from Settings → Privacy & Security → Integrations. |
| **Anything else** | The IMAP host and port from your provider. SMTP is only needed if you ever grant sending. |

"Test" really signs in and counts the inbox, and the outcome is written on the
account. The Missions catalogue reads the same outcome: a mail mission is
greyed until the last sign-in succeeded.

## Setting up a calendar

Two doors, because the two big providers open different ones without an OAuth
application:

| Provider | What to enter |
|---|---|
| **Google Calendar** | The calendar's **secret address in iCal format** (calendar.google.com → Settings → your calendar → Integrate calendar). Anyone with the address can read the calendar: treat it as a password. |
| **Outlook.com** | A published ICS link (Settings → Calendar → Shared calendars → Publish). |
| **iCloud** | CalDAV: `https://caldav.icloud.com/`, your Apple ID and an app-specific password. The calendars are discovered. |
| **Fastmail** | CalDAV: `https://caldav.fastmail.com/` and an app password with Calendar access. |
| **Nextcloud and others** | The server's CalDAV root, or one calendar's own URL, and an app password. |

```
bento calendar set --preset google --url 'https://calendar.google.com/calendar/ical/…/basic.ics'
bento calendar test
bento calendar today
bento calendar week
```

Recurring events: a CalDAV server is asked to expand them itself. For an ICS
address the reader expands the common shapes (daily, weekly with days, monthly,
yearly, with interval, count, until, exceptions and moved instances) and says
in a note which rule it could not expand, rather than guessing.

## The missions built on them

| Mission | Needs | What you get |
|---|---|---|
| Triage my inbox every morning | mail | Needs you / needs a decision / FYI / noise, with a draft reply for each "needs you" |
| Brief me before today's meetings | calendar (mail if set up) | One paragraph per meeting: who, what we know, the last thread, what to bring |
| Show me the week ahead | calendar | The next seven days on one page: meetings, deadlines, free days |
| Tell me who I owe a reply to | mail | The threads waiting on you, and the ones you are waiting on |

A mission that wants an account you have not set up is shown greyed with the
sentence that would fix it, and the save refuses it until then. A mission that
would only *use* one (meeting prep with mail) runs without it and says so in
its own instructions, so its specialist never goes looking for a tool it was
not granted.

## What is deliberately not here

- No OAuth. It would mean registering an application with each provider and
  shipping a client secret; app passwords give the same read access with
  nothing to register and nothing to renew.
- No Exchange Web Services, no Graph API. Microsoft 365 tenants that disable
  IMAP cannot be read yet; the test says so.
- No writing. Not to the mailbox, not to the calendar. The day that changes it
  will be an action of its own, granted apart, like `mail.send` is.
