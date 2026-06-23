"""Shared deterministic content-research engine.

crawl → OKF → randomise → per-item relevance loop (stop at threshold) →
per-item generate. Reused by craicgpt.ie / thegeekwiththepeak.com /
thescriptingpaddy.com so all three stay at parity.
"""

from grazlab_content_research.candidate import Candidate
from grazlab_content_research.desk import Desk
from grazlab_content_research.pipeline import (
    run_desk,
    stage_crawl,
    stage_generate,
    stage_okf_store,
    stage_relevance,
    working_key,
)
from grazlab_content_research.sources import FeedSource

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "Desk",
    "FeedSource",
    "run_desk",
    "stage_crawl",
    "stage_okf_store",
    "stage_relevance",
    "stage_generate",
    "working_key",
    "__version__",
]
