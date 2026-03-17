# Plan Feature

Use this template when planning a feature or refactor in `infra-ai`.

Before planning, read:

- `docs/architecture.md`
- `docs/architecture-rules.md`
- any directly relevant implementation files

Treat the architecture rules as binding.

## Planning Goals

Produce a plan that:

- preserves router architectural invariants,
- keeps boundaries explicit,
- prefers the smallest clean step,
- keeps runtime behavior deterministic,
- avoids fake explicitness or hidden coupling.

## Planning Checklist

1. Restate the problem in repo terms.
2. Summarize the current behavior.
3. Identify the architectural invariants that constrain the change.
4. Name the smallest acceptable design step.
5. Separate clearly:
   - declaration-spec state
   - declared structure
   - strategy-derived constraints
   - execution progress
   - boundary compatibility logic
6. List the files likely to change.
7. List the tests that must be added or updated.
8. List explicit non-goals.
9. Call out risks, open questions, and rollback points.

## Required Output Shape

Keep the plan short and concrete.

Include:

- `Problem`
- `Current State`
- `Constraints`
- `Proposed Change`
- `Files`
- `Tests`
- `Risks`
- `Out of Scope`

## Repo-Specific Review Questions

Before finalizing the plan, answer these:

- Does this keep `ConversationTurn` as the core representation?
- Does orchestration still operate on `ExecutionStep` and `ExecutionPlan`?
- Is plan truth explicit rather than reconstructed from turns?
- Is declared structure represented as explicit plan/declaration state rather than only transport metadata on tool calls?
- Is provider-specific logic confined to `router/provider_output/*`?
- Does the tool loop remain provider-agnostic?
- Are `Normalized*` models still boundary-only?
- Is deterministic bounded execution preserved?
- Is backward compatibility handled at boundaries instead of in the core?
