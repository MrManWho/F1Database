"""Reads CHANGELOG.md for the in-app "What's new" page."""

import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup, escape

BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
CODE = re.compile(r"`([^`]+)`")


def _inline(text):
    html = str(escape(text))
    html = CODE.sub(r"<code>\1</code>", html)
    html = BOLD.sub(r"<b>\1</b>", html)
    html = ITALIC.sub(r"<em>\1</em>", html)
    return Markup(html)


@lru_cache(maxsize=4)
def _parse(path, mtime):
    versions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            number, _, title = line[3:].partition("·")
            versions.append({"version": number.strip(), "title": title.strip(), "items": []})
        elif versions and line.startswith("- "):
            versions[-1]["items"].append({"text": _inline(line[2:]), "children": []})
        elif versions and versions[-1]["items"] and re.match(r"^\s{2,}- ", line):
            versions[-1]["items"][-1]["children"].append(_inline(line.strip()[2:]))
    return versions


def versions(base_dir):
    path = Path(base_dir) / "CHANGELOG.md"
    if not path.exists():
        return []
    return _parse(str(path), path.stat().st_mtime)
