"""The base type for a crawl source. Repos own the actual lists.

A desk's source list is a ``list[FeedSource]``. The library is source-agnostic;
craicgpt keeps ``ai_sources.AI_FEEDS`` / ``fun_sources.FUN_FEEDS``, geek keeps
``sources.{ADVISORY,INTEL}_FEEDS`` + its Serper sweep queries, etc. — each maps
its own list onto ``FeedSource`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass

# Recognised crawl kinds. ``rss``/``atom`` parse identically (namespace-agnostic);
# ``youtube`` is an Atom feed that also carries media:statistics views; the
# ``serper-*`` kinds are query strings resolved by the Serper crawler, not URLs.
FEED_KINDS = frozenset({"rss", "atom", "youtube", "serper-news", "serper-video"})


@dataclass(frozen=True)
class FeedSource:
    """One place to crawl: a name (used as attribution), a url/query, and a kind."""

    name: str
    url: str
    kind: str = "rss"
    desk: str = ""
