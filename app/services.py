"""Document validation and bounded integration with the public GitHub API."""
import asyncio
import base64
import re
from pathlib import Path
import httpx
from fastapi import HTTPException

MAX_FILE_BYTES = 5 * 1024 * 1024
CATEGORIES = {'Engineering', 'Operations', 'Product', 'Research'}
MEDIA = {'.pdf': 'application/pdf', '.txt': 'text/plain', '.md': 'text/markdown', '.csv': 'text/csv'}

def validate_file(name: str, content: bytes):
    if not name or len(name) > 160 or any(c in name for c in '/\\\x00\r\n') or any(ord(c)<32 for c in name):
        raise HTTPException(422, 'Use a filename without paths or control characters (160 characters maximum).')
    extension = Path(name).suffix.lower()
    if extension not in MEDIA:
        raise HTTPException(415, 'Supported formats: PDF, TXT, Markdown and CSV.')
    if not content:
        raise HTTPException(422, 'The file is empty.')
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, 'Files must be 5 MB or smaller.')
    if extension == '.pdf':
        if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
            raise HTTPException(415, 'This file does not have a valid PDF signature.')
    else:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(415, 'Text files must use UTF-8 encoding.')
        if '\x00' in text:
            raise HTTPException(415, 'Binary content is not allowed in text files.')
    return MEDIA[extension]

async def github_readme(owner: str, repo: str):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', owner) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', repo):
        raise HTTPException(422, 'Enter a valid GitHub owner and repository name.')
    url = f'https://api.github.com/repos/{owner}/{repo}/readme'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8), follow_redirects=False) as client:
            for attempt in range(2):
                async with client.stream('GET', url, headers={'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'TeamDocs-Bootcamp'}) as response:
                    if response.status_code in {502,503,504} and attempt == 0:
                        await asyncio.sleep(0.25)
                        continue
                    if response.status_code == 404:
                        raise HTTPException(404, 'Public repository README not found.')
                    if response.status_code in {403,429}:
                        raise HTTPException(503, 'GitHub rate limit reached. Try again later.')
                    if response.status_code != 200:
                        raise HTTPException(502, 'GitHub could not provide this README.')
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise HTTPException(413, 'This README is too large to import.')
                    import json
                    data = json.loads(raw)
                    if data.get('encoding') != 'base64':
                        raise HTTPException(422, 'GitHub returned an unsupported README format.')
                    return f'{repo}-README.md', base64.b64decode(data['content'], validate=False)
    except httpx.TimeoutException:
        raise HTTPException(504, 'GitHub took too long to respond. Please retry.')
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, 'Unable to read the GitHub response.')
