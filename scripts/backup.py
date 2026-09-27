"""Run with the application STOPPED so database and file snapshots agree."""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default='data')
    parser.add_argument('--output',default='backups')
    parser.add_argument('--app-stopped',action='store_true',required=True,help='Confirm the application is stopped.')
    args=parser.parse_args()
    root=Path(args.data_dir).resolve()
    if not (root/'teamdocs.db').is_file():parser.error('No TeamDocs database in data directory.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination=Path(args.output).resolve()/stamp
    if destination.is_relative_to(root):parser.error('Backup destination must be outside the data directory.')
    destination.mkdir(parents=True,exist_ok=False)
    source=sqlite3.connect(root/'teamdocs.db');target=sqlite3.connect(destination/'teamdocs.db')
    try:
        source.backup(target)
        # Restores should require new sign-ins rather than resurrect old sessions.
        target.execute('DELETE FROM sessions');target.commit()
        assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally:
        source.close();target.close()
    shutil.copytree(root/'files',destination/'files')
    (destination/'manifest.json').write_text(json.dumps({'created_at':stamp,'format':1,'sessions':'cleared'},indent=2))
    print(destination)

if __name__=='__main__':main()
