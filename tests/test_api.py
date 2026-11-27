"""API: chat across turns, session view, staff approval flow, validation and CORS."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from llm.base import LLMResponse
from shop_db import store
from tests.test_graph import Scripted, call

ORDER = "#W6779827"  # pending, $4079.45, ethan_lopez_6291


@pytest.fixture
def db(tmp_path):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path / "shop.db"
    store.reset(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    yield conn
    conn.close()


TOKEN = "test-staff-token"
STAFF = {"X-Staff-Token": TOKEN}


def client(db, replies, token=TOKEN):
    return TestClient(create_app(Scripted(replies), db, staff_token=token))


def cancel_flow(db):
    """Login, summary, then a confirmed cancel that needs staff approval ($4079.45 > $200)."""
    email = store.get(db, "users", "ethan_lopez_6291")["email"]
    c = client(db, [
        call("find_user_id_by_email", email=email), LLMResponse(text="Verified."),
        LLMResponse(text=f"Cancel order {ORDER}, reason 'no longer needed'? (yes/no)"),
        call("cancel_pending_order", order_id=ORDER, reason="no longer needed"),
        LLMResponse(text="Your order is cancelled."),
    ])
    first = c.post("/chat", json={"message": email}).json()
    sid = first["session_id"]
    c.post("/chat", json={"session_id": sid, "message": "cancel my order"})
    third = c.post("/chat", json={"session_id": sid, "message": "yes"}).json()
    return c, first, third


def test_health(db):
    assert client(db, []).get("/health").json()["status"] == "ok"


def test_chat_returns_reply_and_tool_calls(db):
    _, first, _ = cancel_flow(db)
    assert first["reply"] == "Verified." and first["pending_approval"] is None
    roles = [m["role"] for m in first["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert first["messages"][2]["content"] == "ethan_lopez_6291"
    assert all("provider_data" not in m for m in first["messages"])


def test_approval_flow(db):
    c, _, third = cancel_flow(db)
    approval = third["pending_approval"]
    assert third["reply"] is None and approval["amount"] == 4079.45 and approval["tool"] == "cancel_pending_order"
    sid = third["session_id"]
    assert c.get(f"/sessions/{sid}").json()["pending_approval"]["id"] == approval["id"]
    assert c.post("/chat", json={"session_id": sid, "message": "hello?"}).status_code == 409
    assert store.get(db, "orders", ORDER)["status"] == "pending"

    done = c.post(f"/approvals/{approval['id']}", json={"approved": True}, headers=STAFF).json()
    assert done["reply"] == "Your order is cancelled." and done["pending_approval"] is None
    assert store.get(db, "orders", ORDER)["status"] == "cancelled"
    assert c.post(f"/approvals/{approval['id']}", json={"approved": True}, headers=STAFF).status_code == 404  # used up


def test_rejection(db):
    c, _, third = cancel_flow(db)
    done = c.post(f"/approvals/{third['pending_approval']['id']}", json={"approved": False, "note": "check ID"},
                  headers=STAFF)
    tool_msgs = [m["content"] for m in done.json()["messages"] if m["role"] == "tool"]
    assert "Staff rejected this refund" in tool_msgs[-1] and "check ID" in tool_msgs[-1]
    assert store.get(db, "orders", ORDER)["status"] == "pending"


def test_session_view_and_errors(db):
    c = client(db, [LLMResponse(text="Hi! What's your email?")])
    sid = c.post("/chat", json={"session_id": "abc-1", "message": "hello"}).json()["session_id"]
    view = c.get(f"/sessions/{sid}").json()
    assert sid == "abc-1" and view["user_id"] is None and len(view["messages"]) == 2
    assert c.get("/sessions/nope").status_code == 404
    assert c.post("/approvals/nope", json={"approved": True}, headers=STAFF).status_code == 404
    assert c.post("/chat", json={"message": ""}).status_code == 422
    assert c.post("/chat", json={"session_id": "bad id!", "message": "hi"}).status_code == 422


def test_llm_unavailable_is_503(db):
    model = Scripted([])
    model._chat = lambda *a: (_ for _ in ()).throw(RuntimeError("quota"))
    c = TestClient(create_app(model, db, staff_token=TOKEN))
    r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 503 and "quota" in r.json()["detail"]


def test_cors_allows_vite_dev_server(db):
    r = client(db, []).options("/chat", headers={"Origin": "http://localhost:5280",
                                                 "Access-Control-Request-Method": "POST"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5280"


def test_approval_needs_staff_token(db):
    c, _, third = cancel_flow(db)
    url = f"/approvals/{third['pending_approval']['id']}"
    assert c.post(url, json={"approved": True}).status_code == 403                                   # customer
    assert c.post(url, json={"approved": True}, headers={"X-Staff-Token": "guess"}).status_code == 403
    assert store.get(db, "orders", ORDER)["status"] == "pending"
    assert c.post(url, json={"approved": True}, headers=STAFF).status_code == 200


def test_approvals_disabled_without_token(db):
    c = client(db, [], token="")
    assert c.post("/approvals/x", json={"approved": True}, headers={"X-Staff-Token": ""}).status_code == 503


def test_list_approvals_for_staff(db):
    c, _, third = cancel_flow(db)
    assert c.get("/approvals").status_code == 403  # customers cannot list
    listed = c.get("/approvals", headers=STAFF).json()
    assert len(listed) == 1
    item = listed[0]
    assert item["id"] == third["pending_approval"]["id"] and item["session_id"] == third["session_id"]
    assert item["amount"] == 4079.45 and item["customer_message"] == "yes"

    c.post(f"/approvals/{item['id']}", json={"approved": True}, headers=STAFF)
    assert c.get("/approvals", headers=STAFF).json() == []  # decided -> gone


def test_cors_preflight_allows_staff_header(db):
    r = client(db, []).options("/approvals", headers={
        "Origin": "http://localhost:5280", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-staff-token"})
    assert r.status_code == 200 and "x-staff-token" in r.headers["access-control-allow-headers"].lower()
