# ShopHelp Customer Support Agent – Project Plan

This document is a build plan meant to be handed to Claude Code. Work one step at a time, in order. Test, commit and push after every step.

## 1. Project overview

A customer support agent for a fictional online shop. Customers chat with it to check orders, cancel, return or exchange items, and update details. Unlike a plain chatbot, the agent takes real actions on the shop database through tools, while following the shop's written policy.

Key selling points for the portfolio:

- Measured quality: evaluated on the retail domain of τ-bench (Sierra), with pass^k to show reliability, not just average success.
- Safety: identity checks, policy enforcement, confirmation before any change, and human approval for risky actions.
- Model-agnostic: Gemini by default, with Claude and OpenAI as drop-in options.
- Built with LangGraph, with a clear reason: multi-turn conversations, tool calls, branching and human-in-the-loop approval.

## 2. Environment and constraints (must follow)

- OS: Windows. 8 GB RAM. No GPU. Everything runs on CPU.
- The C: drive is full. The project and ALL caches live on E:. Project root: `E:\projects\shophelp-agent`.
- Use the same cache environment variables as the FinanceBench project: `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `HF_HOME`, `npm_config_cache`, `TEMP`/`TMP`, all pointing to folders under `E:\cache` (run `E:\projects\setup_e_drive.ps1`).
- The developer is in Sudan. Prefer open-source, locally-run tools, with a local fallback for every online service.
- Default LLM: Gemini (free tier). Expect rate limits: throttle requests, retry with backoff, and cache responses where it is safe.
- Evaluation uses an LLM for the simulated customer too, so each test costs about twice as many requests. Keep test runs small.

## 3. Tech stack

- Python environment and packages: uv
- Backend: FastAPI
- Frontend: React (Vite + TypeScript)
- Agent orchestration: LangGraph, with a checkpointer to keep conversation state
- Shop data: the τ-bench retail domain data (users, orders, products), loaded into SQLite on E:
- LLM: Gemini via the `google-genai` SDK (default); Anthropic and OpenAI as optional providers behind one interface
- Evaluation: τ-bench retail tasks (simulated user + final database check) plus a custom runner
- Tracing: LangSmith, with Arize Phoenix or Langfuse as a local fallback
- Config: `.env` plus pydantic-settings

## 4. Architecture

- `shop_db/` – loads the τ-bench retail data into SQLite and can reset it to a clean state. (Raw files and the database itself live in `data/`.)
- `tools/` – one Python function per action (look up user, get order, cancel order, return items, exchange items, modify address, transfer to human). Each tool validates inputs and enforces policy rules in code.
- `policy/` – the shop policy text given to the agent.
- `llm/` – provider interface: `GeminiProvider` (default), `AnthropicProvider`, `OpenAIProvider`, chosen with `LLM_PROVIDER`.
- `agent/` – the LangGraph graph.
- `eval/` – τ-bench runner, metrics and reports.
- `api/` – FastAPI app. `frontend/` – React chat app.

## 5. Build phases

### Phase 1 – Setup

- **Step 1.1:** set the E: cache variables, create the project with `uv init`, folder structure, `.env.example`, `.gitignore`, README skeleton.
- **Step 1.2:** initialise Git, create the GitHub repo, push the first commit.
- Done when: the project runs on E:, nothing was written to C:, and the repo is on GitHub.

### Phase 2 – Shop data and tools

- **Step 2.1:** get the retail domain data and policy from the `sierra-research/tau-bench` GitHub repo. Study its structure and tools before writing code.
- **Step 2.2:** load users, orders and products into SQLite, with a reset function so every test starts from the same state.
- **Step 2.3:** read-only tools: find user by email or by name and zip code, get user details, get order details, get product details.
- **Step 2.4:** action tools: cancel pending order, return delivered items, exchange delivered items, modify pending order address, transfer to a human agent.
- **Step 2.5:** enforce the policy in code, not only in the prompt (for example, only pending orders can be cancelled). Add unit tests for every tool.
- Done when: all tools pass their tests and the database resets cleanly.

### Phase 3 – Baseline agent

- **Step 3.1:** provider interface with tool calling for Gemini; stubs for Claude and OpenAI.
- **Step 3.2:** a simple tool-calling loop in LangGraph: model → tools → model, until it replies to the user.
- **Step 3.3:** system prompt with the shop policy, and rules: authenticate the user first, never invent information, confirm with the user before any change.
- **Step 3.4:** a command-line chat to try it manually.
- Done when: a manual conversation can authenticate a user and cancel an order correctly.

### Phase 4 – Evaluation (baseline)

- **Step 4.1:** connect the agent to the τ-bench retail tasks (simulated user + final database comparison).
- **Step 4.2:** pick a small subset first (10 to 20 tasks) and make the subset a config setting.
- **Step 4.3:** run each task 2 or 3 times and report pass^1 and pass^k, plus the average number of turns and tool calls.
- **Step 4.4:** save results and failed conversations in `eval/reports/`. Write a short failure analysis (for example: skipped authentication, wrong item, acted without confirmation).
- Put baseline scores in the README.

### Phase 5 – Safety and improvements

- **Step 5.1:** an explicit authentication step in the graph: no account tools until the user is verified.
- **Step 5.2:** a confirmation step: before any action tool, the agent must summarise the change and get a clear yes.
- **Step 5.3:** human-in-the-loop with LangGraph `interrupt`: refunds above a set amount pause for staff approval.
- **Step 5.4:** guardrails: refuse requests outside the shop's scope and resist attempts to bypass the policy.
- **Step 5.5:** re-run the evaluation and compare with the baseline in the README.

### Phase 6 – API and frontend

- **Step 6.1:** FastAPI endpoints: `POST /chat` (session ID + message), `GET /sessions/{id}`, `POST /approvals/{id}` (approve or reject), `GET /health`. Add CORS and basic tests.
- **Step 6.2:** React chat app with Vite + TypeScript, npm cache on E:.
- **Step 6.3:** a side panel showing tool calls and their results, so the viewer sees what the agent did.
- **Step 6.4:** a simple staff view listing pending approvals with approve and reject buttons.
- Done when: the full flow works locally in the browser.

### Phase 7 – Tracing and monitoring

- LangSmith tracing for every conversation, optional via env var, with Phoenix or Langfuse as a local fallback.
- Log latency, token usage, tool errors and escalations per conversation.

### Phase 8 – Packaging and deployment (optional, last)

- Everything runs locally with one command per service, documented in the README.
- A short demo video, screenshots, and the score tables in the README.
- Optional: Podman or Docker Engine, and free hosting such as Hugging Face Spaces, if available from Sudan.

## 6. Rules for Claude Code

- Follow the phases in order. Work on one step at a time.
- After every step: run the tests, commit with a clear message (for example `phase-2.4: add action tools`), and push to GitHub. Tag the end of each phase (for example `phase-2-done`) and push the tag.
- If a step fails or is unclear, stop and ask instead of guessing.
- Keep everything on E:. Never write caches, models or data to C:.
- Policy rules must be enforced in tool code, not only in the prompt.
- Keep the LLM provider swappable. No provider-specific code outside `llm/`.
- Never commit API keys, `.env`, databases or large data files.
- Simple, readable code with short docstrings and tests. Update the README after each phase.
