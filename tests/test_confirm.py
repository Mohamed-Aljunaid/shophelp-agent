"""Confirmation detection: clear yes vs anything else, and the summary check."""
import pytest

from agent.confirm import confirmation_problem, is_clear_yes


@pytest.mark.parametrize("text", ["yes", "Yes, please go ahead.", "Yeah, do it", "ok", "Correct, proceed.",
                                  "Actually, the reason is that I ordered by mistake. But yes, please go ahead"])
def test_clear_yes(text):
    assert is_clear_yes(text)


@pytest.mark.parametrize("text", ["no", "No thanks", "Wait, not yet", "Don't do it", "hmm, maybe",
                                  "Yes, but not that one", "Which items are included?"])
def test_not_clear_yes(text):
    assert not is_clear_yes(text)


def convo(summary, answer):
    return [{"role": "user", "content": "cancel it"},
            {"role": "assistant", "content": summary, "tool_calls": []},
            {"role": "user", "content": answer}]


def test_confirmed_when_summary_names_order():
    assert confirmation_problem(convo("Cancel order #W123 (no longer needed)? yes/no", "yes"),
                                "cancel_pending_order", {"order_id": "#W123"}) is None
    assert confirmation_problem(convo("Cancel order W123?", "yes"), "cancel_pending_order",
                                {"order_id": "#W123"}) is None  # '#' optional


def test_address_change_needs_zip_in_summary():
    args = {"user_id": "u", "zip": "73301"}
    assert confirmation_problem(convo("Change your address to 1 Main St, Austin TX 73301?", "yes"),
                                "modify_user_address", args) is None
    assert "zip" in confirmation_problem(convo("Change your address?", "yes"), "modify_user_address", args)


def test_no_user_message_yet():
    assert confirmation_problem([], "cancel_pending_order", {"order_id": "#W1"}).startswith("Not confirmed")
