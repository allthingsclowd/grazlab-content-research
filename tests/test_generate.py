"""Per-item generation — one call per selected item, source link always preserved."""

from grazlab_content_research import generate
from grazlab_content_research.candidate import Candidate

C = Candidate(
    title="A release", summary="lab shipped X", url="https://e.com/x", source="Lab", desk="ai"
)


def test_write_one_returns_title_body_and_restamps_the_source_link():
    def fake_gen(prompt):
        # model omits the source link entirely — the writer must put it back
        return {"title": "Lab ships X", "body": "Today a lab shipped X."}

    item = generate.write_one(
        C, desk_prompt="Write a punchy short.", model="l", fallback_model="f", generate=fake_gen
    )
    assert item["title"] == "Lab ships X"
    assert item["body"] == "Today a lab shipped X."
    assert item["source_url"] == "https://e.com/x"  # re-stamped from the candidate
    assert item["source"] == "Lab"


def test_write_one_ignores_a_model_invented_url_and_keeps_the_candidate_url():
    def fake_gen(prompt):
        return {"title": "T", "body": "B", "source_url": "https://hallucinated.example/made-up"}

    item = generate.write_one(C, desk_prompt="…", model="l", fallback_model="f", generate=fake_gen)
    assert item["source_url"] == "https://e.com/x"  # never trust a model-emitted link


def test_generate_all_writes_each_item_and_is_fail_soft():
    pool = [
        C,
        Candidate(title="Second", summary="y", url="https://e.com/2", source="L2", desk="ai"),
    ]
    calls = {"n": 0}

    def flaky_gen(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model hiccup on the first item")
        return {"title": "ok", "body": "fine"}

    items = generate.generate_all(
        pool, desk_prompt="…", model="l", fallback_model="f", generate=flaky_gen
    )
    # first item failed both attempts → skipped; second written. Never crashes the run.
    assert len(items) == 1
    assert items[0]["source_url"] == "https://e.com/2"
