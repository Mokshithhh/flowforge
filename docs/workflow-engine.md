# Workflow Engine

## Graph contract

A definition contains `nodes` and `edges`. Each node has a stable ID, a `data.type` from the registry, `data.config`, and an optional canvas position. Edges use source and target node IDs; condition branches may set `sourceHandle` to `true` or `false`. Publication rejects duplicate/empty IDs, unknown node types, missing Manual Trigger, dangling edges, cycles, and graphs over 50 nodes.

## Execution

`run_execution` loads the exact `WorkflowVersion` referenced by the execution, validates and topologically sorts it, then invokes one registered handler at a time. Node input configuration is expression-resolved against outputs already produced. Each node has a persisted running/success/failed record with input, output, error, retry count, and duration. A failed node stops the graph and fails the parent execution. Conditional branches skip the non-selected branch and its downstream dependants.

## Expressions

The supported expression grammar is `{{nodes.<node_id>.output.<path>}}`. A full-string expression returns the referenced JSON value with its original type. Embedded expressions stringify the value. Lookup is restricted to dictionaries and known output values. No Python evaluation, arbitrary imports, shell execution, or model-generated code exists in this path.

## Registry

- Triggers: `manual-trigger`; webhooks and schedules enter through the API and supply execution input.
- Data: `http-request`, `database-query`, `json-transform`.
- Logic: `condition`, `filter`, `delay`.
- AI: `llm-prompt`, `summarizer`.
- Actions: `email`, `webhook`.

HTTP supports GET/POST/PUT/PATCH/DELETE and explicit timeouts. Database Query is a single read-only SELECT with SQLAlchemy bound parameters. LLM nodes call the configured provider and report missing credentials as configuration failures. SMTP nodes report configuration and delivery errors without claiming success.

## Limits and retries

The graph is capped at 50 nodes, HTTP timeout at 60 seconds, delay at 30 seconds, task time is bounded by `EXECUTION_TIMEOUT_SECONDS`, and API retry creation is capped at three attempts per retry chain. Retry currently queues the whole workflow against the current published version; it does not resume an individual failed node. Transient node-level automatic retries and cancellation are not implemented.
