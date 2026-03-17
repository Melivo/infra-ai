# AGENTS

This file defines the default Codex working convention for `Melivo/infra-ai`.

## Authority Order

When these documents exist, follow them in this order:

1. `docs/architecture-rules.md`
2. `docs/architecture.md`
3. `AGENTS.md`
4. task-specific prompt files under `docs/prompts/`

If there is a conflict, architecture rules win.

## Default Working Mode

- Default: work directly without sub-agents.
- If the user says `nutze deine agenten`, `nutze die 3 agenten`, or equivalent, use this standard 3-agent setup:
  - Architecture / Implementation Agent
  - QA / Invariants Agent
  - Docs / Prompt Hygiene Agent
- Reuse the same 3-role structure unless the user asks for a different split.
- Do not invent additional agent roles unless there is a strong task-specific reason.

## Agent Responsibilities

### 1. Architecture / Implementation Agent

- owns code changes
- preserves router architectural invariants
- works primarily in:
  - `router/conversation.py`
  - `router/tool_loop.py`
  - `router/provider_output/*`
  - related tests and docs

Must enforce:

- Turn-First Core
- `ExecutionStep` as orchestration unit
- `ExecutionPlan` as first-class state
- provider boundary isolation
- no `Normalized*` leakage into the core

### 2. QA / Invariants Agent

- reviews for architecture-rule violations
- focuses on hidden coupling, determinism, boundary regressions, and missing tests

Must explicitly check:

- no provider-specific logic in router core
- no ad hoc plan reconstruction during execution
- no reintroduction of `NormalizedMessage` / `NormalizedGeneration` as core models
- deterministic bounded tool execution
- compatibility preserved at HTTP/provider boundaries

### 3. Docs / Prompt Hygiene Agent

- updates docs if implementation changes wording or architectural explanation
- keeps prompt templates aligned with current repo practice

Must explicitly check:

- architecture docs still match implementation direction
- prompt templates under `docs/prompts/` stay current
- missing prompt files are called out explicitly

## Repo-Specific Working Rules

- Treat `docs/architecture-rules.md` as non-negotiable.
- Prefer small, explicit, deterministic changes.
- Keep provider-specific parsing inside `router/provider_output/*`.
- Keep `ToolLoopEngine` provider-agnostic.
- Keep `Normalized*` models at boundaries only.
- Preserve current V1 behavior unless the task explicitly changes it.
- Do not add parallel execution, MCP, RAG, or agent-framework behavior unless explicitly requested.
- Use targeted tests for changed behavior.

## Push Policy

- For future sessions, after completing any requested change, commit it and push it to `origin/main` immediately unless the user explicitly says not to.
- Do not wait for a separate `push` instruction after finishing a change.
- Keep commit messages precise and scoped to the change.
