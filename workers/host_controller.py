"""Fixed host-side adapter for validated public-code releases.

Only operator-configured argv is executed. Request files are treated as untrusted
data and never supply commands, environment variables, or arbitrary destinations.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import string
import subprocess
from pathlib import Path
from typing import Any

from ops.common import atomic_json, digest, inside, now, read_json, redact

REQUIRED_CHECKS = ('http', 'search', 'prices', 'mobile')
ALLOWED_PREFIXES = (
    'src/components/', 'src/layouts/', 'src/styles/', 'src/pages/news',
    'src/pages/guides', 'src/pages/search', 'src/pages/prices',
    'src/pages/products', 'src/pages/showcase', 'src/pages/content/',
)
PROTECTED_PATHS = ('ops', 'tests', 'tests-web', 'tests-workers', 'workers', 'src/lib', 'src/pages/api', 'src/pages/admin', 'sources.json')
IGNORED_PARTS = {'.local', '.git', 'node_modules', '__pycache__', 'dist', '.astro'}
PLACEHOLDERS = {'id', 'releasePath', 'manifestHash', 'releaseId', 'previousRelease', 'expectedReleaseId'}
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,120}$')
HASH_RE = re.compile(r'^[a-f0-9]{64}$')


class ControllerError(Exception):
    """An input, configuration, or validation failure safe to report locally."""


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _safe_release(value: Any) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == 'nt':
        kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel32.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel32.OpenProcess.restype=ctypes.c_void_p
        handle=kernel32.OpenProcess(0x1000,0,pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error()==5  # Access denied still means the process exists.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class LivenessLock:
    """Cross-process exclusive lock that permits recovery after owner exit."""

    def __init__(self, path: Path):
        self.path = path
        self.owned = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ControllerError('lock path cannot be a symbolic link')
        payload = json.dumps({'pid': os.getpid(), 'startedAt': now()}).encode('utf-8')
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    previous = read_json(self.path)
                    pid = int(previous.get('pid', -1))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = -1
                if _is_process_alive(pid):
                    return False
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self.owned = True
            return True
        return False

    def release(self) -> None:
        if self.owned:
            try:
                current = read_json(self.path)
                if current.get('pid') == os.getpid():
                    self.path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            self.owned = False

    def __enter__(self):
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.release()


def _command_env() -> dict[str, str]:
    """Pass only ordinary OS runtime variables, never the worker's full env."""
    names = ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT')
    return {name: os.environ[name] for name in names if name in os.environ}


def _validate_config(root: Path, exchange: Path, config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or config.get('schemaVersion') != 1:
        raise ControllerError('host controller config is missing or unsupported')
    configured_root = config.get('projectRoot')
    configured_exchange = config.get('hostExchangeDirectory')
    if not isinstance(configured_root, str) or Path(configured_root).resolve() != root.resolve():
        raise ControllerError('config projectRoot does not match the selected project')
    if not isinstance(configured_exchange, str) or Path(configured_exchange).resolve() != exchange.resolve():
        raise ControllerError('config hostExchangeDirectory does not match the exchange')
    timeout = config.get('commandTimeoutSeconds', 120)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 900:
        raise ControllerError('commandTimeoutSeconds must be between 1 and 900')
    def argv(name: str) -> list[str]:
        result = config.get(name)
        if not isinstance(result, list) or not result or any(not isinstance(item, str) or not item or '\x00' in item for item in result):
            raise ControllerError(f'{name} must be a non-empty trusted argv list')
        if not Path(result[0]).is_absolute() or not Path(result[0]).is_file():
            raise ControllerError(f'{name} executable must be an absolute operator-configured path')
        _validate_templates(result, name)
        return result
    deploy = argv('deployArgv')
    rollback = argv('rollbackArgv')
    verify = config.get('verifyArgv')
    if not isinstance(verify, dict) or set(verify) != set(REQUIRED_CHECKS):
        raise ControllerError('verifyArgv must configure exactly http, search, prices, and mobile')
    checks = {name: verify[name] for name in REQUIRED_CHECKS}
    for name, value in checks.items():
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item or '\x00' in item for item in value):
            raise ControllerError(f'verifyArgv.{name} must be a non-empty trusted argv list')
        if not Path(value[0]).is_absolute() or not Path(value[0]).is_file():
            raise ControllerError(f'verifyArgv.{name} executable must be an absolute operator-configured path')
        _validate_templates(value, f'verifyArgv.{name}')
    return {'timeout': timeout, 'deploy': deploy, 'rollback': rollback, 'verify': checks}


