import ipaddress
import re
import smtplib
import time
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from app.config import settings
from app.models import NodeExecution, WorkflowExecution, WorkflowVersion

MAX_NODES = 50
EXPRESSION = re.compile(r"\{\{\s*nodes\.([A-Za-z0-9_-]+)\.output((?:\.[A-Za-z0-9_-]+)*)\s*\}\}")
REGISTRY = {
    "manual-trigger", "http-request", "json-transform", "condition", "filter", "delay",
    "llm-prompt", "summarizer", "email", "webhook", "database-query"
}


class WorkflowError(Exception):
    def __init__(self, message: str, category: str = "node_execution"):
        super().__init__(message)
        self.category = category


def validate_graph(definition: dict) -> list[dict]:
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    if not isinstance(nodes, list) or not nodes or len(nodes) > MAX_NODES:
        raise WorkflowError(f"A workflow must contain 1-{MAX_NODES} nodes", "validation")
    by_id = {node.get("id"): node for node in nodes}
    if len(by_id) != len(nodes) or None in by_id:
        raise WorkflowError("Node IDs must be unique and non-empty", "validation")
    if not any(node.get("data", {}).get("type") == "manual-trigger" for node in nodes):
        raise WorkflowError("A Manual Trigger node is required", "validation")
    for node in nodes:
        node_type = node.get("data", {}).get("type")
        if node_type not in REGISTRY:
            raise WorkflowError(f"Unsupported node type: {node_type}", "validation")
    for edge in edges:
        if edge.get("source") not in by_id or edge.get("target") not in by_id:
            raise WorkflowError("Every edge must reference existing nodes", "validation")
    indegree = {node_id: 0 for node_id in by_id}
    children = {node_id: [] for node_id in by_id}
    for edge in edges:
        indegree[edge["target"]] += 1
        children[edge["source"]].append(edge["target"])
    ready = [node_id for node_id, count in indegree.items() if count == 0]
    ordered = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(by_id[node_id])
        for target in children[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(ordered) != len(nodes):
        raise WorkflowError("Workflow graph contains a cycle", "validation")
    return ordered


def resolve(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        result = outputs.get(match.group(1), {})
        for part in match.group(2).strip(".").split("."):
            if not part:
                continue
            if not isinstance(result, dict) or part not in result:
                raise WorkflowError(f"Expression path not found: {match.group(0)}", "validation")
            result = result[part]
        return result if match.start() == 0 and match.end() == len(value) else str(result)

    matches = list(EXPRESSION.finditer(value))
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return replace(matches[0])
    return EXPRESSION.sub(lambda match: str(replace(match)), value)


def _execute_node(node_type: str, config: dict, context: dict, db) -> dict:
    if node_type == "manual-trigger":
        return {"input": context.get("trigger_input", {})}
    if node_type == "http-request":
        url = config.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise WorkflowError("HTTP Request requires a valid http(s) URL", "validation")
        hostname = parsed.hostname.lower().rstrip(".")
        if parsed.username or parsed.password or hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise WorkflowError("HTTP Request URL targets a disallowed host", "validation")
        try:
            if not ipaddress.ip_address(hostname).is_global:
                raise WorkflowError("HTTP Request URL targets a non-public IP address", "validation")
        except ValueError:
            pass
        method = config.get("method", "GET").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise WorkflowError("Unsupported HTTP method", "validation")
        try:
            response = httpx.request(method, url, headers=config.get("headers"), params=config.get("params"), json=config.get("body"), timeout=min(float(config.get("timeout", 20)), 60))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise WorkflowError("HTTP request timed out", "timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise WorkflowError(f"HTTP request returned status {exc.response.status_code}", "network") from exc
        except httpx.HTTPError as exc:
            raise WorkflowError("HTTP request failed due to a network error", "network") from exc
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text}
        return {"status": response.status_code, "body": body, "headers": dict(response.headers)}
    if node_type == "json-transform":
        template = config.get("template", {})
        return {"value": resolve(template, context["outputs"])}
    if node_type == "condition":
        left = config.get("left")
        right = config.get("right")
        operator = config.get("operator", "equals")
        operations = {"equals": lambda: left == right, "not-equals": lambda: left != right, "gt": lambda: left > right, "gte": lambda: left >= right, "lt": lambda: left < right, "contains": lambda: right in left}
        if operator not in operations:
            raise WorkflowError("Unsupported condition operator", "validation")
        try:
            passed = bool(operations[operator]())
        except TypeError as exc:
            raise WorkflowError("Condition values are incompatible", "validation") from exc
        return {"passed": passed}
    if node_type == "filter":
        items = config.get("items", [])
        key = config.get("key", "")
        value = config.get("value")
        operator = config.get("operator", "equals")
        operations = {"equals": lambda item: item == value, "not-equals": lambda item: item != value, "gt": lambda item: item > value, "gte": lambda item: item >= value, "lt": lambda item: item < value, "lte": lambda item: item <= value, "contains": lambda item: value in item}
        if not isinstance(items, list) or operator not in operations:
            raise WorkflowError("Filter requires a list and a supported operator", "validation")
        try:
            filtered = [item for item in items if isinstance(item, dict) and operations[operator](item.get(key))]
        except TypeError as exc:
            raise WorkflowError("Filter values are incompatible", "validation") from exc
        return {"items": filtered}
    if node_type == "delay":
        seconds = max(0, min(float(config.get("seconds", 0)), 30))
        time.sleep(seconds)
        return {"delayed_seconds": seconds}
    if node_type in ("llm-prompt", "summarizer"):
        if not settings.llm_api_key:
            raise WorkflowError("LLM is not configured: set LLM_API_KEY", "configuration")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.llm_api_key, timeout=30)
            prompt = config.get("prompt", "Summarize the provided input.")
            response = client.chat.completions.create(model=settings.llm_model, temperature=float(config.get("temperature", 0.2)), max_tokens=int(config.get("max_tokens", 500)), messages=[{"role": "system", "content": config.get("system_prompt", "You are a concise assistant.")}, {"role": "user", "content": prompt}])
            return {"text": response.choices[0].message.content}
        except ImportError as exc:
            raise WorkflowError("LLM provider package is unavailable", "configuration") from exc
        except Exception as exc:
            raise WorkflowError("LLM provider request failed", "provider") from exc
    if node_type == "email":
        if not settings.smtp_host or not settings.smtp_sender:
            raise WorkflowError("SMTP is not configured: set SMTP_HOST and SMTP_SENDER", "configuration")
        message = EmailMessage()
        message["From"] = settings.smtp_sender
        message["To"] = config.get("to", "")
        message["Subject"] = config.get("subject", "")
        message.set_content(str(config.get("body", "")))
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.starttls()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
        except Exception as exc:
            raise WorkflowError("SMTP delivery failed; verify the SMTP configuration", "provider") from exc
        return {"sent": True, "to": message["To"]}
    if node_type == "webhook":
        return _execute_node("http-request", {"url": config.get("url"), "method": config.get("method", "POST"), "headers": config.get("headers", {}), "body": config.get("body", context.get("trigger_input", {})), "timeout": config.get("timeout", 20)}, context, db)
    if node_type == "database-query":
        query = config.get("query", "")
        if not query.strip().lower().startswith("select "):
            raise WorkflowError("Database Query supports read-only SELECT statements", "validation")
        if ";" in query.rstrip("; "):
            raise WorkflowError("Only one SQL statement is allowed", "validation")
        try:
            result = db.execute(text(query), config.get("parameters", {}))
            return {"rows": [dict(row._mapping) for row in result], "count": result.rowcount}
        except Exception as exc:
            raise WorkflowError("Database query failed; verify the query and database configuration", "database") from exc
    raise WorkflowError(f"Unsupported node type: {node_type}", "validation")


def run_execution(db, execution: WorkflowExecution) -> None:
    execution.status = "running"
    from app.models import now
    execution.started_at = now()
    db.commit()
    definition = db.get(WorkflowVersion, execution.workflow_version_id).definition
    try:
        nodes = validate_graph(definition)
        outputs: dict[str, Any] = {}
        skipped = set()
        context = {"trigger_input": execution.trigger_input or {}, "outputs": outputs}
        for node in nodes:
            blocked = any(edge["target"] == node["id"] and edge["source"] in skipped for edge in definition.get("edges", []))
            if blocked:
                skipped.add(node["id"])
            if node["id"] in skipped:
                continue
            node_type = node["data"]["type"]
            config = resolve(node["data"].get("config", {}), outputs)
            record = NodeExecution(execution_id=execution.id, node_id=node["id"], node_type=node_type, status="running", input=config)
            db.add(record)
            db.commit()
            started = time.monotonic()
            try:
                output = _execute_node(node_type, config, context, db)
                record.output = output
                record.status = "success"
                outputs[node["id"]] = output
                if node_type == "condition":
                    source_edges = [edge for edge in definition.get("edges", []) if edge.get("source") == node["id"]]
                    for edge in source_edges:
                        if edge.get("sourceHandle") and edge["sourceHandle"] != ("true" if output["passed"] else "false"):
                            skipped.add(edge["target"])
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                execution.status = "failed"
                execution.error = str(exc)
                execution.finished_at = now()
                record.duration_ms = int((time.monotonic() - started) * 1000)
                db.commit()
                return
            record.duration_ms = int((time.monotonic() - started) * 1000)
            db.commit()
        execution.status = "success"
        execution.result = {"nodes": outputs}
    except Exception as exc:
        execution.status = "failed"
        execution.error = str(exc)
    execution.finished_at = now()
    db.commit()
