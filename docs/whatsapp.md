# WhatsApp

Your agent, on the app you already have open. Same conversation, same memory, same
tools, same permission prompts as at the desk — a reply on your phone continues the
thread you started this morning.

This brings a conversation **in**, to your agent — the only kind of channel
AgentOS offers. (An earlier build also listed platforms "carried" by the Hermes
gateway, which could deliver out but were answered by a different agent; that tier
was removed.)

## Two ways in — pick one

| | **Linked device (Baileys)** | **Business Cloud API** |
|---|---|---|
| Setup | scan a QR from your phone | Meta app + business verification |
| Needs a public HTTPS address | **no** | yes (a tunnel) |
| 24-hour reply window | **no** | yes — it cannot speak first to a silent chat |
| Supported by Meta | **no** — see the warning below | yes |
| Extra dependencies | Node.js + ~60 MB | none |

Both reach **this** agent, with your memory, tools and permission prompts. They are
mutually exclusive per number; switch with the link in Settings → Channels → WhatsApp.

### The linked device, in three steps

```
bento channels whatsapp --pair       # prints a QR in the terminal
```

or in the desktop: **Settings → Channels → WhatsApp → Link with a QR code**. Then:

1. Install the bridge when asked — MIT (Baileys), needs Node.js, ~60 MB. Nothing is
   downloaded until you say yes.
2. On your phone: **WhatsApp → Settings → Linked devices → Link a device**, and scan.
   The code rotates every ~20 seconds; the screen refreshes itself.
3. Message it once from your phone. The first chat to write becomes the owner.

`bento channels whatsapp --unpair` unlinks the device and forgets the paired chat.

> **This one is unofficial.** It works by emulating a linked WhatsApp Web session.
> WhatsApp does not support it and has banned accounts for automating on it. Use a
> spare number if that matters to you. This is stated on the install screen too — it
> is your account, and the choice is yours to make with the risk in view.

Two smaller differences worth knowing: approvals arrive as **numbered replies**
(`1` deny, `2` allow once, `3` allow and remember) because a linked device has no
interactive buttons; and only **direct messages** are read — groups and status
updates are ignored.

## What the Cloud API needs
Four values from [developers.facebook.com](https://developers.facebook.com) — create
an app, add the **WhatsApp** product, and it hands you a test number to start with:

| | Where it comes from |
|---|---|
| **Phone number ID** | WhatsApp → API Setup. Not the phone number — the numeric id beside it. |
| **Access token** | WhatsApp → API Setup. The 24-hour test token works for trying it; create a **system user token** before you rely on it, or the channel will simply stop tomorrow. |
| **App secret** | App settings → Basic. Used to prove a webhook delivery really came from Meta. |
| **Verify token** | Any string you invent. You paste the same one into Meta's console. |

Set them in **Settings → Channels → WhatsApp**, or from a terminal:

```
bento channels whatsapp --set phone_number_id=123456789012345 \
                        --set access_token=EAAG… \
                        --set app_secret=… \
                        --set verify_token=whatever-you-like --on
```

## The webhook

WhatsApp does not poll; Meta calls **you**. So this machine has to be reachable from
the internet over HTTPS.

Turn on a public tunnel in **Settings → Remote access**, and the WhatsApp card then
shows the exact callback URL to paste — something like
`https://your-tunnel.example/api/whatsapp/webhook`. `bento channels whatsapp` prints
the same URL, or the sentence saying why there isn't one yet.

In Meta's console: **Configuration → Edit**, paste the callback URL and your verify
token, save, then **subscribe to `messages`**. If you forget the subscription
everything looks correct and nothing ever arrives.

Every delivery is checked against `X-Hub-Signature-256` before it is parsed. Without
an app secret configured, deliveries are refused rather than trusted — this is a
public URL, and an unverifiable one is worse than none.

## Pairing

Message the number from your phone. The first chat to write becomes the owner and is
told so. Every other number is told this machine is not theirs; you can allow one
individually from the WhatsApp card. Approvals arrive as three reply buttons — Deny,
Allow once, Allow & remember — and only the owner's taps count.

## The 24-hour window

This is WhatsApp's rule, not ours, and it is the one thing that will surprise you:

> Outside 24 hours from your last message to it, Meta will not carry a free-form
> message. Only a pre-approved template is allowed.

So a scheduled 08:00 briefing **cannot** reach a chat that has been silent since
Sunday. AgentOS does not paper over this:

- The card says whether the window is open right now.
- `whatsapp_send` refuses with that sentence and the fix — say anything to the
  number and it reopens for a day — rather than a bare API error.
- A **job** that delivers to WhatsApp is told to `save_report` *first* and message
  second, so a refused send loses nothing.
- For genuinely unattended work, Telegram or Reports is the right delivery.

## What it is allowed to do

`whatsapp` is a real IO gate, like `gui` and `telegram`, so permissions can be scoped
to it: "may fetch pages when I ask from WhatsApp" is expressible, and shows in the
Permissions app like any other rule. Its posture (Settings → Channels → WhatsApp →
Permissions) sets how far the channel is trusted independently of who is asking —
"Ask me first" is a sensible default for a channel you use from a phone in public.

## Troubleshooting

| What you see | What it is |
|---|---|
| Card says "Meta cannot reach this machine yet" | No public HTTPS address. Turn on a tunnel in Settings → Remote access. |
| Meta's console says the callback URL failed | Verify token mismatch, or the tunnel was down when you saved. |
| Nothing arrives, no errors anywhere | You did not subscribe to `messages` in Meta's console. |
| Worked yesterday, dead today | A 24-hour test token expired. Create a system user token. |
| Logs show "refused an unsigned webhook delivery" | Wrong app secret — or something that is not Meta is POSTing at you. |
| Sends refuse with "24 hours" | The window closed. Message the number; it reopens. |
