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


class FeedbackUnavailable(ValueError):
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
                CREATE TABLE IF NOT EXISTS workspace_accounts (
                    username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS officer_reviews (
                    run_id TEXT PRIMARY KEY REFERENCES jobs(run_id), reviewer TEXT NOT NULL,
                    outcome TEXT NOT NULL, note TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    run_id TEXT PRIMARY KEY REFERENCES jobs(run_id),
                    extension TEXT NOT NULL, content BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workers (worker_id TEXT PRIMARY KEY, last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS feedback (
                    run_id TEXT PRIMARY KEY REFERENCES jobs(run_id), rating TEXT NOT NULL,
                    category TEXT NOT NULL, comment TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, result_json TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at REAL NOT NULL);
            ''')
            columns = {row['name'] for row in con.execute('PRAGMA table_info(jobs)')}
            for name in ('traceparent', 'cache_key', 'facts_json', 'private_record', 'owner'):
                if name not in columns:
                    con.execute(f'ALTER TABLE jobs ADD COLUMN {name} TEXT')

    def submit(self, petition, mode, correlation_id, capacity=100, traceparent=None, cache_key=None, facts=None, private_record=False, attachment=None, owner=None):
        now, run_id = self.clock(), str(uuid4())
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                pending = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
                if pending >= capacity:
                    raise QueueFull('Queue capacity reached')
                con.execute('INSERT INTO jobs(run_id,petition,mode,correlation_id,status,created_at,updated_at,traceparent,cache_key,facts_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (run_id, petition, mode, correlation_id, 'QUEUED', now, now, traceparent, cache_key, json.dumps(facts) if facts else None))
                if private_record:
                    con.execute("UPDATE jobs SET private_record='1',owner=? WHERE run_id=?", (owner,run_id))
                if attachment is not None:
                    con.execute('INSERT INTO attachments VALUES(?,?,?)', (run_id, *attachment))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        return run_id

    def create_account(self, username, role, password_hash):
        with self.connection() as con:
            return con.execute('INSERT OR IGNORE INTO workspace_accounts VALUES(?,?,?)',
                               (username,role,password_hash)).rowcount==1

    def account(self, username):
        with self.connection() as con:
            row=con.execute('SELECT role,password_hash FROM workspace_accounts WHERE username=?',(username,)).fetchone()
        return dict(row) if row else None

    def owns_run(self, run_id, username):
        with self.connection() as con:
            return con.execute('SELECT 1 FROM jobs WHERE run_id=? AND owner=?',(run_id,username)).fetchone() is not None

    def private_cases(self, owner=None):
        scope="j.private_record='1'" if owner is None else "j.private_record='1' AND j.owner=?"
        with self.connection() as con:
            rows=con.execute(
                'SELECT j.run_id,j.status,j.created_at,r.outcome FROM jobs j LEFT JOIN officer_reviews r ON j.run_id=r.run_id WHERE '
                + scope + ' ORDER BY (r.run_id IS NOT NULL), j.created_at DESC LIMIT 100',
                () if owner is None else (owner,)).fetchall()
        return [dict(row) for row in rows]

    def officer_review(self, run_id):
        with self.connection() as con:
            row=con.execute('SELECT reviewer,outcome,note,updated_at FROM officer_reviews WHERE run_id=?',(run_id,)).fetchone()
        return dict(row) if row else None

    def record_officer_review(self, run_id, reviewer, outcome, note):
        with self.connection() as con:
            return con.execute(
                """INSERT INTO officer_reviews SELECT run_id,?,?,?,? FROM jobs
                   WHERE run_id=? AND private_record='1' AND status IN ('SUCCEEDED','FAILED')
                   ON CONFLICT(run_id) DO UPDATE SET reviewer=excluded.reviewer,outcome=excluded.outcome,
                   note=excluded.note,updated_at=excluded.updated_at""",
                (reviewer,outcome,note,self.clock(),run_id)).rowcount==1

    def attachment(self, run_id):
        with self.connection() as con:
            row = con.execute('SELECT extension,content FROM attachments WHERE run_id=?',(run_id,)).fetchone()
        return tuple(row) if row else None

    def delete_attachment(self, run_id):
        with self.connection() as con:
            return con.execute('DELETE FROM attachments WHERE run_id=?',(run_id,)).rowcount == 1

    def quarantine(self, body, correlation_id, errors, truncated=False):
        identifier = str(uuid4())
        with self.connection() as con:
            con.execute('INSERT INTO quarantine VALUES(?,?,?,?,?,?,?)',
                        (identifier, correlation_id, self.clock(), body, hashlib.sha256(body).hexdigest(),
                         int(truncated), json.dumps(errors)))
        return identifier

    def get(self, run_id, include_private_text=False):
        with self.connection() as con:
            row = con.execute('SELECT jobs.*, EXISTS(SELECT 1 FROM attachments WHERE attachments.run_id=jobs.run_id) AS attachment_available FROM jobs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result_json = result.pop('result_json')
        error_json = result.pop('error_json')
        result['result'] = json.loads(result_json) if result_json is not None else None
        result['error'] = json.loads(error_json) if error_json is not None else None
        if include_private_text and result['private_record']:
            result['private_petition'] = result['petition']
            facts=json.loads(result['facts_json'] or '{}')
            result['attendance_percent']=facts.get('attendance_percent')
            result['officer_review']=self.officer_review(run_id)
        # Other internal petition and lease fields are never returned.
        for key in ('petition', 'lease_token', 'lease_until', 'traceparent', 'cache_key', 'facts_json', 'private_record','owner'):
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

    def save_feedback(self, run_id, rating, category, comment):
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row = con.execute('SELECT status FROM jobs WHERE run_id=?', (run_id,)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                if row['status'] != 'SUCCEEDED':
                    raise FeedbackUnavailable('Feedback requires a completed run')
                con.execute('INSERT INTO feedback VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET rating=excluded.rating,category=excluded.category,comment=excluded.comment,updated_at=excluded.updated_at',
                            (run_id, rating, category, comment, self.clock()))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        return self.get_feedback(run_id)

    def get_feedback(self, run_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM feedback WHERE run_id=?', (run_id,)).fetchone()
        return dict(row) if row else None

    def quality_samples(self, limit=20):
        """Prioritize failures/escalations/negative feedback, then stable hash sample.

        Return metadata only; never raw petitions, quotes or free-text comments.
        """
        with self.connection() as con:
            rows = con.execute("SELECT j.run_id,j.status,j.mode,j.created_at,j.result_json,f.rating,f.category FROM jobs j LEFT JOIN feedback f ON j.run_id=f.run_id WHERE j.status IN ('SUCCEEDED','FAILED')").fetchall()
        samples = []
        for row in rows:
            result = json.loads(row['result_json']) if row['result_json'] else {}
            reasons = []
            if row['status'] == 'FAILED':
                reasons.append('workflow_failed')
            if result.get('status') == 'ESCALATE':
                reasons.append('escalated')
            if row['rating'] == 'needs_review':
                reasons.append('negative_feedback')
            if result.get('safety', {}).get('output') == 'blocked':
                reasons.append('output_blocked')
            bucket = int(hashlib.sha256(row['run_id'].encode()).hexdigest()[:8], 16)
            if reasons or bucket % 10 == 0:
                samples.append(dict(run_id=row['run_id'], status=row['status'], mode=row['mode'],
                                    triage_status=result.get('status'), rating=row['rating'], category=row['category'],
                                    reasons=reasons or ['stable_10_percent_sample'], created_at=row['created_at']))
        samples.sort(key=lambda item: (not any(reason != 'stable_10_percent_sample' for reason in item['reasons']), -item['created_at'], item['run_id']))
        return samples[:limit]
