"""End-to-end: crawl → okf_store → relevance → generate, with S3-key passing.

This is the whole engine as a unit — the RCA proof at the pipeline level: a 33-item
crawl pool with threshold 10 yields exactly 10 written items, each with its source
link, plus a conformant OKF artifact persisted to the (in-memory) store.
"""

from datetime import UTC, datetime

from grazlab_content_research import okf, okf_store, pipeline, relevance
from grazlab_content_research.desk import Desk
from grazlab_content_research.sources import FeedSource

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
DATE = "2026-06-23"


def _rss_with(n: int) -> str:
    items = "".join(
        f"<item><title>Story {i}</title><link>https://e.com/{i}</link>"
        f"<description>Summary {i}</description>"
        f"<pubDate>Tue, 23 Jun 2026 1{i % 10}:00:00 GMT</pubDate></item>"
        for i in range(n)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _store():
    box: dict[str, dict] = {}
    return box, (lambda k, v: box.__setitem__(k, v)), (lambda k: box[k])


def _desk():
    return Desk(
        name="ai",
        sources=[FeedSource(name="Feed", url="https://e.com/feed", kind="rss", desk="ai")],
        threshold=10,
        relevance_prompt="Relevant = an AI story.",
        generate_prompt="Write a punchy short.",
        model="local",
        fallback_model="frontier",
        okf_concept_type="AIStory",
        max_per_feed=50,  # one test feed stands in for many real ones
    )


def _all_relevant(_c):
    return relevance.Verdict(relevant=True, score=0.9, reason="on-topic")


def _fake_write(prompt):
    return {"title": "Written", "body": "A short piece."}


def test_full_desk_pipeline_yields_exactly_threshold_items_with_source_links():
    box, put, get = _store()
    desk = _desk()
    result = pipeline.run_desk(
        desk,
        date=DATE,
        put_json=put,
        get_json=get,
        fetch=lambda _u: _rss_with(33),
        now=NOW,
        gauge=_all_relevant,
        generate=_fake_write,
    )
    written = get(result["written_key"])["items"]
    assert len(written) == 10
    assert all(it["source_url"].startswith("https://e.com/") for it in written)
    assert all(it["title"] == "Written" for it in written)


def test_pipeline_persists_a_conformant_okf_artifact_for_grounding():
    box, put, get = _store()
    desk = _desk()
    pipeline.run_desk(
        desk,
        date=DATE,
        put_json=put,
        get_json=get,
        fetch=lambda _u: _rss_with(33),
        now=NOW,
        gauge=_all_relevant,
        generate=_fake_write,
    )
    okf_key = pipeline.working_key(DATE, "ai", "okf")
    artifact = get(okf_key)
    bundle = okf_store.bundle_from_artifact(artifact)
    assert len(bundle.concepts) == 33  # the FULL pool is grounded, not just the selected
    assert all(c.type == "AIStory" for c in bundle.concepts)
    assert okf.validate(okf.bundle_files(bundle)) == []


def test_stages_pass_state_through_s3_keys():
    box, put, get = _store()
    desk = _desk()
    c = pipeline.stage_crawl(desk, date=DATE, put_json=put, fetch=lambda _u: _rss_with(5), now=NOW)
    assert c["count"] == 5
    o = pipeline.stage_okf_store(
        desk, date=DATE, get_json=get, put_json=put, candidates_key=c["candidates_key"]
    )
    r = pipeline.stage_relevance(
        desk, date=DATE, get_json=get, put_json=put, okf_key=o["okf_key"], gauge=_all_relevant
    )
    assert r["count"] == 5  # only 5 in the pool, threshold 10 → all 5, exhausted
    assert r["exhausted"] is True
    w = pipeline.stage_generate(
        desk,
        date=DATE,
        get_json=get,
        put_json=put,
        selected_key=r["selected_key"],
        generate_fn=_fake_write,
    )
    assert w["count"] == 5
