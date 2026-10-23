"""Durable SQLite queue with atomic claims, leases and fenced completions."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

class QueueFull(RuntimeError):
    pass

class JobStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    run_id TEXT PRIMARY KEY, petition TEXT NOT NULL, mode TEXT NOT NULL,
                    correlation_id TEXT NOT NULL, status TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL, lease_token TEXT, result_json TEXT, error_json TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS quarantine (
                    quarantine_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, created_at REAL NOT NULL,
                    body BLOB NOT NULL, body_sha256 TEXT NOT NULL, truncated INTEGER NOT NULL,
                    errors_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workers (worker_id TEXT PRIMARY KEY, last_seen REAL NOT NULL);
            ''')

    def submit(self, petition, mode, correlation_id, capacity=100):
        now, run_id = self.clock(), str(uuid4())
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                pending = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
                if pending >= capacity:
                    raise QueueFull('Queue capacity reached')
                con.execute('INSERT INTO jobs(run_id,petition,mode,correlation_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                            (run_id, petition, mode, correlation_id, 'QUEUED', now, now))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        return run_id

    def quarantine(self, body, correlation_id, errors, truncated=False):
        identifier = str(uuid4())
        with self.connection() as con:
            con.execute('INSERT INTO quarantine VALUES(?,?,?,?,?,?,?)',
                        (identifier, correlation_id, self.clock(), body, hashlib.sha256(body).hexdigest(),
                         int(truncated), json.dumps(errors)))
        return identifier

    def get(self, run_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM jobs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result_json = result.pop('result_json')
        error_json = result.pop('error_json')
        result['result'] = json.loads(result_json) if result_json is not None else None
        result['error'] = json.loads(error_json) if error_json is not None else None
        # Internal petition and lease data are never returned by status polling.
        for key in ('petition', 'lease_token', 'lease_until'):
            result.pop(key)
        result['triage_status'] = result['result'].get('status') if result['result'] else None
        return result

    def touch_worker(self, worker_id):
        with self.connection() as con:
            con.execute('INSERT INTO workers VALUES(?,?) ON CONFLICT(worker_id) DO UPDATE SET last_seen=excluded.last_seen',
                        (worker_id, self.clock()))

    def claim(self, worker_id, lease_seconds=120, max_attempts=2):
        now = self.clock()
        token = str(uuid4())
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                con.execute("UPDATE jobs SET status='FAILED',updated_at=?,lease_token=NULL,lease_until=NULL,error_json=? WHERE status='RUNNING' AND lease_until<=? AND attempts>=?",
                            (now, json.dumps({'code': 'WORKER_LEASE_EXHAUSTED'}), now, max_attempts))
                row = con.execute("SELECT * FROM jobs WHERE status='QUEUED' OR (status='RUNNING' AND lease_until<=? AND attempts<?) ORDER BY created_at,run_id LIMIT 1",
                                  (now, max_attempts)).fetchone()
                if row is None:
                    con.commit()
                    return None
                con.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1,updated_at=?,lease_until=?,lease_token=? WHERE run_id=?",
                            (now, now + lease_seconds, token, row['run_id']))
                con.commit()
                return dict(row) | {'lease_token': token, 'worker_id': worker_id, 'attempts': row['attempts'] + 1}
            except BaseException:
                con.rollback()
                raise

    def renew(self, run_id, token, lease_seconds):
        with self.connection() as con:
            return con.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE run_id=? AND status='RUNNING' AND lease_token=?",
                               (self.clock() + lease_seconds, self.clock(), run_id, token)).rowcount == 1

    def finish(self, run_id, token, result=None, error=None):
        with self.connection() as con:
            return con.execute("UPDATE jobs SET status=?,updated_at=?,result_json=?,error_json=?,lease_until=NULL,lease_token=NULL WHERE run_id=? AND status='RUNNING' AND lease_token=?",
                               ('FAILED' if error else 'SUCCEEDED', self.clock(), json.dumps(result) if result is not None else None,
                                json.dumps(error) if error else None, run_id, token)).rowcount == 1

    def health(self):
        with self.connection() as con:
            counts = {r['status']: r['n'] for r in con.execute('SELECT status,COUNT(*) AS n FROM jobs GROUP BY status')}
            workers = con.execute('SELECT COUNT(*) FROM workers WHERE last_seen>?', (self.clock() - 15,)).fetchone()[0]
        return {'database': 'ok', 'jobs': counts, 'active_workers': workers}
