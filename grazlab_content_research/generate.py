"""Per-item generation — ONE call per selected item, source link always preserved.

This replaces the single-shot "write the whole section in one JSON call" path. Each
selected candidate is written individually (``write_one``); the candidate's real
``source_url`` is **re-stamped** onto the output regardless of what the model
emits, so attribution can never drift to a hallucinated link. ``generate_all`` is
fail-soft per item: a model hiccup on one item drops that item, never the run.

Shape lifted from craicgpt ``writer.write_fun_story`` (title/body/source_url/source
+ the URL-fallback guard), generalised to any desk via an injected ``generate``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from grazlab_content_research.candidate import Candidate
from grazlab_content_research.providers import invoke_json, run_with_fallback

logger = logging.getLogger(__name__)

# One structured generation call: prompt -> ``{title, body, ...}``.
Generate = Callable[[str], dict[str, Any]]

_WRITE_INSTRUCTIONS = (
    "Write this ONE item for today's edition in the voice/brief above. Reply with "
    'ONLY a JSON object: {"title": "<headline>", "body": "<the piece>"}. Do not '
    "invent facts beyond the item; do not include a URL — the source link is added "
    "for you."
)


def generate_prompt(c: Candidate, desk_prompt: str) -> str:
    """The single-item generation prompt: the desk voice/brief + one candidate."""
    return (
        f"{desk_prompt}\n\n{_WRITE_INSTRUCTIONS}\n\n"
        f"Item:\nTitle: {c.title}\nSummary: {c.summary}\nSource: {c.source}\nURL: {c.url}"
    )


def _make_default_generate(model: str, fallback_model: str) -> Generate:
    def gen(prompt: str) -> dict[str, Any]:
        result = run_with_fallback(
            lambda m: invoke_json(m, prompt),
            local_model=model,
            fallback_model=fallback_model,
            validate=lambda r: isinstance(r, dict) and bool(r.get("body")),
        )
        return result.output  # type: ignore[no-any-return]

    return gen


def write_one(
    candidate: Candidate,
    *,
    desk_prompt: str,
    model: str,
    fallback_model: str,
    generate: Generate | None = None,
) -> dict[str, Any]:
    """Write ONE item from a selected candidate, re-stamping its source link.

    ``source_url`` is ALWAYS the candidate's real URL — a model-emitted link is
    ignored (it could point somewhere the model invented). ``source`` carries the
    candidate's attribution (the byline/credit).
    """
    gen = generate or _make_default_generate(model, fallback_model)
    data = gen(generate_prompt(candidate, desk_prompt))
    return {
        "title": data.get("title", ""),
        "body": data.get("body", ""),
        "source_url": candidate.url,  # re-stamped — never trust a model link
        "source": candidate.source,
        "desk": candidate.desk,
    }


def generate_all(
    candidates: list[Candidate],
    *,
    desk_prompt: str,
    model: str,
    fallback_model: str,
    generate: Generate | None = None,
) -> list[dict[str, Any]]:
    """Write every selected candidate; skip (don't crash on) an item that fails."""
    gen = generate or _make_default_generate(model, fallback_model)
    out: list[dict[str, Any]] = []
    for c in candidates:
        try:
            out.append(
                write_one(
                    c,
                    desk_prompt=desk_prompt,
                    model=model,
                    fallback_model=fallback_model,
                    generate=gen,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad item must not sink the run
            logger.warning("[generate] skipped %s — write failed: %s", c.url, exc)
    return out
