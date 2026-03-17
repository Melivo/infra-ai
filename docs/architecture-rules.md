# Architecture Rules

This document defines the non-negotiable architectural invariants of `infra-ai`.

These rules must never be violated.
All refactors and features must preserve them.

## 1. Turn-First Core

- `ConversationTurn` is the primary internal representation.
- All router logic operates on turns.
- No feature may introduce an alternative internal core representation.

## 2. ExecutionStep Is the Orchestration Unit

- `ExecutionStep` is the authoritative unit for:
  - reasoning
  - planning
  - execution
  - finalization
- Orchestration logic must operate on steps, not raw turns.

## 3. ExecutionPlan Is First-Class State

- `ExecutionPlan` represents:
  - tool calls
  - dependencies
  - execution state
- Declared plan structure must be represented as explicit internal plan state and must not rely solely on transport metadata attached to tool-call turns.
- Plan state must not be reconstructed ad hoc from turns during execution.
- Sequential execution is a strategy, not the definition of the plan.

## 4. Provider Boundary Isolation

- Providers must not leak into router core logic.
- Provider-specific parsing only happens in:
  - `router/provider_output/*`
- The tool loop and execution logic must remain provider-agnostic.

## 5. Tool Loop Purity

- `ToolLoopEngine` must:
  - operate only on internal models (`turns`, `steps`, `plans`)
  - not depend on provider formats
- No provider-specific branching inside the tool loop.

## 6. Normalized Models Are Boundary-Only

- `NormalizedMessage` and `NormalizedGeneration` are:
  - API boundary
  - provider serialization layer
- They must not be used as internal core models.

## 7. Structured Tool Results

- Tool outputs must use structured data (`content_json`).
- String-based parsing inside the core is forbidden.

## 8. No Hidden Coupling

- No implicit dependencies between:
  - router core
  - provider layer
  - HTTP layer
- Data flow must be explicit and directional.

## 9. Deterministic Execution

- Tool execution must remain:
  - deterministic
  - bounded via `max_tool_steps`
- No uncontrolled agent-like behavior.

## 10. Backward Compatibility via Boundaries

- Changes to internal models must not break:
  - HTTP API
  - provider integrations
- Compatibility must be handled at boundaries, not in the core.

## Refactor Checklist

Before merging any change, verify:

- Does this introduce provider logic into the core?
- Does this bypass `ExecutionStep` or `ExecutionPlan`?
- Does this reintroduce `Normalized*` into the core?
- Does this create hidden coupling?
- Does this break determinism?

If yes, redesign.
