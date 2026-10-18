"""The agent's markdown, as Telegram shows it.

Replies went out as plain text, so every `**India**` arrived on the phone with its stars and
every bullet as a dash. Telegram reads a small HTML set (b, i, code, pre, a, blockquote), so
the reply is converted to that: escaped first, then only the shapes below are turned into tags.
Anything else stays the text it was. Stdlib only, free of HTTP, like comic.py.
"""

from __future__ import annotations

import html
import re

_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITAL = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_HEAD = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.M)
_QUOTE = re.compile(r"^&gt;\s?(.*)$", re.M)


def to_html(text: str) -> str:
    """Markdown to Telegram's HTML. Code is kept apart first, so nothing inside it is read."""
    keep: list[str] = []

    def stash(s: str) -> str:
        keep.append(s)
        return f"\x00{len(keep) - 1}\x00"

    s = html.escape(text or "", quote=False)
    s = _FENCE.sub(lambda m: stash(f"<pre>{m.group(1).rstrip()}</pre>"), s)
    s = _CODE.sub(lambda m: stash(f"<code>{m.group(1)}</code>"), s)
    s = _LINK.sub(lambda m: stash(f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>'), s)
    s = _HEAD.sub(lambda m: f"<b>{m.group(1)}</b>", s)
    s = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", s)
    s = _ITAL.sub(lambda m: f"<i>{m.group(1)}</i>", s)
    s = _BULLET.sub(lambda m: m.group(1) + "• ", s)
    s = _QUOTE.sub(lambda m: f"<blockquote>{m.group(1)}</blockquote>", s)
    s = s.replace("</blockquote>\n<blockquote>", "\n")
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)


def chunks(text: str, size: int) -> list[str]:
    """The text cut into pieces under `size`, at a blank line, then a line, then a space,
    so no tag or code block is split across two messages."""
    out, rest = [], text or ""
    while len(rest) > size:
        cut = -1
        for sep in ("\n\n", "\n", " "):
            cut = rest.rfind(sep, 0, size)
            if cut > size // 3:
                break
        if cut <= 0:
            cut = size
        piece = rest[:cut]
        if piece.count("```") % 2:            # never inside a code block
            back = piece.rfind("```")
            if back > 0:
                cut, piece = back, rest[:back]
        out.append(piece)
        rest = rest[cut:].lstrip("\n")
    if rest or not out:
        out.append(rest)
    return out
