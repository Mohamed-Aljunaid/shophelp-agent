"""Agent loop with a scripted fake model: tools run, errors go back to the model,
and login persists across turns of the same conversation."""
import shutil

import pytest

from agent.graph import build_graph
from llm.base import LLMResponse, Provider
from shop_db import store
from tools.policy import ShopSession
from tools.schemas import TOOL_SPECS

ORDER = "#W6779827"  # pending, ethan_lopez_6291


class Scripted(Provider):
    """Returns the given replies in order and records what it was sent."""
    name = "scripted"

    def __init__(self, replies):
        super().__init__("m", max_rpm=0)
        self.replies, self.seen, self.tools_seen = list(replies), [], []

    def _chat(self, system, messages, tools):
        self.seen.append(list(messages))
        self.tools_seen.append(sorted(t["name"] for t in tools))
        return self.replies.pop(0)


def call(name, **args):
    return LLMResponse(text=None, tool_calls=[{"id": name, "name": name, "args": args}])


@pytest.fixture
def conn(tmp_path):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path / "shop.db"
    store.reset(path)
    c = store.connect(path)
    yield c
    c.close()


def ask(graph, text, thread="t1"):
    out = graph.invoke({"messages": [{"role": "user", "content": text}]}, {"configurable": {"thread_id": thread}})
    return out


def test_specs_cover_all_tools():
    by_name = {s["name"]: s for s in TOOL_SPECS}
    assert len(by_name) == 16
    items = by_name["return_delivered_order_items"]["parameters"]["properties"]["item_ids"]
    assert items == {"type": "array", "items": {"type": "string"}}
    assert "conn" not in by_name["calculate"]["parameters"]["properties"]


def test_login_then_cancel_across_turns(conn):
    email = store.get(conn, "users", "ethan_lopez_6291")["email"]
    model = Scripted([
        call("find_user_id_by_email", email=email),
        LLMResponse(text="You're verified. What can I do?"),
        LLMResponse(text=f"I will cancel order {ORDER}, reason 'no longer needed'. Shall I proceed (yes/no)?"),
        call("cancel_pending_order", order_id=ORDER, reason="no longer needed"),
        LLMResponse(text="Your order is cancelled."),
    ])
    graph = build_graph(model, conn, "sys")
    first = ask(graph, f"I'm {email}")
    assert first["messages"][-1]["content"] == "You're verified. What can I do?"
    assert first["user_id"] == "ethan_lopez_6291"

    ask(graph, "Cancel my order, I don't need it anymore.")
    third = ask(graph, "Yes, go ahead.")
    assert third["messages"][-1]["content"] == "Your order is cancelled."
    assert store.get(conn, "orders", ORDER)["status"] == "cancelled"
    assert [m["role"] for m in third["messages"]] == (
        ["user", "assistant", "tool", "assistant", "user", "assistant", "user", "assistant", "tool", "assistant"])


def logged_in(conn, replies):
    """Graph whose first turn logs Ethan in; returns (graph, model)."""
    email = store.get(conn, "users", "ethan_lopez_6291")["email"]
    model = Scripted([call("find_user_id_by_email", email=email), LLMResponse(text="Verified.")] + replies)
    graph = build_graph(model, conn, "sys")
    ask(graph, email)
    return graph, model


@pytest.mark.parametrize("summary,answer,error", [
    (None, "Cancel #W6779827, no longer needed.", "Not confirmed"),                  # never asked
    (f"Cancel {ORDER}? (yes/no)", "No, wait.", "Not confirmed"),                     # customer said no
    ("Cancel your latest order? (yes/no)", "yes", "did not mention order_id"),       # summary too vague
])
def test_write_blocked_without_clear_confirmation(conn, summary, answer, error):
    replies = ([LLMResponse(text=summary)] if summary else []) + [
        call("cancel_pending_order", order_id=ORDER, reason="no longer needed"), LLMResponse(text="ok")]
    graph, _ = logged_in(conn, replies)
    if summary:
        ask(graph, "cancel my order")
    out = ask(graph, answer)
    assert error in [m["content"] for m in out["messages"] if m["role"] == "tool"][-1]
    assert store.get(conn, "orders", ORDER)["status"] == "pending"


def test_reads_need_no_confirmation(conn):
    graph, _ = logged_in(conn, [call("get_order_details", order_id=ORDER), LLMResponse(text="It's pending.")])
    out = ask(graph, "status of my order?")
    assert out["messages"][-1]["content"] == "It's pending."
    assert not [m for m in out["messages"] if m["role"] == "tool" and m["content"].startswith("Error")]


def test_policy_errors_go_back_to_model(conn):
    model = Scripted([
        call("cancel_pending_order", order_id=ORDER, reason="no longer needed"),
        call("get_order_details", oops="x"),
        LLMResponse(text="Please tell me your email first."),
    ])
    out = ask(build_graph(model, conn, "sys"), "cancel my order")
    tool_msgs = [m["content"] for m in out["messages"] if m["role"] == "tool"]
    assert tool_msgs[0].startswith("Error: Authenticate the user first")
    assert tool_msgs[1].startswith("Error: Invalid arguments for get_order_details")
    assert store.get(conn, "orders", ORDER)["status"] == "pending"
    assert out["messages"][-1]["content"] == "Please tell me your email first."


def test_threads_are_separate(conn):
    email = store.get(conn, "users", "ethan_lopez_6291")["email"]
    model = Scripted([call("find_user_id_by_email", email=email), LLMResponse(text="ok"),
                      LLMResponse(text="who are you?")])
    graph = build_graph(model, conn, "sys")
    assert ask(graph, "hi", "a")["user_id"] == "ethan_lopez_6291"
    assert ask(graph, "hi", "b").get("user_id") is None
    assert len(model.seen[-1]) == 1  # thread b starts empty


def test_invalid_args_rejected_by_policy(conn):
    with pytest.raises(ValueError, match="Invalid arguments"):
        ShopSession(conn).call("find_user_id_by_email")


def test_system_prompt_has_rules_and_policy(conn):
    from agent.prompt import system_prompt
    prompt = system_prompt()
    for phrase in ["Authenticate first", "Never invent information", 'explicit "yes"', "<policy>",
                   "Cancel pending order"]:
        assert phrase.lower() in prompt.lower()
    model = Scripted([LLMResponse(text="hi")])
    sent = {}
    model._chat = lambda system, messages, tools: sent.update(system=system) or LLMResponse(text="hi")
    ask(build_graph(model, conn), "hello")
    assert sent["system"] == prompt  # default prompt is used by the graph


def test_only_login_tools_offered_until_verified(conn):
    email = store.get(conn, "users", "ethan_lopez_6291")["email"]
    model = Scripted([
        call("find_user_id_by_email", email=email),
        LLMResponse(text="Verified."),
    ])
    out = ask(build_graph(model, conn, "sys"), f"cancel my order, I'm {email}")
    assert model.tools_seen[0] == ["calculate", "find_user_id_by_email", "find_user_id_by_name_zip",
                                   "transfer_to_human_agents"]
    assert len(model.tools_seen[1]) == 16  # all tools once the user is verified
    assert out["user_id"] == "ethan_lopez_6291"


def test_failed_login_keeps_tools_restricted(conn):
    model = Scripted([call("find_user_id_by_email", email="nobody@example.com"), LLMResponse(text="Not found.")])
    ask(build_graph(model, conn, "sys"), "hi")
    assert len(model.tools_seen[1]) == 4
