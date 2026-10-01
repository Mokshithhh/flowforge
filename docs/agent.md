# AI Workflow Agent

The agent is a LangGraph state graph with a single generation node. It sends the user's natural-language request to the configured OpenAI-compatible chat model using a Pydantic structured-output schema. The resulting object contains a workflow name, controlled node list, edges, and missing-information list.

The prompt restricts node types to the registry and instructs the model not to invent credentials, recipients, URLs, database names, or executable code. The backend maps this structured result to the exact graph definition used by the editor and validates it with the same graph validator used for publish. Provider configuration errors return HTTP 503; malformed or invalid graphs return HTTP 422.

The endpoint does not create, publish, or execute workflows. The frontend places the draft into the visual editor and displays missing information. A person reviews and edits the graph, then explicitly saves/publishes it and starts a run. Model output is untrusted input and must continue to pass validation at publication.

The initial implementation has no deterministic local fallback: if `LLM_API_KEY` is absent, generation fails with an explicit configuration error. This is intentional; it does not invent a response that looks like an actual AI-generated plan.
