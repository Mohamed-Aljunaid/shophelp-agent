"""FastAPI backend for the ShopHelp agent.

  uv run uvicorn api.app:create_app --factory --reload    # development, http://localhost:8000/docs
  uv run python -m api                                    # production: API + built frontend on one port

POST /chat               {"session_id"?, "message"} -> agent reply, this turn's tool calls, pending approval
GET  /sessions/{id}      full conversation, logged-in user, pending approval
GET  /approvals           (staff) refunds waiting for a decision
POST /approvals/{id}     (staff) {"approved", "note"?} -> decision; the agent continues
GET  /health
Staff endpoints need the X-Staff-Token header (STAFF_TOKEN in .env).
"""
import secrets
import sqlite3
import threading
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.graph import build_graph
from config import settings
from llm import LLMError, Provider, get_provider
from shop_db import store

SESSION_ID = r"^[A-Za-z0-9_-]{1,64}$"


class ChatIn(BaseModel):
    session_id: str | None = Field(default=None, pattern=SESSION_ID)
    message: str = Field(min_length=1, max_length=4000)


class ApprovalIn(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1000)


def public(messages: list[dict]) -> list[dict]:
    """Messages for the client: drop provider-internal data."""
    return [{k: v for k, v in m.items() if k != "provider_data"} for m in messages]


def create_app(provider: Provider | None = None, conn: sqlite3.Connection | None = None,
               staff_token: str | None = None) -> FastAPI:
    """Build the app. Tests pass a fake provider, a temporary DB and a staff token."""
    staff_token = settings.staff_token if staff_token is None else staff_token
    if conn is None:
        if not store.DB_PATH.exists():
            store.reset(store.DB_PATH)
        conn = sqlite3.connect(store.DB_PATH, check_same_thread=False)
    graph = build_graph(provider or get_provider(), conn)
    # shortcut: one lock = one agent turn at a time, and sessions live in memory (lost on restart);
    # use a SQLite checkpointer and per-session locks if this serves real traffic.
    lock = threading.Lock()
    approvals: dict[str, str] = {}  # approval (interrupt) id -> session id

    app = FastAPI(title="ShopHelp agent API")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def config(session_id: str) -> dict:
        return {"configurable": {"thread_id": session_id}}

    def pending(session_id: str) -> dict | None:
        interrupts = graph.get_state(config(session_id)).interrupts
        if not interrupts:
            return None
        approvals[interrupts[0].id] = session_id
        return {"id": interrupts[0].id, **interrupts[0].value}

    def turn(session_id: str, graph_input) -> dict:
        """Run the graph, return the reply and everything new since this turn started."""
        before = len(graph.get_state(config(session_id)).values.get("messages", []))
        try:
            graph.invoke(graph_input, config(session_id))
        except LLMError as exc:
            raise HTTPException(503, f"The language model is unavailable: {exc}") from exc
        state = graph.get_state(config(session_id))
        new = state.values.get("messages", [])[before:]
        approval = pending(session_id)
        last = new[-1] if new else {}
        reply = last.get("content") if last.get("role") == "assistant" and not approval else None
        return {"session_id": session_id, "reply": reply, "messages": public(new), "pending_approval": approval}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "llm_provider": settings.llm_provider}

    @app.post("/chat")
    def chat(body: ChatIn) -> dict:
        session_id = body.session_id or uuid.uuid4().hex
        with lock:
            if pending(session_id):
                raise HTTPException(409, "This conversation is waiting for staff approval")
            return turn(session_id, {"messages": [{"role": "user", "content": body.message}]})

    @app.get("/sessions/{session_id}")
    def session(session_id: str) -> dict:
        state = graph.get_state(config(session_id))
        if not state.values:
            raise HTTPException(404, "Session not found")
        return {"session_id": session_id, "user_id": state.values.get("user_id"),
                "messages": public(state.values.get("messages", [])), "pending_approval": pending(session_id)}

    def require_staff(x_staff_token: str = Header(default="")) -> None:
        """Customers use the same API, so only staff holding the token may see or decide refunds."""
        if not staff_token:
            raise HTTPException(503, "Approvals are disabled: set STAFF_TOKEN")
        if not secrets.compare_digest(x_staff_token, staff_token):
            raise HTTPException(403, "Staff token required")

    @app.get("/approvals", dependencies=[Depends(require_staff)])
    def list_approvals() -> list[dict]:
        """All refunds waiting for staff, oldest first, with the customer's last message for context."""
        with lock:
            out = []
            for approval_id, session_id in list(approvals.items()):
                current = pending(session_id)
                if not current or current["id"] != approval_id:
                    del approvals[approval_id]  # decided or replaced meanwhile
                    continue
                messages = graph.get_state(config(session_id)).values["messages"]
                last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                out.append({**current, "session_id": session_id, "customer_message": last_user})
            return out

    @app.post("/approvals/{approval_id}", dependencies=[Depends(require_staff)])
    def decide(approval_id: str, body: ApprovalIn) -> dict:
        with lock:
            session_id = approvals.get(approval_id)
            current = pending(session_id) if session_id else None
            if not current or current["id"] != approval_id:
                raise HTTPException(404, "No pending approval with this id")
            del approvals[approval_id]
            return turn(session_id, Command(resume={"approved": body.approved, "note": body.note}))

    # Production: serve the built frontend from the same origin (added last, so API routes win).
    if (settings.frontend_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app

