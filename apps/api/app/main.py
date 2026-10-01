import json
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import generate_workflow
from app.config import settings
from app.db import Base, engine, get_db
from app.engine import WorkflowError, validate_graph
from app.models import Credential, Organization, OrganizationMember, User, Workflow, WorkflowExecution, WorkflowVersion
from app.schemas import AgentRequest, ExecuteInput, LoginRequest, RegisterRequest, WorkflowInput
from app.security import create_token, decode_token, hash_password, verify_password
from app.tasks import execute_workflow

app = FastAPI(title="Flowforge API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url, "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        claims = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token")
    user = db.get(User, claims.get("sub"))
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == claims.get("sub"), OrganizationMember.organization_id == claims.get("org")))
    if user is None or member is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid organization membership")
    return user, member.organization_id


def scoped_workflow(db: Session, workflow_id: str, organization_id: str) -> Workflow:
    workflow = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.organization_id == organization_id))
    if workflow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return workflow


def workflow_data(workflow: Workflow):
    return {"id": workflow.id, "name": workflow.name, "definition": workflow.definition, "enabled": workflow.enabled, "published_version_id": workflow.published_version_id, "schedule_cron": workflow.schedule_cron, "created_at": workflow.created_at, "updated_at": workflow.updated_at}


def execution_data(execution: WorkflowExecution, include_nodes=True):
    data = {"id": execution.id, "workflow_id": execution.workflow_id, "workflow_version_id": execution.workflow_version_id, "status": execution.status, "trigger_input": execution.trigger_input, "result": execution.result, "error": execution.error, "retry_count": execution.retry_count, "created_at": execution.created_at, "started_at": execution.started_at, "finished_at": execution.finished_at}
    if include_nodes:
        data["nodes"] = [{"id": n.id, "node_id": n.node_id, "node_type": n.node_type, "status": n.status, "input": n.input, "output": n.output, "error": n.error, "retry_count": n.retry_count, "duration_ms": n.duration_ms} for n in execution.nodes]
    return data


def enqueue(db: Session, workflow: Workflow, organization_id: str, trigger_input: dict):
    if workflow.published_version_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Publish the workflow before executing it")
    execution = WorkflowExecution(organization_id=organization_id, workflow_id=workflow.id, workflow_version_id=workflow.published_version_id, trigger_input=trigger_input)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    try:
        execute_workflow.delay(execution.id)
    except Exception as exc:
        execution.status = "failed"
        execution.error = "Queue unavailable; verify Redis and the worker are running"
        execution.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, execution.error) from exc
    return execution


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    organization = Organization(name=body.organization_name)
    db.add_all([user, organization])
    db.flush()
    db.add(OrganizationMember(user_id=user.id, organization_id=organization.id, role="owner"))
    db.commit()
    db.refresh(user)
    return {"access_token": create_token(user), "token_type": "bearer", "user": {"id": user.id, "email": user.email}, "organization": {"id": organization.id, "name": organization.name}}


