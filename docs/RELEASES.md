# Release process

## Versioning

This project uses semantic versioning:

- Patch: bug fixes and safe internal changes
- Minor: backward-compatible features
- Major: breaking API or data changes

Keep these values aligned when releasing:

1. `pyproject.toml` project version
2. `app/version.py` application version
3. `CHANGELOG.md` release section

## Release checklist

1. Run compilation, linting, tests, and security checks.
2. Apply and verify database migrations.
3. Update the version and changelog.
4. Review API changes and backward compatibility.
5. Commit with a release-focused message.
6. Create a Git tag such as `v0.1.0`.
