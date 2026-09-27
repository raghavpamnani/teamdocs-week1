"""SQLite persistence; every resource query must be scoped to a verified tenant."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (
 user_id TEXT REFERENCES users(id), tenant_id TEXT REFERENCES tenants(id),
 role TEXT NOT NULL CHECK(role IN ('admin','member','viewer')), PRIMARY KEY(user_id,tenant_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, tenant_id TEXT REFERENCES tenants(id), owner_id TEXT REFERENCES users(id),
 name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL, size INTEGER NOT NULL, media_type TEXT NOT NULL,
 category TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('review','approved')),
 created_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'upload'
);
CREATE INDEX IF NOT EXISTS documents_tenant_created ON documents(tenant_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS documents_tenant_status ON documents(tenant_id,status);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_tenant_created ON audit(tenant_id,id DESC);
"""

class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
