# ShopHelp Customer Support Agent

A customer support agent for a fictional online shop that checks, cancels, returns and exchanges orders through tools while following the shop's policy. Evaluated on the retail domain of tau-bench, with pass^k for reliability.

> Work in progress. See `PLAN.md` for the build plan.

## Status

- Phase 1 – Setup: done.
- Phase 2 – Shop data and tools: done. τ³-bench retail data in SQLite with reset, all 16 retail tools (matching τ³'s database changes exactly), and policy checks in code (log in first, one user, own orders only).
- Phase 3 – Baseline agent: done. LangGraph tool-calling loop on Gemini (Claude/OpenAI stubs), system prompt with the shop policy, and a terminal chat. A live chat logs a customer in, confirms, and cancels an order correctly.
- Next: Phase 4 – evaluation on τ³-bench retail tasks.

## Results

Scores will be added here after the evaluation phase.

## Run locally

Requires [uv](https://docs.astral.sh/uv/). All caches must be on E: (run `E:\projects\setup_e_drive.ps1` once).

```powershell
uv sync                 # create .venv (Python 3.11) and install dependencies
copy .env.example .env  # then fill in GEMINI_API_KEY
uv run python -m shop_db.fetch   # download the τ³-bench retail data into data/
uv run python -m shop_db.store   # build (or reset) data/shop.db
uv run python -m agent.cli --reset   # chat with the agent in the terminal (needs GEMINI_API_KEY and GEMINI_MODEL)
uv run uvicorn api.app:create_app --factory --reload   # API on http://localhost:8000 (docs at /docs)
cd frontend; npm install; npm run dev   # chat app on http://localhost:5280, staff approvals at /#staff
uv run pytest           # run the tests
```

More instructions will be added as the project is built.

## Monitoring

Every conversation is logged locally to `data/logs/events.jsonl`: each LLM call (latency, input/output tokens, cache hit), tool call (ok or error), escalation (transfer to a human, staff approval and its decision) and guardrail flag. No service is needed.

```powershell
uv run python -m agent.monitor            # per-conversation report (last 20)
uv run python -m agent.monitor --last 100
```

LangSmith tracing is optional: set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`. Each LLM call is then traced with its conversation, tool names and token usage, inside the LangGraph run.

