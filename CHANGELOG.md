# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog.

## [0.1.0] - 2026-03-15

### Added

- Router Core as the central, frontend-agnostic platform layer
- Provider routing for local `vLLM`, `Gemini API`, and `OpenAI API`
- Explicit routing modes: `auto`, `local`, `reasoning`, `heavy`
- Router capabilities introspection via `GET /v1/router/capabilities`
- Minimal terminal CLI as a reference frontend
- Minimal structured router logs for start, request flow, route selection, and provider failures

### Improved

- Fail-fast startup configuration validation
- Strict request validation for `POST /v1/chat/completions`
- Consistent router-level error contract for clients
- Router-controlled provider timeouts
- Explicit handling of local-only streaming support
- Clear separation of frontend, router, and provider responsibilities

### Testing

- Router contract matrix tests for chat requests
- GET contract tests for `GET /healthz`, `GET /v1/router/capabilities`, and `GET /v1/models`
- Tests for request validation, provider error normalization, and provider timeouts
- Logging helper tests for stable structured log payloads

### Docs

- README updated to reflect the current router platform contract
- Frontend architecture documented
- Planning documents added for future Code OSS and browser companion integrations
- Repository strategy, architecture, and roadmap documented for the first public router-core release
