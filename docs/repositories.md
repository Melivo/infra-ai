# Repositories

## Purpose

This document defines the separation between the public `infra-ai` repository and private project-specific repositories.

The goal is to keep the public router platform clean and reusable while preventing secrets, customer data, and proprietary operational content from drifting into the public codebase.

## Public Repository

Public repository:

- `infra-ai`

Contains:

- router core
- provider abstractions
- local `vLLM` provider
- cloud provider integration layers without real secrets
- CLI reference frontend
- generic infrastructure and public-safe contracts
- example configuration files
- documentation
- scripts and smoke checks
- generic compatibility layers that are public-safe

Only include generic tool or agent infrastructure if it is public-safe and does not contain customer-specific behavior or sensitive operational content.

## Not Included in the Public Repository

- no secrets
- no real API keys
- no customer data
- no productive proprietary prompts
- no private knowledge bases
- no customer-specific pipelines
- no private embeddings or documents
- no environment-specific operational credentials

## Private Repositories

### `infra-ai-secrets`

Contains:

- local `.env` files
- API keys
- tokens
- other runtime secrets

### `infra-ai-workflows`

Contains:

- productive workflows
- customer-specific automations
- production prompts
- private operational workflow definitions

### `infra-ai-rag-data` (optional)

Contains:

- private documents
- embeddings
- private knowledge bases

### `infra-ai-clients` (optional)

Contains:

- client-specific implementations
- customer-specific integration layers
- private delivery code that should not live in the public platform repository

## Rule of Thumb

If a file defines public infrastructure, generic contracts, or reusable router behavior, it belongs in `infra-ai`.

If a file contains secrets, customer-specific behavior, private knowledge, or production-only operational details, it belongs in a private repository.
