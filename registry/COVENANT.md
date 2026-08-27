# The commons covenant

This commons is open to every kind of author — people, AI agents, and the two
working together — on identical terms: same manifest, same scan, same consent
screen, same signature mechanics. It exists for one reason: apps that make the
machines they land on more useful to the people who own them. Keeping it worth
trusting takes a few rules, and every one of them is checked where checking is
possible rather than merely asked for.

1. **Say who made it.** Every package carries `author.kind`
   (`human` | `agent` | `hybrid`), derived from the app's own edit history at
   export and shown on the consent screen. An agent's work is welcome; an
   agent's work passing as a person's is not. CI refuses packages without it.
2. **Ask only for what the app needs, with reasons.** Every permission is shown
   to the person installing; an app that over-asks reads as exactly what it is.
3. **No deception.** No fake system UI, no credential harvesting, no dark
   patterns, no code hidden from the scan (obfuscation is flagged, and a scan
   verdict that disagrees with a fresh scan of the same bytes is refused by CI).
4. **No exfiltration.** An app's data belongs to the machine it runs on.
   Talking to external hosts is flagged by the scan and must be what the app's
   description says it does.
5. **Serve the person using it.** The measure of an app here is that the owner
   of the machine is better off with it — not engagement extracted, not data
   gathered, not another party's interest served quietly.

Breaking these gets a package refused, delisted, or its signer's key dropped —
in that order, by people, with the reason stated.
