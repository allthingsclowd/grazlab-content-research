"""The probabilistic adapters the relevance loop drives — the LLM-facing layer.

:mod:`relevance` owns the deterministic control flow; this module owns the
judgement that flows through it:

* **``make_gauge``** — the bulk path: ONE cheap structured call per candidate
  (``invoke_json`` through ``run_with_fallback``) → ``{relevant, score, reason}``.
  A mid-confidence score is flagged ``borderline`` for the loop to refine.
* **``make_web_fetch_refiner``** — the tie-breaker: fetch the candidate's page and
  re-gauge with that text in context, so a borderline call is decided on the
  article body, not its headline.
* **``make_deep_refiner``** — the agentic variant: a LangChain/deepagents react
  agent with ``fetch_page`` + ``web_search`` tools, for desks that want multi-step
  verification. Constructed here, exercised end-to-end (heavy, like geek's judge).
* **``make_topup``** — the thin-pool search: resolve desk queries through Serper to
  add fresh candidates when the crawl pool can't reach the threshold.

Every external call (``invoke``, ``fetch_page``, ``post``, the agent factory) is
injectable, so the bulk of this is unit-tested offline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from grazlab_content_research import crawl
from grazlab_content_research.candidate import Candidate
from grazlab_content_research.providers import invoke_json, run_with_fallback
from grazlab_content_research.relevance import Gauge, Refine, Topup, Verdict

logger = logging.getLogger(__name__)

Invoke = Callable[..., Any]

_GAUGE_INSTRUCTIONS = (
    "Judge whether THIS ONE item belongs in today's edition. Be strict: relevance "
    "is about fit to the brief, not mere topicality. Reply with ONLY a JSON object:\n"
    '{"relevant": true|false, "score": 0.0-1.0, "reason": "<one short sentence>"}'
)


def gauge_prompt(c: Candidate, desk_prompt: str) -> str:
    """The single-item relevance prompt: the desk brief + one candidate."""
    return (
        f"{desk_prompt}\n\n{_GAUGE_INSTRUCTIONS}\n\n"
        f"Item:\nTitle: {c.title}\nSummary: {c.summary}\nSource: {c.source}\nURL: {c.url}"
    )


def _parse_verdict(raw: Any, *, borderline_band: tuple[float, float]) -> Verdict:
    if not isinstance(raw, dict):
        return Verdict(relevant=False, reason="unparseable verdict")
    score = float(raw.get("score", 0) or 0)
    lo, hi = borderline_band
    return Verdict(
        relevant=bool(raw.get("relevant", False)),
        score=score,
        reason=str(raw.get("reason", "")),
        borderline=lo <= score <= hi,
    )


def make_gauge(
    *,
    desk_prompt: str,
    model: str,
    fallback_model: str,
    borderline_band: tuple[float, float] = (0.4, 0.6),
    invoke: Invoke | None = None,
) -> Gauge:
    """A per-candidate gauge: one structured, local-first call → :class:`Verdict`.

    Fail-soft: if both the local and fallback routes fail, the candidate is judged
    not-relevant (skipped, never crashing the loop) and the failure is logged.
    """
    inv = invoke or invoke_json

    def gauge(c: Candidate) -> Verdict:
        prompt = gauge_prompt(c, desk_prompt)
        try:
            result = run_with_fallback(
                lambda m: inv(m, prompt),
                local_model=model,
                fallback_model=fallback_model,
                validate=lambda r: isinstance(r, dict) and "relevant" in r,
            )
        except Exception as exc:  # noqa: BLE001 — un-judgeable → skip, not crash
            logger.warning("[agent] gauge failed for %s: %s", c.url, exc)
            return Verdict(relevant=False, reason=f"gauge error: {exc}")
        return _parse_verdict(result.output, borderline_band=borderline_band)

    return gauge


def make_web_fetch_refiner(
    *,
    desk_prompt: str,
    model: str,
    fallback_model: str,
    fetch_page: Callable[[str], str] | None = None,
    invoke: Invoke | None = None,
) -> Refine:
    """A borderline tie-breaker: fetch the page, re-gauge with its text in context."""
    inv = invoke or invoke_json
    fetch = fetch_page or _default_fetch_page

    def refine(c: Candidate) -> Verdict:
        page = fetch(c.url)
        prompt = (
            f"{gauge_prompt(c, desk_prompt)}\n\nArticle text (for your decision):\n{page[:4500]}"
        )
        try:
            result = run_with_fallback(
                lambda m: inv(m, prompt),
                local_model=model,
                fallback_model=fallback_model,
                validate=lambda r: isinstance(r, dict) and "relevant" in r,
            )
        except Exception as exc:  # noqa: BLE001 — couldn't refine → leave it out
            logger.warning("[agent] refine failed for %s: %s", c.url, exc)
            return Verdict(relevant=False, reason=f"refine error: {exc}")
        return _parse_verdict(result.output, borderline_band=(0.0, 0.0))

    return refine


def make_topup(
    *,
    desk: str,
    queries: list[str],
    serper_api_key: str = "",
    kind: str = "serper-news",
    post: crawl.Post | None = None,
) -> Topup:
    """A thin-pool search: resolve desk queries through Serper into candidates."""

    def topup(_needed: int) -> list[Candidate]:
        out: list[Candidate] = []
        for q in queries:
            out += crawl.serper_search(q, kind=kind, desk=desk, api_key=serper_api_key, post=post)
        return out

    return topup


def _default_fetch_page(url: str) -> str:
    """Fetch a page and return its readable text (~4500 chars). Lifted from
    craicgpt ``agent/tools.fetch_page`` (ported httpx → requests)."""
    import re

    import requests

    from grazlab_content_research.config import WEB_USER_AGENT

    try:
        resp = requests.get(
            url, timeout=15, allow_redirects=True, headers={"User-Agent": WEB_USER_AGENT}
        )
        resp.raise_for_status()
        text = re.sub(
            r"<script.*?</script>|<style.*?</style>",
            " ",
            resp.text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:4500]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[agent] fetch_page failed for %s: %s", url, exc)
        return f"fetch_page error: {exc}"


def make_deep_refiner(
    *,
    desk_prompt: str,
    model: str,
    create_agent: Callable[..., Any] | None = None,
    fetch_page: Callable[[str], str] | None = None,
    search: Callable[[str], str] | None = None,
) -> Refine:
    """A LangChain/deepagents react-agent tie-breaker (the agentic variant).

    Builds a one-candidate deep agent armed with ``fetch_page`` (+ optional
    ``web_search``) tools and asked to return a final relevance JSON. Mirrors how
    geek wires ``deepagents`` for its one-shot judge; exercised end-to-end rather
    than in unit tests (the agent loop hits the network/model). ``create_agent`` is
    injectable so the wiring can still be smoke-tested.
    """
    from langchain_core.tools import tool

    from grazlab_content_research.providers import get_litellm_llm

    fetch = fetch_page or _default_fetch_page

    @tool
    def read_page(url: str) -> str:
        """Fetch a candidate's page and return its readable text."""
        return fetch(url)

    tools = [read_page]
    if search is not None:

        @tool
        def web_search(query: str) -> str:
            """Search the web for corroborating coverage of a claim."""
            return search(query)

        tools.append(web_search)

    factory = create_agent or _default_create_deep_agent
    system_prompt = (
        f"{desk_prompt}\n\nYou are deciding if ONE item belongs in today's edition. "
        "Use read_page (and web_search if available) to verify, then reply with ONLY "
        '{"relevant": true|false, "score": 0.0-1.0, "reason": "…"}.'
    )

    def refine(c: Candidate) -> Verdict:
        llm = get_litellm_llm(model, temperature=0)
        agent = factory(model=llm, system_prompt=system_prompt, tools=tools)
        user_msg = {"role": "user", "content": gauge_prompt(c, desk_prompt)}
        try:
            out = agent.invoke({"messages": [user_msg]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[agent] deep refine failed for %s: %s", c.url, exc)
            return Verdict(relevant=False, reason=f"deep refine error: {exc}")
        return _parse_verdict(_extract_json(out), borderline_band=(0.0, 0.0))

    return refine


def _default_create_deep_agent(*, model: Any, system_prompt: str, tools: list[Any]) -> Any:
    from deepagents import create_deep_agent

    return create_deep_agent(model=model, system_prompt=system_prompt, tools=tools)


def _extract_json(agent_output: Any) -> Any:
    """Pull the final assistant message's JSON object out of a react-agent result."""
    import json

    msgs = agent_output.get("messages", []) if isinstance(agent_output, dict) else []
    text = ""
    for m in reversed(msgs):
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        if content:
            text = str(content)
            break
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(text[s : e + 1])
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}
