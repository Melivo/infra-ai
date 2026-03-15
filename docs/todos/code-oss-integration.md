# Code OSS Integration TODO

## 1. Goal of the IDE Integration

`infra-ai` should integrate with Code OSS / VS Code so the IDE can act as another frontend for the existing router platform.

The IDE must remain a frontend only:

- it talks only to the `infra-ai` Router
- it never talks directly to OpenAI, Gemini, or local model runtimes
- it does not own routing logic
- it does not own provider logic
- it does not store provider API keys

The router remains the single AI orchestration layer:

```text
Code OSS
  -> infra-ai Router
    -> local vLLM
    -> Gemini API
    -> OpenAI API
```

This keeps all model selection, route selection, timeout handling, error normalization, and future tool or agent behavior in one backend layer.

## 2. Possible Integration Approaches

### VS Code Extension

Short explanation:
A standard extension can add commands, views, panels, settings, and HTTP communication with the router.

Pros:

- full control over UI and router communication
- works well with Code OSS / VS Code extension model
- easy to keep the IDE as a thin client
- can evolve from simple chat to richer router-backed workflows

Cons:

- requires extension packaging and maintenance
- more UI and lifecycle work than a minimal script-based integration

Compatibility with infra-ai router architecture:
High. This aligns best with the router as the single backend integration point.

### Chat Participant

Short explanation:
Use the IDE chat participant model so infra-ai appears as one participant inside the built-in chat experience.

Pros:

- native IDE chat UX
- lower UI design burden if the host chat APIs are available

Cons:

- depends on specific VS Code chat APIs and edition support
- may be more constrained than a custom extension surface
- can push architecture toward editor-specific assumptions

Compatibility with infra-ai router architecture:
Medium. It can still use the router cleanly, but host API constraints may shape the frontend too much.

### Language Model Provider

Short explanation:
Expose infra-ai through the IDE's language model provider interfaces, if available.

Pros:

- potentially deep IDE integration
- could reuse built-in chat or completion surfaces

Cons:

- depends heavily on editor API maturity
- may blur boundaries between frontend and backend if not designed carefully
- can create pressure to mirror provider or model concepts in the extension

Compatibility with infra-ai router architecture:
Medium. Possible, but more care is needed to keep router authority intact.

### Custom Chat Panel

Short explanation:
Build a dedicated webview or panel inside the extension for infra-ai chat.

Pros:

- full control over UI, streaming, and router-specific features
- easy to reflect router capabilities and routing modes directly
- does not depend on built-in chat platform constraints

Cons:

- more UI code to own
- needs explicit design for state, sessions, and streaming rendering

Compatibility with infra-ai router architecture:
High. A custom panel can stay fully router-centric and frontend-only.

### OpenAI-Compatible Endpoint Usage

Short explanation:
Point an IDE integration layer at the router's OpenAI-compatible API surface.

Pros:

- simplest initial protocol fit
- can reuse common chat request patterns

Cons:

- not enough on its own for router-specific capabilities
- can hide routing modes and capabilities unless extra router endpoints are also used
- may encourage treating infra-ai as only a generic OpenAI proxy

Compatibility with infra-ai router architecture:
Medium to high. Useful as one transport pattern, but incomplete without router-specific capability and model endpoints.

## 3. Recommended Architecture

Preferred solution:

**Custom VS Code / Code OSS Extension**

```text
Code OSS IDE
  -> infra-ai Extension
    -> infra-ai Router API
      -> Providers
```

Why this is the cleanest fit:

- the IDE remains only a frontend
- the extension can consume router capabilities, model lists, routing modes, and streaming responses
- provider details stay fully backend-side
- routing behavior is not duplicated in the extension
- future router features such as context, tools, agents, or MCP can remain backend-driven

This approach keeps the system architecture honest: the router stays the platform, the extension stays the client.

## 4. Minimal Extension Architecture (Concept)

Example conceptual structure:

```text
infra-ai-vscode-extension/
  src/
    extension.ts
    routerClient.ts
    chatViewProvider.ts
  media/
    chat-ui/
  package.json
```

Responsibilities:

- `extension.ts`
  Extension entry point. Registers commands, activates the extension, wires views or panels, and initializes the router client.

- `routerClient.ts`
  Thin HTTP client for the router. Handles calls to router endpoints, streaming consumption, error mapping for UI display, and capability/model fetching.

- `chatViewProvider.ts`
  Hosts the IDE chat surface. Sends user prompts to the router, renders streamed responses, displays route/model options provided by the router, and shows normalized router errors.

- `media/chat-ui`
  Optional frontend assets for a custom chat panel or webview.

- `package.json`
  Declares extension metadata, activation events, commands, configuration, and views.

No provider logic belongs in any of these components.

## 5. Router Communication Model

The extension should communicate only with router endpoints such as:

```text
GET /v1/router/capabilities
GET /v1/models
POST /v1/chat/completions
```

Communication model:

- the router defines which routes exist
- the router defines which providers are enabled
- the router defines which routing modes are available
- the router defines which models are visible
- the extension only reads and presents this information

The extension should:

- fetch router capabilities on activation or when opening the chat UI
- fetch model data from the router instead of hardcoding model names
- pass selected routing modes to the router unchanged
- stream responses from the router instead of implementing provider-specific streaming
- surface normalized router errors without interpreting provider internals

The extension must not:

- contain direct OpenAI, Gemini, or vLLM API calls
- store provider API keys
- implement fallback behavior on its own
- infer routing decisions that belong to the router

## 6. Future Features

Possible future capabilities for a later IDE integration:

- workspace context
- file selection prompts
- current editor selection as prompt context
- streaming token rendering
- session memory
- tool calling via router-managed tools
- agent workflows via router-managed orchestration
- MCP integration through router-managed capabilities

These are conceptual only. They should remain backend-driven wherever possible.

## 7. Implementation TODO List

- [ ] Define the initial extension scope as frontend-only router integration
- [ ] Decide whether the first UI should be a custom chat panel or a thinner native integration
- [ ] Scaffold the Code OSS / VS Code extension project
- [ ] Define extension configuration for the router base URL
- [ ] Implement a thin router client for `GET /v1/router/capabilities`
- [ ] Implement a thin router client for `GET /v1/models`
- [ ] Implement a thin router client for `POST /v1/chat/completions`
- [ ] Implement streaming response handling from the router
- [ ] Display routing modes provided by the router
- [ ] Display router-provided model information without hardcoding providers
- [ ] Render normalized router errors in the IDE UI
- [ ] Add a minimal chat view or panel
- [ ] Add reconnect / router-unavailable handling for local development
- [ ] Add a lightweight session model for chat history in the extension
- [ ] Plan workspace-context support without moving context logic into the extension
- [ ] Plan future tool, agent, and MCP support as router-driven features only
- [ ] Validate that no provider API keys or provider SDK assumptions enter the extension
