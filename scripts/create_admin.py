"""Provision the first workspace without enabling public demo credentials."""
import argparse
import getpass
import os
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import Database
from app.security import hasher

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email',required=True);parser.add_argument('--name',required=True)
    parser.add_argument('--workspace',required=True);parser.add_argument('--data-dir',default=os.getenv('DATA_DIR','data'))
    args=parser.parse_args()
    password=getpass.getpass('Password (12+ characters): ')
    if len(password)<12:parser.error('Use at least 12 characters.')
    if password!=getpass.getpass('Confirm password: '):parser.error('Passwords do not match.')
    db=Database(Path(args.data_dir)/'teamdocs.db')
    with db.connect() as conn:
        if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]:parser.error('This bootstrap command requires an empty database.')
        user,tenant=uuid.uuid4().hex,uuid.uuid4().hex
        conn.execute('INSERT INTO users VALUES(?,?,?,?)',(user,args.name,args.email.lower().strip(),hasher.hash(password)))
        conn.execute('INSERT INTO tenants VALUES(?,?)',(tenant,args.workspace))
        conn.execute('INSERT INTO memberships VALUES(?,?,?)',(user,tenant,'admin'))
    print('Administrator created. Start TeamDocs with DEMO_MODE=false.')

if __name__=='__main__':main()
