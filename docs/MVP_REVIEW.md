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
- Queue health, worker heartbeats, stale-job recovery, and metrics
- Expiring, rotating, and revocable tokens with cookie/CSRF browser protection
- Login abuse throttling, security headers, and prompt-injection boundaries
- Evaluation fixtures and comparison reports
- Alembic migrations
- CI lint, test, migration, and security steps

## Important gaps before deployment

### 1. Runtime verification

The local machine currently blocks SQLAlchemy compiled DLL extensions, so the full pytest
suite has not completed in this environment. Before deployment, run the suite in a clean
Python environment and confirm the GitHub Actions job is green.

### 2. Durable job processing

The project now supports a Redis-backed RQ queue and a separate worker process. Without
`REDIS_URL`, it intentionally falls back to an in-process worker for local development.
Production still needs worker deployment and external operational alerting. Queue health,
worker heartbeats, stale-job recovery, retry behavior, and local recovery procedures are
implemented or documented in `docs/RUNBOOK.md`.

### 3. Authentication hardening

Bearer tokens now expire using `AUTH_TOKEN_TTL_SECONDS` (one hour by default), and refresh
tokens plus persistent access-token revocation and refresh-token rotation are implemented.
Production authentication now supports an HttpOnly browser cookie in addition to bearer
headers, CSRF protection, token rotation, and revocation. Password reset and email
verification still require an email provider. Login abuse throttling is Redis-backed when
`REDIS_URL` is configured, with a process-local fallback for development.

### 4. File storage and limits

Source content is stored directly in the relational database. Production still needs formal
retention, deletion, encryption, backup/restore, and larger-project storage policies.
Archive decompression limits, input-size limits, and expired revoked-token cleanup are
implemented locally.

### 5. AI reliability and safety

The system now has configurable model timeouts, stronger output validation, and explicit
prompt-injection boundaries for untrusted source files. Production still needs cancellation
tests, maximum context/token controls, and broader adversarial evaluation coverage.

### 6. Billing and subscriptions

Usage limits exist, but subscription plans, payment processing, invoices, and billing
webhooks are not implemented. Billing remains intentionally deferred.

### 7. Production infrastructure

Deployment, TLS, domain configuration, managed PostgreSQL/Redis, secret-manager integration,
external backups, monitoring, alerting, and autoscaling remain deferred.

## Recommended pre-deployment sequence

1. Resolve the local SQLAlchemy runtime issue and verify CI is green, including migration
   downgrade/upgrade checks.
2. Review stronger integration tests around background jobs, cookie auth, and archive security.
3. Select an email provider and implement password reset/email verification if required.
4. Define production database/file retention and backup policies.
5. Connect `/metrics` and `/health/details` to external monitoring when deployment begins.
6. Decide on billing scope.
7. Begin deployment planning only after these checks pass.

## Readiness decision

Status: **local MVP ready; production deployment not ready**.

The application is suitable for continued local learning, feature development, and demos.
It should not yet handle real customer data or be exposed publicly without the production
gaps above being addressed.
