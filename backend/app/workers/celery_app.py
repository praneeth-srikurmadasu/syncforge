"""Celery application.

Start a worker from the backend folder:

    celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo      # Windows
    celery -A app.workers.celery_app worker --loglevel=INFO --concurrency=4  # Linux

On Windows Celery's default process pool is not supported, so `--pool=solo` (one task at
a time per worker process) is used; run more worker processes to scale. Workers are
stateless: everything they need is in PostgreSQL.

Delivery settings, chosen for at-least-once processing:
* `task_acks_late`: a message is acknowledged only after the task finishes, so a worker
  that dies mid-task does not lose it;
* `task_reject_on_worker_lost`: such a message goes back to the queue;
* `worker_prefetch_multiplier=1`: a worker reserves one message at a time, so a slow
  event does not hold others hostage.
Even if the broker loses a message anyway, the outbox relay re-sends the event once its
lease expires - the database, not Redis, is the source of truth.
"""

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

PROCESS_EVENT_TASK = "syncforge.process_event"

settings = get_settings()

celery_app = Celery("syncforge", broker=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,  # results live in the database, not in a result backend
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_queue="syncforge-events",
    worker_hijack_root_logger=False,
    # Redis redelivers an unacknowledged message after this many seconds; keep it above
    # the longest event so a slow event is not delivered to a second worker meanwhile.
    broker_transport_options={"visibility_timeout": settings.worker_lease_seconds * 2},
)


@setup_logging.connect
def _configure_worker_logging(**_: object) -> None:
    """Use the same structured JSON logs as the API."""
    configure_logging(settings.log_level)
