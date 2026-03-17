# Implement Feature

Use this template when you are ready to implement a feature or refactor in `infra-ai`.

Before doing anything else, read:

- `docs/architecture.md`
- `docs/architecture-rules.md`
- `AGENTS.md`
- any directly relevant implementation files

Treat `docs/architecture-rules.md` as binding.

## Mission

Implement the smallest safe change directly in code.

This template is implementation-phase focused:

- do not stop at planning,
- do not broaden the scope once the safe step is identified,
- prefer explicit helpers over clever logic,
- keep runtime behavior deterministic,
- preserve current V1 behavior unless the task explicitly changes it.

## Non-Negotiables

You must preserve all of these:

- `ConversationTurn` remains the primary internal representation.
- `ExecutionStep` remains the orchestration unit.
- `ExecutionPlan` remains first-class state.
- Declared plan structure must be explicit internal state, not only transport metadata on tool calls.
- Plan state must not be reconstructed ad hoc from turns during execution.
- Provider-specific parsing stays in `router/provider_output/*`.
- `ToolLoopEngine` stays provider-agnostic.
- `NormalizedMessage` and `NormalizedGeneration` remain boundary-only.
- Tool outputs use structured `content_json`.
- Execution stays deterministic and bounded by `max_tool_steps`.
- Compatibility must be handled at boundaries, not in the core.

## Implementation Rules

- Make the smallest clean change that solves the task.
- Keep declaration-spec state, declared structure, strategy-derived constraints, and execution progress separate.
- Do not add parallel execution, MCP, RAG, or agent-framework behavior unless explicitly requested.
- Do not leak provider logic into router core orchestration.
- Do not reintroduce `Normalized*` models into the core.
- Prefer small, explicit helpers and narrow data shapes.
- Update tests together with the code change.
- Update docs only if the implementation meaningfully changes architectural wording.

## Required Workflow

1. Inspect the relevant files and identify the current flow.
2. Implement the smallest explicit change in code.
3. Add or update targeted tests for the changed behavior.
4. Run the most relevant tests for the touched surfaces.
5. Fix only the failures introduced by the change.

## Review Checks

Before finishing, verify:

- Does this keep `ConversationTurn` as the core representation?
- Does orchestration still operate on `ExecutionStep` and `ExecutionPlan`?
- Is plan truth explicit rather than reconstructed from turns?
- Is declared structure represented as explicit plan/declaration state rather than only transport metadata?
- Is provider-specific logic confined to `router/provider_output/*`?
- Does the tool loop remain provider-agnostic?
- Are `Normalized*` models still boundary-only?
- Is deterministic bounded execution preserved?
- Is backward compatibility handled at boundaries instead of in the core?

## Required Output Shape

Keep the final report short and concrete.

Include:

- `Implemented`
- `Tests`
- `Risks`
- `Files`
- `Notes`

## Response Style

- Report the concrete change, not a plan.
- Mention the files you changed.
- Mention the tests you ran and whether they passed.
- Call out any intentional limitations or follow-up risks.
