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
from langgraph.types import interrupt

from agent.approval import refund_amount
from agent.confirm import confirmation_problem
from agent.prompt import system_prompt
from config import settings
from llm import Provider
from tools.policy import AUTH_TOOLS, OPEN_TOOLS, WRITE_TOOLS, ShopSession
from tools.schemas import TOOL_SPECS

PRE_AUTH_SPECS = [s for s in TOOL_SPECS if s["name"] in AUTH_TOOLS | OPEN_TOOLS]


class State(TypedDict):
    messages: Annotated[list[dict], operator.add]  # neutral dicts, see llm/base.py
    user_id: str | None


def build_graph(provider: Provider, conn: sqlite3.Connection, system: str | None = None, checkpointer=None,
                approval_threshold: float | None = None):
    """Compile the agent graph. Invoke with {"messages": [user msg]} and a thread_id.

    Refunds above approval_threshold (REFUND_APPROVAL_THRESHOLD) pause the graph with an
    interrupt; resume with Command(resume={"approved": bool, "note": str})."""
    if approval_threshold is None:
        approval_threshold = settings.refund_approval_threshold
    system = system or system_prompt()

    def model(state: State) -> dict:
        # Authentication step: until a user is verified, the model is only offered login tools.
        tools = TOOL_SPECS if state.get("user_id") else PRE_AUTH_SPECS
        reply = provider.chat(system, state["messages"], tools)
        return {"messages": [reply.to_message()]}

    def needs_approval(history, user_id, call) -> float:
        """The refund amount if this confirmed write must wait for staff approval, else 0."""
        if not user_id or call["name"] not in WRITE_TOOLS or confirmation_problem(history, call["name"], call["args"]):
            return 0.0
        amount = refund_amount(conn, call["name"], call["args"])
        return amount if amount > approval_threshold else 0.0

    def tools(state: State) -> dict:
        calls, history = state["messages"][-1]["tool_calls"], state["messages"][:-1]
        # Ask staff BEFORE running anything: on resume LangGraph re-runs this node from the top.
        decisions = {}
        for call in calls:
            if amount := needs_approval(history, state.get("user_id"), call):
                decisions[call["id"]] = interrupt({
                    "type": "refund_approval", "user_id": state.get("user_id"), "tool": call["name"],
                    "args": call["args"], "amount": amount, "threshold": approval_threshold})
        session = ShopSession(conn)
        session.user_id = state.get("user_id")
        results = []
        for call in calls:
            try:
                if session.user_id and call["name"] in WRITE_TOOLS and (problem := confirmation_problem(
                        history, call["name"], call["args"])):
                    raise ValueError(problem)
                if needs_approval(history, session.user_id, call):
                    decision = decisions.get(call["id"])
                    if decision is None:  # user logged in within this same batch; approval comes next time
                        raise ValueError("This refund needs staff approval. Call the tool again on its own.")
                    if not (isinstance(decision, dict) and decision.get("approved") is True):  # anything else = reject
                        note = decision.get("note") if isinstance(decision, dict) else None
                        note = f" Staff note: {note}" if note else ""
                        raise ValueError(f"Staff rejected this refund; nothing was changed.{note} "
                                         "Tell the customer, or offer a transfer to a human agent.")
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
