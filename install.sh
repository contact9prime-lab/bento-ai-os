#!/bin/sh
# AgentOS one-command installer (Linux/macOS):
#   curl -fsSL https://raw.githubusercontent.com/<you>/agentic-os/main/install.sh | sh
# Installs uv if missing, clones/updates the repo, syncs deps, runs the doctor,
# and installs the app launcher + login service.
set -e

REPO="${AGENTOS_REPO:-https://github.com/YOUR_ORG/agentic-os.git}"
DIR="${AGENTOS_DIR:-$HOME/.local/src/agentic-os}"

say() { printf '\033[36m▲ %s\033[0m\n' "$*"; }

command -v git >/dev/null 2>&1 || { echo "git is required — install it first"; exit 1; }

if ! command -v uv >/dev/null 2>&1; then
  say "installing uv (Python package manager)…"
  curl -fsSL https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
fi

if [ -d "$DIR/.git" ]; then
  say "updating AgentOS in $DIR"
  git -C "$DIR" pull --ff-only
else
  say "cloning AgentOS into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
say "installing dependencies"
uv sync

say "environment check"
uv run agentos doctor || true

say "installing launcher + login service"
uv run agentos install

say "done — AgentOS is at http://127.0.0.1:8321 (launch 'AgentOS' from your app menu)"
