# Full-Stack GenAI SaaS Product

An AI-powered SaaS application with authentication, dashboards, APIs, streaming responses, usage limits, and an agent service.

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

Requirements: Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive API documentation.

The local database defaults to SQLite at `./genai_reviewer.db`. Set `DATABASE_URL`
to a PostgreSQL connection string when using PostgreSQL.

Run tests with:

```powershell
pytest
```
