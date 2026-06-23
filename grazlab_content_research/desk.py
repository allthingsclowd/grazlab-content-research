"""A Desk — the unit of reuse: one config object the engine runs identically.

Each site declares its desks (``craicgpt-ai``, ``craicgpt-fun``, ``geek-cyber``,
``paddy-diary-news``) by filling this in with its own sources, thresholds, voice
prompts and model routes. The library's pipeline does the rest the same way for
every desk. Nothing site-specific lives in the library except as a ``Desk`` value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grazlab_content_research.sources import FeedSource


@dataclass
class Desk:
    """The configuration the engine needs to produce one desk's items."""

    name: str
    sources: list[FeedSource]
    threshold: int  # how many items to select + generate
    relevance_prompt: str
    generate_prompt: str
    model: str
    fallback_model: str
    floor: int = 0  # the site's hard floor (for the site's gate; advisory here)
    okf_concept_type: str = "Candidate"
    since_hours: int = 24
    max_per_feed: int = 4
    borderline_band: tuple[float, float] = (0.4, 0.6)
    topup_queries: list[str] = field(default_factory=list)
    topup_kind: str = "serper-news"
