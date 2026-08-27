# Birthing this registry (owner, one time)

This directory is the complete seed of `contact9prime-lab/bento-app-registry`.

1. Create the empty public repo on GitHub: `bento-app-registry` (default branch `main`).
2. From a checkout of bento-ai-os:
   ```bash
   git clone https://github.com/contact9prime-lab/bento-app-registry.git /tmp/reg
   cp -r registry/. /tmp/reg/
   cd /tmp/reg && rm SETUP.md && git add -A && git commit -m "Registry seed" && git push
   ```
3. Mint the signing identity ON YOUR OWN MACHINE (never CI, never a shared box):
   ```bash
   bento registry keygen
   ```
   - Paste the printed PUBLIC key line into `agentos/appregistry.py` `BUILTIN_KEYS`
     in bento-ai-os and release — that ships trust to every install.
   - Paste the private key FILE's content into the registry repo's Actions secret
     `REGISTRY_SIGNING_KEY` (Settings → Secrets → Actions).
4. Signing an app after merging its PR: Actions → sign → run with the app id.

The private key never enters any repository. If it ever leaks: mint a new one,
ship the new public key, re-sign the registry (one workflow run per app).
