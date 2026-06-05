# Noesis

**Real-time argument evaluation SPA**
React 19 · TypeScript · Zustand · Immer · Tailwind · Vite

---

## What it is

Noesis is a single-user web application for building and evaluating arguments step by step. The user adds propositions and inferential connections; the application evaluates each proposition for truth and each inference for validity in real time, with suggestions for improvement at every step.

It is the interactive frontend for the [Dianoia](https://github.com/rvanegas/dianoia) argument analysis backend.

Named after the Greek term for the highest form of intellectual cognition — direct apprehension of first principles — in Plato's divided line.

---

## Why it exists

Noesis began as a practical tool for argument construction and evaluation. In use, it evolved into something more interesting: a research instrument for studying how well language models actually track logical validity, as opposed to how fluent they are at producing argument-shaped text.

The gap between these two things — argumentative fluency and genuine validity tracking — turns out to be significant and revealing. Noesis makes that gap visible.

---

## Architecture

**State model**: Argument state is managed with Zustand and Immer. All AI evaluations are snapshot-bound — they are tied to the specific argument state that triggered them, so that editing a proposition mid-evaluation does not corrupt or invalidate in-flight results. This enables reliable undo/redo without surprising the user with stale AI assessments.

**Concurrency control**: A three-mode UI state machine (idle, evaluating, editing) prevents concurrent operations that would produce inconsistent state. A polling loop with ref-based concurrency control prevents overlapping fetch requests and stale snapshot results from the Dianoia backend.

**Real-time feedback**: Evaluation results stream back from Dianoia as each agent completes its assessment, giving the user progressive feedback rather than a single blocking wait.

---

## What it demonstrates

- Snapshot-based state management for AI-assisted applications where results must be tied to the state that produced them
- UI state machine design for concurrency control in async workflows
- Integration with a multi-agent backend via polling with stale-result prevention
- A domain model derived from formal logic applied to an interactive editing interface

---

## Related projects

- [Dianoia](https://github.com/rvanegas/dianoia) — the argument analysis backend Noesis calls
- [mdc](https://github.com/rvanegas/mdc) — terminal research platform with Dianoia integration
- [Roxana](https://github.com/rvanegas/roxana) — multi-user collaborative version of similar ideas
