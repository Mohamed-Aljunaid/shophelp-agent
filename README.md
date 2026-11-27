# ShopHelp Customer Support Agent

A customer support agent for a fictional online shop. Customers chat with it to check orders, cancel, return or exchange items, and update their details. Unlike a plain chatbot, it **takes real actions on the shop database through tools**, while the shop's written policy is **enforced in code**, not just in the prompt.

- **Measured, not assumed:** evaluated on the retail domain of [τ³-bench](https://github.com/sierra-research/tau2-bench) (Sierra) with a simulated customer, scoring **pass^k** to show reliability across repeated runs.
- **Safe by construction:** login before account access, own data only, explicit confirmation before any change, staff approval for large refunds, and guardrails against policy-bypass attempts.
- **Model-agnostic:** Gemini by default (free tier: throttled, retried, cached); Claude and OpenAI plug in behind one interface.
- **Built with LangGraph** for a clear reason: multi-turn state, tool calls, branching, and human-in-the-loop pauses (`interrupt`).

> Demo video and screenshots: see [docs/demo.md](docs/demo.md) (to be recorded).

## How it works

```
 customer ──► React chat (:5280) ──► FastAPI ──► LangGraph agent ──► LLM (Gemini / Claude / OpenAI)
                                        │             │
 staff ─────► staff view (/#staff) ─────┘             ├─► policy layer ──► 16 shop tools ──► SQLite
              approve / reject refunds                │   (login, ownership,     (τ³ retail)
                                                      │    confirmation, approval)
                                                      └─► event log (latency, tokens, tool errors, escalations)
```

Each customer message runs the graph **model → tools → model** until the agent replies. Every tool call passes through these checks, in order:

| Layer | Rule (enforced in code) | Where |
|---|---|---|
| Authentication | Until the customer is verified (email, or name + zip), the model is only offered the login tools; account tools are refused anyway. | [agent/graph.py](agent/graph.py), [tools/policy.py](tools/policy.py) |
| Ownership | One customer per conversation; other customers' orders look like "not found". | [tools/policy.py](tools/policy.py) |
| Confirmation | A write runs only right after a clear "yes" to a summary that named the order. | [agent/confirm.py](agent/confirm.py) |
| Staff approval | Refunds above `REFUND_APPROVAL_THRESHOLD` pause the graph until staff approve or reject. | [agent/approval.py](agent/approval.py) |
| Shop rules | Only pending orders can be cancelled, refunds go to the original method or a gift card, and so on (τ³'s rules). | [tools/action_tools.py](tools/action_tools.py) |
| Guardrails | Out-of-scope requests are declined; bypass attempts ("I'm the manager", "ignore your rules") get a reminder, and red-team tests show the checks above still hold if the model is fooled. | [agent/guardrails.py](agent/guardrails.py) |

The 16 tools reproduce τ³-bench's retail tools exactly (cross-checked against τ³'s own code on all 114 tasks), so scores are comparable to the benchmark.

## Results

Evaluation: 15 tasks from τ³-bench's retail test split × 3 trials; an LLM plays the customer; a task passes if the final database exactly matches the expected one. (τ³'s official score also uses an LLM judge for written assertions, which we skip, so our numbers can be a little higher.)

| Agent | pass^1 | pass^2 | pass^3 | avg turns | avg tool calls |
|---|---|---|---|---|---|
| Baseline (Phase 3) | pending | pending | pending | | |
| With safety layers (Phase 5) | pending | pending | pending | | |

The runs are limited by the Gemini free-tier daily quota; reports and failed conversations are saved in `eval/reports/`.

