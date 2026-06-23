"""Cross-run dedup: don't repeat a story we covered in the last few days."""

from grazlab_content_research import recency
from grazlab_content_research.candidate import Candidate


def test_story_key_set_matches_the_candidate_keying():
    c = Candidate(title="Big News!", summary="x", url="https://e.com/a/", source="E")
    assert recency.story_key_set("big news", "https://e.com/a") & c.keys()


def test_drop_covered_removes_colliding_candidates_keeps_fresh():
    a = Candidate(title="Yesterday's lead", summary="x", url="https://e.com/old", source="E")
    b = Candidate(title="Brand new", summary="y", url="https://e.com/new", source="E")
    covered = recency.story_key_set("Yesterday's lead", "https://e.com/old")
    kept = recency.drop_covered([a, b], covered)
    assert [c.title for c in kept] == ["Brand new"]


def _mem_store():
    box: dict[str, dict] = {}

    def get(key):
        return box.get(key, {})

    def put(key, payload):
        box[key] = payload
        return key

    return box, get, put


def test_record_then_load_covered_round_trips_within_window():
    _box, get, put = _mem_store()
    recency.record_covered("2026-06-22", {"url:https://e.com/a", "title:lead"}, get=get, put=put)
    loaded = recency.load_covered(today="2026-06-23", within_days=3, get=get)
    assert "url:https://e.com/a" in loaded


def test_load_covered_excludes_today_and_old_entries():
    _box, get, put = _mem_store()
    recency.record_covered("2026-06-20", {"k:old"}, get=get, put=put)
    recency.record_covered("2026-06-23", {"k:today"}, get=get, put=put)
    loaded = recency.load_covered(today="2026-06-23", within_days=1, get=get)
    assert "k:today" not in loaded  # excluded: it's today
    assert "k:old" not in loaded  # excluded: 3 days > within_days=1


def test_load_covered_degrades_to_empty_when_the_store_is_missing():
    def boom(_key):
        raise RuntimeError("S3 down")

    assert recency.load_covered(today="2026-06-23", get=boom) == frozenset()
