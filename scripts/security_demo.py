"""Read-only demo of tenant isolation and viewer permissions against a running demo server."""
import argparse
import httpx

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000');args=parser.parse_args()
    with httpx.Client(base_url=args.url,timeout=10) as client:
        response=client.post('/api/auth/login',json={'email':'viewer@teamdocs.demo','password':'DemoPass123!'})
        response.raise_for_status();client.headers['X-CSRF-Token']=response.json()['csrf']
        cases=[('Read own workspace', '/api/v1/workspaces/northstar/documents',200),
               ('Export as a viewer', '/api/v1/workspaces/northstar/export',403),
               ('Access another workspace', '/api/v1/workspaces/orbit/documents',404),
               ('Guess another tenant document ID', '/api/v1/workspaces/northstar/documents/orbit-private/download',404)]
        for label,path,expected in cases:
            result=client.get(path)
            print(f'{"PASS" if result.status_code==expected else "FAIL"}  {label:<38} HTTP {result.status_code}')
            assert result.status_code==expected,result.text
        client.post('/api/auth/logout').raise_for_status()

if __name__=='__main__':main()
