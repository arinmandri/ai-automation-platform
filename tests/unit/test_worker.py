import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://unused:unused@localhost/unused",
)

from automation_service.worker import celery_app


def test_worker_reliability_defaults() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
