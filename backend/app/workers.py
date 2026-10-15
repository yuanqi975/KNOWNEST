from celery import Celery
from app.core.config import get_settings

celery_app = Celery("weknora", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_track_started=True, task_serializer="json", accept_content=["json"], result_serializer="json")


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