## Run locally

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 20.19+, and a free [Gemini API key](https://aistudio.google.com/). On this machine all caches live on E: (run `E:\projects\setup_e_drive.ps1` once).

**Setup (once):**

```powershell
uv sync                          # Python 3.11 env + dependencies
copy .env.example .env           # fill in GEMINI_API_KEY, GEMINI_MODEL, STAFF_TOKEN
uv run python -m shop_db.fetch   # download the τ³-bench retail data into data/
uv run python -m shop_db.store   # build (or reset) the shop database data/shop.db
cd frontend; npm install; cd ..
```

**Run (one command per service):**

| What | Command | Open |
|---|---|---|
| Everything, production build | `cd frontend; npm run build; cd ..` then `uv run python -m api` | http://localhost:8000 (staff: `/#staff`) |
| API, development | `uv run uvicorn api.app:create_app --factory --reload` | http://localhost:8000/docs |
| Frontend, development | `cd frontend; npm run dev` | http://localhost:5280 (staff: `/#staff`) |
| Terminal chat | `uv run python -m agent.cli --reset` | – |

To try the approval flow: log in as `ethan.lopez8943@example.com`, ask to cancel order `#W6779827` ($4,079.45), say yes, then approve it in the staff view with your `STAFF_TOKEN`.

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `anthropic` or `openai` (the last two are stubs) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | – | Gemini credentials and model name |
| `LLM_MAX_REQUESTS_PER_MINUTE` | `10` | Throttle for free-tier limits |
| `LLM_CACHE` | `true` | Cache LLM replies in `data/llm_cache.sqlite` |
| `REFUND_APPROVAL_THRESHOLD` | `200` | Refunds above this need staff approval |
| `STAFF_TOKEN` | empty | Required to list/decide approvals; empty disables them |
| `API_HOST`, `API_PORT` | `127.0.0.1`, `8000` | Where `python -m api` listens |
| `CORS_ORIGINS` | `["http://localhost:5280"]` | Browser origins allowed to call the API |
| `EVAL_SPLIT`, `EVAL_TASK_COUNT`, `EVAL_TASK_IDS`, `EVAL_TRIALS` | `test`, `15`, –, `3` | Evaluation subset and trials |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | `false`, – | Optional LangSmith tracing |

## Evaluate

```powershell
uv run python -m eval.runner --task 88 -v          # one task, print the conversation
uv run python -m eval.runner --name baseline       # configured subset × trials; saved to eval/reports/baseline/
```

Each run saves `results.jsonl` (resumable: rerun the same `--name` after a quota stop), `summary.json` (pass^k, averages) and `failures/*.md` (failed conversations with expected vs actual database changes). Each trial gets fresh LLM replies, so pass^k is meaningful.

## Monitoring

Every conversation is logged locally to `data/logs/events.jsonl`: each LLM call (latency, input/output tokens, cache hit), tool call (ok or error), escalation (transfer to a human, staff approval and its decision) and guardrail flag. No extra service is needed.

```powershell
uv run python -m agent.monitor            # per-conversation report (last 20)
uv run python -m agent.monitor --last 100
```

LangSmith tracing is optional: set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`.

## Tests

```powershell
uv run pytest                    # ~160 tests; offline except one live Gemini check
uv run pytest -k "not gemini_live"
cd frontend; npm test; npm run build; npm run lint
```

The tests use a scripted fake model, so they cover the agent loop, every policy layer, the API, the approval flow and the evaluation runner without spending LLM quota.

## Project structure

```
agent/      LangGraph graph, system prompt, confirmation, approval, guardrails, monitoring, CLI
tools/      the 16 shop tools (read + action) and the policy layer
llm/        provider interface: Gemini, plus Claude/OpenAI stubs; throttle, retry, cache, tracing
shop_db/    fetch τ³-bench retail data; SQLite store with reset
policy/     the shop policy given to the agent
eval/       τ³-bench runner, pass^k metrics, reports
api/        FastAPI app (python -m api runs everything)
frontend/   React + Vite + TypeScript chat and staff view
docs/       benchmark notes, demo script
tests/      pytest suite
```

## Limitations

- Sessions and pending approvals are kept in memory: restarting the API forgets them. One agent turn runs at a time.
- The confirmation check looks for a clear "yes" by keywords and checks only the order id / zip in the summary.
- Refunds from price differences (exchanges, item changes) are not gated by staff approval.
- No container image yet (no Docker/Podman on the build machine); hosting is not set up.

## Credits

Shop data, tasks, tool behaviour and policy come from [τ³-bench](https://github.com/sierra-research/tau2-bench) by Sierra (MIT license). See [docs/tau-bench-notes.md](docs/tau-bench-notes.md).
