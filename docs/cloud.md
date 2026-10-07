# Put Bento in the cloud

Your own Bento at an https address, running while your computer is off. The quickest way
takes about five minutes and no terminal:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/contact9prime-lab/bento-ai-os)

1. Press the button and sign in to Render with GitHub, GitLab or Google.
2. Render shows one box, **AGENTOS_PASSPHRASE**. Type a password there. It's the lock on
   your cloud Bento, so make it long. Settings → System → Put Bento in the cloud suggests one
   you can copy.
3. Press **Deploy Blueprint**. The first build takes about five minutes.
4. Open the address Render gives you (`https://bento-….onrender.com`) and sign in with that
   password. Setup starts as it does on a new computer.

The same choices are in Settings → System → **Put Bento in the cloud**, and in a terminal:

```bash
bento cloud
```

![Settings → System → Put Bento in the cloud: a suggested password, Deploy on Render, and the other ways](screenshots/cloud-deploy.png)

## What you get

- **A disk.** Everything Bento keeps (memory, chats, missions, accounts, saved passwords) lives
  under `/data`, and `/data` is a disk that survives restarts and redeploys.
- **HTTPS**, from Render. Your password and your session never cross the internet in the clear.
- **A lock from the first second.** The password is asked for on Render's page and never written
  in any file, so there is no moment when the machine is open.
- **No local model.** A cloud server has no graphics card, so add a key in Settings → AI providers
  (Anthropic, OpenAI, Google or OpenRouter) when setup asks for a brain.

It costs about $7 a month for Render's Starter server, plus about $0.25 a month for the 1 GB disk
(their prices as of October 2026). The free server is not used because it has no disk: it would
forget everything on every restart.

## Once it's up

Two things this OS already does with a cloud machine:

- **Use it as your standby.** On the cloud Bento, open Settings → System → Cloud standby and press
  **Show a code**. On your computer, type the cloud's address and that code and press **Pair**. Your
  computer does the work; the cloud takes over only while your computer is away.
  [Cloud standby →](standby.md)
- **Move this machine there.** Settings → System → Backup on your computer, then **Restore from a
  backup** on the cloud Bento. Everything comes across: accounts, memory, missions, the vault.
  [Backup →](backup.md)

Want people to have their own sign-in instead of one shared password? Add accounts in the Users
app. Accounts replace the password once there is one. [Users →](users.md)

## Other ways

**Fly.io**, four commands in a terminal, also with HTTPS and a disk. About $3 a month for a 512 MB
machine plus $0.15 a month per GB of disk.

```bash
git clone https://github.com/contact9prime-lab/bento-ai-os.git && cd bento-ai-os
fly launch --copy-config --no-deploy
fly secrets set AGENTOS_PASSPHRASE='<your password>'
fly deploy --volume-initial-size 1
```

`fly.toml` keeps the machine awake (`auto_stop_machines = "off"`): missions, schedules and
Telegram need it running, and a machine woken by the next web request would have missed them.

**Your own server**, any Linux machine you can reach (Hetzner, DigitalOcean, Lightsail):

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh -s -- --yes --passphrase='<your password>'
```

This one has no HTTPS of its own. Put Caddy, a Cloudflare Tunnel or Tailscale in front of it before
you use it over the internet. [Remote access →](remote-access.md)

**Any Docker host** runs the image as it is: publish port 8321 (or set `PORT`), mount a volume at
`/data` and set `AGENTOS_PASSPHRASE`.

## Not offered, and why

| Host | Why not |
|---|---|
| Railway | Its deploy button can't add a disk. It works if you add one at `/data` by hand. |
| DigitalOcean App Platform | No disk, so every restart forgets everything. |
| Google Cloud Run | No disk, so every restart forgets everything. |

## When something goes wrong

- **The deploy says it failed its health check.** The first build is slow. Render checks `/login`,
  which answers once the server is up; give it the full five minutes before retrying.
- **Forgot the password.** In Render, open the service → Environment, change `AGENTOS_PASSPHRASE`
  and save. Bento restarts with the new one and every device signs in again. Restarting with the
  same password keeps everyone signed in.
- **Render says the repository has no render.yaml.** The button reads `render.yaml` from the
  repository's default branch. A fork deploys itself: Settings and `bento cloud` point the button
  at the repository this machine updates from.

## How it works

`render.yaml` (the button's blueprint) and `fly.toml` describe the same thing: the Dockerfile in
this repository, a disk at `/data`, the password from the host's secret store, and `/login` as the
health check, because it answers without a session. The container's entrypoint listens on the
`PORT` the host hands it (Render uses 10000), turns remote access on with the password, and
starts the server. `agentos/clouddeploy.py` is the one list of options that Settings, `bento cloud`
and this page describe. `tests/test_cloud_deploy.py` checks the blueprint against the image.

Tested by running the image the way Render does (`PORT=10000`, the password in the environment,
a volume at `/data`, a proxy's `X-Forwarded-Proto: https`): `/login` answers 200 and the API 401
without a session, a signed-in save works through the cross-origin guard, and a restart keeps both
the data and the session. Idle, it uses about 100 MB of memory and 2 MB of disk.
