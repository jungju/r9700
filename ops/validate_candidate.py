"""Trusted entrypoint inside a pinned, offline validation image only.

The operator-provided image includes Python, Node/npm, /opt/node_modules built
from the protected lockfile, and Playwright Chromium. The host never executes
candidate code directly. A missing mobile checker is a failure, not a waiver.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    workspace=Path('/work/repo')
    shutil.copytree('/candidate',workspace)
    os.symlink('/opt/node_modules',workspace/'node_modules',target_is_directory=True)
    os.chdir(workspace)
    checks=[('python',['python','-m','unittest','discover','-s','tests','-p','test_*.py']),
            ('web-tests',['npm','test']),('typecheck',['npm','run','check']),('build',['npm','run','build']),
            ('mobile',['node','tests-web/mobile-check.mjs'])]
    completed=[]
    for name,command in checks:
        result=subprocess.run(command,capture_output=True,text=True,timeout=180)
        if result.returncode:
            print(json.dumps({'state':'FAIL','failedCheck':name,'checks':completed}))
            return 1
        completed.append(name)
    print(json.dumps({'state':'PASS','checks':completed}))
    return 0


if __name__=='__main__': raise SystemExit(main())
