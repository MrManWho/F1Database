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
    """## <version> · <title>, then optional "_Released <date>_" and "> overview" lines, then "### Section" groups
    (Added, Improved, Fixed, Security, Migration notes, Known limitations, Highlights, Action needed…) of "- " items."""
    versions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            number, _, title = line[3:].partition("·")
            versions.append({"version": number.strip(), "title": title.strip(), "items": [], "sections": [],
                             "date": "", "overview": ""})
        elif not versions:
            continue
        elif line.startswith("### "):
            versions[-1]["sections"].append({"title": line[4:].strip(), "items": []})
        elif line.startswith("_Released ") and line.rstrip().endswith("_"):
            versions[-1]["date"] = line.strip("_ ").replace("Released ", "")
        elif line.startswith("> "):
            versions[-1]["overview"] = (versions[-1]["overview"] + " " + line[2:].strip()).strip()
        elif line.startswith("- "):
            item = {"text": _inline(line[2:]), "children": []}
            versions[-1]["items"].append(item)
            if versions[-1]["sections"]:
                versions[-1]["sections"][-1]["items"].append(item)
        elif versions[-1]["items"] and re.match(r"^\s{2,}- ", line):
            versions[-1]["items"][-1]["children"].append(_inline(line.strip()[2:]))
    for v in versions:
        v["overview"] = _inline(v["overview"]) if v["overview"] else ""
        v["highlights"] = next((sec["items"] for sec in v["sections"] if sec["title"].lower() == "highlights"), [])
        v["action"] = next((sec["items"] for sec in v["sections"] if sec["title"].lower().startswith("action")), [])
    return versions


def entry(base_dir, version):
    return next((v for v in versions(base_dir) if v["version"] == version), None)


def versions(base_dir):
    path = Path(base_dir) / "CHANGELOG.md"
    if not path.exists():
        return []
    return _parse(str(path), path.stat().st_mtime)
