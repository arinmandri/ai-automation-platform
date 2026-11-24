from celery import Celery

from automation_service.config import get_settings

settings = get_settings()

celery_app = Celery(
    "automation-platform",
    broker=settings.redis_url.get_secret_value(),
)
celery_app.conf.update(
    task_acks_late=True,
    task_ignore_result=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)
