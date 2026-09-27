import csv
import io
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

BASE='/api/v1/workspaces/northstar'

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path,demo=True)) as client:
        yield client

def login(client,role='admin'):
    response=client.post('/api/auth/login',json={'email':f'{role}@teamdocs.demo','password':'DemoPass123!'})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf']
    return response

def upload(client,name='notes.md',content=b'# Planning\nA useful document.'):
    return client.post(BASE+'/documents',files={'file':(name,content)},data={'category':'Engineering'})

def test_authentication_and_cookie_security(client):
    assert client.get(BASE+'/documents').status_code==401
    assert client.post('/api/auth/login',json={'email':'admin@teamdocs.demo','password':'wrong'}).status_code==401
    response=login(client)
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert client.get('/api/auth/me').json()['name']=='Alex Morgan'

def test_session_expiration_and_logout(client):
    login(client)
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me').status_code==401
    login(client)
    with client.app.state.db.connect() as conn:
        conn.execute('UPDATE sessions SET expires_at=?',(int(time.time())-1,))
    assert client.get('/api/auth/me').status_code==401

def test_csrf_enforced(client):
    login(client);del client.headers['X-CSRF-Token']
    assert upload(client).status_code==403
    assert client.delete(BASE+'/documents/demo-1').status_code==403

def test_viewer_cannot_mutate_or_export(client):
    login(client,'viewer')
    assert client.get(BASE+'/documents').status_code==200
    assert client.get(BASE+'/documents/demo-1/download').status_code==200
    assert upload(client).status_code==403
    assert client.delete(BASE+'/documents/demo-1').status_code==403
    assert client.post(BASE+'/documents/demo-3/approve').status_code==403
    assert client.get(BASE+'/export').status_code==403
    assert client.get(BASE+'/members').status_code==403
    assert client.get(BASE+'/audit').status_code==403

def test_tenant_isolation_on_every_resource_route(client):
    login(client)
    assert client.get('/api/v1/workspaces/orbit/documents').status_code==404
    assert client.get(BASE+'/documents/orbit-private/download').status_code==404
    assert client.delete(BASE+'/documents/orbit-private').status_code==404
    assert client.post(BASE+'/documents/orbit-private/approve').status_code==404
    assert client.patch(BASE+'/members/taylor',json={'role':'viewer'}).status_code==404
    assert b'Orbit private' not in client.get(BASE+'/export').content
    login(client,'other')
    assert client.get('/api/v1/workspaces/orbit/documents').json()['total']==1
    assert client.get(BASE+'/documents').status_code==404

def test_owner_rule_and_full_document_lifecycle(client):
    login(client,'member')
    assert client.delete(BASE+'/documents/demo-1').status_code==403
    response=upload(client);assert response.status_code==201,response.text
    doc=response.json()['id']
    download=client.get(BASE+f'/documents/{doc}/download')
    assert download.content==b'# Planning\nA useful document.'
    assert 'attachment' in download.headers['content-disposition']
    assert client.post(BASE+f'/documents/{doc}/approve').status_code==403
    assert client.delete(BASE+f'/documents/{doc}').status_code==204
    assert client.get(BASE+f'/documents/{doc}/download').status_code==404

@pytest.mark.parametrize('name,content,code',[
    ('fake.pdf',b'not a pdf',415),('bad.exe',b'MZ',415),('../escape.txt',b'bad path',422),
    ('empty.txt',b'',422),('binary.txt',b'hello\x00world',415),('encoding.txt',b'\xff',415),
    ('large.txt',b'x'*(5*1024*1024+1),413),
])
def test_invalid_uploads(client,name,content,code):
    login(client)
    before=client.get(BASE+'/overview').json()['total']
    assert upload(client,name,content).status_code==code
    assert client.get(BASE+'/overview').json()['total']==before

def test_total_request_size_limit(client):
    login(client)
    assert upload(client,'large.txt',b'x'*(6*1024*1024)).status_code==413

def test_roles_change_immediately_and_last_admin_is_protected(client):
    login(client)
    assert client.patch(BASE+'/members/alex',json={'role':'viewer'}).status_code==409
    assert client.patch(BASE+'/members/jamie',json={'role':'viewer'}).status_code==200
    login(client,'member')
    assert upload(client).status_code==403

