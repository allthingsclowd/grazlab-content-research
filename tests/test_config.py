"""The shared config reads LiteLLM/generation knobs from the environment."""

from grazlab_content_research.config import WEB_USER_AGENT, ResearchConfig


def test_litellm_base_url_defaults_to_a_local_proxy():
    # No private infrastructure baked into the public default — point it at your
    # own endpoint via LITELLM_BASE_URL.
    assert ResearchConfig().litellm_base_url == "http://localhost:4000/v1"


def test_litellm_base_url_is_env_overridable(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.example/v1")
    assert ResearchConfig().litellm_base_url == "https://proxy.example/v1"


def test_generation_defaults_are_env_overridable(monkeypatch):
    monkeypatch.setenv("GEN_TEMPERATURE", "0.7")
    monkeypatch.setenv("GEN_MAX_TOKENS", "8192")
    cfg = ResearchConfig()
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 8192


def test_web_user_agent_is_a_real_browser_not_a_bot():
    # A bot UA gets blocked / 429'd when fetching feeds and validating links.
    assert "Mozilla/5.0" in WEB_USER_AGENT
    assert "bot" not in WEB_USER_AGENT.lower()
