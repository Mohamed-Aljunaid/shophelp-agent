"""Run tau3-bench retail tasks against our agent: an LLM plays the customer, then
the final shop DB is compared with the DB after replaying the task's gold actions.

  uv run python -m eval.runner --task 66            # one task, prints the transcript
  uv run python -m eval.runner --task 66 --task 69  # several

Scoring: reward = 1 if the final DB matches the gold DB exactly, else 0.
tau3's official reward also needs an LLM judge for NL assertions; we skip that
here, so our score can be higher than the official one. `communicate_info` (values
the agent should tell the customer) is reported separately, not in the reward.
"""
import argparse
import json
import shutil
import tempfile
import textwrap
import uuid
from pathlib import Path

from langgraph.errors import GraphRecursionError

from agent.graph import build_graph
from llm import LLMError, Provider, get_provider
from shop_db import store
from tools.policy import TOOLS

TASKS_PATH = store.SOURCE.parent / "tasks.json"
GREETING = "Hi! How can I help you today?"  # tau3's fixed first agent message
STOP_TOKENS = ("###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###")

# tau3-bench text-mode user simulation guidelines (MIT, Sierra), default English persona.
USER_GUIDELINES = """# User Simulation Guidelines
You are playing the role of a customer contacting a customer service representative.
Your goal is to simulate realistic customer interactions while following specific scenario instructions.

## Core Principles
- Generate one message at a time, maintaining natural conversation flow.
- Strictly follow the scenario instructions you have received.
- When providing addresses or other multi-part entity values from the task, preserve the order of their components exactly as given; do not rearrange them to match local conventions unless the task explicitly instructs a different order.
- Never make up or hallucinate information not provided in the scenario instructions. Information that is not provided in the scenario instructions should be considered unknown or unavailable.
- Avoid repeating the exact instructions verbatim. Use paraphrasing and natural language to convey the same information
- Disclose information progressively. Wait for the agent to ask for specific information before providing it.

## Task Completion
- The goal is to continue the conversation until the task is complete.
- If the instruction goal is satisified, generate the '###STOP###' token to end the conversation.
- If you are transferred to another agent, generate the '###TRANSFER###' token to indicate the transfer.
- If you find yourself in a situation in which the scenario does not provide enough information for you to continue the conversation, generate the '###OUT-OF-SCOPE###' token to end the conversation.
Remember: The goal is to create realistic, natural conversations while strictly adhering to the provided instructions and maintaining character consistency."""


def load_tasks(ids: list[str] | None = None) -> list[dict]:
    """All tau3 retail tasks, or only the given ids (in the given order)."""
    tasks = {t["id"]: t for t in json.loads(TASKS_PATH.read_text(encoding="utf-8"))}
    return [tasks[i] for i in ids] if ids else list(tasks.values())


def user_system_prompt(task: dict) -> str:
    """Simulator prompt, formatted like tau3's str(UserScenario)."""
    scenario, ins = task["user_scenario"], task["user_scenario"]["instructions"]
    if isinstance(ins, dict):
        parts = [f"Domain: {ins['domain']}", f"Reason for call:\n{textwrap.indent(ins['reason_for_call'], chr(9))}"]
        for key, label in [("known_info", "Known info"), ("unknown_info", "Unknown info")]:
            if ins.get(key) is not None:
                parts.append(f"{label}:\n{textwrap.indent(ins[key], chr(9))}")
        parts.append(f"Task instructions:\n{textwrap.indent(ins['task_instructions'], chr(9))}")
        ins = "\n".join(parts)
    lines = ([f"Persona:\n{textwrap.indent(scenario['persona'], chr(9))}"] if scenario.get("persona") else [])
    lines += ["Instructions:", textwrap.indent(ins, "\t")]
    return f"{USER_GUIDELINES}\n\n<scenario>\n" + "\n".join(lines) + "\n</scenario>"


