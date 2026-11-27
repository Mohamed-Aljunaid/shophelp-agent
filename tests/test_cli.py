"""CLI chat: runs a scripted conversation end to end through input()/print()."""
import pytest

from agent import cli
from llm.base import LLMResponse
from shop_db import store
from tests.test_graph import Scripted, call

ORDER = "#W6779827"


def test_cli_conversation(tmp_path, monkeypatch, capsys):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    db = tmp_path / "shop.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    model = Scripted([
        call("get_order_details", order_id=ORDER),
        LLMResponse(text="Please give me your email first."),
        RuntimeError("quota"),
        LLMResponse(text="Still here."),
    ])
    real_chat = model._chat
    def chat(*a):
        if isinstance(model.replies[0], Exception):
            raise model.replies.pop(0)
        return real_chat(*a)
    model._chat = chat
    monkeypatch.setattr(cli, "get_provider", lambda: model)
    inputs = iter(["where is my order?", "", "hello?", "again", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("sys.argv", ["cli"])

    cli.main()
    out = capsys.readouterr().out
    assert "[tool] get_order_details({'order_id': '#W6779827'})" in out
    assert "[result] Error: Authenticate the user first" in out
    assert "agent> Please give me your email first." in out
    assert "[error] LLMError: scripted call failed: RuntimeError: quota" in out
    assert "agent> Still here." in out
    assert db.exists()


def test_ask_staff(monkeypatch, capsys):
    answers = iter(["n", "too large"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    req = {"amount": 500.0, "threshold": 200.0, "tool": "cancel_pending_order", "args": {}, "user_id": "u"}
    assert cli.ask_staff(req) == {"approved": False, "note": "too large"}
    assert "[approval needed] refund $500.00" in capsys.readouterr().out
