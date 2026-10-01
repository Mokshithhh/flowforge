from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from croniter import croniter
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.engine import run_execution
from app.models import Workflow, WorkflowExecution

celery_app = Celery("workflow", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_time_limit=settings.execution_timeout_seconds + 30, task_soft_time_limit=settings.execution_timeout_seconds, worker_prefetch_multiplier=1, beat_schedule={"dispatch-workflow-schedules": {"task": "workflow.dispatch_schedules", "schedule": crontab(minute="*")}})


@celery_app.task(name="workflow.execute", autoretry_for=(), max_retries=0)
def execute_workflow(execution_id: str):
    db = SessionLocal()
    try:
        execution = db.get(WorkflowExecution, execution_id)
        if execution is None or execution.status != "pending":
            return
        run_execution(db, execution)
    finally:
        db.close()


@celery_app.task(name="workflow.dispatch_schedules")
def dispatch_schedules():
    db = SessionLocal()
    try:
        minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        workflows = db.scalars(select(Workflow).where(Workflow.enabled.is_(True), Workflow.schedule_cron.is_not(None), Workflow.published_version_id.is_not(None))).all()
        for workflow in workflows:
            if not croniter.match(workflow.schedule_cron, minute):
                continue
            if workflow.last_scheduled_at and workflow.last_scheduled_at.replace(second=0, microsecond=0) >= minute:
                continue
            execution = WorkflowExecution(organization_id=workflow.organization_id, workflow_id=workflow.id, workflow_version_id=workflow.published_version_id, trigger_input={"scheduled_at": minute.isoformat()})
            db.add(execution)
            workflow.last_scheduled_at = minute
            db.commit()
            execute_workflow.delay(execution.id)
    finally:
        db.close()
