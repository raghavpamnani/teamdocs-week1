"""Server-side sessions, current membership lookup, CSRF and permission guards."""
import hashlib
import secrets
import time
from dataclasses import dataclass
from fastapi import HTTPException, Request
from argon2 import PasswordHasher

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash('not-a-real-account-password')
PERMISSIONS = {
    'admin': {'read', 'upload', 'export', 'approve', 'delete', 'members', 'audit'},
    'member': {'read', 'upload', 'export', 'delete'},
    'viewer': {'read'},
}

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

@dataclass
class Context:
    user_id: str
    name: str
    email: str
    csrf: str
    tenant_id: str = ''
    role: str = ''

def current_user(request: Request) -> Context:
    token = request.cookies.get('teamdocs_session', '')
    with request.app.state.db.connect() as conn:
        row = conn.execute('SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id '
                           'WHERE token_hash=? AND expires_at>?', (token_hash(token), int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, 'Sign in to continue.')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        supplied = request.headers.get('X-CSRF-Token', '')
        if not secrets.compare_digest(supplied, row['csrf']):
            raise HTTPException(403, 'Invalid CSRF token. Reload and try again.')
    return Context(row['id'], row['name'], row['email'], row['csrf'])

def context(request: Request) -> Context:
    ctx = current_user(request)
    tenant = request.path_params.get('tenant_id', '')
    with request.app.state.db.connect() as conn:
        membership = conn.execute('SELECT role FROM memberships WHERE user_id=? AND tenant_id=?',
                                  (ctx.user_id, tenant)).fetchone()
    if not membership:
        raise HTTPException(404, 'Workspace not found.')
    ctx.tenant_id, ctx.role = tenant, membership['role']
    return ctx

def require(ctx: Context, permission: str):
    if permission not in PERMISSIONS[ctx.role]:
        raise HTTPException(403, 'Your role does not allow this action.')
