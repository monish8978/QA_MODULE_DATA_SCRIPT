from celery import Celery
from celery.schedules import crontab
from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND, POLL_INTERVAL_SECONDS

# Initialize Celery app
celery_app = Celery(
    "qa_tasks",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks"]
)

# Celery Configurations
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max execution time for safety
)

# Define Celery Beat Schedule
celery_app.conf.beat_schedule = {
    "poll-database-for-new-calls-every-interval": {
        "task": "app.tasks.poll_new_calls_task",
        "schedule": float(POLL_INTERVAL_SECONDS),  # Runs every configured interval
    }
}
