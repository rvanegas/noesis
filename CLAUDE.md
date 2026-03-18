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

### Database migrations (from `backend/`)

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
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

- `api/` — FastAPI routers: `argument.py` (argue, assume, remove, gen-name), `agents.py` (results, active tasks)
- `services/agents.py` — Agent implementations (ContentEvaluation, FormalEvaluator, Formalization, Improvement, NameGeneration)
- `services/agent_coordinator.py` — Thread-based task queue; `AgentResultManager` stores results keyed by `(conversation_id, snapshot_id)`
- `services/agent_prompts.py` — All LLM prompt templates
- `services/argument_service.py` — Core argument manipulation logic
- `core/logic.py` — Mathematical logic formalization classes (terms, predicates, quantifiers, binary ops, modal operators)
- `models/` — SQLAlchemy ORM models; `schemas/` — Pydantic request/response schemas

### Agent System

Agents run in background threads after each user action. The **ImprovementAgent** is the primary user-facing agent; it triggers after content/formal evaluation results are available and generates cohesive recommendation sets to strengthen the concluding proposition. Results are filtered by `snapshot_id` so stale results from earlier conversation states are not shown.

Agent trigger logic lives in `agent_coordinator.py`. Cooldown periods prevent duplicate runs.

### Frontend Structure

- `conversationStore.ts` — Zustand store; single source of truth for conversation state, snapshots, agent results, endorsements
- `ConversationHooks.tsx` — Custom hooks wrapping Axios calls to the backend API
- `AllAgentResults.tsx` — Renders improvement recommendations from agents
- State is snapshot-based: each argument modification creates a new snapshot, enabling isolated agent results per state

### Key Concepts

- **Snapshot**: Immutable capture of argument state at a point in time. Agent results are bound to a snapshot so recommendations remain coherent.
- **Formalization**: Each proposition can be given a formal logical representation (from `core/logic.py`) that a user can endorse. Once all propositions in an argument are endorsed, the FormalEvaluator runs.
- **Improvement recommendations**: Sets of suggested proposition additions/rewrites produced by the ImprovementAgent, each with expected score improvements and reasoning.

## Environment Variables

Backend (`.env` in `backend/`):
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o
DATABASE_URL=postgresql://user:pass@host:5432/db
```

Frontend (`.env` in `frontend/`):
```
VITE_API_BASE_URL=http://localhost:8000
```
