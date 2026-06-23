"""Conductor template — the granular per-desk workflow + task definitions.

The binding rule on Graham's sites is one Conductor task per pipeline stage, so
every box is independently visible and retriable. This module emits that shape for
a site's desks: a ``FORK_JOIN`` fans out one branch per desk, each branch a chain
of four SIMPLE tasks (``crawl → okf → relevance → generate``) passing S3 keys, and
a ``JOIN`` barrier before the site's own ``compile → gate → publish → enrich``
tail (which stays site-owned — the library doesn't know each site's gate).

The JSON is a template: each site writes it to its ``workflows/`` dir (geek
in-repo, craicgpt in grazlab-llm-fleet) and registers it with its existing
``conductor/register-workflow.py``. Crawl/okf are deterministic (no LLM) so they
get tight timeouts; relevance/generate call the model and get realistic
(NVFP4-eager) ones.
"""

from __future__ import annotations

from typing import Any

STAGES = ("crawl", "okf", "relevance", "generate")

# Conductor requires an ownerEmail on workflows/tasks; the caller supplies their
# own (no personal address is baked into the library).
DEFAULT_OWNER_EMAIL = "owner@example.com"

# Deterministic stages vs the model-calling ones — drives the timeout split.
_DETERMINISTIC = {"crawl", "okf"}
_DET_TIMEOUT_S = 180
_LLM_TIMEOUT_S = 900  # generous: per-item gauge/generate over a full pool on NVFP4-eager


def stage_task_names(site: str, desk: str) -> dict[str, str]:
    """The four granular task names for one desk: ``<site>_<desk>_<stage>``."""
    return {stage: f"{site}_{desk}_{stage}" for stage in STAGES}


def _simple_task(name: str, ref: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "taskReferenceName": ref,
        "type": "SIMPLE",
        "inputParameters": inputs,
    }


def desk_branch(
    site: str, desk: str, *, date_expr: str = "${workflow.input.date}"
) -> list[dict[str, Any]]:
    """One desk's branch: the four stage tasks, each consuming the prior's S3 key."""
    names = stage_task_names(site, desk)
    crawl = _simple_task(names["crawl"], f"{desk}_crawl", {"desk": desk, "date": date_expr})
    okf = _simple_task(
        names["okf"],
        f"{desk}_okf",
        {
            "desk": desk,
            "date": date_expr,
            "candidates_key": f"${{{desk}_crawl.output.candidates_key}}",
        },
    )
    relevance = _simple_task(
        names["relevance"],
        f"{desk}_relevance",
        {"desk": desk, "date": date_expr, "okf_key": f"${{{desk}_okf.output.okf_key}}"},
    )
    generate = _simple_task(
        names["generate"],
        f"{desk}_generate",
        {
            "desk": desk,
            "date": date_expr,
            "selected_key": f"${{{desk}_relevance.output.selected_key}}",
        },
    )
    return [crawl, okf, relevance, generate]


def build_workflow(
    site: str,
    desks: list[str],
    *,
    version: int = 1,
    description: str = "",
    owner_email: str = DEFAULT_OWNER_EMAIL,
) -> dict[str, Any]:
    """The ``<site>_daily`` workflow: fan out over desks, JOIN, then a site tail hook.

    The downstream ``compile → gate → publish → enrich`` is left as a single named
    placeholder ref (``compile``) the site replaces with its own tasks — the
    library owns crawl→generate, the site owns gate→publish.
    """
    branches = [desk_branch(site, d) for d in desks]
    fork = {
        "name": f"{site}_desks_fork",
        "taskReferenceName": "desks_fork",
        "type": "FORK_JOIN",
        "forkTasks": branches,
    }
    join = {
        "name": f"{site}_desks_join",
        "taskReferenceName": "desks_join",
        "type": "JOIN",
        "joinOn": [f"{d}_generate" for d in desks],
    }
    return {
        "name": f"{site}_daily",
        "version": version,
        "description": description or f"{site} daily content — granular per-desk research engine",
        "schemaVersion": 2,
        "tasks": [fork, join],
        "failureWorkflow": f"{site}_failure_notify",
        "ownerEmail": owner_email,
    }


def build_task_definitions(
    site: str,
    desks: list[str],
    *,
    det_timeout_s: int = _DET_TIMEOUT_S,
    llm_timeout_s: int = _LLM_TIMEOUT_S,
    owner_email: str = DEFAULT_OWNER_EMAIL,
) -> list[dict[str, Any]]:
    """One task definition per stage per desk, deterministic vs LLM timeouts split."""
    defs: list[dict[str, Any]] = []
    for desk in desks:
        for stage, name in stage_task_names(site, desk).items():
            timeout = det_timeout_s if stage in _DETERMINISTIC else llm_timeout_s
            defs.append(
                {
                    "name": name,
                    "retryCount": 1,
                    "timeoutSeconds": timeout,
                    "responseTimeoutSeconds": timeout,
                    "timeoutPolicy": "TIME_OUT_WF",
                    "retryLogic": "FIXED",
                    "retryDelaySeconds": 10,
                    "ownerEmail": owner_email,
                }
            )
    return defs
