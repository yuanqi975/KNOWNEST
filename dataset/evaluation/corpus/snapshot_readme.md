# KNOWNEST

KNOWNEST is a Python knowledge application with document indexing,
retrieval-assisted answers, bounded Agent research and source citations.

## Stack

- FastAPI, SQLAlchemy and PostgreSQL
- Milvus for 4096-dimensional Qwen/Qwen3-VL-Embedding-8B vectors
- Redis and Celery for document indexing jobs
- OpenAI and DeepSeek compatible chat providers
- Vue 3 frontend with independent RAG and Agent routes

## Run locally

Start the PostgreSQL service first (the local backend connects to it through
`localhost:5432`):

```powershell
Copy-Item .env.example .env
python -m pip install -r backend/requirements.txt
docker compose -f docker-compose.python.yml up -d postgres
```

Copy the example only for a new installation. Keep the existing `.env` and
data volumes when upgrading; see [upgrade notes](docs/UPGRADING.md).

```powershell
$env:PYTHONPATH = 'backend'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The backend creates its tables in PostgreSQL on startup. SQLite is used only
by isolated tests and is not the local runtime database.

In another terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/runtime`.

## Configuration

Use the root `.env`, an optional `backend/.env`, or process environment variables
(highest priority).
Configure `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` and `SILICONFLOW_API_KEY` for
real model calls. Reranking uses `RERANK_MODEL` and the `/rerank` endpoint;
`RERANK_API_KEY` is optional and falls back to `SILICONFLOW_API_KEY`. Set
`RERANK_ENABLED=false` to disable it. `backend/API.md` contains the complete
API contract.

## Agent

The Agent uses a bounded ReAct loop. It can search the selected knowledge base,
read indexed documents, calculate arithmetic expressions and call explicitly
enabled MCP tools. Each request is limited to six reasoning steps, three tool
calls per step and thirty seconds per tool call. Hidden chain of thought is
never sent to the browser; only tool actions, evidence and final answers are
streamed.

## Verification

```powershell
python -m pytest backend/tests -q
cd frontend
npm.cmd run type-check
npm.cmd run build
```

The evaluation fixtures under `dataset/evaluation/` are required by the backend
tests. See their [instructions](dataset/evaluation/README.md) for validation.

## License

See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
