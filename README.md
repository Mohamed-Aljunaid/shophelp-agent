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
uv run pytest           # run the tests
```

More instructions will be added as the project is built.
