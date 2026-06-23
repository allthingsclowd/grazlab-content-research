"""Cross-run dedup — don't reheat a story covered in the last few days.

Two halves, lifted from the sites and generalised:

* **Keying** — ``story_key_set`` (craicgpt ``curation.story_key_set``) and
  ``drop_covered`` filter candidates whose normalised url/title collide with a set
  of already-covered keys. Matches :meth:`Candidate.keys` so the keys are shared.
* **A dated covered-store** — ``load_covered`` / ``record_covered`` (geek
  ``research/memory.py``, generalised from cve-ids to arbitrary candidate keys): a
  tiny S3 record mapping each covered key to the date it last ran, with a recency
  window and a retention prune. Injectable get/put so it unit-tests without S3.

Per-site published-edition shapes differ, so the site maps its editions to
(title, url) pairs and feeds them through ``story_key_set``; the library owns the
mechanics, not the edition schema.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

from grazlab_content_research.candidate import Candidate

logger = logging.getLogger(__name__)

COVERED_KEY = "working/research/_covered.json"


def _normalise_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", (title or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def story_key_set(title: str, url: str) -> set[str]:
    """The dedup keys for a story: its normalised URL and normalised title.

    Mirrors craicgpt ``curation.story_key_set`` and :meth:`Candidate.keys` so the
    covered-key set and a candidate's keys are directly comparable.
    """
    keys: set[str] = set()
    u = (url or "").strip().rstrip("/").lower()
    if u:
        keys.add(f"url:{u}")
    t = _normalise_title(title or "")
    if t:
        keys.add(f"title:{t}")
    return keys


def drop_covered(candidates: list[Candidate], covered_keys: set[str]) -> list[Candidate]:
    """Drop candidates whose keys intersect ``covered_keys`` (already published)."""
    return [c for c in candidates if not (c.keys() & covered_keys)]


def _days_between(a: str, b: str) -> int:
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def load_covered(
    *,
    today: str,
    within_days: int = 3,
    get: Callable[[str], dict[str, Any]] | None = None,
    store_key: str = COVERED_KEY,
) -> frozenset[str]:
    """Keys covered within the last ``within_days`` (excluding ``today``).

    Missing/unreadable store → empty set (first run, or an S3 hiccup: degrade to
    'nothing covered', never crash the selection).
    """
    fetch = get or _default_get
    try:
        covered = fetch(store_key).get("covered", {})
    except Exception as exc:  # noqa: BLE001 — no memory yet ≠ a failure
        logger.info("[recency] no covered store (%s) — treating as empty", exc)
        return frozenset()
    recent = {
        key
        for key, date in covered.items()
        if date != today and _days_between(date, today) <= within_days
    }
    return frozenset(recent)


def record_covered(
    date: str,
    keys: Iterable[str],
    *,
    get: Callable[[str], dict[str, Any]] | None = None,
    put: Callable[[str, dict[str, Any]], Any] | None = None,
    retain_days: int = 30,
    store_key: str = COVERED_KEY,
) -> dict[str, str]:
    """Mark ``keys`` as covered on ``date``; prune entries older than
    ``retain_days`` so the store stays small. Returns the new covered map."""
    fetch = get or _default_get
    store = put or _default_put
    try:
        covered = dict(fetch(store_key).get("covered", {}))
    except Exception:  # noqa: BLE001 — first write
        covered = {}
    for key in keys:
        if key:
            covered[key] = date
    covered = {k: d for k, d in covered.items() if _days_between(d, date) <= retain_days}
    store(store_key, {"covered": covered})
    return covered


def _default_get(key: str) -> dict[str, Any]:
    raise NotImplementedError(
        "recency.load_covered/record_covered need an injected get/put (S3 helper) — "
        "the library doesn't bind an S3 client"
    )


def _default_put(key: str, payload: dict[str, Any]) -> str:
    raise NotImplementedError(
        "recency.load_covered/record_covered need an injected get/put (S3 helper) — "
        "the library doesn't bind an S3 client"
    )
