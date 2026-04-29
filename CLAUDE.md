# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Noesis** is the React frontend for an AI-powered argumentation platform. Users build structured logical arguments (thesis + assumptions → conclusion) and review AI-generated evaluations and improvement recommendations. The companion server is **Dianoia** (`~/src/dianoia`).

## Commands

### Frontend (run from `frontend/`)

```bash
npm run dev          # dev server (press 'o' to open browser, 'q' to quit)
npm run typecheck    # TypeScript check
npm run lint         # ESLint
npm run build        # production build

# or use scripts:
./bin/frontend-dev
./bin/frontend-type-check
./bin/frontend-build
```

## Architecture

### Request Flow

```
Noesis (React/Zustand) → FastAPI routes on Dianoia → Agent results (polled)
```

### Frontend Structure

- `conversationStore.ts` — Zustand store (with Immer); single source of truth for conversation state, snapshots, agent results, endorsements. `sessionId` is a `crypto.randomUUID()` generated once per browser session.
- `ConversationHooks.tsx` — Custom hooks wrapping Axios calls; `makeApiCall()` and `handleApiError()` handle 422 `AssistantResponseError` responses
- `AllAgentResults.tsx` — Renders improvement recommendations from agents
- State is snapshot-based: each argument modification creates a new snapshot, enabling isolated agent results per state

### Key Concepts

- **Snapshot**: Immutable capture of argument state at a point in time. Agent results are bound to a snapshot so recommendations remain coherent.
- **Formalization**: Each proposition can be given a formal logical representation that a user can endorse. Once all propositions are endorsed, the Formal Evaluator runs on the server.
- **Improvement recommendations**: Sets of suggested proposition additions/rewrites, each with expected score improvements and reasoning.

## Configuration

```
frontend/.env
```

```
VITE_API_BASE_URL=http://localhost:8000
```

Point `VITE_API_BASE_URL` at wherever the Dianoia server is running.
