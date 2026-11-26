# ShopHelp Customer Support Agent

A customer support agent for a fictional online shop that checks, cancels, returns and exchanges orders through tools while following the shop's policy. Evaluated on the retail domain of tau-bench, with pass^k for reliability.

> Work in progress. See `PLAN.md` for the build plan.

## Status

Phase 1 – Setup: done (uv project, tests, GitHub repo). Next: Phase 2 – shop data and tools.

## Results

Scores will be added here after the evaluation phase.

## Run locally

Requires [uv](https://docs.astral.sh/uv/). All caches must be on E: (run `E:\projects\setup_e_drive.ps1` once).

```powershell
uv sync                 # create .venv (Python 3.11) and install dependencies
copy .env.example .env  # then fill in GEMINI_API_KEY
uv run pytest           # run the tests
```

More instructions will be added as the project is built.
