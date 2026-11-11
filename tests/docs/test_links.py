"""Check local Markdown destinations and fragments without network access."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]


def _prose(text: str) -> str:
    return re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", text, flags=re.MULTILINE | re.DOTALL)


def _destinations(text: str) -> Iterator[str]:
    # Include inline links/images, reference definitions and HTML links/images.
    prose = _prose(text)
    for match in re.finditer(r"!?\[[^\]\n]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)", prose):
        yield match[1]
    for match in re.finditer(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", prose, re.MULTILINE):
        yield match[1]
    for match in re.finditer(r"(?:href|src)=[\"']([^\"']+)[\"']", prose):
        yield match[1]


def _anchors(path: Path) -> set[str]:
    text = _prose(path.read_text(encoding="utf-8"))
    anchors = set(re.findall(r"(?:id|name)=[\"']([^\"']+)[\"']", text))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", text, re.MULTILINE):
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\-\s]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


@pytest.mark.parametrize("page", PAGES, ids=lambda path: str(path.relative_to(ROOT)))
def test_relative_links_resolve(page: Path) -> None:
    for destination in _destinations(page.read_text(encoding="utf-8")):
        url = urlsplit(destination)
        if url.scheme or url.netloc:
            continue
        target = (page.parent / unquote(url.path)).resolve() if url.path else page
        assert target.is_relative_to(ROOT), f"{page}: link leaves the repository: {destination}"
        assert target.exists(), f"{page}: missing {destination}"
        if url.fragment and target.suffix == ".md":
            assert unquote(url.fragment) in _anchors(target), (
                f"{page}: missing anchor {destination}"
            )
