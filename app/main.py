import csv
import io
import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

from argon2.exceptions import VerificationError
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.db import Database
from app.security import Context, context, current_user, require, hasher, DUMMY_HASH, token_hash, PERMISSIONS
from app.services import validate_file, github_readme, MAX_FILE_BYTES, CATEGORIES

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('teamdocs')
STATIC = Path(__file__).parent / 'static'

def now():
    return datetime.now(timezone.utc).isoformat()

class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)

class RoleUpdate(BaseModel):
    role: Literal['admin', 'member', 'viewer']

class ImportRequest(BaseModel):
    owner: str = Field(max_length=39)
    repo: str = Field(max_length=100)
    category: Literal['Engineering', 'Operations', 'Product', 'Research'] = 'Engineering'

class BodyLimit:
    """Cap the entire HTTP body, including chunked multipart requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        maximum = MAX_FILE_BYTES + 65536
        headers = dict(scope.get('headers', []))
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = maximum + 1
        if length > maximum:
            return await JSONResponse({'error': {'code': 413, 'message': 'Files must be 5 MB or smaller.'}}, 413)(scope, receive, send)
        consumed = 0
        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > maximum:
                raise HTTPException(413, 'Files must be 5 MB or smaller.')
            return message
        await self.app(scope, bounded_receive, send)

def create_app(data_dir=None, demo=None):
    root = Path(data_dir or os.getenv('DATA_DIR', './data')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    files = root / 'files'
    files.mkdir(exist_ok=True)
    db = Database(root / 'teamdocs.db')
    demo = os.getenv('DEMO_MODE', 'false').lower() == 'true' if demo is None else demo
    secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'

    @asynccontextmanager
    async def lifespan(app):
        if demo:
            seed(db, files)
        yield

    app = FastAPI(title='TeamDocs API', version='1.0.0', lifespan=lifespan,
                  description='Tenant-aware document workflows. Sign in using the browser, then use the API explorer.')
    app.state.db, app.state.files, app.state.demo = db, files, demo
    app.state.metrics = {'requests': 0, 'errors': 0, 'duration_ms': 0.0}
    app.state.limits = defaultdict(deque)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BodyLimit)

    @app.middleware('http')
    async def observe(request, call_next):
        request.state.request_id = uuid.uuid4().hex[:16]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception('Unhandled error request_id=%s', request.state.request_id)
            response = JSONResponse({'error': {'code': 500, 'message': 'Something went wrong.',
                                    'request_id': request.state.request_id}}, 500)
        elapsed = (time.perf_counter()-start)*1000
        metrics = app.state.metrics
        metrics['requests'] += 1
        metrics['errors'] += int(response.status_code >= 500)
        metrics['duration_ms'] += elapsed
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path in {'/docs','/redoc'}:
            # FastAPI's API explorer loads its official UI assets from jsDelivr.
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; worker-src blob:; frame-ancestors 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        log.info(json.dumps({'request_id': request.state.request_id, 'method': request.method,
                             'route': getattr(request.scope.get('route'), 'path', 'static'),
                             'status': response.status_code, 'duration_ms': round(elapsed, 2)}))
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error': {'code': exc.status_code, 'message': exc.detail,
                                      'request_id': getattr(request.state, 'request_id', '')}},
                            status_code=exc.status_code, headers=exc.headers)

    from fastapi.exceptions import RequestValidationError
    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'error': {'code': 422, 'message': 'Check your input and try again.',
                                      'request_id': request.state.request_id}}, 422)

    def limit(key, count=30):
        # Bounded single-process limiter; use a shared store when scaling out.
        clock = time.monotonic()
        buckets = app.state.limits
        if len(buckets) > 2000:
            for old in list(buckets):
                if not buckets[old] or buckets[old][-1] < clock-60:
                    del buckets[old]
        bucket = buckets[key]
        while bucket and bucket[0] < clock-60:
            bucket.popleft()
        if len(bucket) >= count:
            raise HTTPException(429, 'Too many requests. Try again in a minute.', headers={'Retry-After': '60'})
        bucket.append(clock)

    def audit(conn, request, ctx, action, target, outcome='success'):
        conn.execute('INSERT INTO audit(tenant_id,actor,action,target,outcome,created_at,request_id) VALUES(?,?,?,?,?,?,?)',
                     (ctx.tenant_id,ctx.name,action,str(target)[:160],outcome,now(),request.state.request_id))

    def guard(request, ctx, permission, target):
        try:
            require(ctx, permission)
        except HTTPException:
            with db.connect() as conn:
                audit(conn,request,ctx,permission,target,'denied')
            raise

    def find_document(conn, ctx, doc_id):
        row = conn.execute('SELECT * FROM documents WHERE tenant_id=? AND id=?', (ctx.tenant_id,doc_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Document not found.')
        return row

    def store_document(request,ctx,name,content,category,source='upload'):
        media = validate_file(name, content)
        if category not in CATEGORIES:
            raise HTTPException(422, 'Select a valid category.')
        doc_id, key = uuid.uuid4().hex, uuid.uuid4().hex
        destination = files / key
        try:
            with destination.open('xb') as output:
                output.write(content)
            with db.connect() as conn:
                conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             (doc_id,ctx.tenant_id,ctx.user_id,name,key,len(content),media,category,'review',now(),source))
                audit(conn,request,ctx,'document.imported' if source != 'upload' else 'document.uploaded',name)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {'id':doc_id,'name':name,'status':'review'}

    @app.get('/api/config')
    def config():
        return {'demo':demo,'max_upload_mb':5}

    @app.post('/api/auth/login')
    def login(body:Login, request:Request):
        limit(('login',request.client.host if request.client else 'unknown'),10)
        with db.connect() as conn:
            user = conn.execute('SELECT * FROM users WHERE email=?',(body.email.lower().strip(),)).fetchone()
            try:
                hasher.verify(user['password_hash'] if user else DUMMY_HASH,body.password)
            except VerificationError:
                raise HTTPException(401,'Email or password is incorrect.')
            if not user:
                raise HTTPException(401,'Email or password is incorrect.')
            token,csrf = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            conn.execute('DELETE FROM sessions WHERE expires_at<=?',(int(time.time()),))
            old = request.cookies.get('teamdocs_session','')
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(old),))
            conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(token),user['id'],csrf,int(time.time())+28800))
        response = JSONResponse({'csrf':csrf})
        response.set_cookie('teamdocs_session',token,httponly=True,secure=secure,samesite='strict',max_age=28800,path='/')
        return response

    @app.post('/api/auth/logout')
    def logout(request:Request, ctx:Context=Depends(current_user)):
        with db.connect() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(request.cookies.get('teamdocs_session','')),))
        response = JSONResponse({'ok':True})
        response.delete_cookie('teamdocs_session',path='/')
        return response

    @app.get('/api/auth/me')
    def me(ctx:Context=Depends(current_user)):
        with db.connect() as conn:
            workspaces = [dict(r) for r in conn.execute('SELECT t.id,t.name,m.role FROM tenants t JOIN memberships m ON m.tenant_id=t.id WHERE m.user_id=? ORDER BY t.name',(ctx.user_id,))]
        return {'id':ctx.user_id,'name':ctx.name,'email':ctx.email,'csrf':ctx.csrf,'workspaces':workspaces}

    @app.get('/api/v1/workspaces/{tenant_id}/documents')
    def documents(tenant_id:str,ctx:Context=Depends(context),q:str=Query('',max_length=100),
                  category:str='',status:str='',page:int=Query(1,ge=1,le=10000),limit_:int=Query(8,alias='limit',ge=1,le=50)):
        clauses, values = ['d.tenant_id=?'],[ctx.tenant_id]
        if q:
            clauses.append("d.name LIKE ? ESCAPE '\\'")
            values.append('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        for col,val in [('category',category),('status',status)]:
            if val:
                clauses.append(f'd.{col}=?'); values.append(val)
        where = ' AND '.join(clauses)
        with db.connect() as conn:
            total = conn.execute(f'SELECT COUNT(*) FROM documents d WHERE {where}',values).fetchone()[0]
            rows = conn.execute(f'SELECT d.id,d.name,d.size,d.media_type,d.category,d.status,d.created_at,d.owner_id,d.source,u.name AS owner FROM documents d JOIN users u ON u.id=d.owner_id WHERE {where} ORDER BY d.created_at DESC,d.id DESC LIMIT ? OFFSET ?',[*values,limit_,(page-1)*limit_]).fetchall()
        return {'items':[dict(r) for r in rows],'total':total,'page':page,'limit':limit_}

    @app.get('/api/v1/workspaces/{tenant_id}/overview')
    def overview(tenant_id:str,ctx:Context=Depends(context)):
        with db.connect() as conn:
            stats=dict(conn.execute("SELECT COUNT(*) AS total,COALESCE(SUM(size),0) AS bytes,COALESCE(SUM(status='review'),0) AS review,COALESCE(SUM(status='approved'),0) AS approved FROM documents WHERE tenant_id=?",(ctx.tenant_id,)).fetchone())
            stats['members']=conn.execute('SELECT COUNT(*) FROM memberships WHERE tenant_id=?',(ctx.tenant_id,)).fetchone()[0]
        return stats

    @app.post('/api/v1/workspaces/{tenant_id}/documents',status_code=201)
    async def upload(tenant_id:str,request:Request,ctx:Context=Depends(context),file:UploadFile=File(...),category:str=Form('Engineering')):
        guard(request,ctx,'upload','document')
        limit(('upload',ctx.user_id),15)
        # Multipart spools to disk; validation is bounded to the explicit 5 MB limit.
        try:
            content=await file.read(MAX_FILE_BYTES+1)
            return store_document(request,ctx,file.filename or '',content,category)
        finally:
            await file.close()

    @app.post('/api/v1/workspaces/{tenant_id}/imports/github',status_code=201)
    async def import_github(tenant_id:str,body:ImportRequest,request:Request,ctx:Context=Depends(context)):
        guard(request,ctx,'upload','github-import')
        limit(('import',ctx.user_id),5)
        name,content=await github_readme(body.owner,body.repo)
        return store_document(request,ctx,name,content,body.category,f'github:{body.owner}/{body.repo}')

    @app.get('/api/v1/workspaces/{tenant_id}/documents/{doc_id}/download')
    def download(tenant_id:str,doc_id:str,request:Request,ctx:Context=Depends(context)):
        with db.connect() as conn:
            row=find_document(conn,ctx,doc_id)
            path=files/row['storage_key']
            if not path.is_file():
                raise HTTPException(404,'File unavailable. Contact your administrator.')
            audit(conn,request,ctx,'document.downloaded',row['name'])
        return FileResponse(path,media_type=row['media_type'],filename=row['name'],content_disposition_type='attachment')

    @app.post('/api/v1/workspaces/{tenant_id}/documents/{doc_id}/approve')
    def approve(tenant_id:str,doc_id:str,request:Request,ctx:Context=Depends(context)):
        guard(request,ctx,'approve',doc_id)
        with db.connect() as conn:
            row=find_document(conn,ctx,doc_id)
            if row['status']!='approved':
                conn.execute("UPDATE documents SET status='approved' WHERE tenant_id=? AND id=?",(ctx.tenant_id,doc_id))
                audit(conn,request,ctx,'document.approved',row['name'])
        return {'status':'approved'}

    @app.delete('/api/v1/workspaces/{tenant_id}/documents/{doc_id}',status_code=204)
    def delete(tenant_id:str,doc_id:str,request:Request,ctx:Context=Depends(context)):
        guard(request,ctx,'delete',doc_id)
        with db.connect() as conn:
            row=find_document(conn,ctx,doc_id)
            if ctx.role!='admin' and row['owner_id']!=ctx.user_id:
                raise HTTPException(403,'Members may delete only their own documents.')
            conn.execute('DELETE FROM documents WHERE tenant_id=? AND id=?',(ctx.tenant_id,doc_id))
            audit(conn,request,ctx,'document.deleted',row['name'])
        (files/row['storage_key']).unlink(missing_ok=True)

    @app.get('/api/v1/workspaces/{tenant_id}/export')
    def export(tenant_id:str,request:Request,ctx:Context=Depends(context)):
        guard(request,ctx,'export','document register')
        with db.connect() as conn:
            audit(conn,request,ctx,'register.exported','CSV')
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
        def stream():
            buf=io.StringIO(); writer=csv.writer(buf)
            writer.writerow(['Name','Category','Status','Owner','Bytes','Created'])
            yield buf.getvalue();buf.seek(0);buf.truncate(0)
            with db.connect() as conn:
                cursor=conn.execute('SELECT d.name,d.category,d.status,u.name,d.size,d.created_at FROM documents d JOIN users u ON u.id=d.owner_id WHERE d.tenant_id=? ORDER BY d.created_at DESC,d.id DESC',(ctx.tenant_id,))
                for row in cursor:
                    writer.writerow([safe(v) for v in row]);yield buf.getvalue();buf.seek(0);buf.truncate(0)
        return StreamingResponse(stream(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="teamdocs-register.csv"'})

    @app.get('/api/v1/workspaces/{tenant_id}/members')
    def members(tenant_id:str,ctx:Context=Depends(context)):
        require(ctx,'members')
        with db.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT u.id,u.name,u.email,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? ORDER BY u.name',(ctx.tenant_id,))]

    @app.patch('/api/v1/workspaces/{tenant_id}/members/{user_id}')
    def update_role(tenant_id:str,user_id:str,body:RoleUpdate,request:Request,ctx:Context=Depends(context)):
        guard(request,ctx,'members',user_id)
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            member=conn.execute('SELECT role FROM memberships WHERE tenant_id=? AND user_id=?',(ctx.tenant_id,user_id)).fetchone()
            if not member: raise HTTPException(404,'Member not found.')
            if member['role']=='admin' and body.role!='admin':
                admins=conn.execute("SELECT COUNT(*) FROM memberships WHERE tenant_id=? AND role='admin'",(ctx.tenant_id,)).fetchone()[0]
                if admins<=1: raise HTTPException(409,'A workspace must keep at least one administrator.')
            conn.execute('UPDATE memberships SET role=? WHERE tenant_id=? AND user_id=?',(body.role,ctx.tenant_id,user_id))
            audit(conn,request,ctx,'member.role_changed',f'{user_id}: {member["role"]} → {body.role}')
        return {'role':body.role}

    @app.get('/api/v1/workspaces/{tenant_id}/audit')
    def audit_list(tenant_id:str,ctx:Context=Depends(context),page:int=Query(1,ge=1)):
        require(ctx,'audit')
        with db.connect() as conn:
            rows=conn.execute('SELECT * FROM audit WHERE tenant_id=? ORDER BY id DESC LIMIT 30 OFFSET ?',(ctx.tenant_id,(page-1)*30)).fetchall()
            total=conn.execute('SELECT COUNT(*) FROM audit WHERE tenant_id=?',(ctx.tenant_id,)).fetchone()[0]
        return {'items':[dict(r) for r in rows],'total':total,'page':page}

    @app.get('/api/v1/workspaces/{tenant_id}/metrics')
    def metrics(tenant_id:str,ctx:Context=Depends(context)):
        require(ctx,'audit')
        m=app.state.metrics
        return {**m,'mean_duration_ms':round(m['duration_ms']/max(m['requests'],1),2),'scope':'single application process'}

    @app.get('/health/live')
    def live(): return {'status':'alive'}

    @app.get('/health/ready')
    def ready():
        try:
            with db.connect() as conn: conn.execute('SELECT 1').fetchone()
            if not os.access(files,os.W_OK): raise OSError('Storage unavailable')
        except (sqlite3.Error,OSError):
            raise HTTPException(503,'A required dependency is unavailable.')
        return {'status':'ready','database':'ok','storage':'ok'}

    @app.get('/')
    def index(): return FileResponse(STATIC/'index.html')

    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    return app

def seed(db, files):
    """Explicit demo mode only. Never enabled by default for production."""
    with db.connect() as conn:
        if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]: return
        password=hasher.hash('DemoPass123!')
        people=[('alex','Alex Morgan','admin@teamdocs.demo'),('jamie','Jamie Chen','member@teamdocs.demo'),('sam','Sam Rivera','viewer@teamdocs.demo'),('taylor','Taylor Brooks','other@teamdocs.demo')]
        conn.executemany('INSERT INTO users VALUES(?,?,?,?)',[(i,n,e,password) for i,n,e in people])
        conn.executemany('INSERT INTO tenants VALUES(?,?)',[('northstar','Northstar Studio'),('orbit','Orbit Labs')])
        conn.executemany('INSERT INTO memberships VALUES(?,?,?)',[('alex','northstar','admin'),('jamie','northstar','member'),('sam','northstar','viewer'),('taylor','orbit','admin')])
        docs=[('Product launch brief.md','Product','approved','alex'),('API integration guide.md','Engineering','approved','jamie'),('Customer interview notes.txt','Research','review','jamie'),('Team onboarding checklist.md','Operations','approved','alex'),('Release readiness checklist.md','Engineering','review','jamie'),('Research participant register.csv','Research','approved','alex')]
        for index,(name,category,status,owner) in enumerate(docs):
            content=(f'# {name.rsplit(".",1)[0]}\n\nNorthstar Studio · Sample document\n\n## Purpose\nKeep our team aligned with clear ownership and reviewable decisions.\n\n## Next steps\n- Confirm the owner.\n- Review the proposal.\n- Record the decision.\n').encode()
            if name.endswith('.csv'): content=b'Participant,Session,Status\nSample A,Discovery,Complete\nSample B,Usability,Scheduled\n'
            key=uuid.uuid4().hex;(files/key).write_bytes(content)
            created=(datetime.now(timezone.utc)-timedelta(hours=index*7)).isoformat()
            conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)',(f'demo-{index+1}','northstar',owner,name,key,len(content),validate_file(name,content),category,status,created,'sample'))
            conn.execute('INSERT INTO audit(tenant_id,actor,action,target,outcome,created_at,request_id) VALUES(?,?,?,?,?,?,?)',('northstar',dict((i,n) for i,n,e in people)[owner],'document.uploaded',name,'success',created,'seed'))
        key=uuid.uuid4().hex;content=b'Orbit Labs private planning notes. This belongs to a different tenant.\n';(files/key).write_bytes(content)
        conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)',('orbit-private','orbit','taylor','Orbit private roadmap.txt',key,len(content),'text/plain','Product','review',now(),'sample'))
