"""Bounded transport retries and a reusable circuit breaker for the stub service."""
import time
import httpx
from runtime_config import secret
from telemetry import carrier


class ServiceUnavailable(RuntimeError):
    pass


class StubClient:
    def __init__(self, url, timeout=60, transport=None, clock=time.monotonic, sleep=time.sleep):
        self.url, self.timeout, self.clock, self.sleep = url, timeout, clock, sleep
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
        self.failures, self.open_until, self.attempts = 0, 0, 0

    def run(self, petition):
        if self.clock() < self.open_until:
            raise ServiceUnavailable('CIRCUIT_OPEN')
        for attempt in range(2):
            self.attempts += 1
            try:
                headers = {'Authorization':'Bearer '+secret()} if secret() else {}
                if carrier(): headers['traceparent'] = carrier()
                response = self.client.post(self.url.rstrip('/')+'/generate', json={'petition':petition}, headers=headers)
                if response.status_code == 200:
                    result = response.json()
                    if not isinstance(result,dict): raise ValueError('Invalid response')
                    self.failures = 0
                    return result
                if response.status_code not in (500,502,503,504):
                    break
            except (httpx.TransportError, ValueError):
                pass
            if attempt == 0:
                self.sleep(.25 * 2**attempt)
        self.failures += 1
        if self.failures >= 3:
            self.open_until = self.clock()+30
        raise ServiceUnavailable('STUB_UNAVAILABLE')
