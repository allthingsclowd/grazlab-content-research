"""The per-run artifact — the crawled pool persisted to S3 for the next stage.

Two purposes in one S3 object (``working/<date>.<desk>.okf.json``):

* a **lossless candidate list** — the inter-stage hand-off (crawl → relevance)
  across the granular Conductor boundary, restored with every field intact; and
* a **per-run OKF bundle** — one ``Concept`` per candidate (its source link as a
  citation), so the same artifact doubles as provenance and as judge-grounding.

Pure transforms plus injectable get/put — no S3 client is bound in the library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from grazlab_content_research import okf
from grazlab_content_research.candidate import Candidate


def _candidate_to_dict(c: Candidate) -> dict[str, Any]:
    return {
        "title": c.title,
        "summary": c.summary,
        "url": c.url,
        "source": c.source,
        "published": c.published.isoformat() if c.published else None,
        "desk": c.desk,
        "extra": dict(c.extra),
    }


def _candidate_from_dict(d: dict[str, Any]) -> Candidate:
    pub = d.get("published")
    return Candidate(
        title=d["title"],
        summary=d.get("summary", ""),
        url=d["url"],
        source=d.get("source", ""),
        published=datetime.fromisoformat(pub) if pub else None,
        desk=d.get("desk", ""),
        extra=dict(d.get("extra", {})),
    )


def _slug(text: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "item"


def candidate_concept(c: Candidate, i: int, *, concept_type: str = "Candidate") -> okf.Concept:
    """One crawled candidate → one OKF concept, citing its real source link."""
    return okf.Concept(
        concept_id=f"candidates/{i:02d}-{_slug(c.title)}",
        type=concept_type,
        title=c.title,
        description=c.source,
        resource=c.url,
        tags=[t for t in [c.desk, c.source] if t],
        timestamp=c.published.isoformat() if c.published else "",
        body=c.summary,
        citations=[c.url],
    )


def bundle_from_candidates(
    candidates: list[Candidate],
    *,
    name: str = "",
    description: str = "",
    concept_type: str = "Candidate",
) -> okf.Bundle:
    """An OKF bundle of the crawled pool — one concept per candidate."""
    return okf.Bundle(
        name=name,
        description=description,
        concepts=[
            candidate_concept(c, i, concept_type=concept_type) for i, c in enumerate(candidates)
        ],
    )


def to_artifact(
    candidates: list[Candidate],
    *,
    name: str = "",
    description: str = "",
    concept_type: str = "Candidate",
) -> dict[str, Any]:
    """The S3 artifact: the lossless candidate list + the derived OKF bundle."""
    bundle = bundle_from_candidates(
        candidates, name=name, description=description, concept_type=concept_type
    )
    return {
        "candidates": [_candidate_to_dict(c) for c in candidates],
        "okf": okf.bundle_to_json(bundle),
    }


def dump_candidates(candidates: list[Candidate]) -> dict[str, Any]:
    """The lossless candidate-list payload for the crawl stage's S3 key (no OKF)."""
    return {"candidates": [_candidate_to_dict(c) for c in candidates]}


def candidates_from_artifact(artifact: dict[str, Any]) -> list[Candidate]:
    """Restore the crawled pool (lossless) — the relevance loop's input.

    Reads the ``candidates`` list, so it works on both a full ``to_artifact``
    envelope and a bare ``dump_candidates`` payload.
    """
    return [_candidate_from_dict(d) for d in artifact.get("candidates", [])]


def bundle_from_artifact(artifact: dict[str, Any]) -> okf.Bundle:
    """The per-run OKF bundle — judge-grounding + provenance."""
    return okf.bundle_from_json(artifact.get("okf", {}))


PutJson = Any  # Callable[[str, dict], Any]
GetJson = Any  # Callable[[str], dict]


def write_artifact(artifact: dict[str, Any], *, key: str, put: PutJson) -> str:
    """Persist the artifact to ``key`` via an injected ``put(key, payload)``."""
    put(key, artifact)
    return key


def read_artifact(*, key: str, get: GetJson) -> dict[str, Any]:
    """Read the artifact from ``key`` via an injected ``get(key) -> dict``."""
    return get(key)  # type: ignore[no-any-return]
