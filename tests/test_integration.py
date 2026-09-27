import asyncio
import base64
import httpx
import pytest
from fastapi import HTTPException
from app import services

@pytest.mark.parametrize('status,expected',[(404,404),(429,503),(403,503),(500,502)])
def test_github_error_mapping(monkeypatch,status,expected):
    factory=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(status))
    monkeypatch.setattr(services.httpx,'AsyncClient',lambda **kw:factory(transport=transport,**kw))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(services.github_readme('example','repo'))
    assert exc.value.status_code==expected

def test_github_transient_retry_and_mapping(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(str(request.url))
        if len(calls)==1:return httpx.Response(503)
        return httpx.Response(200,json={'encoding':'base64','content':base64.b64encode(b'# Hello').decode()})
    factory=httpx.AsyncClient
    monkeypatch.setattr(services.httpx,'AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(respond),**kw))
    assert asyncio.run(services.github_readme('example','repo'))==('repo-README.md',b'# Hello')
    assert len(calls)==2 and calls[0]=='https://api.github.com/repos/example/repo/readme'

def test_github_timeout_and_invalid_path(monkeypatch):
    def respond(request):raise httpx.ReadTimeout('timed out')
    factory=httpx.AsyncClient
    monkeypatch.setattr(services.httpx,'AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(respond),**kw))
    with pytest.raises(HTTPException) as exc:asyncio.run(services.github_readme('example','repo'))
    assert exc.value.status_code==504
    with pytest.raises(HTTPException) as exc:asyncio.run(services.github_readme('example','../../private'))
    assert exc.value.status_code==422
