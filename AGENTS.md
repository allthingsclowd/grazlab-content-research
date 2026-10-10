# AGENTS.md — grazlab-content-research

> Single source of truth for agents. CLAUDE.md / GEMINI.md /
> .github/copilot-instructions.md are symlinks to this file. Global conventions
> (voice, hard rules, branch-per-feature, conventional commits) live in
> ~/.claude/CLAUDE.md and apply here in full.

## What this is

The **shared deterministic content-research engine** behind all three of Graham's
content sites (craicgpt.ie, thegeekwiththepeak.com, thescriptingpaddy.com). It
encodes one reusable per-**desk** pipeline:

```
crawl(sources, since_hours=24) → candidates[]      # deterministic, source links MANDATORY
  → okf_store.write(run, candidates)               # per-run OKF bundle → S3 (provenance + judge-grounding)
  → randomise(seed=date)                           # day-stable shuffle
  → relevance_loop(candidates, threshold)          # deepagent gauges one item at a time, STOPS at threshold
  → generate(selected) → [write_one(c) …]          # ONE call per item, source_url re-stamped
  → gate → publish                                 # the gate/publish stay in each site
```

**Why it exists:** the sites used to generate a whole section in one single JSON LLM
call over a char-clipped candidate pool, truncating with no top-up — so the item count
depended on one model emitting ≥N items in one response. It under-filled and held
editions (craicgpt, 2026-06-22: 7 shorts vs a floor of 11, with 33 candidates
available). This engine draws from the **full** pool, evaluates each candidate, and
reaches the threshold whenever the pool holds enough relevant items.

## A "desk" is the unit of reuse

A `Desk` is a config object: `{name, sources, threshold, floor, relevance_prompt,
generate_prompt/voice, okf_concept_type}`. The library runs the identical pipeline per
desk. Live desks: `craicgpt-ai`, `craicgpt-fun`, `geek-cyber`, `paddy-diary-news`.

## Repo-specific rules (not derivable from lockfiles)

- **Source-link preservation is a hard invariant.** Every `Candidate` carries a real
  `url`; `write_one` re-stamps it onto the generated item even if the model drops it. A
  candidate with no source link is never emitted.
- **Deterministic where correctness matters** (crawl, randomise, dedup, OKF bundle,
  threshold counting), **probabilistic only for** the per-item relevance gauge and the
  per-item prose. Same seed (the date) → same shuffle → reproducible selection.
- **Models are LiteLLM route names, never engine URLs** — env-var overridable via
  `LITELLM_BASE_URL` (any OpenAI-compatible endpoint), with `run_with_fallback`
  (local-first, frontier-fallback).
- **Loud on empty.** A crawl that returns nothing FAILS its stage loudly — never a
  silent thin edition.
- **The library owns crawl→select→generate; the site owns gate→publish.** Source
  lists, voice prompts, personas, the gate and the publish path stay in each repo; the
  library is desk-agnostic mechanics.
- **OKF bundle is per-run** (S3 artifact) for provenance + judge-grounding; cross-run
  dedup (don't repeat yesterday's stories) is separate and stays as each site has it.

## Commands

```bash
make bootstrap   # uv sync + install the pre-commit and pre-push hooks
make lint        # ruff check + ruff format --check
make typecheck   # mypy
make test        # pytest
make ci          # all of the above; THE bar for every PR (no GitHub CI)
make pre-push    # uv sync --locked + make ci — what the pre-push hook runs
```

- **The gate is local, not GitHub.** GitHub Actions became a cost constraint, so
  `.github/workflows/ci.yml` is deleted and **`make ci`** — ruff + mypy + pytest — is
  THE bar for every PR, run by the authoring agent. What the workflow did beyond a bare
  `make ci` (a locked `uv sync --all-extras --dev`, so lockfile drift fails) lives in
  **`make pre-push`**, wired to `git push` by the `.pre-commit-config.yaml` pre-push hook
  `make bootstrap` installs. Paste the gate's result line in the PR body. GitHub stays
  the remote copy: push branches, open PRs, never delete history.
