"""The relevance loop — draw from the FULL pool, gauge each item, STOP at threshold.

This is the RCA fix: the old single-shot path clipped the pool to 12k chars and
truncated to N with no top-up, so the count rode on one model emitting N items.
The loop here evaluates every candidate and reaches the threshold whenever the
pool holds enough relevant items.
"""

from grazlab_content_research import relevance
from grazlab_content_research.candidate import Candidate


def _pool(n: int) -> list[Candidate]:
    return [
        Candidate(
            title=f"Story {i}", summary=f"s{i}", url=f"https://e.com/{i}", source="E", desk="ai"
        )
        for i in range(n)
    ]


def _relevant(_c: Candidate) -> relevance.Verdict:
    return relevance.Verdict(relevant=True, score=0.9, reason="on-topic")


def _irrelevant(_c: Candidate) -> relevance.Verdict:
    return relevance.Verdict(relevant=False, score=0.1, reason="off-topic")


def test_rca_thirty_three_candidates_threshold_ten_selects_exactly_ten():
    sel = relevance.relevance_loop(_pool(33), threshold=10, gauge=_relevant)
    assert len(sel.selected) == 10
    assert not sel.exhausted
    # source links preserved on every selected item
    assert all(c.url.startswith("https://e.com/") for c in sel.selected)


def test_loop_stops_gauging_the_moment_the_threshold_is_reached():
    sel = relevance.relevance_loop(_pool(33), threshold=10, gauge=_relevant)
    assert sel.calls == 10  # didn't gauge all 33


def test_only_seven_relevant_of_thirty_three_yields_seven_and_flags_exhausted():
    # 7 relevant scattered among 33 — the loop finds all 7 (no clip hides them).
    relevant_ids = {3, 8, 11, 17, 22, 28, 31}

    def gauge(c):
        i = int(c.url.rsplit("/", 1)[-1])
        return relevance.Verdict(
            relevant=i in relevant_ids, score=0.9 if i in relevant_ids else 0.1, reason=""
        )

    sel = relevance.relevance_loop(_pool(33), threshold=10, gauge=gauge)
    assert len(sel.selected) == 7
    assert sel.exhausted  # below threshold → the site's floor decides what to do
    assert sel.calls == 33  # gauged the whole pool looking for more


def test_borderline_items_are_refined_before_a_decision():
    def gauge(_c):
        return relevance.Verdict(relevant=False, score=0.5, reason="unsure", borderline=True)

    def refine(_c):  # the web-fetch tie-breaker promotes it
        return relevance.Verdict(relevant=True, score=0.8, reason="confirmed via page")

    sel = relevance.relevance_loop(_pool(3), threshold=3, gauge=gauge, refine_borderline=refine)
    assert len(sel.selected) == 3


def test_randomise_is_stable_for_a_given_seed_and_varies_across_seeds():
    pool = _pool(20)
    a = relevance.randomise(pool, seed="2026-06-22")
    b = relevance.randomise(pool, seed="2026-06-22")
    c = relevance.randomise(pool, seed="2026-06-23")
    assert [x.url for x in a] == [x.url for x in b]  # stable
    assert [x.url for x in a] != [x.url for x in c]  # day-dependent
    assert {x.url for x in a} == {x.url for x in pool}  # a permutation, nothing lost


def test_select_tops_up_a_thin_pool_until_the_threshold():
    # Only 2 relevant in the crawl pool; top-up supplies more.
    base = _pool(2)
    extra = [
        Candidate(title=f"Top {i}", summary="x", url=f"https://t.com/{i}", source="T", desk="ai")
        for i in range(10)
    ]

    def topup(needed):
        return extra

    sel = relevance.select(base, threshold=5, gauge=_relevant, seed="2026-06-22", topup=topup)
    assert len(sel.selected) == 5
    assert not sel.exhausted
