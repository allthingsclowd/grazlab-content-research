"""The Conductor template — one granular SIMPLE task per stage per desk, fanned out."""

from grazlab_content_research import conductor


def test_stage_task_names_are_prefixed_and_granular():
    names = conductor.stage_task_names("geek", "cyber")
    assert names["crawl"] == "geek_cyber_crawl"
    assert set(names) == {"crawl", "okf", "relevance", "generate"}


def test_build_workflow_fans_out_one_branch_per_desk_with_four_stages_each():
    wf = conductor.build_workflow("craicgpt", ["ai", "fun"], version=3)
    assert wf["name"] == "craicgpt_daily"
    assert wf["version"] == 3
    fork = next(t for t in wf["tasks"] if t["type"] == "FORK_JOIN")
    assert len(fork["forkTasks"]) == 2  # one branch per desk
    assert all(len(branch) == 4 for branch in fork["forkTasks"])  # 4 granular stages
    # every stage task is a discrete, retriable SIMPLE box
    simple = [t for b in fork["forkTasks"] for t in b]
    assert all(t["type"] == "SIMPLE" for t in simple)
    assert {t["name"] for t in simple} >= {
        "craicgpt_ai_crawl",
        "craicgpt_ai_relevance",
        "craicgpt_fun_generate",
    }
    # a JOIN barrier waits on both branches before the site's compile/gate/publish
    join = next(t for t in wf["tasks"] if t["type"] == "JOIN")
    assert len(join["joinOn"]) == 2


def test_build_task_definitions_marks_deterministic_vs_llm_stages():
    defs = conductor.build_task_definitions("geek", ["cyber"])
    by_name = {d["name"]: d for d in defs}
    # crawl/okf are deterministic (no LLM); relevance/generate call the model
    assert (
        by_name["geek_cyber_crawl"]["timeoutSeconds"]
        <= by_name["geek_cyber_relevance"]["timeoutSeconds"]
    )
    assert all(d["name"].startswith("geek_cyber_") for d in defs)
