# Upgrading KNOWNEST

## Existing installations

Keep your `.env`, uploaded documents, PostgreSQL database, Redis jobs and Milvus
collection. Branding changes do not migrate or delete application data.

Fresh installations default to database/user `knownest` and collection
`knownest_vectors`. Existing installations must explicitly keep their original
`DATABASE_URL` and `MILVUS_COLLECTION`. A collection change without reindexing
would make existing document vectors unavailable.

For Compose, retain `COMPOSE_PROJECT_NAME` to reuse existing named volumes.
Set `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` to the credentials
already initialized in that volume. These variables do not rename existing
PostgreSQL users or databases. `COMPOSE_DATABASE_URL` optionally overrides the
container connection URL (host `postgres`); local Python uses `DATABASE_URL`
with `localhost`. Credentials with URL-reserved characters must be percent
encoded in connection URLs. Never delete a data volume to resolve a branding
mismatch.

New password hashes use `knownest-sha256$`. Verification recognizes historical
application-labelled SHA-256/bcrypt hashes by their `-sha256$` algorithm suffix
and also accepts plain bcrypt, so existing accounts remain usable without
changing stored hashes.

Browser storage now uses `knownest_python_token` and `knownest_active_conversation`
keys. Sign in again after upgrading. Conversations and uploaded documents remain
on the server. Evaluation-only variables are `KNOWNEST_EVAL_ENV` and
`KNOWNEST_EVAL_TOKEN`; update local evaluation scripts accordingly.

The optional SQLite import defaults to `knownest-local.db`; an older filename
can be passed explicitly with `--source`. A local SQLite backup can be renamed
without changing its contents. No SQLite database is required to start the
PostgreSQL runtime.

## Verification

From the repository root:

```powershell
python -m pytest backend/tests -q
$env:PYTHONPATH = 'backend'
python -m app.evaluation_cli --validate-only
docker compose -f docker-compose.python.yml config --quiet
cd frontend
npm.cmd ci
npm.cmd run build
```

The synthetic `dataset/evaluation/` fixtures are versioned and required by the
backend tests. Runtime uploads, exports and evaluation reports remain ignored.
The current application uses Python and Vue; the removed Go/Rust services,
Swagger output, desktop releases and plugin workflows are not runtime inputs.
Original copyright and license notices remain in `LICENSE`,
`THIRD_PARTY_NOTICES.md` and `licenses/`.
