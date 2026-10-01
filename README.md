# Flowforge

Flowforge is a self-hosted workflow automation MVP. It combines a React Flow editor, organization-scoped API, immutable published snapshots, a persisted graph runner, and a Redis/Celery execution path. The project intentionally favors working execution and inspection over broad connector coverage.

## Architecture

- `apps/web`: React, TypeScript, Vite, React Router, React Flow. The editor persists the same node/edge graph consumed by the worker.
- `apps/api`: FastAPI, Pydantic, SQLAlchemy, Alembic, JWT authentication, workflow APIs, integration handlers, and the LangGraph workflow generator.
- `apps/worker`: Celery worker and Beat are run from the API image; execution is queued through Redis and persisted in PostgreSQL.
- `packages/shared`: reserved for API/client contracts shared across runtimes.
- `infrastructure`: reserved for deployment-specific assets.
- `docs`: architecture, execution engine, and agent details.

## Features

- Registration, login, JWT-protected endpoints, password hashing, and organization-scoped resource access.
- Workflow CRUD, visual node editing, graph validation, immutable publish snapshots, manual execution, webhook triggers, cron scheduling, and execution inspection/retry.
- Node registry: Manual Trigger, HTTP Request, JSON Transform, Condition, Filter, Delay, LLM Prompt, Summarizer, Email, Webhook, and read-only Database Query.
- Safe expression lookup for `{{nodes.node_id.output.path}}`; no Python `eval` or generated executable code.
- Per-node inputs, outputs, status, duration, and error persistence. Execution runs asynchronously in a Celery worker.
- Credential records encrypted with Fernet and masked in API responses.
- LangGraph workflow drafts use a structured Pydantic output and require a human to review and publish them.

## Start Locally

Requirements: Docker Desktop with Compose v2.24 or newer. No `.env` file is required for a local-only run; development defaults are used. For provider integrations, copy `.env.example` to `.env` and set the values described below.

```powershell
docker compose up --build
```

Open the web client at [http://localhost:5173](http://localhost:5173), the API at [http://localhost:8001](http://localhost:8001), and interactive API documentation at [http://localhost:8001/docs](http://localhost:8001/docs). The API, worker, scheduler, Postgres, and Redis are separate Compose services. Stop them with `docker compose down`; `docker compose down -v` also deletes local database data.

Register at `/register`, then create a workflow at `/workflows/new`. Add Manual Trigger, HTTP Request, JSON Transform, and Condition nodes; connect them on the canvas, configure each node, save, publish, and run. The worker will perform network calls against the configured URLs, so use endpoints you control. The HTTP node defaults to GET and has a 20-second request timeout.

## Environment Variables

| Variable | Required for | Notes |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Postgres | Local defaults are for development only. |
| `DATABASE_URL` | API, worker, Beat | PostgreSQL SQLAlchemy URL. Compose constructs it from the Postgres variables. |
| `REDIS_URL` | API, worker, Beat | Celery broker and result backend. |
| `JWT_SECRET` | Authentication | Set a long random secret outside local development. |
| `CREDENTIAL_ENCRYPTION_KEY` | Credential vault | Fernet key; generate with the command below. Needed to store credentials. |
| `LLM_API_KEY`, `LLM_MODEL` | LLM nodes and agent | OpenAI-compatible provider key and model. Missing keys produce a configuration error. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER` | Email node | SMTP delivery is attempted only when configured. |
| `FRONTEND_URL` | CORS | Browser origin, default `http://localhost:5173`. |
| `EXECUTION_TIMEOUT_SECONDS` | Worker | Celery soft execution time limit. |

Create a credential encryption key:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Never commit `.env`, provider keys, passwords, JWT signing keys, or Fernet keys. The `.env.example` file contains names and local-only defaults, not production secrets.

## Database and Migrations

The API creates missing tables on startup for local development. Alembic is also configured and has an initial schema revision:

```powershell
cd apps/api
$env:PYTHONPATH = "."
alembic upgrade head
```

Run future schema changes through reviewed Alembic revisions; do not use `create_all` as a production migration strategy.

## Tests and Builds

From the repository root:

```powershell
$env:PYTHONPATH = "apps/api"
python -m pytest apps/api/tests -q
Push-Location apps/web
npm ci
npm test
npm run lint
npm run build
Pop-Location
```

The backend integration test runs the real engine through Manual Trigger → HTTP Request → JSON Transform → Condition (with the HTTP transport mocked). Additional tests cover graph cycles, expression resolution, persisted failures, registration/login, tenant isolation, publishing, execution queue requests, and retry creation. The frontend test inspects a failed execution and invokes the retry API. Compose CI builds both Docker images.

## Workflow Engine

A published version is an immutable JSON snapshot. The API validates node IDs, supported types, graph references, required Manual Trigger, and acyclicity before publication. Execution loads that exact version, topologically orders nodes, resolves expressions as data paths, calls registered handlers, and saves each node's input/output/status. HTTP and SMTP/LLM failures are surfaced on the execution record. See [docs/workflow-engine.md](docs/workflow-engine.md).

## AI Agent

`POST /agent/generate-workflow` calls the configured model through a LangGraph state graph and requires a Pydantic-structured workflow response. The model may choose only registered node types; it cannot execute nodes, return code, or publish. Missing provider configuration produces HTTP 503. Generated nodes are only a draft in the editor; users must inspect, save, and explicitly publish/run them. See [docs/agent.md](docs/agent.md).

## Security Notes

- Organization IDs are derived from the signed JWT and applied in backend resource lookups; workflow and execution IDs alone do not grant access.
- Passwords are hashed; stored credentials are Fernet-encrypted and normal API responses never return their plaintext.
- Published graph snapshots cannot be changed through the API; edits change only the workflow draft and subsequent published version.
- Database Query accepts one read-only SELECT and binds configured values as SQL parameters. It currently queries the application database, not an arbitrary stored PostgreSQL credential.
- HTTP nodes reject localhost/local-domain targets and literal non-public IP addresses. DNS resolution/rebinding defenses are not complete; do not expose the service to untrusted users without network-level egress restrictions.
- The local Compose JWT/database defaults are not production-safe. Add TLS, a secret manager, database backups, rate limits, and an explicit organization membership/role administration flow before production use.

## Known Limitations

This is a functional MVP, not a production-ready Zapier replacement. Scheduling is dispatched by Celery Beat at minute precision. Cron matching is implemented, but multi-Beat leader election and distributed schedule locking are not. Retry creates a new execution of the latest published version rather than resuming only the failed node or pinning retry to its original version. Credential storage is real and encrypted, but provider nodes currently consume environment-configured LLM/SMTP settings and HTTP node configuration directly; stored credentials are not yet injected into those handlers. Database Query uses the application connection. There is no organization switching/invitation UI, cancellation endpoint, SSE stream, OAuth integration catalog, or external-provider live test in CI. These boundaries are called out rather than represented as complete functionality.
