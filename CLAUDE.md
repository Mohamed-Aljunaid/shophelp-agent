# ShopHelp Customer Support Agent – instructions for Claude Code

The full plan is in `PLAN.md`. Read it before doing anything.

## How to work

- Do one step at a time, in the order of PLAN.md. Do only the step or phase the user asks for.
- After every step: run the tests, commit with a clear message (for example `phase-2.3: short description`), and push to GitHub.
- At the end of each phase, tag the commit (for example `phase-2-done`) and push the tag.
- If a step fails or is unclear, stop and ask. Do not guess.
- After each phase, update the Progress section below and the README.

## Machine constraints (must follow)

- Windows, 8 GB RAM, no GPU. Keep memory use low and run everything on CPU.
- The C: drive is full. Everything stays in this folder on E:, and all caches go to `E:\cache` (see `E:\projects\setup_e_drive.ps1`). Check each library's default cache path.
- The developer is in Sudan. Some services may be blocked. Prefer open-source, local tools with a local fallback.
- Default LLM is Gemini on the free tier: throttle, retry with backoff, and cache responses.

## Code rules

- Use uv for everything: `uv add <package>`, `uv run <command>`. No pip, no global installs.
- Backend: FastAPI. Frontend: React with Vite + TypeScript in `frontend/`.
- Keep the LLM provider swappable. No provider-specific code outside `llm/`.
- Never commit API keys, `.env`, datasets, models, indexes or databases.
- Simple, readable code with short docstrings and tests in `tests/`.
- PLAN.md calls the data-loading module `data/`; it is `shop_db/` here instead, so that `data/` holds only raw files and the SQLite database (ignored by Git).
- Policy rules must be enforced in tool code, not only in the prompt.
- Benchmark: use the τ³-bench retail domain (`sierra-research/tau2-bench`, pinned in `shop_db/fetch.py`), not the outdated original tau-bench. Notes: `docs/tau-bench-notes.md`.
- Build the full τ³ retail tool set (15 tools), not only those listed in PLAN.md step 2.4. Tools must change the data exactly as τ³ does, because scoring compares DB hashes.

## Progress

- [x] Phase 1 – Setup (uv project, Python 3.11, Git, GitHub: Mohamed-Aljunaid/shophelp-agent)
- [ ] Phase 2 – Shop data and tools (2.1–2.2 done; next: step 2.3, read-only tools)
