"""LLM providers with a unified streaming interface.

Internal message format (OpenAI-style):
    {"role": "system"|"user"|"assistant", "content": str, "tool_calls": [...]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}

Assistant tool_calls entries:
    {"id": str, "name": str, "args": dict}

chat() yields event dicts:
    {"type": "text", "text": delta}
    {"type": "thinking", "text": delta}
    {"type": "tool_call", "id": str, "name": str, "args": dict}
    {"type": "finish", "reason": "stop"|"length"|...}   # why generation ended ("length" = token limit)
    {"type": "done"}

`options` (all optional): num_ctx (Ollama context window), max_tokens (output budget,
Anthropic/OpenAI-compatible). Callers that don't pass options get provider defaults.
"""

import json
import uuid
from typing import AsyncIterator

import httpx

TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)


class ProviderError(Exception):
    pass


def _tool_id() -> str:
    return "call_" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------

def _split_data_url(u: str) -> tuple[str, str]:
    """'data:image/png;base64,AAA…' -> ('image/png', 'AAA…')."""
    if u.startswith("data:") and ";base64," in u:
        head, b64 = u.split(";base64,", 1)
        return head[5:] or "image/png", b64
    return "image/png", u


def _norm_finish(reason: str) -> str:
    return "length" if reason in ("length", "max_tokens") else (reason or "stop")


async def _chat_ollama(base_url: str, model: str, messages: list, tools: list,
                       options: dict | None = None) -> AsyncIterator[dict]:
    msgs = []
    for m in messages:
        if m["role"] == "tool":
            msgs.append({"role": "tool", "content": m["content"], "tool_name": m.get("name", "")})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            msgs.append({
                "role": "assistant",
                "content": m.get("content") or "",
                "tool_calls": [
                    {"function": {"name": tc["name"], "arguments": tc["args"]}}
                    for tc in m["tool_calls"]
                ],
            })
        else:
            entry = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("images"):   # vision models take raw base64 (no data: prefix)
                entry["images"] = [_split_data_url(u)[1] for u in m["images"]]
            msgs.append(entry)

    payload = {"model": model, "messages": msgs, "stream": True}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    opts = {}
    if options and options.get("num_ctx"):
        # never rely on Ollama's silent 2-4k default: an oversized prompt gets
        # truncated without any error, and the model "forgets" its instructions
        opts["num_ctx"] = int(options["num_ctx"])
    if options and options.get("num_predict"):
        opts["num_predict"] = int(options["num_predict"])
    if opts:
        payload["options"] = opts
    # per-request keep_alive beats a server-wide OLLAMA_KEEP_ALIVE=-1 (which pins
    # every model in VRAM forever and starves whatever loads next)
    payload["keep_alive"] = (options or {}).get("keep_alive") or "30m"
    if options and options.get("think") is not None:
        # thinking models can burn the whole output budget reasoning (a 9B model can
        # spend minutes in its thinking channel and never emit the answer) — callers
        # doing structured work (builds) turn it off
        payload["think"] = bool(options["think"])

    # if the model rejects the thinking switch (HTTP 400), retry once without it
    attempts = [payload]
    if "think" in payload:
        attempts.append({k: v for k, v in payload.items() if k != "think"})
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for i, pl in enumerate(attempts):
            async with client.stream("POST", f"{base_url}/api/chat", json=pl) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")[:500]
                    if resp.status_code == 400 and "think" in body and i + 1 < len(attempts):
                        continue
                    raise ProviderError(f"Ollama HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ProviderError(f"Ollama: {chunk['error']}")
                    msg = chunk.get("message") or {}
                    if msg.get("thinking"):
                        yield {"type": "thinking", "text": msg["thinking"]}
                    if msg.get("content"):
                        yield {"type": "text", "text": msg["content"]}
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {"_raw": args}
                        yield {"type": "tool_call", "id": _tool_id(), "name": fn.get("name", ""), "args": args}
                    if chunk.get("done"):
                        yield {"type": "usage", "input": chunk.get("prompt_eval_count", 0),
                               "output": chunk.get("eval_count", 0)}
                        yield {"type": "finish", "reason": _norm_finish(chunk.get("done_reason", "stop"))}
                        yield {"type": "done"}
                        return
                break
    yield {"type": "done"}


async def ollama_models(base_url: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, LM Studio, vLLM, Groq, ...)
# ---------------------------------------------------------------------------

def _openai_messages(messages: list) -> list:
    """Our neutral history → OpenAI-compatible wire messages.

    Tool calls may carry provider baggage in `extra` (Gemini 2.5 signs every
    function call and returns HTTP 400 on the next turn if the signature is not
    replayed) — it is echoed back verbatim."""
    msgs = []
    for m in messages:
        if m["role"] == "tool":
            msgs.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            msgs.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                     **(tc.get("extra") or {})}
                    for tc in m["tool_calls"]
                ],
            })
        elif m.get("images"):
            parts = [{"type": "image_url", "image_url": {"url": u}} for u in m["images"]]
            if m.get("content"):
                parts.append({"type": "text", "text": m["content"]})
            msgs.append({"role": m["role"], "content": parts})
        else:
            msgs.append({"role": m["role"], "content": m.get("content") or ""})
    return msgs


