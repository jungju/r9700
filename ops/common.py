from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp must include timezone')
    return result


def next_slot(value: str | None = None) -> str:
    dt = parse_time(value or now()).astimezone(KST)
    slot = dt.replace(hour=dt.hour // 6 * 6, minute=0, second=0, microsecond=0)
    return (slot + timedelta(hours=6)).isoformat()


def current_slot(value: str | None = None) -> str:
    dt = parse_time(value or now()).astimezone(KST)
    return dt.replace(hour=dt.hour // 6 * 6, minute=0, second=0, microsecond=0).isoformat()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value) -> str:
    if not isinstance(value, bytes):
        value = (value if isinstance(value, str) else dumps(value)).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with tmp.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(dumps(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def redact(text: str) -> str:
    text = re.sub(r'(?i)(?:bearer\s+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*)\S+', '[REDACTED]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)
    text = re.sub(r'(?:[A-Za-z]:\\|/home/|/Users/)[^\s]+', '[PATH]', text)
    return text[:2000]


def inside(root: Path, path: str | Path) -> Path:
    root = root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError('path escapes configured root')
    return target
