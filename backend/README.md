# KNOWNEST Backend

FastAPI backend for the focused KNOWNEST application.

## Local development

Start PostgreSQL first (for example, with the repository's Compose service):

```powershell
docker compose -f docker-compose.python.yml up -d postgres
```

```powershell
$env:PYTHONPATH = 'backend'
python -m uvicorn app.main:app --reload --port 8000
```

Local and production deployments use PostgreSQL, Redis, Milvus and Celery.
`backend/.env.example` lists the supported environment variables. OpenAPI is
available at `/docs`.

Run these commands from the repository root. Install Python dependencies with
`python -m pip install -r backend/requirements.txt` first. Environment settings
are loaded from the root `.env` and optional `backend/.env`; process variables
take precedence. Keep the existing database URL when upgrading an installation.

To merge the legacy SQLite database into PostgreSQL without truncating the
target database:

```powershell
python backend/scripts/migrate_sqlite_to_postgres.py --source knownest-local.db --target '<existing PostgreSQL URL>'
```

The migration reuses an existing account with the same username and keeps
existing PostgreSQL rows with conflicting primary keys.

The complete endpoint contract is documented in [API.md](API.md).

Context budgeting, durable summaries, Redis caching and PostgreSQL/pgvector
memories are described in [CONTEXT_MEMORY.md](../docs/CONTEXT_MEMORY.md), including
Alembic upgrades, the context/memory workers, scheduler and integration tests.
