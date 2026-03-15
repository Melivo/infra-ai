# Roadmap

## Current Status

The router core is currently stable as the public platform boundary.

This includes:

- frontend-agnostic router architecture
- explicit provider routing
- strict request validation
- normalized error contract
- router-level provider timeouts
- minimal structured router logging
- contract-oriented tests for chat and GET endpoints
- CLI as a thin reference frontend

## Deferred / Explicitly Out of Scope for v0.1.0

- tool calling
- agents
- MCP integration
- RAG or project context
- IDE integration
- browser companion
- workflow automation

These items are intentionally deferred so the first public release can stay focused on a stable router-core platform contract.

## Next Major Expansion Paths

- tool execution layer on top of the router
- agent layer on top of tools
- project context and RAG support
- additional frontends on top of the same router contract
