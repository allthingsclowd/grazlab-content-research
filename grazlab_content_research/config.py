"""Env-driven configuration — the single integration point (craicgpt/geek pattern).

Every model is a LiteLLM *route name* placed by the proxy onto the right box; we
never hard-code an engine URL. Model routes themselves are passed per call
(``run_with_fallback`` takes explicit ``local_model``/``fallback_model``) so each
site picks its own — this config only holds the proxy endpoint, generation
defaults, and the shared fetch knobs. All values are 12-factor env overridable.
"""

import os
from dataclasses import dataclass, field

# A real browser User-Agent: fetching feeds / validating links from a bot UA gets
# blocked or 429'd (craicgpt's 2026-06-04 hallucination traced back to 429s).
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ResearchConfig:
    """Proxy endpoint, generation defaults, and shared knobs for the engine."""

    # ── LiteLLM proxy (single integration point) ─────────────────────────────
    # Point this at YOUR OpenAI-compatible endpoint (a LiteLLM proxy, LM Studio,
    # vLLM, Ollama, …) via ``LITELLM_BASE_URL``. The default is a local LiteLLM
    # proxy so the library ships with no one's private infrastructure baked in.
    litellm_base_url: str = field(
        default_factory=lambda: os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
    )
    litellm_api_key: str = field(
        default_factory=lambda: os.getenv("LITELLM_API_KEY", "sk-no-key-required")
    )

    # ── Generation defaults ──────────────────────────────────────────────────
    temperature: float = field(default_factory=lambda: float(os.getenv("GEN_TEMPERATURE", "0.3")))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("GEN_MAX_TOKENS", "4096")))
    request_timeout: int = field(default_factory=lambda: int(os.getenv("GEN_TIMEOUT_S", "300")))
    # Client-level retries per call. The langchain default of 2 means a hung route
    # burns 3×timeout before failing; keep it low — the model fallback IS the retry.
    llm_max_retries: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "1")))

    # ── External services (fail-soft: unset → that path quietly degrades) ─────
    serper_api_key: str = field(default_factory=lambda: os.getenv("SERPER_API_KEY", ""))
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "eu-west-1"))


cfg = ResearchConfig()
