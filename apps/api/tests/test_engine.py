import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.engine import WorkflowError, _execute_node, resolve, run_execution, validate_graph
from app.models import Organization, Workflow, WorkflowExecution, WorkflowVersion


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def graph():
    return {
        "nodes": [
            {"id": "manual", "data": {"type": "manual-trigger", "config": {}}},
            {"id": "http", "data": {"type": "http-request", "config": {"method": "GET", "url": "https://example.test/products"}}},
            {"id": "transform", "data": {"type": "json-transform", "config": {"template": {"count": "{{nodes.http.output.body.count}}"}}}},
            {"id": "condition", "data": {"type": "condition", "config": {"left": "{{nodes.transform.output.value.count}}", "operator": "gt", "right": 5}}},
        ],
        "edges": [
            {"source": "manual", "target": "http"},
            {"source": "http", "target": "transform"},
            {"source": "transform", "target": "condition"},
        ],
    }


def test_manual_http_transform_condition_executes_real_engine(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(200, json={"count": 8}, request=httpx.Request(method, url))

    monkeypatch.setattr("app.engine.httpx.request", fake_request)
    with TestingSession() as db:
        organization = Organization(name="Test")
        db.add(organization)
        db.flush()
        workflow = Workflow(organization_id=organization.id, name="Inventory check", definition=graph())
        db.add(workflow)
        db.flush()
        version = WorkflowVersion(workflow_id=workflow.id, version=1, definition=graph())
        db.add(version)
        db.flush()
        execution = WorkflowExecution(organization_id=organization.id, workflow_id=workflow.id, workflow_version_id=version.id, trigger_input={"run": True})
        db.add(execution)
        db.commit()
        run_execution(db, execution)
        assert execution.status == "success"
        assert execution.result["nodes"]["transform"]["value"] == {"count": 8}
        assert execution.result["nodes"]["condition"] == {"passed": True}
        assert [node.status for node in execution.nodes] == ["success"] * 4


def test_validation_rejects_cycles_and_expression_is_data_only():
    definition = graph()
    definition["edges"].append({"source": "condition", "target": "manual"})
    try:
        validate_graph(definition)
        assert False, "cycle should be rejected"
    except WorkflowError as error:
        assert "cycle" in str(error)
    assert resolve("{{nodes.a.output.x}}", {"a": {"x": 12}}) == 12
    try:
        resolve("{{nodes.a.output.missing}}", {"a": {"x": 12}})
        assert False, "missing expression should fail"
    except WorkflowError:
        pass


def test_filter_supports_numeric_comparisons_and_local_http_targets_are_rejected():
    result = _execute_node("filter", {"items": [{"stock": 2}, {"stock": 14}], "key": "stock", "operator": "lt", "value": 10}, {"outputs": {}}, None)
    assert result["items"] == [{"stock": 2}]
    try:
        _execute_node("http-request", {"url": "http://127.0.0.1/private"}, {"outputs": {}}, None)
        assert False, "private network target should be rejected"
    except WorkflowError as error:
        assert "non-public" in str(error)


def test_failed_http_node_is_persisted(monkeypatch):
    def broken_request(method, url, **kwargs):
        response = httpx.Response(503, request=httpx.Request(method, url))
        response.raise_for_status()
        return response

    monkeypatch.setattr("app.engine.httpx.request", broken_request)
    with TestingSession() as db:
        organization = Organization(name="Test")
        db.add(organization)
        db.flush()
        definition = graph()
        workflow = Workflow(organization_id=organization.id, name="Will fail", definition=definition)
        db.add(workflow)
        db.flush()
        version = WorkflowVersion(workflow_id=workflow.id, version=1, definition=definition)
        db.add(version)
        db.flush()
        execution = WorkflowExecution(organization_id=organization.id, workflow_id=workflow.id, workflow_version_id=version.id)
        db.add(execution)
        db.commit()
        run_execution(db, execution)
        assert execution.status == "failed"
        assert execution.nodes[-1].status == "failed"
        assert execution.error
