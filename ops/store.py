from __future__ import annotations

import os
import ctypes
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .common import digest, dumps, now, read_json


def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:
        return False
    if os.name=='nt':
        # Python os.kill(pid, 0) is CTRL_C_EVENT on Windows, not a harmless probe.
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.GetExitCodeProcess.restype=ctypes.c_int
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel.CloseHandle.restype=ctypes.c_int
        handle=kernel.OpenProcess(0x1000,0,pid)
        if not handle:
            return ctypes.get_last_error()!=87  # uncertainty/access denial cannot evict a worker
        try:
            code=ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError,OSError):
        return True

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, url TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'MANUAL', automation_verified INTEGER NOT NULL DEFAULT 0,
 last_attempt TEXT,last_success TEXT,checkpoint TEXT,published_revision TEXT,etag TEXT,last_modified TEXT,
 retry_at TEXT,retry_count INTEGER NOT NULL DEFAULT 0,coverage_gap TEXT,policy TEXT);
CREATE TABLE IF NOT EXISTS source_fetches(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
 event_id TEXT NOT NULL,at TEXT NOT NULL,status TEXT NOT NULL,http_status INTEGER,body_hash TEXT,
 discovered INTEGER DEFAULT 0,accepted INTEGER DEFAULT 0,detail TEXT,UNIQUE(source_id,event_id));
CREATE TABLE IF NOT EXISTS content_items(id TEXT PRIMARY KEY,canonical_url TEXT UNIQUE NOT NULL,
 payload TEXT NOT NULL,content_hash TEXT NOT NULL,material_revision TEXT NOT NULL,first_seen TEXT NOT NULL,
 last_seen TEXT NOT NULL,visible INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS source_attempts(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,event_id TEXT NOT NULL,
 at TEXT NOT NULL,status TEXT NOT NULL,http_status INTEGER,detail TEXT);
CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,hash TEXT NOT NULL,
 payload TEXT NOT NULL,at TEXT NOT NULL,UNIQUE(entity_id,hash));
CREATE TABLE IF NOT EXISTS content_sources(content_id TEXT NOT NULL,source_id TEXT NOT NULL,
 claim_key TEXT NOT NULL DEFAULT 'metadata',anchor TEXT NOT NULL DEFAULT 'source',version_condition TEXT,
 evidence_hash TEXT NOT NULL,publisher_key TEXT NOT NULL,changed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(content_id,source_id,claim_key));
CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY,identity TEXT NOT NULL UNIQUE,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS price_observations(id TEXT PRIMARY KEY,offer_id TEXT NOT NULL REFERENCES offers(id),
 collection_event_id TEXT NOT NULL,payload TEXT NOT NULL,observed_at TEXT NOT NULL,UNIQUE(offer_id,collection_event_id));
