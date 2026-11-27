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