async def _chat_openai(base_url: str, api_key: str, model: str, messages: list, tools: list,
                       options: dict | None = None) -> AsyncIterator[dict]:
    msgs = _openai_messages(messages)

    payload = {"model": model, "messages": msgs, "stream": True}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    if options and options.get("max_tokens"):
        payload["max_tokens"] = int(options["max_tokens"])

    payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    pending: dict[int, dict] = {}  # index -> {id, name, args_str}
    usage = {"input": 0, "output": 0}
    finish_reason = ""

    def flush_pending():
        out = []
        for idx in sorted(pending):
            p = pending[idx]
            try:
                args = json.loads(p["args_str"]) if p["args_str"].strip() else {}
            except Exception:
                args = {"_raw": p["args_str"]}
            call = {"type": "tool_call", "id": p["id"] or _tool_id(), "name": p["name"], "args": args}
            if p.get("extra"):
                call["extra"] = p["extra"]
            out.append(call)
        pending.clear()
        return out

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{base_url}/chat/completions", json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
                raise ProviderError(f"{base_url} HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    u = chunk["usage"]
                    usage["input"] = u.get("prompt_tokens", 0)
                    usage["output"] = u.get("completion_tokens", 0)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield {"type": "text", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    p = pending.setdefault(idx, {"id": "", "name": "", "args_str": "", "extra": {}})
                    if tc.get("id"):
                        p["id"] = tc["id"]
                    # Provider-specific baggage that MUST be echoed back verbatim.
                    # Gemini 2.5 signs every function call ("thought_signature") and
                    # rejects the next request with HTTP 400 if the signature is not
                    # replayed with the call. Keep whatever we are handed.
                    if isinstance(tc.get("extra_content"), dict):
                        p["extra"].setdefault("extra_content", {}).update(tc["extra_content"])
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        p["name"] += fn["name"]
                    if fn.get("arguments"):
                        p["args_str"] += fn["arguments"]
    for ev in flush_pending():
        yield ev
    yield {"type": "usage", **usage}
    yield {"type": "finish", "reason": _norm_finish(finish_reason)}
    yield {"type": "done"}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

async def _chat_anthropic(base_url: str, api_key: str, model: str, messages: list, tools: list,
                          options: dict | None = None) -> AsyncIterator[dict]:
    system = ""
    msgs = []
    for m in messages:
        if m["role"] == "system":
            system += ("\n\n" if system else "") + (m.get("content") or "")
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                     "content": m["content"]}
            # tool results must be user messages; merge consecutive ones
            if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                msgs[-1]["content"].append(block)
            else:
                msgs.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            content = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})
            msgs.append({"role": "assistant", "content": content})
        elif m.get("images"):
            content = []
            for u in m["images"]:
                mt, b64 = _split_data_url(u)
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": mt, "data": b64}})
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            msgs.append({"role": m["role"], "content": content})
        else:
            msgs.append({"role": m["role"], "content": m.get("content") or ""})

    max_tokens = int((options or {}).get("max_tokens") or 16384)
    payload = {"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": True}
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in tools
        ]

    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    blocks: dict[int, dict] = {}
    usage = {"input": 0, "output": 0}
    stop_reason = ""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{base_url}/v1/messages", json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
                raise ProviderError(f"Anthropic HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                t = ev.get("type")
                if t == "message_start":
                    usage["input"] = ((ev.get("message") or {}).get("usage") or {}).get("input_tokens", 0)
                elif t == "message_delta":
                    usage["output"] = (ev.get("usage") or {}).get("output_tokens", usage["output"])
                    if (ev.get("delta") or {}).get("stop_reason"):
                        stop_reason = ev["delta"]["stop_reason"]
                if t == "content_block_start":
                    cb = ev["content_block"]
                    blocks[ev["index"]] = {"type": cb["type"], "id": cb.get("id", ""),
                                           "name": cb.get("name", ""), "json": ""}
                elif t == "content_block_delta":
                    d = ev["delta"]
                    if d["type"] == "text_delta":
                        yield {"type": "text", "text": d["text"]}
                    elif d["type"] == "thinking_delta":
                        yield {"type": "thinking", "text": d.get("thinking", "")}
                    elif d["type"] == "input_json_delta":
                        blocks[ev["index"]]["json"] += d.get("partial_json", "")
                elif t == "content_block_stop":
                    b = blocks.pop(ev["index"], None)
                    if b and b["type"] == "tool_use":
                        try:
                            args = json.loads(b["json"]) if b["json"].strip() else {}
                        except Exception:
                            args = {"_raw": b["json"]}
                        yield {"type": "tool_call", "id": b["id"] or _tool_id(), "name": b["name"], "args": args}
                elif t == "message_stop":
                    yield {"type": "usage", **usage}
                    break
                elif t == "error":
                    raise ProviderError(f"Anthropic: {ev.get('error', {}).get('message', 'unknown error')}")
    yield {"type": "finish", "reason": _norm_finish(stop_reason)}
    yield {"type": "done"}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def parse_model_id(model_id: str) -> tuple[str, str]:
    """'ollama/qwen3.5:9b' -> ('ollama', 'qwen3.5:9b')"""
    if "/" not in model_id:
        return "ollama", model_id
    provider, model = model_id.split("/", 1)
    return provider, model


async def chat(cfg: dict, model_id: str, messages: list, tools: list,
               options: dict | None = None) -> AsyncIterator[dict]:
    provider, model = parse_model_id(model_id)
    p = cfg["providers"].get(provider)
    if not p:
        raise ProviderError(f"Unknown provider: {provider}")
    if provider == "ollama":
        gen = _chat_ollama(p["base_url"], model, messages, tools, options)
    elif provider == "anthropic":
        if not p.get("api_key"):
            raise ProviderError("Anthropic API key not set — add it in Settings.")
        gen = _chat_anthropic(p["base_url"], p["api_key"], model, messages, tools, options)
    elif provider == "google":
        if not p.get("api_key"):
            raise ProviderError("Google (Gemini) API key not set — add it in Settings.")
        # Gemini speaks an OpenAI-compatible dialect under /v1beta/openai
        gen = _chat_openai(openai_base(provider, p), p["api_key"], model, messages, tools, options)
    elif provider in ("openai", "custom", "openrouter", "deepseek", "moonshot"):
        if provider == "custom" and not p.get("base_url"):
            raise ProviderError("Custom provider base URL not set — add it in Settings.")
        # Name the provider the way the user chose it — somebody who picked "Kimi"
        # has no idea what a "moonshot" is, and an error naming the wrong thing sends
        # them looking in the wrong Settings row.
        _KEYED = {"openrouter": "OpenRouter", "deepseek": "DeepSeek",
                  "moonshot": "Moonshot (Kimi)"}
        if provider in _KEYED and not p.get("api_key"):
            raise ProviderError(f"{_KEYED[provider]} API key not set — add it in Settings.")
        # openai_base, not the raw setting: the URL that answers a turn has to be
        # the one the picker listed from, or a model you can see is one you cannot use.
        gen = _chat_openai(openai_base(provider, p), p.get("api_key", ""), model,
                           messages, tools, options)
    else:
        raise ProviderError(f"Unknown provider: {provider}")
    async for ev in gen:
        yield ev


async def complete(cfg: dict, model_id: str, prompt: str, system: str = "") -> str:
    """One-shot, non-streaming, tool-free completion. Used for background jobs
    (knowledge extraction, summaries) that need a plain text answer."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    parts: list[str] = []
    async for ev in chat(cfg, model_id, messages, []):
        if ev["type"] == "text":
            parts.append(ev["text"])
    return "".join(parts)


# Model families that cannot answer a turn. Listing them is not a neutral
# inconvenience — picking one produces "does not support chat" on the first
# message, which reads as the OS being broken. Deliberately conservative: it
# excludes only families that are unambiguously not chat, because hiding a model
# that CAN answer is the worse of the two mistakes.
_NOT_CHAT = ("embed", "embedding", "whisper", "tts", "dall-e", "imagen", "veo",
             "moderation", "rerank", "-image", "aqa", "stable-diffusion", "clip",
             "bge-", "gte-", "nomic-", "mxbai-")


def is_chat_model(name: str) -> bool:
    n = (name or "").lower()
    return bool(n) and not any(k in n for k in _NOT_CHAT)


def openai_base(prov: str, conf: dict) -> str:
    """The OpenAI-compatible root for a provider, exactly as `chat()` resolves it.

    Derived here rather than copied, because a listing that probes a different URL
    from the one that answers turns is worse than no listing: it would show models
    that cannot be reached, or hide ones that can.

    A bare host with no path gets `/v1`. That is what makes a stock **llama.cpp**
    (`llama-server`, port 8080) work when someone types the URL it printed at
    startup: every OpenAI-compatible server — llama.cpp, LM Studio, vLLM, Ollama's
    shim, Groq — serves the API under `/v1`, and only OpenAI's own docs make the
    user paste a URL that already contains it. Anything with a real path is left
    exactly as written, so a reverse proxy on a subpath is not second-guessed.
    """
    base = (conf.get("base_url") or "").rstrip("/")
    if not base:
        return ""
    if prov == "google":
        # Gemini speaks an OpenAI dialect under /v1beta/openai
        return base + ("" if base.endswith("/openai") else "/v1beta/openai")
    from urllib.parse import urlsplit
    if urlsplit(base).path in ("", "/"):
        return base + "/v1"
    return base


async def openai_models(base_url: str, api_key: str = "") -> list[str]:
    """Ask an OpenAI-compatible endpoint what it can run (`GET /models`).

    Every provider here except Anthropic implements it — OpenAI, OpenRouter,
    Gemini's compatibility layer, and the whole LM Studio / vLLM / llama.cpp /
    Groq family behind `custom`. Without this the picker could only show a static
    list somebody typed into config, which is why a working custom endpoint
    appeared to have no models at all: `custom.models` defaults to `[]`.

    Best-effort by design. A slow or non-conforming endpoint returns nothing and
    the caller falls back to the configured list — a model picker must never be
    the reason the OS looks broken.
    """
    if not base_url:
        return []
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = base_url.rstrip("/")
    # Try what we resolved, then the other convention. Servers disagree about
    # whether the caller supplies `/v1`, and a 404 here would look to the user
    # exactly like "this endpoint has no models" — which is the bug being fixed.
    candidates = [base] + ([base + "/v1"] if not base.endswith("/v1") else [base[:-3]])
    body = None
    for cand in candidates:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(f"{cand}/models", headers=headers)
                r.raise_for_status()
                body = r.json()
                break
        except Exception:
            continue
    if body is None:
        return []
    # {"data": [{"id": ...}]} is the spec; some local servers return a bare list.
    rows = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        mid = row.get("id") if isinstance(row, dict) else row
        if not (isinstance(mid, str) and mid.strip()):
            continue
        mid = mid.strip()
        # Gemini's compatibility layer returns canonical names ("models/gemini-3-pro").
        # Kept as the bare name so it matches what a user pins by hand and does not
        # appear twice in the picker under two spellings.
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        out.append(mid)
    return sorted(set(out))


async def available_models(cfg: dict) -> list[dict]:
    """All usable models as [{'id': 'provider/model', 'provider': ..., 'name': ...}].

    Fetched from each provider where the provider can be asked, falling back to
    whatever is pinned in config. Both are kept: a hand-pinned model that the
    endpoint does not advertise (a private deployment, an alias) must not vanish
    from the picker just because a listing succeeded.
    """
    out: list[dict] = []
    p = cfg["providers"]
    if p["ollama"].get("enabled", True):
        for m in await ollama_models(p["ollama"]["base_url"]):
            out.append({"id": f"ollama/{m}", "provider": "ollama", "name": m})
    for prov in ("anthropic", "openai", "openrouter", "google", "custom"):
        conf = p.get(prov) or {}
        if not (conf.get("enabled") and (conf.get("api_key") or prov == "custom")):
            continue
        names = list(conf.get("models") or [])
        # Anthropic has no OpenAI-style /models endpoint; the rest do.
        if prov != "anthropic":
            fetched = await openai_models(openai_base(prov, conf), conf.get("api_key", ""))
            names += [m for m in fetched if m not in names]
        for m in names:
            out.append({"id": f"{prov}/{m}", "provider": prov, "name": m})
    # A pinned model is somebody's explicit choice and is never filtered; a
    # FETCHED one is a whole catalogue, and catalogues contain embedders, image
    # and speech models that cannot answer a turn.
    return [m for m in out if is_chat_model(m["name"]) or m["name"] in _pinned(p)]


def _pinned(providers_cfg: dict) -> set:
    out = set()
    for conf in (providers_cfg or {}).values():
        for m in (conf.get("models") or []):
            out.add(m)
    return out
