# Forge Review operations runbook

This guide explains how to start the local stack, check its dependencies, and diagnose
the most common failures. Deployment is intentionally outside the current project scope.

## Local startup

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The API documentation is available at `/docs`.

## Ollama checks

Forge Review uses Ollama for the AI review. Confirm that Ollama is running and the
configured model exists:

```powershell
ollama serve
ollama list
ollama pull llama3.2:3b
```

The application uses `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. The detailed health endpoint
shows whether Ollama is reachable:

```text
GET /health/details
```

If Ollama is unavailable, authentication and project management can still work, but review
execution will fail until the service is restored.

## Redis and the review worker

Redis is optional for local development. Without `REDIS_URL`, the API uses a small
in-process fallback worker.

For durable jobs, start Redis and a separate worker:

```powershell
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
python -m app.worker
```

The worker listens on the `forge-reviews` queue. Review jobs retry up to two times with
short backoff intervals. The job API exposes attempt count, start time, and heartbeat time.
The worker publishes a short-lived heartbeat that is included in `/health/details`.

If jobs remain queued:

1. Check `GET /health/details` and confirm Redis is `ok`.
2. Confirm `python -m app.worker` is still running.
3. Check the worker logs for `review_worker_started` and job failures.
4. Inspect the job endpoint shown in the UI or call `GET /api/v1/jobs/{job_id}`.

If `/health/details` reports stale heartbeats, inspect those jobs before retrying them.
The current worker timeout and stale threshold are controlled by `OLLAMA_TIMEOUT_SECONDS`
and `JOB_STALE_SECONDS`. A stale job should be retried after confirming that no worker is
still processing it.
Owners can recover an eligible stale review with `POST /api/v1/reviews/{review_id}/recover`.
The endpoint refuses jobs whose heartbeat is still recent.

Refresh tokens are single-use. A successful refresh revokes the supplied refresh token and
returns a replacement pair. Reusing an older refresh token returns `401` and should be
treated as a possible token replay event.

Login-attempt throttling uses Redis when `REDIS_URL` is configured, allowing counters to be
shared across API instances. Without Redis, it falls back to a process-local limiter.

## Failed reviews

A failed review stores an error message and can be retried from the review history panel.
The retry action resets the execution metadata and submits the existing review again.

If retries continue to fail:

- Check Ollama availability and model name.
- Check the review files for unusually large content.
- Inspect worker logs using the request/job identifiers shown by the API.
- Run the review synchronously through the UI/API to isolate queue problems from AI errors.

## Database migrations

Apply all migrations before starting a fresh or upgraded instance:

```powershell
alembic upgrade head
```

To inspect the current revision:

```powershell
alembic current
```

CI also verifies a clean downgrade to `base` followed by an upgrade to `head` using a
temporary database. This catches migration ordering and downgrade mistakes before changes
are merged.

To run the complete verification manually, open the repository’s GitHub Actions tab, select
the `CI` workflow, and choose **Run workflow** on the `main` branch. Review the pytest and
coverage artifacts after the run completes.

Never edit an already-applied migration. Create a new revision for schema changes and test
both upgrade and downgrade behavior where practical.

## Data retention and backups

Expired revoked-token records are cleaned up during refresh and logout operations. Review
source files and findings remain stored until the owning project is deleted; define a formal
retention period before handling customer data.

For a local SQLite backup, stop write activity and copy the database file, or use SQLite’s
backup tooling. For PostgreSQL, schedule regular logical or managed backups and test a
restore periodically. Backups must receive the same access controls as production data and
must not be committed to the repository.

## Health and logs

- `GET /health` is a lightweight liveness check.
- `GET /health/details` checks the database, Ollama, Redis, and worker availability.
- `GET /metrics` exposes review, queue, and stale-job gauges for future monitoring.
- Every HTTP response includes `X-Request-ID`.
- HTTP responses include browser security headers such as `X-Content-Type-Options`,
  `X-Frame-Options`, and a restrictive Content Security Policy.
- The same ID is included in request completion and unhandled-error logs.

When reporting a failure, include the request ID, job ID, endpoint, and approximate time,
but never include passwords, bearer tokens, or source code contents.

## Test environment notes

CI installs the project dependencies, applies migrations, runs the complete test suite, and
uploads JUnit results as an artifact. Some Windows development environments may block
SQLAlchemy compiled DLLs through application-control policy; in that case, run the full
suite in CI or an unrestricted virtual environment. Pure archive and evaluation tests can
still be run locally:

```powershell
python -m pytest -q tests/test_archive.py tests/test_evaluation.py tests/test_eval_comparison.py tests/test_eval_runner.py
```
