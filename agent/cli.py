"""Chat with the agent in the terminal.

  uv run python -m agent.cli            # uses data/shop.db as it is
  uv run python -m agent.cli --reset    # start from a clean shop database
Type 'quit' (or Ctrl+C) to stop. Tool calls are shown as [tool] lines.
"""
import argparse
import uuid

from langgraph.types import Command

from agent.graph import build_graph
from llm import LLMError, get_provider
from shop_db import store


def show(messages: list[dict], width: int = 300) -> None:
    """Print tool calls, tool results and the agent's reply."""
    for m in messages:
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                print(f"  [tool] {c['name']}({c['args']})")
            if m.get("content"):
                print(f"agent> {m['content']}")
        elif m["role"] == "tool":
            text = m["content"]
            print(f"  [result] {text[:width]}{'...' if len(text) > width else ''}")


def ask_staff(request: dict) -> dict:
    """Play the staff member: approve or reject a refund in the terminal."""
    print(f"  [approval needed] refund ${request['amount']:.2f} (over ${request['threshold']:.2f}) "
          f"for {request['tool']}({request['args']}), user {request['user_id']}")
    approved = input("staff> approve? [y/N] ").strip().lower() in {"y", "yes"}
    note = "" if approved else input("staff> note for the agent (optional): ").strip()
    return {"approved": approved, "note": note}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="reset the shop database first")
    args = parser.parse_args()

    try:
        provider = get_provider()
    except LLMError as exc:
        raise SystemExit(f"{exc}. Copy .env.example to .env and fill in the LLM settings.")
    if args.reset or not store.DB_PATH.exists():
        store.reset(store.DB_PATH)
        print(f"Shop database reset: {store.DB_PATH}")
    conn = store.connect(store.DB_PATH)
    graph = build_graph(provider, conn)
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    count = 0
    print("ShopHelp agent. Type 'quit' to stop.")
    try:
        while (text := input("you> ").strip()).lower() not in {"quit", "exit"}:
            if not text:
                continue
            try:
                graph.invoke({"messages": [{"role": "user", "content": text}]}, config)
                while pending := graph.get_state(config).interrupts:  # staff approval for a large refund
                    graph.invoke(Command(resume=ask_staff(pending[0].value)), config)
            except Exception as exc:  # e.g. rate limit after all retries: report and keep chatting
                print(f"  [error] {type(exc).__name__}: {exc}")
            messages = graph.get_state(config).values["messages"]
            show(messages[count + 1:])  # skip the user's own message
            count = len(messages)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
