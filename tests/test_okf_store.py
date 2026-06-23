"""The per-run artifact: candidates round-trip losslessly + an OKF bundle for grounding."""

from datetime import UTC, datetime

from grazlab_content_research import okf, okf_store
from grazlab_content_research.candidate import Candidate

CANDS = [
    Candidate(
        title="First",
        summary="s1",
        url="https://e.com/1",
        source="E",
        published=datetime(2026, 6, 22, 9, 0, tzinfo=UTC),
        desk="ai",
        extra={"views": 10},
    ),
    Candidate(title="Second", summary="s2", url="https://e.com/2", source="F", desk="ai"),
]


def test_candidates_round_trip_losslessly_through_the_artifact():
    art = okf_store.to_artifact(CANDS, name="ai 2026-06-22", concept_type="AIStory")
    back = okf_store.candidates_from_artifact(art)
    assert [c.title for c in back] == ["First", "Second"]
    assert back[0].published == datetime(2026, 6, 22, 9, 0, tzinfo=UTC)
    assert back[0].extra == {"views": 10}
    assert back[0].desk == "ai"


def test_artifact_embeds_a_conformant_okf_bundle_one_concept_per_candidate():
    art = okf_store.to_artifact(CANDS, name="run", concept_type="AIStory")
    bundle = okf_store.bundle_from_artifact(art)
    assert len(bundle.concepts) == 2
    assert all(c.type == "AIStory" for c in bundle.concepts)
    # every candidate's source link is a citation in its concept
    assert "https://e.com/1" in bundle.concepts[0].citations
    assert okf.validate(okf.bundle_files(bundle)) == []


def test_write_then_read_artifact_through_an_injected_store():
    box: dict[str, dict] = {}
    art = okf_store.to_artifact(CANDS, name="run")
    okf_store.write_artifact(art, key="working/x.okf.json", put=lambda k, v: box.__setitem__(k, v))
    got = okf_store.read_artifact(key="working/x.okf.json", get=lambda k: box[k])
    assert [c.title for c in okf_store.candidates_from_artifact(got)] == ["First", "Second"]