def _validate_templates(argv: list[str], label: str) -> None:
    for arg in argv:
        try:
            pieces=string.Formatter().parse(arg)
            for _literal,field,format_spec,conversion in pieces:
                if field is not None and (field not in PLACEHOLDERS or format_spec or conversion):
                    raise ControllerError(f'{label} contains an unsupported placeholder')
        except ValueError as error:
            raise ControllerError(f'{label} contains an invalid argv template') from error


def _render_argv(argv: list[str], values: dict[str, str]) -> list[str]:
    rendered: list[str] = []
    for arg in argv:
        try:
            pieces = string.Formatter().parse(arg)
            for _literal, field, format_spec, conversion in pieces:
                if field is not None and (field not in PLACEHOLDERS or format_spec or conversion):
                    raise ControllerError('trusted argv contains an unsupported placeholder')
            rendered.append(arg.format_map(values))
        except (KeyError, ValueError) as error:
            raise ControllerError('trusted argv placeholder could not be resolved') from error
    return rendered


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, shell=False, check=False, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=timeout,
                              env=_command_env())
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ControllerError(redact(str(error))) from error


def _project_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directory=Path(current)
        retained=[]
        for name in directories:
            path=directory/name
            if name in IGNORED_PARTS or name.startswith('.env'):
                continue
            if path.is_symlink():
                raise ControllerError(f'symbolic link is not allowed in release comparison: {path.relative_to(root).as_posix()}')
            retained.append(name)
        directories[:]=retained
        for name in files:
            path=directory/name
            relative=path.relative_to(root)
            if relative.as_posix()=='validation-receipt.json' or path.name.startswith('.env'):
                continue
            if path.is_symlink():
                raise ControllerError(f'symbolic link is not allowed in release comparison: {relative.as_posix()}')
            if path.is_file():
                result[relative.as_posix()]=path
    return result


def _tree_hashes(files: dict[str, Path]) -> dict[str, str]:
    return {name: digest(path.read_bytes()) for name, path in files.items()}


