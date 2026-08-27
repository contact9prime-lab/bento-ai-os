#!/usr/bin/env python3
"""Rebuild index.json from the packages on disk. The index is DERIVED, never
edited: a hand-edit would let an entry claim verified without a signature, which
is the one lie this whole repository exists to make impossible."""
import json
from pathlib import Path

from agentos import appregistry as reg

ROOT = Path(__file__).resolve().parent.parent
entries = []
for path in sorted(ROOT.glob("apps/*/*.agentapp.json")):
    pkg = json.loads(path.read_text())
    entries.append(reg.index_entry(pkg, str(path.relative_to(ROOT))))
out = {"registry": reg.REGISTRY_REPO, "format": "bento-registry-index/1",
       "apps": entries}
(ROOT / "index.json").write_text(json.dumps(out, indent=1) + "\n")
print(f"index.json: {len(entries)} app(s)")
