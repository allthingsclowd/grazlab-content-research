"""A Candidate always carries a real source link — the hard invariant."""

import pytest

from grazlab_content_research.candidate import Candidate


def test_a_candidate_with_a_real_http_url_is_constructible():
    c = Candidate(
        title="A thing happened", summary="…", url="https://example.com/x", source="Example"
    )
    assert c.url == "https://example.com/x"
    assert c.extra == {}


def test_a_candidate_with_no_url_is_rejected():
    with pytest.raises(ValueError, match="source link"):
        Candidate(title="A thing happened", summary="…", url="", source="Example")


def test_a_candidate_with_a_non_http_url_is_rejected():
    with pytest.raises(ValueError, match="source link"):
        Candidate(title="A thing", summary="…", url="javascript:alert(1)", source="Example")


def test_a_candidate_with_no_title_is_rejected():
    with pytest.raises(ValueError, match="title"):
        Candidate(title="", summary="…", url="https://example.com/x", source="Example")


def test_candidates_collide_on_a_shared_normalised_title():
    # Dedup keys mirror craicgpt's story_key_set: {url:…, title:…}, collision by
    # intersection. Casing/punctuation/whitespace differences normalise away.
    a = Candidate(title="Same Story", summary="x", url="https://e.com/a", source="E")
    b = Candidate(title="same   story!", summary="y", url="https://e.com/b", source="E")
    assert a.keys() & b.keys()


def test_candidates_collide_on_a_shared_url_modulo_trailing_slash():
    a = Candidate(title="X", summary="x", url="https://e.com/a/", source="E")
    b = Candidate(title="Y", summary="y", url="https://e.com/a", source="E")
    assert a.keys() & b.keys()


def test_distinct_candidates_do_not_collide():
    a = Candidate(title="Apples", summary="x", url="https://e.com/a", source="E")
    b = Candidate(title="Oranges", summary="y", url="https://e.com/b", source="E")
    assert not (a.keys() & b.keys())