@app.post("/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return {"access_token": create_token(user), "token_type": "bearer", "user": {"id": user.id, "email": user.email}}


@app.post("/auth/logout")
def logout(_identity=Depends(current_user)):
    return {"status": "logged_out"}


@app.get("/auth/me")
def me(identity=Depends(current_user)):
    user, organization_id = identity
    return {"id": user.id, "email": user.email, "organization_id": organization_id}


@app.get("/workflows")
def list_workflows(identity=Depends(current_user), db: Session = Depends(get_db)):
    _, organization_id = identity
    workflows = db.scalars(select(Workflow).where(Workflow.organization_id == organization_id).order_by(Workflow.updated_at.desc())).all()
    return [workflow_data(workflow) for workflow in workflows]


@app.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(body: WorkflowInput, identity=Depends(current_user), db: Session = Depends(get_db)):
    _, organization_id = identity
    workflow = Workflow(organization_id=organization_id, name=body.name, definition=body.definition)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow_data(workflow)


@app.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    return workflow_data(scoped_workflow(db, workflow_id, identity[1]))


@app.put("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, body: WorkflowInput, identity=Depends(current_user), db: Session = Depends(get_db)):
    workflow = scoped_workflow(db, workflow_id, identity[1])
    workflow.name, workflow.definition = body.name, body.definition
    db.commit()
    db.refresh(workflow)
    return workflow_data(workflow)


@app.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    workflow = scoped_workflow(db, workflow_id, identity[1])
    db.delete(workflow)
    db.commit()


@app.post("/workflows/{workflow_id}/publish")
def publish_workflow(workflow_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    workflow = scoped_workflow(db, workflow_id, identity[1])
    try:
        validate_graph(workflow.definition)
    except WorkflowError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    version_num = db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow.id)) or 0
    version = WorkflowVersion(workflow_id=workflow.id, version=version_num + 1, definition=workflow.definition)
    db.add(version)
    db.flush()
    workflow.published_version_id = version.id
    db.commit()
    return {"workflow_id": workflow.id, "version_id": version.id, "version": version.version}


@app.post("/workflows/{workflow_id}/execute", status_code=status.HTTP_202_ACCEPTED)
def execute(workflow_id: str, body: ExecuteInput, identity=Depends(current_user), db: Session = Depends(get_db)):
    workflow = scoped_workflow(db, workflow_id, identity[1])
    execution = enqueue(db, workflow, identity[1], body.input)
    return {"id": execution.id, "status": execution.status}


@app.get("/workflows/{workflow_id}/webhook")
def get_webhook_url(workflow_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    workflow = scoped_workflow(db, workflow_id, identity[1])
    return {"url": f"/webhooks/{workflow.webhook_token}"}


@app.post("/workflows/{workflow_id}/schedule")
def set_schedule(workflow_id: str, body: dict, identity=Depends(current_user), db: Session = Depends(get_db)):
    from croniter import croniter
    workflow = scoped_workflow(db, workflow_id, identity[1])
    cron = body.get("cron")
    if cron is not None and (not isinstance(cron, str) or not croniter.is_valid(cron)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid cron expression")
    workflow.schedule_cron = cron
    workflow.enabled = bool(body.get("enabled", cron is not None))
    db.commit()
    return {"enabled": workflow.enabled, "cron": workflow.schedule_cron}


@app.get("/executions")
def list_executions(identity=Depends(current_user), db: Session = Depends(get_db)):
    _, organization_id = identity
    executions = db.scalars(select(WorkflowExecution).where(WorkflowExecution.organization_id == organization_id).order_by(WorkflowExecution.created_at.desc()).limit(100)).all()
    return [execution_data(item, False) for item in executions]


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    execution = db.scalar(select(WorkflowExecution).where(WorkflowExecution.id == execution_id, WorkflowExecution.organization_id == identity[1]))
    if execution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")
    return execution_data(execution)


@app.post("/executions/{execution_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_execution(execution_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    old = db.scalar(select(WorkflowExecution).where(WorkflowExecution.id == execution_id, WorkflowExecution.organization_id == identity[1]))
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found")
    if old.status != "failed" or old.retry_count >= 3:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed executions can be retried, up to three times")
    workflow = scoped_workflow(db, old.workflow_id, identity[1])
    new = enqueue(db, workflow, identity[1], old.trigger_input)
    new.retry_count = old.retry_count + 1
    db.commit()
    return {"id": new.id, "status": new.status, "retry_count": new.retry_count}


@app.post("/agent/generate-workflow")
def agent(body: AgentRequest, _identity=Depends(current_user)):
    try:
        result = generate_workflow(body.prompt)
        return result.model_dump()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not generate a valid workflow: {exc}") from exc


@app.post("/webhooks/{token}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_webhook(token: str, request: Request, db: Session = Depends(get_db)):
    if len(token) > 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    workflow = db.scalar(select(Workflow).where(Workflow.webhook_token == token, Workflow.enabled.is_(True)))
    if workflow is None or workflow.published_version_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_000_000:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Webhook payload too large")
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Webhook body must be valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Webhook body must be a JSON object")
    execution = enqueue(db, workflow, workflow.organization_id, payload)
    return {"id": execution.id, "status": execution.status}


@app.get("/dashboard")
def dashboard(identity=Depends(current_user), db: Session = Depends(get_db)):
    _, org_id = identity
    workflows = db.scalars(select(Workflow).where(Workflow.organization_id == org_id)).all()
    executions = db.scalars(select(WorkflowExecution).where(WorkflowExecution.organization_id == org_id).order_by(WorkflowExecution.created_at.desc()).limit(10)).all()
    counts = db.execute(select(WorkflowExecution.status, func.count()).where(WorkflowExecution.organization_id == org_id).group_by(WorkflowExecution.status)).all()
    return {"workflow_count": len(workflows), "active_workflows": sum(1 for w in workflows if w.enabled and w.published_version_id), "execution_counts": dict(counts), "recent_executions": [execution_data(item, False) for item in executions]}


def _fernet():
    try:
        return Fernet(settings.credential_encryption_key.encode())
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Credential encryption is not configured: set CREDENTIAL_ENCRYPTION_KEY") from exc


@app.get("/credentials")
def list_credentials(identity=Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Credential).where(Credential.organization_id == identity[1])).all()
    return [{"id": item.id, "name": item.name, "kind": item.kind, "masked": True, "created_at": item.created_at} for item in items]


@app.post("/credentials", status_code=status.HTTP_201_CREATED)
def save_credential(body: dict, identity=Depends(current_user), db: Session = Depends(get_db)):
    name, kind, value = body.get("name"), body.get("kind"), body.get("value")
    if not all(isinstance(x, str) and x for x in (name, kind, value)) or kind not in {"llm", "postgres", "smtp", "http"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide name, supported kind, and secret value")
    item = Credential(organization_id=identity[1], name=name[:160], kind=kind, encrypted_data=_fernet().encrypt(value.encode()).decode())
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name, "kind": item.kind, "masked": True}


@app.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: str, identity=Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(Credential).where(Credential.id == credential_id, Credential.organization_id == identity[1]))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    db.delete(item)
    db.commit()
