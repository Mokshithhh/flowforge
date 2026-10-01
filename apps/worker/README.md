# Worker Runtime

The Compose `worker` service builds from `apps/api` so it shares the versioned graph engine and SQLAlchemy models. Its process entry point is `celery -A app.tasks.celery_app worker`; the scheduler runs the same Celery application with Beat. Workflow task and schedule dispatch implementation is in `apps/api/app/tasks.py`.
