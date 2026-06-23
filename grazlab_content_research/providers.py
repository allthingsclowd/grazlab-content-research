"""LiteLLM-proxy provider plus the local-first / frontier-fallback wrapper.

Lifted from thegeekwiththepeak.com (content_pipeline/providers/litellm.py).
Everything routes through the grazlab LiteLLM proxy; ``run_with_fallback`` tries
the local open-source route first and only retries on a frontier model when it
raises or fails validation — and the returned :class:`GenerationResult` records
*which* model actually ran, so published attribution stays truthful.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from grazlab_content_research.config import cfg

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def invoke_json(
    model: str,
    prompt: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 6000,
    timeout: float | None = None,
) -> Any:
    """Invoke a model and parse a JSON object/array from the reply, robustly.

    Suppresses Qwen3.6's thinking preamble (``enable_thinking: false`` — without
    it the reasoning stream eats the budget and the body is non-JSON), strips
    code fences, and extracts the outermost ``{...}``/``[...]`` so a stray
    sentence around the JSON doesn't break parsing. ``timeout`` overrides the
    default per-call deadline. Raises ValueError on no JSON.
    """
    llm = get_litellm_llm(
        model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    raw = str(llm.invoke(prompt).content).strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    starts = [p for p in (raw.find("{"), raw.find("[")) if p != -1]
    ends = [p for p in (raw.rfind("}"), raw.rfind("]")) if p != -1]
    if starts and ends:
        return json.loads(raw[min(starts) : max(ends) + 1])
    raise ValueError(f"no JSON in model reply (model={model}, {len(raw)} chars)")


@dataclass
class GenerationResult:
    """Outcome of a local-first generation attempt.

    ``model_used`` is what gets stamped into any published attribution note;
    ``error`` carries the local failure reason when ``fell_back`` is True.
    """

    output: Any
    model_used: str
    fell_back: bool
    error: str | None = None


def run_with_fallback(
    fn: Callable[[str], Any],
    *,
    local_model: str,
    fallback_model: str,
    validate: Callable[[Any], bool] | None = None,
) -> GenerationResult:
    """Run ``fn(model)`` on the local model, falling back to a frontier model.

    ``fn`` is called at most twice: once with ``local_model``, then — only on
    failure (exception or ``validate`` returning False; default is a truthiness
    check) — once with ``fallback_model``. If BOTH attempts fail the fallback's
    failure propagates — we never return a silent dud.
    """
    check = validate if validate is not None else bool

    local_error: str | None = None
    try:
        output = fn(local_model)
        if check(output):
            logger.info("[fallback] local model %s succeeded", local_model)
            return GenerationResult(output=output, model_used=local_model, fell_back=False)
        local_error = f"validation failed for output from {local_model}"
        logger.warning("[fallback] %s", local_error)
    except Exception as exc:  # noqa: BLE001 — any local failure is a fallback trigger
        local_error = f"{type(exc).__name__}: {exc}"
        logger.warning("[fallback] local model %s raised: %s", local_model, local_error)

    logger.info("[fallback] retrying on frontier model %s", fallback_model)
    output = fn(fallback_model)  # if this raises, it propagates — no silent dud
    if not check(output):
        raise RuntimeError(
            f"fallback model {fallback_model} also produced invalid output "
            f"(local failure was: {local_error})"
        )
    return GenerationResult(
        output=output,
        model_used=fallback_model,
        fell_back=True,
        error=local_error,
    )


def get_litellm_llm(
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> BaseChatModel:
    """Return a ChatOpenAI bound to the grazlab LiteLLM proxy for ``model``.

    ``model`` is a route name from the grazlab catalog, never an engine URL.
    Construction does no network I/O — the endpoint is only contacted on
    ``.invoke()``. ``extra_body`` is forwarded to the proxy.
    """
    # Imported lazily so the pure fallback logic above doesn't require the heavy
    # langchain_openai stack — keeps unit tests fast.
    from langchain_openai import ChatOpenAI

    logger.info("[provider:litellm] model=%s base_url=%s", model, cfg.litellm_base_url)
    kwargs: dict[str, Any] = {}
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatOpenAI(
        model=model,
        base_url=cfg.litellm_base_url,
        api_key=cfg.litellm_api_key,  # type: ignore[arg-type]
        temperature=cfg.temperature if temperature is None else temperature,
        max_tokens=cfg.max_tokens if max_tokens is None else max_tokens,  # type: ignore[call-arg]
        timeout=cfg.request_timeout if timeout is None else timeout,
        max_retries=cfg.llm_max_retries if max_retries is None else max_retries,
        **kwargs,
    )
