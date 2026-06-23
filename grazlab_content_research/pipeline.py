"""The desk pipeline — the four granular stages, with S3-key passing.

Each stage is what one Conductor SIMPLE task calls; state flows between them as S3
working keys (the geek ``research/cli.py`` convention: a stage ``put_json``s its
output under ``working/research/<date>.<desk>.<suffix>.json`` and the next stage
``get_json``s it). The stages are deterministic orchestration over injected I/O
(``fetch``/``post``/``gauge``/``generate``/``put_json``/``get_json``), so the whole
engine is unit-testable offline; ``run_desk`` chains all four for a worker that
wants to run a desk in one process.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from grazlab_content_research import agent, crawl, generate, okf_store, relevance
from grazlab_content_research.desk import Desk

logger = logging.getLogger(__name__)

WORKING_PREFIX = "working/research"

PutJson = Any  # Callable[[str, dict], Any]
GetJson = Any  # Callable[[str], dict]


def working_key(date: str, desk: str, suffix: str) -> str:
    """The S3 working key for a stage's output (matches the geek convention)."""
    return f"{WORKING_PREFIX}/{date}.{desk}.{suffix}.json"


def stage_crawl(
    desk: Desk,
    *,
    date: str,
    put_json: PutJson,
    fetch: crawl.FetchText | None = None,
    post: crawl.Post | None = None,
    serper_api_key: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Crawl the desk's sources into the FULL candidate pool (deterministic, no LLM).

    Raises :class:`crawl.CrawlEmpty` on a zero-candidate pool — the stage fails
    loudly rather than handing an empty pool downstream.
    """
    cands = crawl.crawl(
        desk.sources,
        since_hours=desk.since_hours,
        max_per_feed=desk.max_per_feed,
        fetch=fetch,
        post=post,
        serper_api_key=serper_api_key,
        now=now,
    )
    key = working_key(date, desk.name, "candidates")
    put_json(key, okf_store.dump_candidates(cands))
    return {"candidates_key": key, "count": len(cands)}


def stage_okf_store(
    desk: Desk,
    *,
    date: str,
    get_json: GetJson,
    put_json: PutJson,
    candidates_key: str,
) -> dict[str, Any]:
    """Persist the pool as a per-run OKF artifact (provenance + judge-grounding)."""
    cands = okf_store.candidates_from_artifact(get_json(candidates_key))
    artifact = okf_store.to_artifact(
        cands,
        name=f"{desk.name} {date}".strip(),
        description=f"Crawled candidate pool for the {desk.name} desk, {date}.",
        concept_type=desk.okf_concept_type,
    )
    key = working_key(date, desk.name, "okf")
    put_json(key, artifact)
    return {"okf_key": key, "count": len(cands)}


def stage_relevance(
    desk: Desk,
    *,
    date: str,
    get_json: GetJson,
    put_json: PutJson,
    okf_key: str,
    gauge: relevance.Gauge,
    refine_borderline: relevance.Refine | None = None,
    topup: relevance.Topup | None = None,
    seed: str | None = None,
) -> dict[str, Any]:
    """Randomise + gauge the pool one item at a time, stopping at ``desk.threshold``."""
    cands = okf_store.candidates_from_artifact(get_json(okf_key))
    selection = relevance.select(
        cands,
        threshold=desk.threshold,
        gauge=gauge,
        seed=seed or date,
        refine_borderline=refine_borderline,
        topup=topup,
    )
    key = working_key(date, desk.name, "selected")
    put_json(key, okf_store.dump_candidates(selection.selected))
    return {
        "selected_key": key,
        "count": len(selection.selected),
        "exhausted": selection.exhausted,
        "calls": selection.calls,
    }


def stage_generate(
    desk: Desk,
    *,
    date: str,
    get_json: GetJson,
    put_json: PutJson,
    selected_key: str,
    generate_fn: generate.Generate | None = None,
) -> dict[str, Any]:
    """Write each selected candidate individually (source link re-stamped)."""
    cands = okf_store.candidates_from_artifact(get_json(selected_key))
    items = generate.generate_all(
        cands,
        desk_prompt=desk.generate_prompt,
        model=desk.model,
        fallback_model=desk.fallback_model,
        generate=generate_fn,
    )
    key = working_key(date, desk.name, "written")
    put_json(key, {"items": items})
    return {"written_key": key, "count": len(items)}


def run_desk(
    desk: Desk,
    *,
    date: str,
    put_json: PutJson,
    get_json: GetJson,
    fetch: crawl.FetchText | None = None,
    post: crawl.Post | None = None,
    serper_api_key: str = "",
    now: datetime | None = None,
    gauge: relevance.Gauge | None = None,
    refine_borderline: relevance.Refine | None = None,
    topup: relevance.Topup | None = None,
    generate: generate.Generate | None = None,
    seed: str | None = None,
) -> dict[str, Any]:
    """Run all four stages in one process (a worker that owns the whole desk).

    Defaults the gauge (and a Serper top-up if the desk declares queries) from the
    desk config when not injected, so a caller need only supply I/O + model routes.
    """
    g = gauge or agent.make_gauge(
        desk_prompt=desk.relevance_prompt,
        model=desk.model,
        fallback_model=desk.fallback_model,
        borderline_band=desk.borderline_band,
    )
    tp = topup
    if tp is None and desk.topup_queries:
        tp = agent.make_topup(
            desk=desk.name,
            queries=desk.topup_queries,
            serper_api_key=serper_api_key,
            kind=desk.topup_kind,
            post=post,
        )

    c = stage_crawl(
        desk,
        date=date,
        put_json=put_json,
        fetch=fetch,
        post=post,
        serper_api_key=serper_api_key,
        now=now,
    )
    o = stage_okf_store(
        desk,
        date=date,
        get_json=get_json,
        put_json=put_json,
        candidates_key=c["candidates_key"],
    )
    r = stage_relevance(
        desk,
        date=date,
        get_json=get_json,
        put_json=put_json,
        okf_key=o["okf_key"],
        gauge=g,
        refine_borderline=refine_borderline,
        topup=tp,
        seed=seed,
    )
    w = stage_generate(
        desk,
        date=date,
        get_json=get_json,
        put_json=put_json,
        selected_key=r["selected_key"],
        generate_fn=generate,
    )
    logger.info(
        "[pipeline] desk=%s crawled=%d selected=%d written=%d exhausted=%s",
        desk.name,
        c["count"],
        r["count"],
        w["count"],
        r["exhausted"],
    )
    return {"crawl": c, "okf": o, "relevance": r, "generate": w, "written_key": w["written_key"]}