CREATE TABLE IF NOT EXISTS price_corrections(id TEXT PRIMARY KEY,observation_id TEXT NOT NULL REFERENCES price_observations(id),
 replacement TEXT,reason TEXT NOT NULL,at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS price_no_update BEFORE UPDATE ON price_observations BEGIN SELECT RAISE(ABORT,'append-only prices'); END;
CREATE TRIGGER IF NOT EXISTS price_no_delete BEFORE DELETE ON price_observations BEGIN SELECT RAISE(ABORT,'append-only prices'); END;
CREATE TRIGGER IF NOT EXISTS correction_no_update BEFORE UPDATE ON price_corrections BEGIN SELECT RAISE(ABORT,'append-only corrections'); END;
CREATE TRIGGER IF NOT EXISTS correction_no_delete BEFORE DELETE ON price_corrections BEGIN SELECT RAISE(ABORT,'append-only corrections'); END;
CREATE TABLE IF NOT EXISTS compatibility_records(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,problem_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,
 evidence_hash TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS improvement_changes(id TEXT PRIMARY KEY,problem_key TEXT NOT NULL,evidence_hash TEXT NOT NULL,
 state TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS promotion_posts(id TEXT PRIMARY KEY,channel TEXT NOT NULL,account_id TEXT NOT NULL,
 content_id TEXT NOT NULL,material_revision TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL,
 sent_at TEXT,remote_id TEXT,UNIQUE(channel,account_id,content_id,material_revision));
CREATE TABLE IF NOT EXISTS generation_jobs(id TEXT PRIMARY KEY,state TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_assets(id TEXT PRIMARY KEY,payload TEXT NOT NULL,hash TEXT,rights TEXT NOT NULL,revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS showcase_items(id TEXT PRIMARY KEY,payload TEXT NOT NULL,visible INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS operation_runs(id TEXT PRIMARY KEY,slot TEXT UNIQUE,kind TEXT NOT NULL,state TEXT NOT NULL,
 started_at TEXT NOT NULL,finished_at TEXT,heartbeat TEXT NOT NULL,pid INTEGER NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS locks(name TEXT PRIMARY KEY,owner TEXT NOT NULL,pid INTEGER NOT NULL,heartbeat TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,due_at TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS costs(id TEXT PRIMARY KEY,category TEXT NOT NULL,state TEXT NOT NULL,reserved REAL NOT NULL,
 actual REAL,currency TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,at TEXT NOT NULL,hash TEXT NOT NULL,path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS processing_cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,at TEXT NOT NULL);
'''


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.local = self.root / '.local'
        self.local.mkdir(parents=True, exist_ok=True)
        self.path = self.local / 'operations.sqlite3'
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args)]

    def setting(self, key, default=None):
        import json
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, dumps(value)))

    @contextmanager
    def transaction(self):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def acquire(self, name, owner):
        with self.transaction():
            old = self.db.execute('SELECT * FROM locks WHERE name=?', (name,)).fetchone()
            if old:
                alive=process_alive(old['pid'])
                if alive:
                    return False
            self.db.execute('INSERT OR REPLACE INTO locks VALUES(?,?,?,?)', (name, owner, os.getpid(), now()))
        return True

    def release(self, name, owner):
        with self.db:
            self.db.execute('DELETE FROM locks WHERE name=? AND owner=?', (name, owner))

    def heartbeat(self, owner):
        with self.db:
            self.db.execute('UPDATE locks SET heartbeat=? WHERE owner=?', (now(), owner))
            self.db.execute('UPDATE operation_runs SET heartbeat=? WHERE id=?', (now(), owner))

    def register_sources(self, data):
        sources = data['sources']
        ids, urls = set(), set()
        for source in sources:
            if source['id'] in ids or source['url'] in urls:
                raise ValueError('duplicate source id or URL')
            ids.add(source['id']); urls.add(source['url'])
        with self.db:
            for source in sources:
                self.db.execute('INSERT INTO sources(id,url,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                                (source['id'], source['url'], dumps(source)))
        return len(sources)

    def content(self, item, source_id=None, publisher_key=None, canonical_url=None):
        """URL identifies a work; material hashes retain every actual edit, not fetch time."""
        payload = dumps(item)
        content_hash = digest(payload)
        canonical_url = canonical_url or item['sourceUrl']
        prior = self.db.execute('SELECT * FROM content_items WHERE canonical_url=?', (canonical_url,)).fetchone()
        item_id = prior['id'] if prior else item['id']
        if prior and prior['content_hash'] == content_hash:
            self.db.execute('UPDATE content_items SET last_seen=? WHERE id=?', (now(), item_id))
            return 'duplicate'
        if prior and item['id'] != item_id:
            item = {**item, 'id': item_id}
            payload = dumps(item); content_hash = digest(payload)
        # A cosmetic edit is a content revision, not permission to advertise again.
        # Re-promotion requires an explicit evidence record for a material change.
        material_revision=prior['material_revision'] if prior else content_hash
        if item.get('materialChangeEvidence'):
            material_revision=digest(item['materialChangeEvidence'])
        self.db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?,?)',
                        (digest(item_id + content_hash), item_id, content_hash, payload, now()))
        self.db.execute('INSERT INTO content_items VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,content_hash=excluded.content_hash,material_revision=excluded.material_revision,last_seen=excluded.last_seen',
                        (item_id, canonical_url, payload, content_hash, material_revision, now(), now()))
        if source_id:
            self.db.execute('UPDATE content_sources SET changed=1 WHERE source_id=? AND evidence_hash<>?', (source_id, content_hash))
            self.db.execute('INSERT OR REPLACE INTO content_sources VALUES(?,?,?,?,?,?,?,0)',
                            (item_id, source_id, 'metadata', 'source', None, content_hash, publisher_key or source_id))
        return 'revised' if prior else 'new'

    def observation(self, item):
        from .validation import validate_price
        validate_price(item)
        identity = {key: item.get(key) for key in ('productId','seller','region','currency','condition','distributor','quantity')}
        identity_hash = digest(identity)
        prior = self.db.execute('SELECT identity FROM offers WHERE id=?', (item['offerId'],)).fetchone()
        if prior and prior[0] != identity_hash:
            raise ValueError('offer identity changed; create a separate offer')
        self.db.execute('INSERT OR IGNORE INTO offers VALUES(?,?,?)', (item['offerId'], identity_hash, dumps(identity)))
        event_id = item['collectionEventId']
        result = self.db.execute('INSERT OR IGNORE INTO price_observations VALUES(?,?,?,?,?)',
                                (item['id'],item['offerId'],event_id,dumps(item),item['observedAt']))
        return result.rowcount

    def correction(self, observation_id, replacement, reason):
        from .validation import validate_price
        if not reason.strip():
            raise ValueError('correction requires a reason')
        if replacement is not None:
            validate_price(replacement)
            original = self.db.execute('SELECT offer_id,collection_event_id,payload FROM price_observations WHERE id=?', (observation_id,)).fetchone()
            if not original or replacement['id']!=observation_id or replacement['offerId'] != original[0] or replacement['collectionEventId'] != original[1]:
                raise ValueError('correction cannot change offer/event identity')
            import json
            previous=json.loads(original['payload'])
            if any(replacement.get(key)!=previous.get(key) for key in ('productId','seller','region','currency','condition','distributor','quantity')):
                raise ValueError('correction cannot change offer conditions')
        correction_id = digest([observation_id,replacement,reason])
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO price_corrections VALUES(?,?,?,?,?)',
                            (correction_id,observation_id,dumps(replacement) if replacement else None,reason,now()))
        return correction_id
