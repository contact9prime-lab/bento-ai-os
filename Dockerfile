# Bento Box AI (AgentOS) in a container.
#
#   docker build -t bento .                       # the code sitting next to you
#   docker build -t bento --build-arg SOURCE=git --build-arg REF=master .
#   docker build -t bento --build-arg SOURCE=git --build-arg REF=my-branch \
#     https://github.com/contact9prime-lab/bento-ai-os.git    # no checkout at all
#
#   docker run -d --name bento -p 8321:8321 -v bento-data:/data \
#     -e AGENTOS_PASSPHRASE='something long and unguessable' bento
#
# Then open http://localhost:8321 and sign in with that passphrase.
#
# TWO SOURCES, ONE IMAGE
# ----------------------
# `SOURCE=local` (the default) builds the working tree, so building tells you
# something about the change you are making. `SOURCE=git` clones a ref, so a
# server can be given a branch name and nothing else. They are separate stages
# rather than an `if`, because a Dockerfile has no `if` — and because the two must
# not be able to half-mix, which is what a clone layered over a COPY would do.
#
# WHY THIS DOES NOT `curl … | bash` THE INSTALLER
# -----------------------------------------------
# The previous version of this file was:
#
#   FROM ubuntu:xenial
#   CMD ["curl", "https://…/install.sh", "|", "bash"]
#
# and it could not have worked, for four separate reasons worth writing down:
#
#   1. Exec-form CMD does not run a shell, so `|` and `bash` were passed to curl
#      as extra URLs. The script was printed, never executed.
#   2. It ran at CONTAINER START, not build time, so the image contained nothing
#      and every restart re-downloaded and re-installed the world.
#   3. It fetched `master`, so the image never contained the code you were sitting
#      next to — building told you nothing about your own changes.
#   4. xenial is Ubuntu 16.04, out of support since 2021, with archived apt repos
#      and a git too old for some of GitHub's TLS.
#
# `install.sh` is for a machine you keep: it clones, offers system packages,
# installs a login service and leaves the thing running. A container has no
# service manager and its filesystem is rebuilt on every deploy, so the image does
# that work directly and the two do not pretend to be one thing.

# Global ARGs, declared before the first FROM so they can be used in a FROM line.
ARG SOURCE=local
ARG REPO=https://github.com/contact9prime-lab/bento-ai-os.git
ARG REF=master


FROM ubuntu:24.04 AS base
ENV DEBIAN_FRONTEND=noninteractive
# ca-certificates is not optional: without it every HTTPS call inside the agent
# fails with a certificate error that reads like a network fault.
# git stays in the runtime image — `bento doctor` looks for it and the self-update
# path uses it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git tini \
    && rm -rf /var/lib/apt/lists/*
# uv brings its own Python, which is the whole reason it is the bootstrap here:
# no system python3, no venv module, no version skew with the base image.
ENV PATH=/root/.local/bin:$PATH
RUN curl -fsSL https://astral.sh/uv/install.sh | sh


# --- where the source comes from -------------------------------------------
FROM base AS src-local
COPY . /src

FROM base AS src-git
ARG REPO
ARG REF
# --depth 1 against a REF that may be a branch, a tag or a full sha. The sha case
# needs the two-step form, so try the cheap clone and fall back rather than making
# the caller know which kind of ref they have.
RUN git clone --depth 1 --branch "$REF" "$REPO" /src 2>/dev/null \
    || (git clone "$REPO" /src && git -C /src checkout --detach "$REF")

# Resolves to src-local or src-git. An unknown SOURCE fails the build here, by
# name, rather than silently picking one.
FROM src-${SOURCE} AS src


# --- the image ---------------------------------------------------------------
FROM base AS runtime
WORKDIR /opt/agentos

# Dependencies first, so editing source does not re-resolve the world on rebuild.
COPY --from=src /src/pyproject.toml /src/uv.lock ./
RUN uv sync --frozen --no-install-project
COPY --from=src /src ./
RUN uv sync --frozen

# What is actually in here, answerable without running it: `docker inspect` on an
# image built from a branch six weeks ago should not require guessing.
ARG SOURCE
ARG REF
LABEL org.opencontainers.image.source="https://github.com/contact9prime-lab/bento-ai-os"
LABEL org.opencontainers.image.description="Bento Box AI — a local-first agentic OS"
LABEL org.opencontainers.image.licenses="MIT"
LABEL ai.bento.source="${SOURCE}"
LABEL ai.bento.ref="${REF}"
RUN if [ -d .git ]; then git rev-parse HEAD > /opt/agentos/.build-ref 2>/dev/null || true; \
    else printf '%s' "${SOURCE}:${REF}" > /opt/agentos/.build-ref; fi

# Everything a person would lose if the container were deleted: config, database,
# memory, assets, the WhatsApp session. One volume, so `docker run -v` is the only
# thing standing between a test container and a real install.
ENV AGENTOS_HOME=/data
VOLUME ["/data"]
EXPOSE 8321

# Any HTTP answer means the server is up. NOT `curl -f`: a machine with accounts
# answers 401 until somebody signs in, and that is a healthy server, not a sick one.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8321/api/platform \
      | grep -qE '^[234]' || exit 1

# From the BUILD CONTEXT, not from `src`. How the image boots is a property of the
# image, not of the revision inside it — and taking it from the cloned tree meant
# `SOURCE=git REF=<anything older than this file>` produced an image that could not
# start at all:
#
#   [FATAL tini (7)] exec /opt/agentos/packaging/docker-entrypoint.sh failed
#
# which says nothing about refs. The context always has it, because it sits next to
# this Dockerfile; a context that genuinely lacks it fails at BUILD time, by name.
# One file either way, so there is nothing to drift.
COPY packaging/docker-entrypoint.sh /usr/local/bin/bento-entrypoint

# tini, because the agent starts child processes (MCP servers, the WhatsApp Node
# bridge, shell commands) and PID 1 in a container does not reap orphans.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/bento-entrypoint"]
