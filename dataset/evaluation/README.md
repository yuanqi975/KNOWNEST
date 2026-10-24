# KNOWNEST P0/P1 evaluation set

This directory contains a fixed, synthetic-safe evaluation corpus for the Python Runtime. It includes exactly 120 golden QA rows (28 simple, 20 multi-document composite, 18 no-answer, 12 conflict/version, 12 table/calculation, 10 multi-turn, 10 tool/MCP, and 10 degradation-behavior rows) plus 16 independent lifecycle/security scenarios in `scenarios.json`. The scenario suite is not mixed into QA scores. The first-pass labels/evidence are mechanically checked against the snapshot; manifest status remains `human_review_pending_before_acceptance` until a reviewer completes the rubric review and adjudicates disagreements.

Project reference documents are copied into `corpus/snapshot_*.md`; synthetic fixtures live beside them. The DOCX contains the tabular gold data. `manifest.json` pins every source and JSONL/scenario hash. Do not use `data/uploads/` or unapproved business documents. The small synthetic employee/policy data are fictional.

## Validate data without calling a runtime

From the repository root:

```powershell
$env:PYTHONPATH = 'backend'
python -m app.evaluation_cli --validate-only
python -m app.evaluation_cli --diagnostic-mocks
```

`--diagnostic-mocks` only checks deterministic metric plumbing. It never calls the API or a model and its report is explicitly not eligible for quality acceptance.

## Run the real evaluation

The default CLI path is a real-model run. It requires the Runtime to be started with a dedicated evaluation database, Milvus collection and storage path, as well as real Embedding, Rerank, and LLM providers. It uploads the hashed corpus into a temporary workspace/knowledge base, runs one request at a time, then deletes that workspace. Reports go to `output/evaluation/<run_id>/` as JSON and Markdown; `report.json` includes the pending manual-review queue.

Create an isolated runtime configuration first. The database and Milvus collection names and storage path must contain `eval`; this is an intentional guard against running against a normal or production deployment. Example environment values (use your local secrets manager for credentials; never paste secret values into the report):

The Runtime loads the repository-root `.env` as well as a working-directory `.env`, so the commands below work when launched from `backend/` while keeping the existing `<project-root>/.env` layout. Process environment variables take precedence over both files.

```powershell
$env:ENVIRONMENT = 'development'
$env:KNOWNEST_EVAL_ENV = 'isolated'
$env:DATABASE_URL = 'postgresql+psycopg://knownest:knownest@localhost:5432/knownest_evaluation'
$env:REDIS_URL = 'redis://localhost:6379/15'
$env:MILVUS_COLLECTION = 'knownest_evaluation_vectors'
$env:STORAGE_PATH = './data/evaluation-uploads'
$env:REQUIRE_MILVUS = 'true'
# Configure OPENAI_API_KEY, SILICONFLOW_API_KEY, and RERANK settings outside the report.
# Start the API and Celery worker with this same isolated environment.
```

Set `KNOWNEST_EVAL_TOKEN` to a dedicated local test user's bearer token, then run from `backend/` so the runtime uses the same `.env` configuration:

```powershell
$env:KNOWNEST_EVAL_TOKEN = '<dedicated local test token>'
python -m app.evaluation_cli --base-url http://127.0.0.1:8000
# To compare category slices with an earlier run of the same snapshot:
python -m app.evaluation_cli --base-url http://127.0.0.1:8000 --compare-to ../output/evaluation/<baseline-run>/report.json
```

The runner accepts loopback API hosts only, refuses non-development runtime environments, requires the explicit isolated marker, and checks that database, collection, Redis database, Milvus, and storage are local/evaluation-specific. Real provider readiness is probed before creating the test workspace. Missing providers fail by default. `--diagnostic-mocks` is the only offline scoring mode; it cannot be marked as acceptance. Provider keys, user tokens, API response bodies and headers are never included in reports.

## Reading results

`report.json` preserves per-case results and provenance. `report.md` summarizes current Runtime baseline metrics by category and compares observable metrics with the separate P0/P1 target thresholds. Pass `--compare-to` with a prior report under `output/evaluation/` to emit per-category deltas; comparison is marked incomparable when the fixed case hash changes. Unsupported or unobservable targets (such as automatic mode dispatch and cross-Workspace security) remain `not_implemented`; QA success does not imply those chain scenarios passed.

The rubric in `rubric.md` is fixed for judge-assisted conclusion/support/refusal scoring. Model-judge output must be reviewed: inspect every high-risk failure and the runner-selected 24-case sample, record adjudication, and only then treat the run as a quality sign-off. For multi-turn cases, the runner resends historical user messages to a fresh session and lets the Runtime regenerate assistant turns; fixture assistant text is deliberately not injected into the model context. A dataset hash change invalidates comparison with earlier runs.

Per-case answer latency and the ordinary/research P95 targets measure only the final question's SSE response. Multi-turn history reconstruction is reported separately as `history_replay_latency_seconds` / `history_replay_p95` so fixture setup time does not inflate answer latency.

## Editing/rebuilding

`build_assets.py` rebuilds the synthetic DOCX, 120-row JSONL, independent scenarios and manifest. It only copies upstream project docs into the corpus when their snapshot copy is missing. Refreshing those copies is explicit:

```powershell
python dataset/evaluation/build_assets.py --refresh-snapshots
```

That action changes hashes and creates a new effective dataset version; review every evidence quote and adjudicate label changes before accepting the rebuilt manifest. Run `--validate-only` after any edit.
