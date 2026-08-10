"""The curated catalogue: first-party MCP servers the public registry does not carry.

Store → Discover is fed by `registry.modelcontextprotocol.io`, and that registry is
a *community publishing* registry: a vendor only appears in it if the vendor chose to
publish there. Most of the popular ones did not. Measured against the live API:

    search "higgsfield"  -> 0 results
    search "canva"       -> third-party knock-offs and Canvas-LMS noise, no official
                            server and no remote URL among them

Their servers are real and running — they are just announced on the vendor's own
domain instead. No amount of better searching finds them, so the fix is not a
better query: it is knowing they exist.

Hence this file. Each entry is a server that:

- **was probed live** before being added (an MCP `initialize` POST, plus the OAuth
  discovery documents). Nothing goes in this list on the strength of a blog post.
- **supports Dynamic Client Registration**, so connecting is one click and the user
  never creates an OAuth app or pastes a key. An entry that needs hand-made
  credentials is not one click, and shipping it here would put a control on screen
  that cannot do what the surrounding controls do. `mcp.stripe.com` is real and
  deliberately absent for exactly this reason.

Entries are merged into Discover's results, ranked above registry hits, and install
through the same path as anything else (`mcp_store.to_conf` understands the shape).

Keeping this list honest is the maintenance cost. `tests/test_mcp_catalog.py` checks
the shape offline; `packaging/dev/probe-catalog.sh` re-probes the endpoints for real
and is the thing to run when an entry is suspected of having rotted.

## A known expiry date on the DCR rule

Canva's own docs (canva.dev/docs/mcp) now describe DCR as **deprecated**, kept for
backward compatibility, with **CIMD** (Client ID Metadata Documents) as the preferred
route: the `client_id` is an HTTPS URL serving a JSON descriptor of the client, so the
authorisation server reads who we are instead of us registering each time.

DCR still works — probed the day this shipped, and probe-catalog.sh will say the day it
stops. But the direction of travel is away from it, and other vendors will follow.
Supporting CIMD is not a code problem: the SDK already takes a `client_metadata_url`,
and `mcp_oauth.provider_for` would pass it. It is that CIMD needs a **stable public
HTTPS URL** to serve the descriptor from, which a local-first OS on somebody's laptop
does not have. That makes it a product decision — a URL on a project-controlled domain,
shipped as a constant — rather than something to quietly invent here.
"""

from __future__ import annotations

# Categories, in the order Discover shows them. "Media & creative" leads because it
# is the one the OS gained a reason for when the media bridge landed: a server that
# returns an image is now worth installing, where before its output was discarded.
CATEGORIES = [
    ("media", "Media & creative"),
    ("productivity", "Productivity"),
    ("developer", "Developer"),
]

