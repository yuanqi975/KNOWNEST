# WeKnora Runtime Backend

FastAPI backend for the focused WeKnora Runtime application.

## Local development

Start PostgreSQL first (for example, with the repository's Compose service):

```powershell
docker compose -f ../docker-compose.python.yml up -d postgres
```

```powershell
$env:PYTHONPATH = 'backend'
$env:DATABASE_URL = 'postgresql+psycopg://weknora:weknora@localhost:5432/weknora'
python -m uvicorn app.main:app --reload --port 8000
```

Local and production deployments use PostgreSQL, Redis, Milvus and Celery.
`backend/.env.example` lists the supported environment variables. OpenAPI is
available at `/docs`.

To merge the legacy SQLite database into PostgreSQL without truncating the
target database:

```powershell
python backend/scripts/migrate_sqlite_to_postgres.py
```

The migration reuses an existing account with the same username and keeps
existing PostgreSQL rows with conflicting primary keys.

The complete endpoint contract is documented in [API.md](API.md).
