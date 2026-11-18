# Security and incident response

Forge Review is currently a local-first MVP. It should not process real customer source
code until the controls below are reviewed for the target environment.

## Current controls

- Passwords use salted PBKDF2-HMAC-SHA256.
- Access tokens expire and can be revoked.
- Refresh tokens are single-use and rotated.
- Browser sessions use an HttpOnly access cookie and CSRF protection.
- Login failures are throttled, with Redis support for multi-instance deployments.
- Project ownership is checked on project, file, review, export, and job routes.
- ZIP paths, file sizes, project file counts, and extracted archive size are bounded.
- AI output is validated before findings are persisted.
- Security response headers and request correlation IDs are enabled.

## Secrets

Rotate `AUTH_SECRET` immediately if it is exposed. Rotation invalidates existing signed
tokens, which is the intended emergency behavior. Redis and database credentials must be
stored in the environment or a secret manager and must never be committed.
When `APP_ENV=production`, startup rejects the default or shorter-than-32-character
`AUTH_SECRET` and rejects an empty `CORS_ORIGINS` setting.

After rotation:

1. Restart API and worker processes.
2. Confirm login issues new credentials.
3. Confirm old credentials are rejected.
4. Review logs for suspicious request IDs and account activity.

## Token compromise

Revoke the affected access token through logout or rotate `AUTH_SECRET` for broad compromise.
Treat refresh-token replay responses as security events. Record the approximate time, user,
request ID, and affected account without recording token values.

## AI and source-code safety

Uploaded files are untrusted input. The review prompt explicitly treats source content as
data, and model output is schema-validated. Before handling sensitive repositories, add
adversarial prompt-injection evaluation, context-size controls, model cancellation tests,
and a documented source-code retention policy.

## Email-dependent features

Password reset and email verification use one-time hashed database tokens. Local development
uses a console email adapter; production requires `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`,
and a verified `EMAIL_FROM` identity. Requests are throttled per email address, and tokens
are never returned by the API.
See `docs/EMAIL_SETUP.md` for configuration guidance.

## Pre-production checklist

- Run the complete GitHub Actions suite and inspect test/coverage artifacts.
- Apply and verify migrations in a clean database.
- Confirm Redis login throttling and worker heartbeats.
- Test backup restore and source-data deletion procedures.
- Configure external metrics collection and alerts.
- Review cookie, CSRF, CORS, TLS, and secret-manager settings for the chosen host.
