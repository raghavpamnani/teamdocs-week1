# Week 1 evidence map

| Day | Curriculum | Evidence in TeamDocs |
|---|---|---|
| 1 | SDLC, Git, terminal, packages, environment, project structure, client/server and HTTP | Public repository, pinned Python dependencies, `.env.example`, browser/API separation, README run instructions, tests and CI |
| 2 | Routes, controllers, services, dependency boundaries, REST, pagination, errors, third-party APIs | Versioned routes, security dependencies, validation/import services, SQLite persistence boundary, pagination/filtering, GitHub README import with timeout/retry/rate-limit handling |
| 3 | Password hashing, sessions, authentication/authorization, tenants, ownership, secrets, CORS | Argon2, server-side sessions, CSRF, tenant-scoped queries, owner deletion rules, same-origin UI, ignored runtime data |
| 4 | Multipart, validation, file limits, naming, temporary files, downloads, CSV, payloads, N+1, indexes, rate limits, compression | 5 MB request/file constraints, generated storage keys, spooled uploads, protected file responses, streamed CSV, bounded pagination, owner JOIN, tenant/date indexes, EXPLAIN test, rate limits and gzip |
| 5 | RBAC, guards, least privilege, permission UI, audits, Docker/Compose, CI/CD, health, observability and backups | Role matrix and guards, immediate demotion checks, audit view, non-root container, persistent volume, CI build/health validation, request logs/metrics, backup and restore verification |

## Deliberate choices

Sessions are chosen instead of JWTs so logout and permission changes are easy to demonstrate. Local private storage and SQLite avoid paid services or configuration that would slow a reviewer down. CSV is the implemented export format; PDF and Excel export are outside this scope. API versioning uses `/api/v1`. The app demonstrates one cohesive implementation, not every alternative mentioned in the emails.

## Acceptance criteria

- A reviewer can start the demo without an API key.
- Upload, approval, download and CSV export work against persistent storage.
- A viewer cannot write or export through direct API calls.
- Guessing a document ID from another tenant does not expose its contents.
- Role changes affect an already-authenticated user.
- Invalid uploads do not create database records.
- At least one real external integration has bounded failure handling.
- Automated checks and a restore drill produce verifiable results.
