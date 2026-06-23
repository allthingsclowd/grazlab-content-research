"""Deterministic discovery of recent candidates from feeds and Serper queries.

Lifted from craicgpt.ie (research/feeds.py) — RSS/Atom/YouTube parsing, the
resilient retrying fetch (``_RETRYABLE_STATUS`` + backoff), and the recency
window — plus a Serper news/video crawler (``qdr:d`` = last-24h) for the geek
sweep + the AI-desk video gap. Stdlib XML parsing only; network I/O (``fetch``
for feeds, ``post`` for Serper) is injected so this is unit-testable offline.

Per-feed failures degrade gracefully (a dead feed is skipped, loudly logged), but
a crawl that yields **zero** candidates raises :class:`CrawlEmpty` — a thin pool
must fail its stage loudly, never publish silently.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

from grazlab_content_research.candidate import Candidate
from grazlab_content_research.config import WEB_USER_AGENT, cfg
from grazlab_content_research.sources import FeedSource

logger = logging.getLogger(__name__)

# ``url -> raw feed XML`` (or None when the feed is missing / unreachable).
FetchText = Callable[[str], str | None]
# ``(url, json, headers) -> parsed response dict`` for the Serper crawler.
Post = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]

SERPER_ENDPOINT = "https://google.serper.dev/search"


class CrawlEmpty(RuntimeError):
    """Raised when a crawl gathers no candidates at all — fail loudly, don't publish."""


class _TransientFetch(Exception):
    """A retryable feed-fetch failure (timeout / 429 / 5xx)."""


# Statuses worth a retry: rate-limit + transient server errors. A burst of feed
# requests can momentarily trip 429; one retry with backoff recovers it.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _fetch_text_once(url: str) -> str | None:
    """ONE fetch attempt: text on 200; None on a permanent failure (404/403);
    raise :class:`_TransientFetch` on a retryable one (network error / 429 / 5xx)."""
    import requests

    try:
        r = requests.get(
            url,
            timeout=12,
            allow_redirects=True,
            headers={
                "User-Agent": WEB_USER_AGENT,
                "Accept": (
                    "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
                ),
            },
        )
    except Exception as exc:  # noqa: BLE001 — network/TLS/timeout → retryable
        raise _TransientFetch(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code == 200:
        return r.text
    if r.status_code in _RETRYABLE_STATUS:
        raise _TransientFetch(f"HTTP {r.status_code}")
    return None  # permanent — caller skips this feed


def _retrying_fetch(
    once: Callable[[str], str | None],
    url: str,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] | None = None,
) -> str | None:
    """Retry ``once(url)`` on transient failures with exponential backoff, logging
    each failure so a feed never fails silently. Injectable ``once``/``sleep``."""
    import time as _time

    sleep = sleep or _time.sleep
    for i in range(attempts):
        try:
            return once(url)  # 200 text OR permanent None — both terminal
        except _TransientFetch as exc:
            if i < attempts - 1:
                logger.warning(
                    "[crawl] transient fetch failure %s (%s) — retry %d/%d",
                    url,
                    exc,
                    i + 1,
                    attempts - 1,
                )
                sleep(base_delay * (2**i))
            else:
                logger.warning("[crawl] GAVE UP on %s after %d attempts: %s", url, attempts, exc)
    return None


def _default_fetch_text(url: str) -> str | None:
    return _retrying_fetch(_fetch_text_once, url)


