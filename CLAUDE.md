# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Dianoia** is an AI-powered argumentation platform. Users build structured logical arguments (thesis + assumptions → conclusion) and receive AI-generated evaluations and improvement recommendations via background agents.

## Commands

### Backend (run from `backend/`)

```bash
# Dev server
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
# or:
./bin/backend-dev

# Tests
pytest                        # all tests
pytest tests/test_file.py::TestClass::test_method -v  # single test
pytest -k "test_improvement"  # by keyword

# Type checking / linting / formatting
mypy .
pylint backend/
black --check .
```

### Frontend (run from `frontend/`)

```bash
npm run dev          # dev server
npm run typecheck    # TypeScript check
npm run lint         # ESLint
npm run build        # production build

# or use scripts:
./bin/frontend-dev
./bin/frontend-type-check
```

### Full stack

```bash
./bin/dev-docker     # Docker Compose (backend + frontend + PostgreSQL)
docker-compose up --build
```

## Architecture

### Request Flow

```
Frontend (React/Zustand) → FastAPI routes (api/) → Service layer (services/) → LLM (OpenAI)
                                                         ↓
                                               Agent Coordinator (background threads)
                                                         ↓
                                               AgentResultManager (in-memory, TTL 3 days)
                                                         ↑
Frontend polls GET /api/agents/results ────────────────────────────────────────
```

### Backend Structure

- `api/argument.py` — Routes: `argue`, `assume`, `remove`, `replace`, `user-justify`, `explain`, `reject-formalization`, `endorse-formalization`, `upload`, `gen-name`
- `api/agents.py` — Routes: `GET /api/agents/results` (grouped by type, filtered by snapshot), `GET /api/agents/active`
- `services/agents.py` — Agent implementations: `ContentEvaluationAgent`, `FormalEvaluatorAgent`, `FormalizationAgent`, `ImprovementAgent`, `NameGenerationAgent`
- `services/agent_coordinator.py` — Thread-based task queue; `AgentResultManager` stores results keyed by `(conversation_id, snapshot_id)`; handles TTL cleanup and cooldown periods
- `services/agent_prompts.py` — All LLM prompt templates
- `services/argument_service.py` — Core argument manipulation (`next_symbol()`, `new_step()`, `clean_citations()`)
- `services/conversation.py` — `Gpt` wrapper class for name generation and explanations
- `core/logic.py` — Mathematical logic formalization: `Term` (Variable, Constant), `Formula` (Predicate, PropVar, Equality, Quantifier, BinaryOp, Modal), each with `to_dict()` / `to_unicode()` / `to_ascii()`
- `schemas/` — Pydantic request/response schemas
- `startup_init.py` — Background thread that pre-warms GPT instances at server startup to avoid first-request delays

### Agent System

Agents run in background threads after each user action. The **ImprovementAgent** is the primary user-facing agent; it triggers after content/formal evaluation results are available and generates cohesive recommendation sets to strengthen the concluding proposition. Results are filtered by `snapshot_id` so stale results from earlier conversation states are not shown.

**Agent filtering:** `FilteredAgentInput` (in `schemas/agent_input.py`) strips irrelevant data before passing to each agent — the `ContentEvaluationAgent` never sees formalization data, the `FormalEvaluatorAgent` never sees natural-language proposition text. Use the class methods `for_content_evaluation()`, `for_formal_evaluation()`, `for_formalization()` when constructing agent inputs.

**Conversation ID format:** Composite key `"session_id:conversation_id"` — enables multi-conversation sessions from a single browser session.

Agent trigger logic and cooldown periods live in `agent_coordinator.py`.

### Frontend Structure

- `conversationStore.ts` — Zustand store (with Immer); single source of truth for conversation state, snapshots, agent results, endorsements. `sessionId` is a `crypto.randomUUID()` generated once per browser session.
- `ConversationHooks.tsx` — Custom hooks wrapping Axios calls; `makeApiCall()` and `handleApiError()` handle 422 `AssistantResponseError` responses
- `AllAgentResults.tsx` — Renders improvement recommendations from agents
- State is snapshot-based: each argument modification creates a new snapshot, enabling isolated agent results per state

### Key Concepts

- **Snapshot**: Immutable capture of argument state at a point in time. Agent results are bound to a snapshot so recommendations remain coherent.
- **Formalization**: Each proposition can be given a formal logical representation (from `core/logic.py`) that a user can endorse. Once all propositions in an argument are endorsed, the `FormalEvaluatorAgent` runs.
- **Improvement recommendations**: Sets of suggested proposition additions/rewrites produced by the `ImprovementAgent`, each with expected score improvements and reasoning.

### Test Patterns

Tests use FastAPI `TestClient`, mock `coordinator.queue_task()`, and patch GPT calls. Key test files: `test_api_argument.py` (route integration), `test_improvement_agent*.py` (trigger logic), `test_api_agents_stale_results.py` (snapshot filtering), `test_result_manager.py` (TTL/cleanup), `test_dual_evaluators.py` (content + formal interaction).

## Environment Variables

Backend (`.env` in `backend/`):
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o
OPENAI_ASSISTANT_ID=...   # optional
```

Frontend (`.env` in `frontend/`):
```
VITE_API_BASE_URL=http://localhost:8000
```
