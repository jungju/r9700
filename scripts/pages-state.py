"""Persist the collection ledger between isolated GitHub Actions runs."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    local=ROOT/'.local';target=local/'pages-state';local.mkdir(exist_ok=True)
    if sys.argv[1]=='restore':
        repo=os.environ.get('GITHUB_REPOSITORY','jungju/r9700')
        result=subprocess.run(['gh','api',f'repos/{repo}/actions/artifacts?name=r9700-collection-state&per_page=20'],capture_output=True,text=True)
        if result.returncode: raise RuntimeError('Cannot inspect prior collection state')
        artifacts=[a for a in json.loads(result.stdout)['artifacts'] if not a['expired']]
        if not artifacts:
            print('First deployment: initializing a new collection ledger');return
        artifact=max(artifacts,key=lambda a:a['created_at'])
        target.mkdir(exist_ok=True)
        result=subprocess.run(['gh','run','download',str(artifact['workflow_run']['id']),'--repo',repo,'--name','r9700-collection-state','--dir',str(target)])
        if result.returncode: raise RuntimeError('Prior state download failed; refusing to reset history')
        source=target/'operations.sqlite3'
        if not source.is_file():raise RuntimeError('Missing state database')
        db=sqlite3.connect(source)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Prior state is corrupt')
            with sqlite3.connect(local/'operations.sqlite3') as destination:db.backup(destination)
        finally:db.close()
        print('Collection ledger restored')
    elif sys.argv[1]=='save':
        source=local/'operations.sqlite3'
        if not source.exists():return
        target.mkdir(exist_ok=True)
        db=sqlite3.connect(source)
        try:
            with sqlite3.connect(target/'operations.sqlite3') as destination:
                db.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('State backup invalid')
        finally:db.close()
        print('Collection ledger checkpoint saved')
    else:raise ValueError('restore or save required')
if __name__=='__main__':main()
