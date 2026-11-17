"""Video from a description, through the one video API left, with its price said first.

Asked for as "voice and image and video agents should also be added in AI Providers in their
own section", answered "build it". Checked on the providers' pages on 2026-11-17: OpenAI shut
Sora's API down (2026-09-24) and Google replaced Veo in the Gemini API with Gemini Omni Flash
(2026-10-22), so Google's `gemini-omni-1.2-flash` on the Interactions endpoint is the provider.
What these defend: the request is the documented shape, the MP4 is read from the answer, the
price is Google's listed one, the tool asks with the cost on the card, a refusal is a sentence,
and the whole tool runs against a local stand-in (no real clip is ever bought by the suite).
"""
import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from agentos import policy, videogen
from agentos.memory import Store

ROOT = Path(__file__).resolve().parent.parent
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def test_the_request_price_and_answer_are_the_documented_ones():
    body = videogen.request("a lantern on a river", 40, "9:16", "1080p")
    assert body["model"] == "gemini-omni-1.2-flash" and body["input"] == "a lantern on a river"
    assert body["response_format"] == {"type": "video", "aspect_ratio": "9:16",
                                       "resolution": "1080p", "duration": "15s"}   # capped at 15
    assert videogen.request("x", 1, "4:3", "8k")["response_format"]["duration"] == "3s"
    assert videogen.request("x", 1, "4:3", "8k")["response_format"]["aspect_ratio"] == "16:9"
    assert videogen.cost(10, "720p") == 0.7 and videogen.cost(8, "4k") == 1.672
    assert "$0.70" in videogen.cost_words(10)
    ans = {"steps": [{"type": "model_output", "content": [
        {"type": "text", "text": "here"},
        {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(MP4).decode()}]}]}
    assert videogen.video_of(ans) == MP4 and videogen.video_of({"steps": []}) is None
    assert "refused the key" in videogen.refusal(403, {"error": {"message": "API key not valid"}})


def test_ready_says_what_is_missing():
    assert not videogen.ready({"providers": {}})[0]
    assert "Google key" in videogen.ready({"providers": {}})[1]
    assert not videogen.ready({"video": {"provider": "off"}, "providers": {"google": {"api_key": "k"}}})[0]
    assert videogen.ready({"providers": {"google": {"api_key": "k"}}})[0]
    assert set(videogen.GONE) == {"openai", "veo"}


class _Google(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _Google.seen.append((self.path, self.headers.get("x-goog-api-key"), body))
        if self.headers.get("x-goog-api-key") != "good":
            out, code = {"error": {"message": "API key not valid"}}, 403
        else:
            out, code = {"id": "i1", "steps": [{"type": "model_output", "content": [
                {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(MP4).decode()}]}]}, 200
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_the_tool_makes_a_clip_keeps_it_and_records_its_cost(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Google)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        from agentos.tools import Toolbox
        store = Store(tmp_path / "t.db")
        base = f"http://127.0.0.1:{srv.server_port}"
        sent = []

        async def bc(ev):
            sent.append(ev)
        tb = SimpleNamespace(cfg={"providers": {"google": {"api_key": "good", "base_url": base}},
                                  "video": {"resolution": "720p"}}, store=store, broadcast=bc)
        out = asyncio.run(Toolbox.generate_video(tb, "a lantern on a river", seconds=10, aspect="9:16"))
        assert out.startswith("generated video asset ") and "$0.70" in out, out
        path, key, body = _Google.seen[-1]
        assert path == "/v1beta/interactions" and key == "good"
        assert body["response_format"]["aspect_ratio"] == "9:16"
        assert sent and sent[-1]["type"] == "assets_update"
        rows = store.db.execute("SELECT * FROM usage WHERE kind='video'").fetchall()
        assert rows and abs(float(dict(rows[0]).get("cost_usd") or 0) - 0.7) < 1e-6
        tb.cfg["providers"]["google"]["api_key"] = "bad"
        out = asyncio.run(Toolbox.generate_video(tb, "x"))
        assert out.startswith("[error] Google refused the key (403)")
        tb.cfg["providers"]["google"] = {}
        assert "Google key" in asyncio.run(Toolbox.generate_video(tb, "x"))
    finally:
        srv.shutdown()


def test_it_is_gated_metered_and_on_every_face():
    assert policy._MEDIA["generate_video"] == ("media.generate", "media:video")
    assert "generate_video" in policy.LLM_TOOLS
    src = (ROOT / "agentos/tools.py").read_text()
    assert 'if name == "generate_video":' in src and '"name": "generate_video"' in src
    st = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "pGroup('Video'" in st and "s-vid-prov" in st and "|vid-|" in st
    assert "['Video','Video']" in (ROOT / "agentos/ui/src/js/11l-setsubs.js").read_text()
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert "def _video_cli" in cli and 'verb("video"' in cli
