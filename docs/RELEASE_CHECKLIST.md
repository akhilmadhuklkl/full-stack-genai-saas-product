# Portfolio Release Checklist

This checklist defines the complete local/repository-ready state. Deployment is intentionally outside this checklist.

## Application

- [x] Custom frontend UI loads locally.
- [x] Registration, login, refresh, logout, and cookie authentication work.
- [x] Email verification and password reset workflows are implemented.
- [x] Console email mode works without external credentials.
- [x] Resend integration is implemented and covered by mocked tests.
- [x] Projects, files, archives, reviews, findings, history, and exports work.
- [x] Ollama local review generation works.

## Infrastructure

- [x] SQLite development database and Alembic migrations work.
- [x] Redis queue support works with localhost-only binding.
- [x] Windows-compatible durable RQ worker works with `SimpleWorker`.
- [x] Local startup script starts Ollama, worker, and API.
- [x] Docker Compose definition is available for local Redis.

## Quality and security

- [x] Full test suite passes.
- [x] Ruff, compile, frontend syntax, and diff checks pass.
- [x] Bandit scan passes.
- [x] Dependency audit passes locally and in GitHub Actions.
- [x] Migration upgrade/downgrade cycle passes.
- [x] Production configuration validation is implemented.
- [x] Security headers, CSRF protection, rate limits, and token revocation are implemented.

## Final local verification

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

Real Resend delivery and public deployment remain deferred because they require external credentials and hosting configuration.
