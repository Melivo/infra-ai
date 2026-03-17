# Router Change Checklist

Use this before merging a router change.

This is an operational checklist, not a replacement for `docs/architecture.md` or `docs/architecture-rules.md`.

- Router core still uses `ConversationTurn` as the primary internal representation.
- Orchestration still runs through `ExecutionStep` and `ExecutionPlan`, not raw-turn inference in the hot path.
- Declared plan structure is explicit internal state, not only transport metadata on tool calls.
- Provider-specific parsing stays inside `router/provider_output/*`.
- `ToolLoopEngine` remains provider-agnostic and operates only on internal router models.
- No `Normalized*` model leaked back into router core logic.
- Tool results still use structured `content_json` in the core.
- Execution remains deterministic and bounded by `max_tool_steps`.
- HTTP/provider compatibility is handled at boundaries, not patched into the core.
- Targeted tests were added or updated for changed router behavior, provider-boundary behavior, and tool-loop behavior as needed.