def _validate_release(root: Path, request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    if not _safe_id(request.get('id')):
        raise ControllerError('request id is invalid')
    if request.get('requiredChecks') != list(REQUIRED_CHECKS):
        raise ControllerError('request requiredChecks must exactly match the host checklist')
    if request.get('rollbackDatabase') is not False:
        raise ControllerError('database rollback is forbidden')
    if not _safe_release(request.get('previousRelease')):
        raise ControllerError('previousRelease is missing or invalid; rollback must be possible')
    manifest_hash = request.get('manifestHash')
    if not isinstance(manifest_hash, str) or not HASH_RE.fullmatch(manifest_hash):
        raise ControllerError('manifestHash is invalid')
    release_value = request.get('releasePath')
    if not isinstance(release_value, str) or not Path(release_value).is_absolute():
        raise ControllerError('releasePath must be an absolute operator-local path')
    releases_root = (root / '.local' / 'code-releases').resolve()
    release = Path(release_value).resolve(strict=True)
    if release == releases_root or release.parent != releases_root or release.name != request['id'] or not release.is_dir() or Path(release_value).is_symlink():
        raise ControllerError('releasePath must name one real release directory under .local/code-releases')
    if (release/'.local').exists() or (release/'.local').is_symlink():
        raise ControllerError('release must not contain operational state or a database')
    receipt_file = release / 'validation-receipt.json'
    if receipt_file.is_symlink() or not receipt_file.is_file():
        raise ControllerError('immutable validation-receipt.json is missing')
    manifest = read_json(receipt_file)
    if digest(manifest) != manifest_hash:
        raise ControllerError('validation receipt digest does not match manifestHash')
    if manifest.get('schemaVersion') != 1 or manifest.get('id') != request['id']:
        raise ControllerError('validation receipt identity or schema is invalid')
    validation = manifest.get('validation')
    if not isinstance(validation, dict) or validation.get('state') != 'PASS' or validation.get('checks') != ['python','web-tests','typecheck','build','mobile']:
        raise ControllerError('release does not have a passing fixed validation receipt')
    changes = manifest.get('changes')
    if not isinstance(changes, dict):
        raise ControllerError('approved file manifest is missing')
    approved = changes.get('files')
    approved_hashes = changes.get('hashes')
    if not isinstance(approved, list) or not approved or len(approved) > 5 or len(set(approved)) != len(approved):
        raise ControllerError('approved file list is invalid')
    if not isinstance(approved_hashes, dict) or set(approved_hashes) != set(approved):
        raise ControllerError('approved file hashes do not match the file list')
    for name in approved:
        if not isinstance(name, str) or name.startswith('/') or '\\' in name or any(part in ('', '.', '..') for part in name.split('/')):
            raise ControllerError('approved file path is invalid')
        if not any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            raise ControllerError('approved file is outside the fixed public-code allowlist')
        if any(name == protected or name.startswith(protected + '/') for protected in PROTECTED_PATHS):
            raise ControllerError('protected file is listed as a candidate change')
        if not isinstance(approved_hashes[name], str) or not HASH_RE.fullmatch(approved_hashes[name]):
            raise ControllerError('approved file hash is invalid')
        candidate_file = release / name
        if candidate_file.is_symlink() or not candidate_file.is_file() or digest(candidate_file.read_bytes()) != approved_hashes[name]:
            raise ControllerError('candidate file hash differs from the validated approval')
    if not isinstance(changes.get('changedLines'), int) or not 1 <= changes['changedLines'] <= 200:
        raise ControllerError('approved change size is invalid')
    # Compare the complete source snapshots, so a changed file cannot hide outside the approved list.
    live_hashes = _tree_hashes(_project_files(root))
    release_hashes = _tree_hashes(_project_files(release))
    changed = sorted(name for name in set(live_hashes) | set(release_hashes) if live_hashes.get(name) != release_hashes.get(name))
    deleted = sorted(name for name in live_hashes if name not in release_hashes)
    if deleted:
        raise ControllerError('release deletes files from the current project')
    if changed != sorted(approved):
        raise ControllerError('release contents differ from the exact approved file list')
    if 'operations.sqlite3' in release_hashes or any(name.startswith('.local/') for name in release_hashes):
        raise ControllerError('operational database or local state must not be in the release')
    return release, manifest


def _verify_release_immutable(release: Path, request: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Recheck sealed evidence after external commands without assuming they leave the source checkout in place."""
    if digest(read_json(release/'validation-receipt.json')) != request.get('manifestHash'):
        raise ControllerError('validation receipt changed while the host command ran')
    for name, expected_hash in manifest['changes']['hashes'].items():
        path=release/name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected_hash:
            raise ControllerError('validated candidate bytes changed while the host command ran')


def _run_check(name: str, commands: dict[str, list[str]], timeout: int, values: dict[str, str], expected_release: str) -> tuple[str, str | None]:
    current = dict(values)
    current['expectedReleaseId'] = expected_release
    result = _run(_render_argv(commands[name], current), timeout)
    if result.returncode != 0:
        return 'FAIL', redact(result.stderr or result.stdout or f'{name} command exited {result.returncode}')
    if name == 'http':
        try:
            response = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return 'FAIL', 'HTTP health verifier did not return JSON'
        if not isinstance(response, dict) or response.get('releaseId') != expected_release:
            return 'FAIL', 'HTTP health releaseId did not match the expected release'
    return 'PASS', None


def _receipt(request_id: str, state: str, manifest_hash: str | None, checks: dict[str, str],
             release_id: str | None, previous_release: str | None, detail: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {'id':request_id,'state':state,'manifestHash':manifest_hash,
                            'checks':{name:checks.get(name,'FAIL') for name in REQUIRED_CHECKS},
                            'releaseId':release_id,'previousRelease':previous_release,'createdAt':now()}
    if detail:
        value['detail']=redact(detail)
    return value


def _write_receipt(receipts: Path, receipt: dict[str, Any]) -> None:
    path=inside(receipts, f"{receipt['id']}.json")
    if path.exists():
        return
    atomic_json(path, receipt)


def _handle_request(root: Path, exchange: Path, request_path: Path,
                    config: dict[str, Any] | None, config_error: str | None) -> dict[str, Any]:
    request_id=request_path.stem
    if not _safe_id(request_id):
        return {'id':request_id,'state':'SKIPPED_INVALID_FILENAME'}
    receipts=exchange/'receipts'; journals=exchange/'journals'
    receipt_path=receipts/f'{request_id}.json'; journal_path=journals/f'{request_id}.json'
    if receipt_path.exists():
        return {'id':request_id,'state':'SKIPPED_RECEIPT_EXISTS'}
    if journal_path.is_symlink():
        result=_receipt(request_id,'FAILED',None,{name:'FAIL' for name in REQUIRED_CHECKS},None,None,'host intent journal must not be a symbolic link')
        _write_receipt(receipts,result)
        return result
    if journal_path.exists():
        # A command may have run before a previous process died. Never replay an ambiguous action.
        try:
            request=read_json(request_path)
            expected_hash=request.get('manifestHash') if isinstance(request,dict) else None
            previous=request.get('previousRelease') if isinstance(request,dict) else None
        except (OSError, ValueError, TypeError):
            expected_hash=None;previous=None
        result=_receipt(request_id,'FAILED',expected_hash,{name:'FAIL' for name in REQUIRED_CHECKS},None,previous,
                        'prior host action journal exists without a terminal receipt; automatic replay is suppressed')
        _write_receipt(receipts,result)
        return result
    try:
        request=read_json(request_path)
        if not isinstance(request,dict) or request.get('id') != request_id:
            raise ControllerError('request filename and id do not match')
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        result=_receipt(request_id,'FAILED',None,{name:'FAIL' for name in REQUIRED_CHECKS},None,None,f'invalid request: {error}')
        _write_receipt(receipts,result)
        return result
    if config is None:
        result=_receipt(request_id,'BLOCKED_CONFIG',request.get('manifestHash'),{name:'FAIL' for name in REQUIRED_CHECKS},None,request.get('previousRelease'),config_error or 'host controller config is missing')
        _write_receipt(receipts,result)
        return result
    checks={name:'FAIL' for name in REQUIRED_CHECKS}
    manifest_hash=request.get('manifestHash') if isinstance(request.get('manifestHash'),str) else None
    previous=request.get('previousRelease') if isinstance(request.get('previousRelease'),str) else None
    journal={'id':request_id,'stage':'VALIDATING','startedAt':now(),'manifestHash':manifest_hash}
    atomic_json(journal_path,journal)
    try:
        release,manifest=_validate_release(root,request)
        release_id=manifest['id']
        values={'id':request_id,'releasePath':str(release),'manifestHash':manifest_hash or '',
                'releaseId':release_id,'previousRelease':previous or ''}
        journal.update({'stage':'DEPLOY_PENDING','releaseId':release_id,'previousRelease':previous,'updatedAt':now()})
        atomic_json(journal_path,journal)
        deploy_result=_run(_render_argv(config['deploy'],values),config['timeout'])
        if deploy_result.returncode != 0:
            failures=[redact(deploy_result.stderr or deploy_result.stdout or f'deploy command exited {deploy_result.returncode}')]
            for check in REQUIRED_CHECKS:
                checks[check]='FAIL'
            deployed=False
        else:
            deployed=True;failures=[]
            for check in REQUIRED_CHECKS:
                try:
                    outcome,detail=_run_check(check,config['verify'],config['timeout'],values,release_id)
                except ControllerError as error:
                    outcome,detail='FAIL',str(error)
                checks[check]=outcome
                if detail: failures.append(f'{check}: {detail}')
        if deployed and all(checks[name]=='PASS' for name in REQUIRED_CHECKS):
            _verify_release_immutable(release,request,manifest)
            result=_receipt(request_id,'DEPLOYED',manifest_hash,checks,release_id,previous)
            _write_receipt(receipts,result)
            journal.update({'stage':'TERMINAL','outcome':'DEPLOYED','updatedAt':now()});atomic_json(journal_path,journal)
            return result
        journal.update({'stage':'ROLLBACK_PENDING','updatedAt':now()});atomic_json(journal_path,journal)
        rollback_ok=False;rollback_detail=None
        try:
            rollback=_run(_render_argv(config['rollback'],values),config['timeout'])
            if rollback.returncode != 0:
                rollback_detail=redact(rollback.stderr or rollback.stdout or f'rollback command exited {rollback.returncode}')
            else:
                rollback_check,rollback_detail=_run_check('http',config['verify'],config['timeout'],values,previous or '')
                rollback_ok=rollback_check=='PASS'
        except ControllerError as error:
            rollback_detail=str(error)
        state='ROLLED_BACK' if rollback_ok else 'FAILED'
        detail='; '.join(failures+([f'rollback: {rollback_detail}'] if rollback_detail else [])) or ('candidate postchecks failed; trusted rollback verified' if rollback_ok else 'candidate postchecks failed and rollback could not be verified')
        result=_receipt(request_id,state,manifest_hash,checks,previous if rollback_ok else None,previous,detail)
        _write_receipt(receipts,result)
        journal.update({'stage':'TERMINAL','outcome':state,'updatedAt':now()});atomic_json(journal_path,journal)
        return result
    except (ControllerError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        # Once deployment may have started, retain a terminal failure and never auto-replay it.
        detail=redact(str(error))
        if journal.get('stage') in ('DEPLOY_PENDING','ROLLBACK_PENDING'):
            try:
                values={'id':request_id,'releasePath':str(root/'.local'/'code-releases'/request_id),
                        'manifestHash':manifest_hash or '', 'releaseId':request_id, 'previousRelease':previous or ''}
                rollback=_run(_render_argv(config['rollback'],values),config['timeout'])
                if rollback.returncode==0:
                    state_check,rollback_detail=_run_check('http',config['verify'],config['timeout'],values,previous or '')
                    if state_check=='PASS':
                        result=_receipt(request_id,'ROLLED_BACK',manifest_hash,checks,previous,previous,detail)
                        _write_receipt(receipts,result);journal.update({'stage':'TERMINAL','outcome':'ROLLED_BACK','updatedAt':now()});atomic_json(journal_path,journal)
                        return result
                    detail += '; rollback verification: '+str(rollback_detail)
                else:
                    detail += '; rollback command failed: '+redact(rollback.stderr or rollback.stdout)
            except (ControllerError, OSError, ValueError, subprocess.SubprocessError) as rollback_error:
                detail += '; rollback failed: '+redact(str(rollback_error))
        result=_receipt(request_id,'FAILED',manifest_hash,checks,None,previous,detail)
        _write_receipt(receipts,result)
        journal.update({'stage':'TERMINAL','outcome':'FAILED','updatedAt':now()});atomic_json(journal_path,journal)
        return result


def process_exchange(project_root: str | Path, exchange_directory: str | Path,
                     config_path: str | Path) -> list[dict[str, Any]]:
    root=Path(project_root).resolve()
    exchange=Path(exchange_directory).resolve()
    if not root.is_dir():
        raise ControllerError('projectRoot must be a real directory')
    for directory in (exchange,exchange/'requests',exchange/'receipts',exchange/'journals',exchange/'locks'):
        directory.mkdir(parents=True,exist_ok=True)
        if directory.is_symlink():
            raise ControllerError('exchange directories cannot be symbolic links')
    config=None;config_error=None
    try:
        config=_validate_config(root,exchange,read_json(Path(config_path)))
    except (OSError, ValueError, TypeError, ControllerError) as error:
        config_error=redact(str(error))
    lock=LivenessLock(exchange/'locks'/'host-controller.lock')
    if not lock.acquire():
        return [{'state':'LOCKED','detail':'another host controller process is alive'}]
    try:
        results=[]
        for request_path in sorted((exchange/'requests').glob('*.json')):
            if request_path.is_symlink() or not request_path.is_file():
                continue
            results.append(_handle_request(root,exchange,request_path,config,config_error))
        return results
    finally:
        lock.release()


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description='Process validated R9700 public-code release receipts')
    parser.add_argument('--root',default='.',help='project root')
    parser.add_argument('--exchange',required=True,help='operator-configured host exchange directory')
    parser.add_argument('--config',default=None,help='trusted host controller JSON config')
    args=parser.parse_args(argv)
    root=Path(args.root).resolve()
    config_path=Path(args.config).resolve() if args.config else root/'.local'/'host-controller.json'
    try:
        result=process_exchange(root,args.exchange,config_path)
    except (ControllerError, OSError) as error:
        print(json.dumps({'state':'FAILED','error':redact(str(error))},ensure_ascii=False))
        return 1
    print(json.dumps({'receipts':result},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
