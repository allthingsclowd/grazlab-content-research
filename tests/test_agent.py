"""The probabilistic adapters: per-item gauge, web-fetch refiner, Serper top-up."""

from grazlab_content_research import agent
from grazlab_content_research.candidate import Candidate

C = Candidate(
    title="New model drops",
    summary="A lab shipped X",
    url="https://e.com/x",
    source="Lab",
    desk="ai",
)


def test_gauge_prompt_carries_the_desk_brief_and_the_single_item():
    p = agent.gauge_prompt(C, "Relevant = a frontier AI release.")
    assert "frontier AI release" in p
    assert "New model drops" in p
    assert "https://e.com/x" in p


def test_make_gauge_parses_a_relevant_verdict():
    def fake_invoke(model, prompt, **kw):
        return {"relevant": True, "score": 0.92, "reason": "a real release"}

    gauge = agent.make_gauge(
        desk_prompt="…", model="local", fallback_model="frontier", invoke=fake_invoke
    )
    v = gauge(C)
    assert v.relevant is True
    assert v.score == 0.92


def test_make_gauge_marks_mid_confidence_as_borderline():
    def fake_invoke(model, prompt, **kw):
        return {"relevant": True, "score": 0.5, "reason": "maybe"}

    gauge = agent.make_gauge(
        desk_prompt="…",
        model="l",
        fallback_model="f",
        invoke=fake_invoke,
        borderline_band=(0.4, 0.6),
    )
    assert gauge(C).borderline is True


def test_make_gauge_is_fail_soft_when_both_models_fail():
    def boom(model, prompt, **kw):
        raise RuntimeError("route down")

    gauge = agent.make_gauge(desk_prompt="…", model="l", fallback_model="f", invoke=boom)
    v = gauge(C)
    assert v.relevant is False  # an un-judgeable candidate is skipped, not crashed


def test_web_fetch_refiner_reads_the_page_then_re_gauges():
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return "The article confirms the release is real and shipping today."

    def fake_invoke(model, prompt, **kw):
        assert "confirms the release" in prompt  # page text threaded into the re-gauge
        return {"relevant": True, "score": 0.85, "reason": "confirmed via page"}

    refine = agent.make_web_fetch_refiner(
        desk_prompt="…", model="l", fallback_model="f", fetch_page=fake_fetch, invoke=fake_invoke
    )
    v = refine(C)
    assert seen["url"] == "https://e.com/x"
    assert v.relevant is True


def test_make_topup_resolves_serper_queries_into_candidates():
    def fake_post(url, json, headers):
        return {"news": [{"title": "Found one", "link": "https://n.com/1", "snippet": "…"}]}

    topup = agent.make_topup(
        desk="ai", queries=["frontier model"], serper_api_key="k", post=fake_post
    )
    got = topup(3)
    assert got[0].title == "Found one"
    assert got[0].desk == "ai"
