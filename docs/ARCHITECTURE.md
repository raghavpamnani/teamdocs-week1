# Architecture decisions

## 1. A conventional backend with a small same-origin frontend

FastAPI provides route handling, validation, dependencies and OpenAPI. Plain JavaScript keeps the browser interface easy to inspect and removes a second build toolchain. The frontend controls visibility for convenience; the server controls access. Framework-independent services handle file validation and GitHub response mapping. SQLite connections provide a transaction boundary. This is layered API architecture, not a claim that FastAPI implements classic server-rendered MVC.

## 2. Opaque sessions, current permissions

The client stores a random session token in an HttpOnly, SameSite=Strict cookie. Only its SHA-256 hash is persisted. The password is independently protected with Argon2. An eight-hour session expiry and explicit logout provide bounded session lifetime. A session-bound CSRF token is required for authenticated mutations. Login rotates the caller's existing session. Membership is queried on each request so a demotion is effective without waiting for an old role-bearing JWT to expire.

## 3. Tenant and ownership are separate checks

Every document lookup includes the verified tenant ID. The caller must belong to that tenant. Within the workspace, all members may read all documents; only administrators may approve, and members may delete only their own uploads. Tenant administrators are not global superusers. A transaction prevents removing the last administrator through concurrent role changes.

## 4. File contents never become paths or executable markup

Original names are display metadata. Random storage keys determine filesystem paths. Uploaded files live outside the static directory. The download route resolves the key only after authorization and uses attachment disposition. The browser escapes record values before inserting table HTML. Text uploads must be UTF-8; PDF checks are deliberately limited and documented.

## 5. Performance follows the actual query

The primary listing filters by tenant and orders by created time and ID. Its composite index follows that access pattern. An owner JOIN avoids one lookup per row. Page size is capped at 50. Search uses escaped `LIKE`; this is suitable for a small workspace, not a full-text search engine. CSV generation iterates a cursor rather than loading the entire register into a Python list. Uploaded file validation is bounded to 5 MB rather than pretending to be a fully streaming parser.

## 6. External integration is constrained

README import accepts an owner and repository name, not an arbitrary URL. Requests go only to `api.github.com`, redirects are not followed, and responses are size-bounded. One retry is allowed for selected upstream gateway failures; authentication/rate-limit failures are surfaced, not blindly retried. Requests have connection/read limits through HTTPX. This prevents unbounded waiting but is not an overall wall-clock deadline against every possible slow-streaming server.

## 7. Operations are observable and reproducible

Audit events describe business actions. Request logs describe HTTP outcomes without request bodies, credentials or query strings. Every response receives a request ID. Metrics are explicitly labeled as process-wide aggregates. Readiness checks the database and storage availability. CI builds and starts the container separately from API tests. Backup scripts capture both metadata and file contents while the app is stopped, clear sessions, and support verification before restoration.
