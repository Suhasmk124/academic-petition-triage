"""Shared TTL cache and fixed-window rate limit; SQLite or optional Redis."""
import hashlib
import json
import os
import time
from pathlib import Path


def cache_key(petition, mode):
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256((petition.strip() + '\0' + mode).encode())
    for path in [root / 'data/processed/handbook_pages.json', *sorted((root / 'prompts').glob('*.txt')), *sorted((root/'src').glob('*.py'))]:
        digest.update(path.read_bytes())
    return digest.hexdigest()


class Operations:
    def __init__(self, store):
        self.store = store
        self.redis = None
        url = os.getenv('REDIS_URL')
        if url:
            from redis import Redis
            self.redis = Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)

    def allow(self, identity, maximum, window=60):
        if maximum <= 0:
            return True
        bucket = int(self.store.clock() // window)
        key = 'rate:' + hashlib.sha256(identity.encode()).hexdigest() + ':' + str(bucket)
        if self.redis:
            # Both operations are atomic together. Redis failure is surfaced, never a bypass.
            count = self.redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", 1, key, window * 2)
        else:
            with self.store.connection() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('DELETE FROM limits WHERE expires_at<?', (self.store.clock(),))
                con.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, (bucket+2)*window))
                count = con.execute('SELECT count FROM limits WHERE key=?', (key,)).fetchone()[0]
                con.commit()
        return count <= maximum

    def cached(self, key):
        if not key:
            return None
        if self.redis:
            try:
                value = self.redis.get('cache:' + key)
                return json.loads(value) if value else None
            except Exception:
                return None
        with self.store.connection() as con:
            row = con.execute('SELECT result_json FROM cache WHERE key=? AND expires_at>?', (key, self.store.clock())).fetchone()
        return json.loads(row['result_json']) if row else None

    def cache(self, key, value, ttl):
        if not key or ttl <= 0 or value.get('status') != 'REVIEW_REQUIRED' or value.get('safety', {}).get('output') != 'passed':
            return
        payload = json.dumps(value)
        if self.redis:
            try:
                self.redis.setex('cache:' + key, ttl, payload)
            except Exception:
                pass  # Cache is optional; the completed durable result remains authoritative.
        else:
            with self.store.connection() as con:
                con.execute('DELETE FROM cache WHERE expires_at<?', (self.store.clock(),))
                con.execute('INSERT INTO cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET result_json=excluded.result_json,expires_at=excluded.expires_at',
                            (key, payload, self.store.clock()+ttl))
