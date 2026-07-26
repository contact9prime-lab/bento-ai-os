#!/usr/bin/env python3
"""Assemble agentos/ui/index.html from agentos/ui/src/.

Zero-dependency concatenator. The shipped artifact stays a single file the
server serves unchanged; src/ is only a development-time decomposition.

Usage:  python -m agentos.ui.build          # write index.html
        python -m agentos.ui.build --check  # exit 1 if index.html is stale
"""
from __future__ import annotations

import pathlib
import sys

UI = pathlib.Path(__file__).resolve().parent
SRC = UI / "src"
OUT = UI / "index.html"


def _parts(sub: str) -> list[pathlib.Path]:
    return sorted((SRC / sub).glob("*"), key=lambda p: p.name)


def assemble() -> str:
    pieces: list[str] = [(SRC / "head.html").read_text()]
    pieces.append("<style>\n")
    pieces += [p.read_text() for p in _parts("css")]
    pieces.append("</style>\n</head>\n<body>\n")
    pieces.append((SRC / "shell.html").read_text())
    pieces.append("<script>\n")
    pieces += [p.read_text() for p in _parts("js")]
    pieces.append("</script>\n</body>\n</html>\n")
    return "".join(pieces)


def main(argv: list[str]) -> int:
    html = assemble()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != html:
            print("index.html is stale — run: python -m agentos.ui.build", file=sys.stderr)
            return 1
        print("index.html is up to date")
        return 0
    OUT.write_text(html)
    print(f"wrote {OUT} ({len(html)//1024} KB from {len(list(_parts('css')))} css + {len(list(_parts('js')))} js parts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