#: Curated first-party servers. `remote_url` + `auth: "oauth"` is the whole config —
#: no keys, no env, no package to install.
CATALOG: list[dict] = [
    {
        "key": "higgsfield",
        "title": "Higgsfield",
        "registry_name": "ai.higgsfield/higgsfield",
        "category": "media",
        "vendor": "Higgsfield AI",
        "homepage": "https://higgsfield.ai",
        "remote_url": "https://mcp.higgsfield.ai/mcp",
        "description": "Generate video, images, audio and 3D; upscale, reframe, "
                       "remove backgrounds, and publish the result.",
    },
    {
        "key": "canva",
        "title": "Canva",
        "registry_name": "com.canva/canva",
        "category": "media",
        "vendor": "Canva",
        "homepage": "https://www.canva.com",
        "remote_url": "https://mcp.canva.com/mcp",
        "description": "Create and edit designs, work with brand templates and "
                       "folders, and export finished artwork.",
    },
    {
        "key": "replicate",
        "title": "Replicate",
        "registry_name": "com.replicate/replicate",
        "category": "media",
        "vendor": "Replicate",
        "homepage": "https://replicate.com",
        "remote_url": "https://mcp.replicate.com/mcp",
        "description": "Run thousands of open image, video and audio models, and "
                       "keep the outputs as assets.",
    },
    {
        "key": "fal",
        "title": "fal",
        "registry_name": "ai.fal/fal",
        "category": "media",
        "vendor": "fal.ai",
        "homepage": "https://fal.ai",
        "remote_url": "https://mcp.fal.ai/mcp",
        "description": "Fast hosted generative media — image, video and audio "
                       "models behind one endpoint.",
    },
    {
        "key": "figma",
        "title": "Figma",
        "registry_name": "com.figma/figma",
        "category": "media",
        "vendor": "Figma",
        "homepage": "https://figma.com",
        "remote_url": "https://mcp.figma.com/mcp",
        "description": "Read designs, inspect frames and components, and turn a "
                       "file into something the agent can build from.",
    },
    {
        "key": "notion",
        "title": "Notion",
        "registry_name": "com.notion/notion",
        "category": "productivity",
        "vendor": "Notion",
        "homepage": "https://notion.so",
        "remote_url": "https://mcp.notion.com/mcp",
        "description": "Search, read and write pages and databases in a Notion "
                       "workspace.",
    },
    {
        "key": "linear",
        "title": "Linear",
        "registry_name": "com.linear/linear",
        "category": "productivity",
        "vendor": "Linear",
        "homepage": "https://linear.app",
        "remote_url": "https://mcp.linear.app/mcp",
        "description": "Read and file issues, move them through a workflow, and "
                       "see what a team is working on.",
    },
]

_BY_NAME = {e["registry_name"]: e for e in CATALOG}
_BY_KEY = {e["key"]: e for e in CATALOG}


def _as_candidate(entry: dict) -> dict:
    """A catalogue entry in the exact shape `mcp_store._normalize` produces.

    Same shape means Discover, `to_conf` and the install path need no special case:
    a curated server installs through the identical code path as a registry one.
    The extra keys (`curated`, `category`, `title`, `auth`) are additive, and the UI
    is the only thing that reads them.
    """
    return {
        "key": entry["key"],
        "registry_name": entry["registry_name"],
        "description": entry["description"],
        "version": "",
        "homepage": entry["homepage"],
        "registry_type": "",
        "identifier": "",
        "runtime_hint": "",
        "remote_url": entry["remote_url"],
        "remote_type": "streamable-http",
        "remote_headers": [],
        "env": [],
        # --- curated-only, additive ---
        "curated": True,
        "auth": "oauth",
        "category": entry["category"],
        "category_title": dict(CATEGORIES).get(entry["category"], ""),
        "title": entry["title"],
        "vendor": entry["vendor"],
    }


def all_candidates() -> list[dict]:
    """The whole catalogue, in declaration order."""
    return [_as_candidate(e) for e in CATALOG]


def get(registry_name: str) -> dict | None:
    """Look one up by registry name (what install posts) or by short key."""
    entry = _BY_NAME.get(registry_name) or _BY_KEY.get(registry_name)
    return _as_candidate(entry) if entry else None


def search(query: str, limit: int = 30) -> list[dict]:
    """Match the catalogue against a query.

    An empty query returns everything: with no search term Discover is a storefront,
    and a storefront that shows nothing until you type teaches people there is
    nothing there. Ranking mirrors `mcp_store.search_local` so merged results
    interleave sensibly rather than by two different notions of "good match".
    """
    q = (query or "").strip().lower()
    words = q.split()
    scored = []
    for entry in CATALOG:
        cand = _as_candidate(entry)
        hay = " ".join([entry["title"], entry["key"], entry["vendor"],
                        entry["registry_name"], entry["description"],
                        cand["category_title"]]).lower()
        if not all(w in hay for w in words):
            continue
        key = entry["key"].lower()
        score = (0 if key == q else
                 1 if q and key.startswith(q) else
                 2 if q and q in key else 3)
        scored.append((score, entry["title"].lower(), cand))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in scored[:max(1, int(limit))]]


def is_curated(registry_name: str) -> bool:
    return registry_name in _BY_NAME or registry_name in _BY_KEY
