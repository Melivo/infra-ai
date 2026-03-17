# Architecture

The non-negotiable architectural invariants for this repository are defined in [docs/architecture-rules.md](docs/architecture-rules.md).

## System Structure

`infra-ai` is organized around a central router platform.

```text
Frontend
  -> infra-ai Router
    -> Provider Layer
      -> local vLLM
      -> Gemini API
      -> OpenAI API
```

The router is the stable platform boundary.

## Layer Responsibilities

### Frontends

Frontends are thin clients.

- They talk only to the router.
- They do not contain model logic.
- They do not contain provider logic.
- They do not implement routing policy.

Current frontend:

- terminal CLI as reference frontend

Planned future frontends remain outside the router core.

### Router

The router controls:

- request validation
- routing modes and policies
- provider selection
- provider response normalization into turn and execution-step state
- tool-loop orchestration against explicit declared-plan, strategy and progress state
- sequential plan execution with explicit dependency-carrying plan nodes
- provider error normalization
- timeout policy
- streaming behavior at the platform boundary
- public capabilities and model discovery endpoints

The router is frontend-agnostic.

Within the router, the orchestration direction is intentionally:

```text
provider output
  -> explicit execution step state
  -> explicit execution plan state
  -> execution progression
  -> turns / history compatibility views
```

V1 still keeps `execution_steps_from_turns()` as a compatibility and recovery path, but orchestration truth now comes primarily from parser-produced step state and explicit plan transitions during the tool loop.

### Provider Layer

Providers are replaceable backend modules behind the router.

- `local_vllm`
- `gemini_fallback`
- `openai_responses`

Providers do not define the public platform contract on their own. The router does.

## Current Platform Guarantees

- strict request validation for `POST /v1/chat/completions`
- explicit routing behavior via `auto`, `local`, `reasoning`, and `heavy`
- no silent cloud fallback
- normalized error contract for frontend clients
- router-level provider timeouts
- router-internal normalized model output
- controlled automatic tool loop for non-streaming requests
- minimal structured router logging
- frontend-agnostic router boundary
- provider modules behind a stable router API
- `GET /v1/models` currently exposed as a local compatibility path, not a multi-provider discovery layer

## Not Yet Implemented

- agents
- MCP integration
- RAG or project context
- workflow automation
- parallel tool calls
- IDE integration
- browser companion
