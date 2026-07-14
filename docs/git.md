# Git & shipping to GitHub

AgentOS treats git as a first-class capability with structured tools — not shell strings —
so every operation carries the right risk level and pushes authenticate without your token
ever appearing in a command line, a remote URL, or tool output.

## The tools

| Tool | Does | Risk |
|---|---|---|
| `git_status` / `git_log` / `git_diff` | inspect a repo | safe — runs free |
| `git_init` / `git_commit` / `git_branch` | local, reversible history | safe **inside the workspace**; asks elsewhere |
| `git_remote_set` / `git_pull` / `git_clone` | remotes & external code | asks |
| `git_push` | publish commits (optionally **creates the GitHub repo** first) | asks |
| `export_app_to_git` | app → real project folder + git repo (+ optional push) | safe; asks when pushing |

The raw shell still works, but `git` is no longer blanket-trusted there: read-only
subcommands (`status`, `log`, `diff`, `show`, …) auto-run, while `git push`, `git reset
--hard`, `git clean`, config writes, and remote changes require approval like any other
mutating command.

## GitHub setup (once)

**Settings → GitHub**: paste a [fine-grained personal access token](https://github.com/settings/tokens)
with only the repo permissions you want to grant. The token is stored in `config.json`,
masked in the API, injected into git via an askpass helper at push time, and never logged.

## Shipping an app you built

> *"Export the Tip Calculator to GitHub as a private repo."*

The agent runs `export_app_to_git(app="Tip Calculator", push=true)`:

1. writes `workspace/projects/tip-calculator/` — `index.html` (the whole app),
   `manifest.json` (name, icon, description, permissions), `README.md`;
2. `git init` + commit;
3. creates the GitHub repo via the API (private by default) and pushes — you approve the push.

Every later refinement of the app can be committed and pushed to the same repo — version
history on GitHub, versions + rollback in App Studio.

## Projects in the workspace

Anything the agent builds in `workspace/projects/` should live in git from the start — the
agent is instructed to `git_init` early and commit as it goes. Ask *"what changed?"*
(`git_diff`), *"commit this as …"*, *"push it"* — the workspace is a real dev environment.
