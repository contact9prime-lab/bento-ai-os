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
    {"type": "done"}
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


async def _chat_ollama(base_url: str, model: str, messages: list, tools: list) -> AsyncIterator[dict]:
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

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
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
                    yield {"type": "done"}
                    return
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

async def _chat_openai(base_url: str, api_key: str, model: str, messages: list, tools: list) -> AsyncIterator[dict]:
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
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
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

    payload = {"model": model, "messages": msgs, "stream": True}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]

    payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    pending: dict[int, dict] = {}  # index -> {id, name, args_str}
    usage = {"input": 0, "output": 0}

    def flush_pending():
        out = []
        for idx in sorted(pending):
            p = pending[idx]
            try:
                args = json.loads(p["args_str"]) if p["args_str"].strip() else {}
            except Exception:
                args = {"_raw": p["args_str"]}
            out.append({"type": "tool_call", "id": p["id"] or _tool_id(), "name": p["name"], "args": args})
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
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield {"type": "text", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    p = pending.setdefault(idx, {"id": "", "name": "", "args_str": ""})
                    if tc.get("id"):
                        p["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        p["name"] += fn["name"]
                    if fn.get("arguments"):
                        p["args_str"] += fn["arguments"]
    for ev in flush_pending():
        yield ev
    yield {"type": "usage", **usage}
    yield {"type": "done"}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

async def _chat_anthropic(base_url: str, api_key: str, model: str, messages: list, tools: list) -> AsyncIterator[dict]:
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

    payload = {"model": model, "messages": msgs, "max_tokens": 8192, "stream": True}
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
                elif t == "error":
                    raise ProviderError(f"Anthropic: {ev.get('error', {}).get('message', 'unknown error')}")
                elif t == "message_stop":
                    break
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


async def chat(cfg: dict, model_id: str, messages: list, tools: list) -> AsyncIterator[dict]:
    provider, model = parse_model_id(model_id)
    p = cfg["providers"].get(provider)
    if not p:
        raise ProviderError(f"Unknown provider: {provider}")
    if provider == "ollama":
        gen = _chat_ollama(p["base_url"], model, messages, tools)
    elif provider == "anthropic":
        if not p.get("api_key"):
            raise ProviderError("Anthropic API key not set — add it in Settings.")
        gen = _chat_anthropic(p["base_url"], p["api_key"], model, messages, tools)
    elif provider in ("openai", "custom", "openrouter"):
        if provider == "custom" and not p.get("base_url"):
            raise ProviderError("Custom provider base URL not set — add it in Settings.")
        if provider == "openrouter" and not p.get("api_key"):
            raise ProviderError("OpenRouter API key not set — add it in Settings.")
        gen = _chat_openai(p["base_url"], p.get("api_key", ""), model, messages, tools)
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


async def available_models(cfg: dict) -> list[dict]:
    """All usable models as [{'id': 'provider/model', 'provider': ..., 'name': ...}]."""
    out = []
    p = cfg["providers"]
    if p["ollama"].get("enabled", True):
        for m in await ollama_models(p["ollama"]["base_url"]):
            out.append({"id": f"ollama/{m}", "provider": "ollama", "name": m})
    for prov in ("anthropic", "openai", "openrouter", "custom"):
        conf = p.get(prov) or {}
        if conf.get("enabled") and (conf.get("api_key") or prov == "custom") :
            for m in conf.get("models", []):
                out.append({"id": f"{prov}/{m}", "provider": prov, "name": m})
    return out
