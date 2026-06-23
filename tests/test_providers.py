"""Local-first / frontier-fallback wrapper + robust JSON invocation."""

import pytest

from grazlab_content_research import providers


def test_run_with_fallback_uses_local_when_it_validates():
    result = providers.run_with_fallback(
        lambda model: f"out-from-{model}",
        local_model="local",
        fallback_model="frontier",
    )
    assert result.output == "out-from-local"
    assert result.model_used == "local"
    assert result.fell_back is False


def test_run_with_fallback_retries_frontier_when_local_raises():
    def fn(model):
        if model == "local":
            raise RuntimeError("local route down")
        return "frontier-output"

    result = providers.run_with_fallback(fn, local_model="local", fallback_model="frontier")
    assert result.output == "frontier-output"
    assert result.model_used == "frontier"
    assert result.fell_back is True
    assert "local route down" in (result.error or "")


def test_run_with_fallback_retries_frontier_when_local_fails_validation():
    calls = []

    def fn(model):
        calls.append(model)
        return "" if model == "local" else "good"

    result = providers.run_with_fallback(
        fn, local_model="local", fallback_model="frontier", validate=bool
    )
    assert calls == ["local", "frontier"]
    assert result.model_used == "frontier"


def test_run_with_fallback_propagates_when_both_fail():
    with pytest.raises(RuntimeError, match="boom"):
        providers.run_with_fallback(
            lambda model: (_ for _ in ()).throw(RuntimeError("boom")),
            local_model="local",
            fallback_model="frontier",
        )


def _fake_llm(reply: str):
    class _Msg:
        content = reply

    class _LLM:
        def invoke(self, _prompt):
            return _Msg()

    return _LLM()


def test_invoke_json_parses_a_fenced_object(monkeypatch):
    monkeypatch.setattr(
        providers, "get_litellm_llm", lambda *a, **k: _fake_llm('```json\n{"n": 3}\n```')
    )
    assert providers.invoke_json("any", "prompt") == {"n": 3}


def test_invoke_json_extracts_object_from_surrounding_prose(monkeypatch):
    monkeypatch.setattr(
        providers,
        "get_litellm_llm",
        lambda *a, **k: _fake_llm('Sure! {"ok": true} hope that helps'),
    )
    assert providers.invoke_json("any", "prompt") == {"ok": True}


def test_invoke_json_raises_when_there_is_no_json(monkeypatch):
    monkeypatch.setattr(providers, "get_litellm_llm", lambda *a, **k: _fake_llm("no json here"))
    with pytest.raises(ValueError, match="no JSON"):
        providers.invoke_json("any", "prompt")
