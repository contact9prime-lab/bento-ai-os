# Publishing an app

From the machine where your app lives:

```bash
bento registry package "My App"          # exports my-app.agentapp.json via your running AgentOS
bento registry scan my-app.agentapp.json --ai   # static + AI security scan, verdict written in
```

Then fork this repository and add it:

```bash
mkdir -p apps/my-app
cp my-app.agentapp.json apps/my-app/
git checkout -b add-my-app && git add -A && git commit -m "Add my-app" && git push
```

Open the pull request. CI re-runs the same validation your machine ran (it is
literally the same code, imported from the product) and refuses:

- a checksum that does not match the bytes,
- a package with no security scan,
- a scan verdict that does not match a fresh scan of the code.

A maintainer reads the scan, and on merge runs the signing workflow — that
signature is what makes your app show as **Verified** on every machine that
installs it.

Ground rules:

- **No secrets in packages.** The export path already strips them; prerequisites
  (MCP servers, skills) are declared by shape and the installing user supplies
  their own keys.
- **Ask for the permissions your app needs, with reasons.** The consent screen
  shows every one; an app that over-asks reads as exactly what it is.
- Findings in the scan are sentences for a human, not an automatic ban — but a
  `caution` verdict will be read closely, so explain it in the PR.
