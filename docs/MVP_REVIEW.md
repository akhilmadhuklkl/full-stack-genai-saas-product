# MVP readiness review

Review date: 2026-11-18

## Current status

The project has a functional local-first MVP foundation for an AI code-review SaaS product.
The main workflow exists end to end:

```text
Register → create project → add files/archive → enqueue review → Ollama worker
→ save findings → inspect history, statistics, and source context
```

The custom web UI, FastAPI API, SQLite/PostgreSQL-compatible models, Ollama integration,
background jobs, migrations, evaluation fixtures, CI, and security checks are present.

## Complete for local MVP

- Custom browser dashboard
- Authentication and ownership checks
- Project and file management
- Secure ZIP ingestion
- Local Ollama reviews
- Synchronous, streaming, and background review paths
- Review findings and status lifecycle
- Prompt version tracking
- Project-specific review instructions
- Usage tracking and rate limiting
- Redis-compatible cache and limiter fallback
- Health checks and request IDs
- Evaluation fixtures and comparison reports
- Alembic migrations
- CI lint, test, migration, and security steps

## Important gaps before deployment

### 1. Runtime verification

The local machine currently blocks SQLAlchemy compiled DLL extensions, so the full pytest
suite has not completed in this environment. Before deployment, run the suite in a clean
Python environment and confirm the GitHub Actions job is green.

### 2. Durable job processing

The worker uses an in-process thread pool. A process restart can lose queued or active jobs.
Before production, replace it with a durable queue and worker system such as Celery/RQ,
Redis Queue, or a managed queue service.

### 3. Authentication hardening

The current bearer tokens are signed but do not expire or support revocation. Production
authentication needs token expiry, refresh/revocation behavior, secure browser storage,
account lockout or abuse controls, and email verification/reset flows.

### 4. File storage and limits

Source content is stored directly in the relational database. Production should define
retention, deletion, encryption, larger-project storage, archive decompression limits, and
possibly object storage for uploaded archives.

### 5. AI reliability and safety

The system needs model timeout/cancellation tests, prompt-injection cases, stronger output
validation, maximum context/token controls, and an explicit policy for untrusted source files.

### 6. Billing and subscriptions

Usage limits exist, but subscription plans, payment processing, invoices, and billing
webhooks are not implemented. Billing remains intentionally deferred.

### 7. Production infrastructure

Deployment, TLS, domain configuration, managed PostgreSQL, Redis, secrets management,
backups, monitoring, alerting, and autoscaling are not implemented yet.

## Recommended next sequence

1. Resolve the local SQLAlchemy runtime issue and verify CI is green.
2. Add stronger integration tests around background jobs and archive security.
3. Replace the in-process worker with a durable queue.
4. Add token expiry and production authentication flows.
5. Add production database/file retention policies.
6. Add monitoring and alerting.
7. Decide on billing scope.
8. Begin deployment planning only after these checks pass.

## Readiness decision

Status: **local MVP ready; production deployment not ready**.

The application is suitable for continued local learning, feature development, and demos.
It should not yet handle real customer data or be exposed publicly without the production
gaps above being addressed.
