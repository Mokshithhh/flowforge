from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Workflow, WorkflowExecution
import app.main as main


test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def setup_function():
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    main.engine = test_engine
    app.dependency_overrides[get_db] = override_db
    main.create_tables = lambda: None
    main.execute_workflow.delay = lambda execution_id: None


def teardown_function():
    app.dependency_overrides.clear()


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


def register(client, email):
    response = client.post("/auth/register", json={"email": email, "password": "long-test-password", "organization_name": "Test team"})
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_login_and_organization_isolation():
    with TestClient(app) as client:
        token_a = register(client, "a@example.com")
        token_b = register(client, "b@example.com")
        assert client.get("/auth/me", headers=headers(token_a)).status_code == 200
        login = client.post("/auth/login", json={"email": "a@example.com", "password": "long-test-password"})
        assert login.status_code == 200
        definition = {"nodes": [{"id": "start", "data": {"type": "manual-trigger", "config": {}}}], "edges": []}
        created = client.post("/workflows", headers=headers(token_a), json={"name": "Private flow", "definition": definition})
        assert created.status_code == 201
        workflow_id = created.json()["id"]
        assert client.get(f"/workflows/{workflow_id}", headers=headers(token_b)).status_code == 404
        assert client.get("/workflows", headers=headers(token_b)).json() == []


def test_publish_execute_and_retry_are_real_api_operations():
    with TestClient(app) as client:
        token = register(client, "owner@example.com")
        auth = headers(token)
        definition = {"nodes": [{"id": "start", "data": {"type": "manual-trigger", "config": {}}}], "edges": []}
        workflow = client.post("/workflows", headers=auth, json={"name": "Runnable", "definition": definition}).json()
        published = client.post(f"/workflows/{workflow['id']}/publish", headers=auth)
        assert published.status_code == 200
        execution = client.post(f"/workflows/{workflow['id']}/execute", headers=auth, json={"input": {"from": "test"}})
        assert execution.status_code == 202
        assert execution.json()["status"] == "pending"
        with TestingSession() as db:
            row = db.get(WorkflowExecution, execution.json()["id"])
            row.status = "failed"
            row.error = "temporary network error"
            db.commit()
        retried = client.post(f"/executions/{execution.json()['id']}/retry", headers=auth)
        assert retried.status_code == 202
        assert retried.json()["retry_count"] == 1
        assert client.get(f"/executions/{retried.json()['id']}", headers=auth).json()["trigger_input"] == {"from": "test"}


def test_webhook_queues_execution_and_persists_incoming_payload():
    with TestClient(app) as client:
        token = register(client, "hook-owner@example.com")
        auth = headers(token)
        definition = {"nodes": [{"id": "start", "data": {"type": "manual-trigger", "config": {}}}], "edges": []}
        workflow = client.post("/workflows", headers=auth, json={"name": "Webhook flow", "definition": definition}).json()
        client.post(f"/workflows/{workflow['id']}/publish", headers=auth)
        with TestingSession() as db:
            secret = db.get(Workflow, workflow["id"]).webhook_token
        response = client.post(f"/webhooks/{secret}", json={"sku": "P-1", "stock": 4})
        assert response.status_code == 202
        execution = client.get(f"/executions/{response.json()['id']}", headers=auth).json()
        assert execution["trigger_input"] == {"sku": "P-1", "stock": 4}
        assert execution["status"] == "pending"
