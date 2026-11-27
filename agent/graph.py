"""Baseline agent: a LangGraph loop model -> tools -> model, until the model replies in text.

State is kept per conversation (thread_id) by the checkpointer: the messages and
the authenticated user id, so login survives across turns.
"""
import json
import operator
import sqlite3
import time
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.approval import refund_amount
from agent.confirm import confirmation_problem
from agent.guardrails import GUARD_NOTE, bypass_attempt
from agent.monitor import log_event
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

    def session_of(config: RunnableConfig) -> str:
        return config["configurable"]["thread_id"]

    def model(state: State, config: RunnableConfig) -> dict:
        # Authentication step: until a user is verified, the model is only offered login tools.
        tools = TOOL_SPECS if state.get("user_id") else PRE_AUTH_SPECS
        last_user = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
        flagged = bypass_attempt(last_user)
        if flagged and state["messages"][-1]["role"] == "user":  # log once per customer message
            log_event(session_of(config), "guardrail")
        turn_system = system + GUARD_NOTE if flagged else system
        start = time.perf_counter()
        try:
            reply = provider.chat(turn_system, state["messages"], tools)
        except Exception as exc:
            log_event(session_of(config), "llm_error", latency_ms=round((time.perf_counter() - start) * 1000),
                      error=f"{type(exc).__name__}: {exc}"[:300])
            raise
        log_event(session_of(config), "llm", latency_ms=round((time.perf_counter() - start) * 1000),
                  input_tokens=reply.usage.get("input_tokens", 0), output_tokens=reply.usage.get("output_tokens", 0),
                  cached=reply.cached, tool_calls=len(reply.tool_calls))
        return {"messages": [reply.to_message()]}

    def needs_approval(history, user_id, call) -> float:
        """The refund amount if this confirmed write must wait for staff approval, else 0."""
        if not user_id or call["name"] not in WRITE_TOOLS or confirmation_problem(history, call["name"], call["args"]):
            return 0.0
        amount = refund_amount(conn, call["name"], call["args"])
        return amount if amount > approval_threshold else 0.0

    def tools(state: State, config: RunnableConfig) -> dict:
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
                if amount := needs_approval(history, session.user_id, call):
                    decision = decisions.get(call["id"])
                    if decision is None:  # user logged in within this same batch; approval comes next time
                        raise ValueError("This refund needs staff approval. Call the tool again on its own.")
                    approved = isinstance(decision, dict) and decision.get("approved") is True  # anything else = reject
                    log_event(session_of(config), "escalation", kind="approval", amount=amount, approved=approved)
                    if not approved:
                        note = decision.get("note") if isinstance(decision, dict) else None
                        note = f" Staff note: {note}" if note else ""
                        raise ValueError(f"Staff rejected this refund; nothing was changed.{note} "
                                         "Tell the customer, or offer a transfer to a human agent.")
                out = session.call(call["name"], **call["args"])
                content = out if isinstance(out, str) else json.dumps(out)
            except ValueError as exc:
                content = f"Error: {exc}"
            ok = not content.startswith("Error:")
            # Logged here, not above: this loop runs once, the interrupt section re-runs on resume.
            log_event(session_of(config), "tool", name=call["name"], ok=ok, error=None if ok else content[7:][:200])
            if ok and call["name"] == "transfer_to_human_agents":
                log_event(session_of(config), "escalation", kind="transfer")
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
