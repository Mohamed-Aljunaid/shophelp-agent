"""Baseline agent: a LangGraph loop model -> tools -> model, until the model replies in text.

State is kept per conversation (thread_id) by the checkpointer: the messages and
the authenticated user id, so login survives across turns.
"""
import json
import operator
import sqlite3
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from llm import Provider
from tools.policy import ShopSession
from tools.schemas import TOOL_SPECS


class State(TypedDict):
    messages: Annotated[list[dict], operator.add]  # neutral dicts, see llm/base.py
    user_id: str | None


def build_graph(provider: Provider, conn: sqlite3.Connection, system: str, checkpointer=None):
    """Compile the agent graph. Invoke with {"messages": [user msg]} and a thread_id."""

    def model(state: State) -> dict:
        reply = provider.chat(system, state["messages"], TOOL_SPECS)
        return {"messages": [reply.to_message()]}

    def tools(state: State) -> dict:
        session = ShopSession(conn)
        session.user_id = state.get("user_id")
        results = []
        for call in state["messages"][-1]["tool_calls"]:
            try:
                out = session.call(call["name"], **call["args"])
                content = out if isinstance(out, str) else json.dumps(out)
            except ValueError as exc:
                content = f"Error: {exc}"
            results.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": content})
        return {"messages": results, "user_id": session.user_id}

    def route(state: State) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    graph = StateGraph(State)
    graph.add_node("model", model)
    graph.add_node("tools", tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route, ["tools", END])
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
