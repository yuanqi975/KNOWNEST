from celery import Celery
from app.core.config import get_settings

celery_app = Celery("knownest", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_track_started=True, task_serializer="json", accept_content=["json"], result_serializer="json")
celery_app.conf.update(
    task_default_queue="ingestion", broker_transport_options={"global_keyprefix": f"knownest:{get_settings().environment}:celery:", "visibility_timeout": 3600},
    result_backend_transport_options={"global_keyprefix": f"knownest:{get_settings().environment}:results:"},
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={"context-outbox": {"task": "app.workers.dispatch_context_jobs", "schedule": 10.0,
                                      "options": {"queue": "context"}}},
)


@celery_app.task(ignore_result=True)
def dispatch_context_jobs():
    from app.core.db import SessionLocal
    from app.services.background import dispatch
    with SessionLocal() as db:
        dispatch(db, lambda job_id, queue: process_context_job.apply_async(args=[job_id], queue=queue, retry=False))


@celery_app.task(ignore_result=True)
def process_context_job(job_id: str):
    import asyncio
    from app.core.db import SessionLocal
    from app.services.background import process
    with SessionLocal() as db:
        asyncio.run(process(db, job_id))


@celery_app.task(bind=True, max_retries=3)
def ingest_document(self, document_id: str) -> dict:
    # The HTTP service owns the transaction and enqueues this task. Keeping
    # the task boundary explicit makes retries and a real worker deployment
    # observable without coupling FastAPI to a thread pool.
    from app.core.db import SessionLocal
    from app.services.ingestion import process_document
    db = SessionLocal()
    try:
        process_document(db, document_id)
        return {"document_id": document_id, "status": "indexed"}
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        db.close()
