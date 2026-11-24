"""The reels' Instagram copy: five hashtags at most, none hidden in the first comment.

Instagram takes five hashtags per post or reel (December 2025), and the caption and the
comments share them, so a sixth is wasted or held back. packaging/dev/reel/skits/reels.py.
"""
import importlib.util
from pathlib import Path

REELS = Path(__file__).resolve().parents[1] / "packaging" / "dev" / "reel" / "skits" / "reels.py"


def _reels():
    spec = importlib.util.spec_from_file_location("reel_scripts", REELS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_reel_has_a_post_with_five_tags_at_most():
    mod = _reels()
    assert mod.MAX_TAGS == 5
    for r in mod.REELS:
        p = r["post"]
        tags = p["tags"]
        assert 1 <= len(tags) <= mod.MAX_TAGS, r["id"]
        assert len(set(tags)) == len(tags), r["id"]
        assert all(t.startswith("#") and " " not in t for t in tags), r["id"]
        assert "#" not in p["caption"] and "#" not in p["first_comment"], r["id"]
        for k in ("cover", "alt", "keywords"):
            assert p[k], (r["id"], k)
        # the first line is what shows above "more" and what search reads first
        first = p["caption"].split("\n", 1)[0]
        assert len(first) <= 125, (r["id"], len(first))