def test_existing_session_demotion(client):
    with TestClient(client.app) as member:
        login(member,'member');login(client)
        assert upload(member).status_code==201
        assert client.patch(BASE+'/members/jamie',json={'role':'viewer'}).status_code==200
        assert upload(member).status_code==403

def test_pagination_filtering_and_parameter_binding(client):
    login(client)
    first=client.get(BASE+'/documents?limit=2&page=1').json()
    second=client.get(BASE+'/documents?limit=2&page=2').json()
    assert first['total']==6 and len(first['items'])==2
    assert {d['id'] for d in first['items']}.isdisjoint(d['id'] for d in second['items'])
    assert client.get(BASE+'/documents',params={'q':"' OR 1=1 --"}).json()['total']==0
    result=client.get(BASE+'/documents?category=Engineering&status=review').json()
    assert result['total']==1
    assert client.get(BASE+'/documents?limit=1000').status_code==422

def test_approval_export_and_audit(client):
    login(client)
    assert client.post(BASE+'/documents/demo-3/approve').status_code==200
    assert client.get(BASE+'/documents?status=approved').json()['total']==5
    assert upload(client,'=SUM(1+1).txt',b'hello').status_code==201
    response=client.get(BASE+'/export')
    rows=list(csv.reader(io.StringIO(response.text)))
    assert rows[1][0].startswith("'=")
    events=client.get(BASE+'/audit').json()['items']
    assert {'register.exported','document.approved','document.uploaded'} <= {e['action'] for e in events}

def test_login_rate_limit(client):
    for _ in range(10):
        client.post('/api/auth/login',json={'email':'nobody@example.com','password':'wrong'})
    response=client.post('/api/auth/login',json={'email':'nobody@example.com','password':'wrong'})
    assert response.status_code==429 and response.headers['retry-after']=='60'

def test_health_headers_and_database_index(client):
    assert client.get('/health/ready').json()['status']=='ready'
    response=client.get('/')
    assert response.status_code==200 and 'frame-ancestors' in response.headers['content-security-policy']
    login(client)
    assert client.get(BASE+'/documents').headers['cache-control']=='no-store'
    with client.app.state.db.connect() as conn:
        plan=conn.execute('EXPLAIN QUERY PLAN SELECT id FROM documents WHERE tenant_id=? ORDER BY created_at DESC,id DESC LIMIT 20',('northstar',)).fetchall()
        assert any('documents_tenant_created' in r[3] for r in plan)

def test_no_demo_accounts_by_default(tmp_path):
    with TestClient(create_app(tmp_path,demo=False)) as client:
        assert client.get('/api/config').json()['demo'] is False
        assert client.post('/api/auth/login',json={'email':'admin@teamdocs.demo','password':'DemoPass123!'}).status_code==401

def test_github_import_mapping_and_permission(client,monkeypatch):
    async def stub(owner,repo):
        assert (owner,repo)==('example','project')
        return 'project-README.md',b'# Public README'
    monkeypatch.setattr('app.main.github_readme',stub)
    login(client)
    response=client.post(BASE+'/imports/github',json={'owner':'example','repo':'project'})
    assert response.status_code==201
    doc=client.get(BASE+'/documents?q=project-README').json()['items'][0]
    assert doc['source']=='github:example/project'
    login(client,'viewer')
    assert client.post(BASE+'/imports/github',json={'owner':'example','repo':'project'}).status_code==403

def test_backup_and_restore_drill(tmp_path):
    import subprocess
    import sys
    import shutil
    data=tmp_path/'source'
    with TestClient(create_app(data,demo=True)) as source:
        login(source)
        assert upload(source,'restore-me.txt',b'Backup content').status_code==201
    # No app is running against this data directory during the snapshot.
    result=subprocess.run([sys.executable,'scripts/backup.py','--data-dir',str(data),'--output',str(tmp_path/'backups'),'--app-stopped'],check=True,capture_output=True,text=True)
    backup=result.stdout.strip()
    subprocess.run([sys.executable,'scripts/restore_check.py',backup],check=True,capture_output=True,text=True)
    restored=tmp_path/'restored';shutil.copytree(backup,restored)
    with TestClient(create_app(restored,demo=False)) as restored_client:
        login(restored_client)
        doc=restored_client.get(BASE+'/documents?q=restore-me').json()['items'][0]
        assert restored_client.get(BASE+f'/documents/{doc["id"]}/download').content==b'Backup content'
