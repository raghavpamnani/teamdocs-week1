"""Check a backup without modifying the running application or original snapshot."""
import argparse
import sqlite3
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('backup');args=parser.parse_args()
    root=Path(args.backup).resolve()
    with sqlite3.connect(f'file:{root / "teamdocs.db"}?mode=ro',uri=True) as conn:
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        assert integrity=='ok',integrity
        rows=conn.execute('SELECT storage_key,size FROM documents').fetchall()
        for key,size in rows:
            path=root/'files'/key
            assert path.is_file(),f'Missing file: {key}'
            assert path.stat().st_size==size,f'File size mismatch: {key}'
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0,'Backup contains active sessions'
    print(f'PASS: database integrity, {len(rows)} file references, file sizes, and cleared sessions.')

if __name__=='__main__':main()
