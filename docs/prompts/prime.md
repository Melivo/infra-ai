# Prime

You are working in repo `Melivo/infra-ai` on current `main`.

Before doing anything else:

1. Read and follow:
   - `docs/architecture.md`
   - `docs/architecture-rules.md`
   - `AGENTS.md` if present
2. Treat `docs/architecture-rules.md` as non-negotiable.
3. If present and relevant, also use:
   - `docs/prompts/plan_feature.md`
   - `docs/prompts/review.md`

## Session Grounding

- `infra-ai` is router-centered.
- The router is the stable platform boundary.
- Frontends stay thin and must not contain provider logic.
- Providers stay behind the router and must not define the public contract.
- `AGENTS.md` defines repo working conventions, but architecture rules win on conflict.

## Core Invariants

You must preserve all of these:

- `ConversationTurn` is the primary internal representation.
- `ExecutionStep` is the orchestration unit.
- `ExecutionPlan` is first-class state.
- Plan state must not be reconstructed ad hoc from turns during execution.
- Provider-specific parsing only happens in `router/provider_output/*`.
- `ToolLoopEngine` must remain provider-agnostic.
- `NormalizedMessage` and `NormalizedGeneration` are boundary-only.
- Tool outputs use structured `content_json`.
- Execution must remain deterministic and bounded by `max_tool_steps`.
- Compatibility belongs at boundaries, not in the core.

## Working Rules

- Prefer small, explicit, low-magic changes.
- Preserve current V1 behavior unless the task explicitly changes it.
- Do not introduce parallel execution, MCP, RAG, or agent-framework behavior unless explicitly requested.
- Do not leak provider logic into router core orchestration.
- Do not reintroduce `Normalized*` models into the core.
- Keep `execution_steps_from_turns()` as compatibility/recovery only unless the architecture docs change.
- Prefer targeted tests over broad rewrites.

## Default Startup Output

At the start of the task, briefly confirm:

1. you read the architecture docs,
2. the main invariants that matter for this task,
3. the first files or surfaces you will inspect.