def _local(tag: str) -> str:
    """Strip an XML namespace: ``{http://www.w3.org/2005/Atom}entry`` -> ``entry``."""
    return tag.rsplit("}", 1)[-1].lower()


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _parse_dt(s: str) -> datetime | None:
    """Parse an RSS (RFC822) or Atom (ISO8601) date to an aware UTC datetime."""
    s = (s or "").strip()
    if not s:
        return None
    try:  # RSS pubDate, e.g. 'Mon, 22 Jun 2026 10:00:00 GMT'
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        pass
    try:  # Atom updated/published, e.g. '2026-06-22T09:00:00Z'
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_feed(xml_text: str, *, source: str, desk: str = "") -> list[Candidate]:
    """Parse RSS 2.0 or Atom into Candidates (tolerant, namespace-agnostic).

    Entries with no usable URL are skipped (the Candidate invariant). YouTube's
    ``<media:statistics views="N">`` is lifted into ``extra['views']``.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[Candidate] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):  # RSS <item> / Atom <entry>
            continue
        title = summary = url = guid = pub = ""
        views: int | None = None
        for child in node:
            t = _local(child.tag)
            if t == "title":
                title = _text(child)
            elif t in ("description", "summary", "content") and not summary:
                summary = _strip_html(_text(child))
            elif t == "link":
                href, rel = child.get("href"), (child.get("rel") or "alternate").lower()
                if href and rel == "alternate" or href and not url:
                    url = href
                elif _text(child):
                    url = _text(child)
            elif t == "guid" and not guid:
                guid = _text(child)
            elif t in ("pubdate", "published", "updated", "date") and not pub:
                pub = _text(child)
        for sub in node.iter():  # media:statistics can sit a few levels down
            if _local(sub.tag) == "statistics" and sub.get("views"):
                try:
                    views = int(sub.get("views"))  # type: ignore[arg-type]
                except ValueError:
                    views = None
                break
        url = url or (guid if guid.startswith("http") else "")
        if not (title and url.strip().lower().startswith(("http://", "https://"))):
            continue
        extra = {"views": views} if views is not None else {}
        items.append(
            Candidate(
                title=title,
                summary=summary[:500],
                url=url.strip(),
                source=source,
                published=_parse_dt(pub),
                desk=desk,
                extra=extra,
            )
        )
    return items


def harvest(
    sources: list[FeedSource],
    *,
    since_hours: int = 24,
    max_per_feed: int = 4,
    fetch: FetchText | None = None,
    now: datetime | None = None,
) -> list[Candidate]:
    """Fetch + parse the feed sources; return recent candidates (best-effort).

    Items newer than ``since_hours`` are kept; undated items are kept (up to
    ``max_per_feed``, feeds list newest-first). Each feed contributes at most
    ``max_per_feed``. Dead/garbled feeds are skipped and named in a warning.
    """
    fetcher = fetch or _default_fetch_text
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=since_hours)
    out: list[Candidate] = []
    failed: list[str] = []
    for src in sources:
        parsed = parse_feed(fetcher(src.url) or "", source=src.name, desk=src.desk)
        if not parsed:
            failed.append(src.name)
            continue
        kept = 0
        for c in parsed:
            if c.published is not None and c.published < cutoff:
                continue
            out.append(c)
            kept += 1
            if kept >= max_per_feed:
                break
    if failed:
        logger.warning(
            "[crawl] %d/%d feeds returned NO items: %s", len(failed), len(sources), failed
        )
    logger.info(
        "[crawl] harvested %d candidates from %d feeds (last %dh)",
        len(out),
        len(sources),
        since_hours,
    )
    return out


def serper_search(
    query: str,
    *,
    kind: str,
    desk: str = "",
    api_key: str = "",
    qdr: str = "d",
    post: Post | None = None,
    name: str = "",
) -> list[Candidate]:
    """Resolve one Serper news/video query into Candidates (last ``qdr`` window).

    ``kind`` is ``serper-news`` or ``serper-video``; ``post`` is injected for
    tests. A missing API key (or empty result) yields ``[]`` — fail-soft.
    """
    key = api_key or cfg.serper_api_key
    if not key:
        logger.warning("[crawl] no SERPER_API_KEY — skipping query %r", query)
        return []
    endpoint = "news" if kind == "serper-news" else "videos"
    result_field = "news" if kind == "serper-news" else "videos"
    poster = post or _default_post
    payload = {"q": query, "tbs": f"qdr:{qdr}"}
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}
    try:
        data = poster(f"{SERPER_ENDPOINT}/{endpoint}", payload, headers)
    except Exception as exc:  # noqa: BLE001 — a flaky search is fail-soft
        logger.warning("[crawl] serper query %r failed: %s", query, exc)
        return []
    out: list[Candidate] = []
    for r in data.get(result_field, []):
        link = (r.get("link") or "").strip()
        title = (r.get("title") or "").strip()
        if not (title and link.lower().startswith(("http://", "https://"))):
            continue
        out.append(
            Candidate(
                title=title,
                summary=(r.get("snippet") or "")[:500],
                url=link,
                source=name or r.get("source") or query,
                published=None,
                desk=desk,
                extra={"serper_query": query},
            )
        )
    return out


def _default_post(url: str, json_body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import requests

    r = requests.post(url, json=json_body, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()  # type: ignore[no-any-return]


def crawl(
    sources: list[FeedSource],
    *,
    since_hours: int = 24,
    max_per_feed: int = 4,
    fetch: FetchText | None = None,
    post: Post | None = None,
    serper_api_key: str = "",
    now: datetime | None = None,
) -> list[Candidate]:
    """Crawl all sources (feeds + Serper queries) into one candidate pool.

    Feeds and Serper queries are dispatched by ``FeedSource.kind``. The result is
    the FULL recent pool — the relevance loop, not this crawl, decides what's
    selected. Raises :class:`CrawlEmpty` if the whole pool is empty.
    """
    feed_sources = [s for s in sources if s.kind in ("rss", "atom", "youtube")]
    serper_sources = [s for s in sources if s.kind in ("serper-news", "serper-video")]

    out: list[Candidate] = []
    if feed_sources:
        out += harvest(
            feed_sources, since_hours=since_hours, max_per_feed=max_per_feed, fetch=fetch, now=now
        )
    for s in serper_sources:
        out += serper_search(
            s.url, kind=s.kind, desk=s.desk, api_key=serper_api_key, post=post, name=s.name
        )

    if not out:
        raise CrawlEmpty(
            f"crawl gathered 0 candidates from {len(sources)} sources "
            f"({len(feed_sources)} feeds, {len(serper_sources)} queries) — refusing a thin edition"
        )
    logger.info("[crawl] pool of %d candidates from %d sources", len(out), len(sources))
    return out
