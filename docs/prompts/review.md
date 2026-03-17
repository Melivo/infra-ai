# Review

Use this template when reviewing code in `infra-ai`.

Before reviewing, read:

- `docs/architecture.md`
- `docs/architecture-rules.md`
- the changed files
- the relevant tests

Treat the architecture rules as binding review criteria.

## Review Priorities

Prioritize findings in this order:

1. correctness bugs and regressions,
2. architecture-rule violations,
3. hidden coupling or boundary leakage,
4. determinism and bounded-execution risks,
5. missing or weak tests,
6. documentation drift.

## Repo-Specific Checks

Explicitly check:

- no provider-specific logic in router core,
- no ad hoc plan reconstruction during execution,
- no fake explicitness where declared structure still only lives on tool-call transport metadata,
- no reintroduction of `NormalizedMessage` or `NormalizedGeneration` as core models,
- no bypass of `ExecutionStep` or `ExecutionPlan`,
- no stringly-typed parsing inside the core where structured data should be used,
- no loss of deterministic bounded tool execution,
- no HTTP/provider compatibility break caused by internal refactors.

## Output Format

Findings first, ordered by severity.

For each finding include:

- severity,
- file reference,
- the concrete issue,
- why it matters in this architecture.

If there are no findings, say exactly:

`no findings`

Then optionally note:

- residual risks,
- missing tests,
- minor follow-ups.

## Review Style

- Be direct and technical.
- Prefer concrete evidence over speculation.
- Do not suggest broad rewrites unless the current design violates the rules.
- Keep summaries brief after the findings.
