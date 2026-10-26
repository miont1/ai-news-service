from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "aibot",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
)

celery_app.conf.beat_schedule = {
    "run-news-pipeline-every-30-mins": {
        "task": "app.tasks.run_news_pipeline_task",
        "schedule": crontab(minute="*/30"),
    },
}
