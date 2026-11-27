"""Eval runner offline: a scripted provider plays both customer and agent on task 88
(gold: cancel #W8835847, 'ordered by mistake')."""
import pytest

from eval import runner
from llm.base import LLMResponse
from shop_db import store
from tests.test_graph import Scripted, call

EMAIL = "daiki.silva6295@example.com"


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path_factory.mktemp("eval") / "clean.db"
    store.reset(path)
    return path


def say(text):
    return LLMResponse(text=text)


def test_user_prompt_format():
    prompt = runner.user_system_prompt(runner.load_tasks(["5"])[0])
    assert prompt.startswith("# User Simulation Guidelines")
    assert "<scenario>\nInstructions:\n\tDomain: retail\n\tReason for call:\n\t\t" in prompt
    assert "###STOP###" in prompt and prompt.endswith("</scenario>")


def test_successful_task_scores_1(clean):
    model = Scripted([
        say(f"Hi, I want to cancel order #W8835847, I ordered it by mistake. My email is {EMAIL}."),  # customer
        call("find_user_id_by_email", email=EMAIL),                                                  # agent
        say("Cancel #W8835847, reason 'ordered by mistake'. Confirm (yes/no)?"),
        say("yes"),                                                                                   # customer
        call("cancel_pending_order", order_id="#W8835847", reason="ordered by mistake"),             # agent
        say("Done, it's cancelled."),
        say("Thanks! ###STOP###"),                                                                    # customer
    ])
    result = runner.run_task(runner.load_tasks(["88"])[0], model, clean)
    assert result["reward"] == 1.0 and result["end"] == "stop"
    assert result["user_turns"] == 3 and result["tool_calls"] == 2
    assert result["approvals"] == 1  # $689.97 refund > default threshold, auto-approved in eval
    assert model.seen[0] == [{"role": "user", "content": runner.GREETING}]  # simulator sees greeting as 'user'
    assert store.get(store.connect(clean), "orders", "#W8835847")["status"] == "pending"  # clean DB untouched


def test_wrong_action_scores_0(clean):
    model = Scripted([
        say(f"Cancel #W8835847 please, my email is {EMAIL}."),
        call("find_user_id_by_email", email=EMAIL),
        call("cancel_pending_order", order_id="#W8835847", reason="no longer needed"),  # wrong reason
        say("Cancelled."),
        say("###STOP###"),
    ])
    result = runner.run_task(runner.load_tasks(["88"])[0], model, clean)
    assert result["reward"] == 0.0 and not result["db_match"]


def test_transfer_and_turn_limit_end_conversation(clean):
    model = Scripted([say("I want a human."), call("transfer_to_human_agents", summary="wants human"),
                      say("YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.")])
    assert runner.run_task(runner.load_tasks(["88"])[0], model, clean)["end"] == "transferred"

    model = Scripted([say("hello?"), say("Hi, how can I help?")] * 2)
    result = runner.run_task(runner.load_tasks(["88"])[0], model, clean, max_user_turns=2)
    assert result["end"] == "max_turns" and result["reward"] == 0.0


def test_communicate_info_checked(clean):
    task = dict(runner.load_tasks(["88"])[0])
    task["evaluation_criteria"] = {**task["evaluation_criteria"], "communicate_info": ["481.50"]}
    model = Scripted([say("hi"), say("Your refund is $481.50."), say("###STOP###")])
    assert runner.run_task(task, model, clean)["communicate"] == {"481.50": True}


def test_select_tasks_from_config():
    from config import Settings
    first = runner.select_tasks(Settings(_env_file=None, eval_split="test", eval_task_count=3))
    assert [t["id"] for t in first] == ["5", "9", "12"]
    assert len(runner.select_tasks(Settings(_env_file=None, eval_split="base", eval_task_count=200))) == 114
    picked = runner.select_tasks(Settings(_env_file=None, eval_task_ids="88, 66"))
    assert [t["id"] for t in picked] == ["88", "66"]
    with pytest.raises(ValueError, match="EVAL_SPLIT"):
        runner.select_tasks(Settings(_env_file=None, eval_split="dev"))


def test_run_eval_trials_use_separate_cache_salt(clean, monkeypatch):
    salts = []
    monkeypatch.setattr(runner, "clean_db_path", lambda: clean)
    monkeypatch.setattr(runner, "run_task", lambda task, p, c: salts.append(p.cache_salt) or
                        {"task_id": task["id"], "reward": 1.0, "end": "stop", "user_turns": 1, "tool_calls": 0})
    results = runner.run_eval(runner.load_tasks(["88", "66"]), 2, Scripted([]))
    assert salts == ["trial1", "trial1", "trial2", "trial2"]
    assert [r["trial"] for r in results] == [1, 1, 2, 2]


def fake_run(outcomes):
    """run_task stand-in: pops (reward, end) per call."""
    def run(task, provider, clean):
        reward, end = outcomes.pop(0)
        return {"task_id": task["id"], "reward": reward, "db_match": reward == 1.0, "communicate": {},
                "end": end, "user_turns": 2, "tool_calls": 1,
                "messages": [{"role": "user", "content": "cancel please"},
                             {"role": "assistant", "content": None, "tool_calls": [
                                 {"id": "x", "name": "cancel_pending_order",
                                  "args": {"order_id": "#W8835847", "reason": "no longer needed"}}]},
                             {"role": "tool", "tool_call_id": "x", "name": "cancel_pending_order", "content": "{}"},
                             {"role": "assistant", "content": "Done."}]}
    return run


def test_saves_resumes_and_writes_failures(clean, monkeypatch, tmp_path):
    from eval import report
    monkeypatch.setattr(runner, "clean_db_path", lambda: clean)
    tasks = runner.load_tasks(["88", "66"])
    out = tmp_path / "rep"
    monkeypatch.setattr(runner, "run_task", fake_run([(1.0, "stop"), (0.0, "stop")]))
    runner.run_eval(tasks, 1, Scripted([]), out_dir=out)
    monkeypatch.setattr(runner, "run_task", fake_run([(1.0, "stop"), (1.0, "stop")]))  # trial 2 only
    results = runner.run_eval(tasks, 2, Scripted([]), out_dir=out)
    assert [(r["task_id"], r["trial"]) for r in results] == [("88", 1), ("66", 1), ("88", 2), ("66", 2)]

    s = report.write_report(out, results, {t["id"]: t for t in tasks})
    assert s["pass_hat_k"] == {1: 0.75, 2: 0.5}
    files = sorted(p.name for p in (out / "failures").iterdir())
    assert files == ["task066_trial1.md"]
    md = (out / "failures" / files[0]).read_text(encoding="utf-8")
    assert "**Expected writes:**" in md and 'cancel_pending_order({"order_id": "#W3361211"' in md
    assert '**Agent writes:**\n- `cancel_pending_order({"order_id": "#W8835847"' in md


def test_llm_errors_not_saved_and_stop_run(clean, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "clean_db_path", lambda: clean)
    monkeypatch.setattr(runner, "run_task", fake_run([(0.0, "user_error: 429")] * 3 + [(1.0, "stop")]))
    results = runner.run_eval(runner.load_tasks(["88", "66"]), 2, Scripted([]), out_dir=tmp_path / "r")
    assert results == [] and not (tmp_path / "r" / "results.jsonl").exists()


def test_final_customer_message_kept(clean):
    model = Scripted([say("hi"), say("Hello, how can I help?"), say("Never mind. ###STOP###")])
    result = runner.run_task(runner.load_tasks(["88"])[0], model, clean)
    assert result["messages"][-1] == {"role": "user", "content": "Never mind. ###STOP###"}
