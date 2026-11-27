"""Confirmation step: a write tool may run only right after the customer clearly said yes
to an agent summary that named what will change."""
import re

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|confirm(ed)?|correct|go ahead|proceed|do it|please do)\b", re.I)
# Leans safe: any of these makes the reply "not a clear yes", so the agent asks again.
NOT_YES = re.compile(r"\b(no|not|don'?t|do not|wait|hold on|never ?mind|stop)\b", re.I)


def is_clear_yes(text: str) -> bool:
    return bool(YES.search(text)) and not NOT_YES.search(text)


def confirmation_problem(messages: list[dict], name: str, args: dict) -> str | None:
    """None if this write is confirmed, else the error to send back to the model.
    `messages` is the conversation before the current model turn's tool calls."""
    last_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), None)
    ask = f"Before {name}, list the exact details to the customer and ask for an explicit yes; call the tool only after they confirm."
    if last_user is None or not is_clear_yes(messages[last_user]["content"]):
        return f"Not confirmed. {ask}"
    summary = next((m.get("content") or "" for m in reversed(messages[:last_user])
                    if m["role"] == "assistant" and m.get("content")), "")
    # shortcut: checks only the order id / zip appear in the summary, not item ids or payment method.
    for key in ("order_id", "zip"):
        if key in args and str(args[key]).lstrip("#") not in summary:
            return f"Not confirmed: your last summary did not mention {key} {args[key]}. {ask}"
    return None