def gold_db(clean_db: Path, task: dict, workdir: Path) -> dict:
    """The DB after replaying the task's gold actions with our tools (identical to tau3's)."""
    path = workdir / "gold.db"
    shutil.copy(clean_db, path)
    conn = store.connect(path)
    try:
        for action in task["evaluation_criteria"]["actions"] or []:
            try:
                TOOLS[action["name"]](conn, **action["arguments"])
            except ValueError:
                pass  # some gold lookups fail on purpose (customer gives a wrong email/zip)
        return store.export(conn)
    finally:
        conn.close()


def run_task(task: dict, provider: Provider, clean_db: Path, max_user_turns: int = 30) -> dict:
    """Simulate one conversation and score it. The same provider plays agent and customer,
    so they share one rate limit."""
    with tempfile.TemporaryDirectory(dir=clean_db.parent) as tmp:
        workdir = Path(tmp)
        path = workdir / "agent.db"
        shutil.copy(clean_db, path)
        conn = store.connect(path)
        try:
            graph = build_graph(provider, conn)
            config = {"configurable": {"thread_id": uuid.uuid4().hex}}
            user_system = user_system_prompt(task)
            user_view = [{"role": "user", "content": GREETING}]  # roles flipped for the simulator
            end, turns = "max_turns", 0
            while turns < max_user_turns:
                try:
                    said = provider.chat(user_system, user_view).text or ""
                except LLMError as exc:
                    end = f"user_error: {exc}"
                    break
                turns += 1
                user_view.append({"role": "assistant", "content": said})
                if any(tok in said for tok in STOP_TOKENS):
                    end = next(tok for tok in STOP_TOKENS if tok in said).strip("#").lower()
                    break
                try:
                    state = graph.invoke({"messages": [{"role": "user", "content": said}]}, config)
                except (LLMError, GraphRecursionError) as exc:
                    end = f"agent_error: {type(exc).__name__}: {exc}"
                    break
                reply = state["messages"][-1].get("content") or ""
                user_view.append({"role": "user", "content": reply})
                if any(m["role"] == "tool" and m["name"] == "transfer_to_human_agents"
                       for m in state["messages"]):
                    end = "transferred"
                    break
            messages = graph.get_state(config).values.get("messages", [])
            final_db = store.export(conn)
        finally:
            conn.close()
        gold = gold_db(clean_db, task, workdir)

    agent_text = " ".join(m["content"] for m in messages if m["role"] == "assistant" and m.get("content"))
    agent_text = agent_text.lower().replace(",", "")
    communicate = {info: info.lower() in agent_text for info in task["evaluation_criteria"].get("communicate_info") or []}
    db_match = final_db == gold
    return {
        "task_id": task["id"],
        "reward": 1.0 if db_match else 0.0,
        "db_match": db_match,
        "communicate": communicate,
        "end": end,
        "user_turns": turns,
        "tool_calls": sum(len(m.get("tool_calls") or []) for m in messages if m["role"] == "assistant"),
        "messages": [{k: v for k, v in m.items() if k != "provider_data"} for m in messages],
    }


def clean_db_path() -> Path:
    """A clean shop DB used as the starting point for every task (data/eval/clean.db)."""
    path = store.DB_PATH.parent / "eval" / "clean.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        store.reset(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", action="append", required=True, help="task id (repeatable)")
    args = parser.parse_args()
    provider, clean = get_provider(), clean_db_path()
    for task in load_tasks(args.task):
        result = run_task(task, provider, clean)
        print(f"\n=== task {task['id']} ===")
        for m in result["messages"]:
            if m["role"] == "user":
                print(f"customer> {m['content']}")
            elif m["role"] == "assistant":
                for c in m.get("tool_calls") or []:
                    print(f"  [tool] {c['name']}({c['args']})")
                if m.get("content"):
                    print(f"agent> {m['content']}")
        print(f"reward={result['reward']} db_match={result['db_match']} end={result['end']} "
              f"turns={result['user_turns']} tool_calls={result['tool_calls']} communicate={result['communicate']}")


if __name__ == "__main__":
    main()
