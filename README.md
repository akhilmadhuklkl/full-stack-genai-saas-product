# Full-Stack GenAI SaaS Product

An AI-powered SaaS application with authentication, dashboards, APIs, streaming responses, usage limits, and an agent service.

Current version: `0.1.0` — see [CHANGELOG.md](CHANGELOG.md).

## Project goal

Build a production-style AI application such as a code reviewer, research assistant, sales assistant, or support bot. The first implementation will focus on a small, complete vertical slice before adding advanced agent tools, retrieval, billing, and background jobs.

## Planned architecture

```text
Web UI -> API gateway -> Business logic API
                         |-> AI agent service
                         |-> Billing and usage service
                         v
                  PostgreSQL / Redis / Vector search
```

## Development status

Milestone 1: backend foundation and the first code-review API contract.

## Local setup

Requirements:

- Python 3.11+
- Ollama
- A local Ollama model, such as `llama3.2:3b`

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Start Ollama and verify a model is available:

```powershell
ollama serve
ollama list
ollama pull llama3.2:3b
```

For durable background jobs, start Redis and a worker with:

```powershell
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
python -m app.worker
```

Without `REDIS_URL`, local development uses an in-process fallback worker.

Prepare local configuration by copying `.env.development.example` to `.env` and
adjusting values if needed. Never commit `.env`.

Apply database migrations and start the API/UI:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Open the application at http://127.0.0.1:8000.

Interactive API documentation is available at:

- http://127.0.0.1:8000/docs — Swagger UI
- http://127.0.0.1:8000/redoc — ReDoc
- http://127.0.0.1:8000/openapi.json — OpenAPI schema

See [docs/API.md](docs/API.md) for the route overview.
See [docs/MVP_REVIEW.md](docs/MVP_REVIEW.md) for the current readiness assessment and remaining gaps.
See [docs/RUNBOOK.md](docs/RUNBOOK.md) for local operations and troubleshooting.
See [docs/SECURITY.md](docs/SECURITY.md) for security controls and incident response.
See [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md) for Resend and local email configuration.

GitHub Actions runs compilation, linting, migration setup, frontend syntax validation,
tests with JUnit and coverage reporting, Bandit security scanning, dependency auditing,
and secret-pattern checks on pushes and pull requests targeting `main`. Test results and
coverage reports are uploaded as workflow artifacts when the CI job finishes.
The workflow can also be started manually from the GitHub Actions tab using **Run workflow**.

The local database defaults to SQLite at `./genai_reviewer.db`. Set `DATABASE_URL`
to a PostgreSQL connection string when using PostgreSQL.

Configuration is loaded from environment variables. Use the example files as a guide:

- `.env.development.example` for local development
- `.env.test.example` for automated tests
- `.env.production.example` as a deployment reference

Never commit real passwords, API keys, database credentials, or production secrets.

Apply database migrations with:

```powershell
alembic upgrade head
```

Create a new migration after changing a model with:

```powershell
alembic revision --autogenerate -m "describe the schema change"
```

Run tests with:

```powershell
pytest
```

The test suite uses an isolated in-memory SQLite database and a deterministic fake AI
reviewer. It does not call Ollama or modify the local development database.

Run the bounded AI evaluation runner with:

```powershell
python evals/run_evals.py --case sql_injection --max-cases 1
```

## Main workflow

1. Register or sign in.
2. Create a project.
3. Add files manually or upload a ZIP archive.
4. Optionally add project-specific review instructions.
5. Start a local AI review.
6. Poll the background job status.
7. Inspect findings, source context, history, and statistics.

### One-command local startup

On Windows, after installing Ollama and `uv`, run this from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

The script starts Ollama when needed, downloads `llama3.2:3b` if it is missing, and starts Forge Review at `http://127.0.0.1:8001`.

For local Redis infrastructure, use `docker compose -f docker-compose.local.yml up -d`.
For a final local health check, run `powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1`.

See [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for the portfolio readiness checklist.
