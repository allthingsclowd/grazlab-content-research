"""OKF v0.1 core — round-trip, conformance, and the one-shot judge flatten."""

from grazlab_content_research import okf


def test_bundle_round_trips_through_json():
    b = okf.Bundle(
        name="Run",
        concepts=[okf.Concept(concept_id="items/1", type="Candidate", title="A", body="body")],
    )
    back = okf.bundle_from_json(okf.bundle_to_json(b))
    assert back.name == "Run"
    assert back.concepts[0].concept_id == "items/1"
    assert back.concepts[0].type == "Candidate"


def test_render_concept_refuses_an_empty_type():
    import pytest

    with pytest.raises(ValueError, match="type"):
        okf.render_concept(okf.Concept(concept_id="items/1", type=""))


def test_validate_flags_a_rendered_file_with_no_type():
    bad = {"items/1.md": "---\ntitle: x\n---\nbody\n"}
    problems = okf.validate(bad)
    assert any("type" in p for p in problems)


def test_validate_passes_a_well_formed_bundle():
    b = okf.Bundle(
        name="Run", concepts=[okf.Concept(concept_id="items/1", type="Candidate", title="A")]
    )
    assert okf.validate(okf.bundle_files(b)) == []


def test_flatten_for_judge_respects_a_tight_budget():
    b = okf.Bundle(
        concepts=[
            okf.Concept(concept_id=f"items/{i}", type="Candidate", body="x" * 200)
            for i in range(10)
        ]
    )
    out = okf.flatten_for_judge(b, budget=100)
    assert len(out) <= 100
