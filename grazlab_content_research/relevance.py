"""The relevance loop — the deterministic orchestration at the core of the engine.

The old single-shot path failed structurally: it clipped the candidate pool to a
fixed character budget, asked one model for N items, and truncated with no top-up,
so the count depended entirely on one response over a clipped pool. This loop
instead draws from the **full** pool, gauges each candidate (one cheap injected
call), and **stops at the threshold** — so it reaches N whenever the pool holds N
relevant items.

Everything here is deterministic and fully unit-tested: ``gauge`` (the LLM-backed
relevance judgement), ``refine_borderline`` (the web-fetch tie-breaker), and
``topup`` (the thin-pool search) are all **injected** — their real, probabilistic
implementations live in :mod:`agent`. The shuffle is seeded by the run date, so
the same day reproduces the same selection.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

from grazlab_content_research.candidate import Candidate

logger = logging.getLogger(__name__)


@dataclass
class Verdict:
    """One candidate's relevance judgement."""

    relevant: bool
    score: float = 0.0
    reason: str = ""
    borderline: bool = False


@dataclass
class Selection:
    """The outcome of a relevance loop."""

    selected: list[Candidate]
    calls: int = 0
    exhausted: bool = False  # True when fewer than ``threshold`` were found


Gauge = Callable[[Candidate], Verdict]
Refine = Callable[[Candidate], Verdict]
Topup = Callable[[int], list[Candidate]]


def randomise(candidates: list[Candidate], *, seed: str) -> list[Candidate]:
    """A day-stable shuffle so selection spreads across the pool, not always the
    top of the feed. ``random.Random(str)`` seeds reproducibly across processes."""
    out = list(candidates)
    random.Random(seed).shuffle(out)
    return out


def relevance_loop(
    candidates: list[Candidate],
    *,
    threshold: int,
    gauge: Gauge,
    refine_borderline: Refine | None = None,
    max_calls: int | None = None,
) -> Selection:
    """Gauge candidates in order, keeping the relevant ones, until ``threshold``.

    A borderline verdict is re-judged by ``refine_borderline`` (the web-fetch
    tie-breaker) before deciding. Stops the moment ``threshold`` is reached (so it
    won't gauge the whole pool needlessly) or the call budget is spent. Reports
    ``exhausted`` when the pool ran out before the threshold — the site's floor,
    not this loop, decides what a short pool means.
    """
    selected: list[Candidate] = []
    calls = 0
    # ``max_calls`` is an explicit safety cap on total LLM calls; the for-loop is
    # already bounded by the pool, so None means "gauge the pool" (and refine each
    # borderline item — refinement doesn't count against an unset budget).
    for c in candidates:
        if len(selected) >= threshold:
            break
        if max_calls is not None and calls >= max_calls:
            break
        v = gauge(c)
        calls += 1
        budget_left = max_calls is None or calls < max_calls
        if v.borderline and refine_borderline is not None and budget_left:
            v = refine_borderline(c)
            calls += 1
        if v.relevant:
            selected.append(c)
    exhausted = len(selected) < threshold
    logger.info(
        "[relevance] %d/%d selected in %d calls (threshold %d, exhausted=%s)",
        len(selected),
        len(candidates),
        calls,
        threshold,
        exhausted,
    )
    return Selection(selected=selected, calls=calls, exhausted=exhausted)


def select(
    candidates: list[Candidate],
    *,
    threshold: int,
    gauge: Gauge,
    seed: str,
    refine_borderline: Refine | None = None,
    topup: Topup | None = None,
    max_topup_rounds: int = 2,
) -> Selection:
    """Randomise the pool, run the relevance loop, and top up a thin pool.

    When the loop exhausts the pool below ``threshold`` and a ``topup`` search is
    available, fetch more candidates (deduped against what's already selected) and
    keep going — bounded by ``max_topup_rounds`` so a barren topic can't loop
    forever. The site's floor still guards the final count.
    """
    pool = randomise(candidates, seed=seed)
    result = relevance_loop(
        pool, threshold=threshold, gauge=gauge, refine_borderline=refine_borderline
    )
    seen: set[str] = set()
    for c in result.selected:
        seen |= c.keys()

    rounds = 0
    while result.exhausted and topup is not None and rounds < max_topup_rounds:
        rounds += 1
        needed = threshold - len(result.selected)
        fresh = [c for c in topup(needed) if not (c.keys() & seen)]
        if not fresh:
            break
        more = relevance_loop(
            fresh, threshold=needed, gauge=gauge, refine_borderline=refine_borderline
        )
        for c in more.selected:
            seen |= c.keys()
        result = Selection(
            selected=result.selected + more.selected,
            calls=result.calls + more.calls,
            exhausted=len(result.selected) + len(more.selected) < threshold,
        )
    return result
