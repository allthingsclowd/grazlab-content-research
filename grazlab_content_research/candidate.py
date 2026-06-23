"""The unit of crawled content — always carrying a real source link.

A ``Candidate`` is what the crawl produces and the relevance loop consumes. The
hard invariant (see AGENTS.md): every candidate has a non-empty http(s) ``url``
and a non-empty ``title``; one that doesn't is never constructed, so it can never
reach a reader without attribution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _normalise_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace (craicgpt's keying)."""
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class Candidate:
    """One crawled item: title + summary + the real source URL it came from."""

    title: str
    summary: str
    url: str
    source: str
    published: datetime | None = None
    desk: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (self.title or "").strip():
            raise ValueError("candidate has no title")
        if not (self.url or "").strip().lower().startswith(("http://", "https://")):
            raise ValueError(f"candidate has no http(s) source link (url={self.url!r})")

    def keys(self) -> set[str]:
        """Dedup/recency keys — normalised URL and normalised title.

        Mirrors craicgpt ``curation.story_key_set`` so cross-run dedup keys match
        across the sites. Two candidates collide if these sets intersect.
        """
        keys: set[str] = set()
        url = self.url.strip().rstrip("/").lower()
        if url:
            keys.add(f"url:{url}")
        title_norm = _normalise_title(self.title)
        if title_norm:
            keys.add(f"title:{title_norm}")
        return keys
