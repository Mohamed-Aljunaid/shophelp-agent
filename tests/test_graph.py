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
        self.replies, self.seen = list(replies), []

    def _chat(self, system, messages, tools):
        self.seen.append(list(messages))
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
        call("cancel_pending_order", order_id=ORDER, reason="no longer needed"),
        LLMResponse(text="Your order is cancelled."),
    ])
    graph = build_graph(model, conn, "sys")
    first = ask(graph, f"I'm {email}")
    assert first["messages"][-1]["content"] == "You're verified. What can I do?"
    assert first["user_id"] == "ethan_lopez_6291"

    second = ask(graph, "Cancel my order, no longer needed. Yes, go ahead.")
    assert second["messages"][-1]["content"] == "Your order is cancelled."
    assert store.get(conn, "orders", ORDER)["status"] == "cancelled"
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "tool", "assistant"] * 2


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
