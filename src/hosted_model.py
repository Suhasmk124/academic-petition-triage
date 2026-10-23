"""Hosted chat adapter with opt-in free-plan confirmation and bounded HTTP attempts."""
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv

class ModelUnavailable(RuntimeError):
    pass

@dataclass
class HostedSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    free_plan_confirmed: bool = False
    timeout: float = 30
    max_output_tokens: int = 1800

    def __post_init__(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelUnavailable('Configure a valid HTTPS LLM_BASE_URL without embedded credentials.')
        if not self.model.strip() or not self.api_key.strip() or not self.free_plan_confirmed:
            raise ModelUnavailable('Set model/key and confirm the account is on its Free Plan in .env.')
        if not 1 <= self.timeout <= 120 or not 128 <= self.max_output_tokens <= 4096:
            raise ModelUnavailable('Invalid model timeout/output token cap.')

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False, encoding='utf-8-sig')
        try:
            return cls(base_url=os.getenv('LLM_BASE_URL', ''), model=os.getenv('LLM_MODEL', ''),
                       api_key=os.getenv('LLM_API_KEY', ''),
                       free_plan_confirmed=os.getenv('LLM_FREE_PLAN_CONFIRMED', '').lower() == 'true',
                       timeout=float(os.getenv('LLM_TIMEOUT_SECONDS', '30')),
                       max_output_tokens=int(os.getenv('LLM_MAX_OUTPUT_TOKENS', '1800')))
        except ValueError as exc:
            raise ModelUnavailable('Model configuration contains invalid numeric limits.') from exc

class HostedChat:
    def __init__(self, settings, client=None, sleep=time.sleep, clock=time.monotonic):
        self.settings, self.sleep, self.clock = settings, sleep, clock
        self.client = client or httpx.Client(timeout=settings.timeout, follow_redirects=False)
        self.events = []
        self.failures = 0
        self.open_until = 0.0

    def close(self):
        self.client.close()

    def complete(self, role, messages, tools):
        if self.clock() < self.open_until:
            raise ModelUnavailable('Model circuit is temporarily open.')
        body = dict(model=self.settings.model, messages=messages,
                    tools=tools, tool_choice='auto', max_completion_tokens=self.settings.max_output_tokens)
        started = self.clock()
        for attempt in range(2):
            event = dict(agent=role, attempt=attempt + 1, success=False,
                         input_tokens=None, output_tokens=None, billed_cost_usd=None)
            try:
                response = self.client.post(self.settings.base_url.rstrip('/') + '/chat/completions',
                                            headers={'Authorization': 'Bearer ' + self.settings.api_key},
                                            json=body, timeout=self.settings.timeout)
                event['http_status'] = response.status_code
                # Do not retry free-quota exhaustion or switch provider/model automatically.
                if response.status_code == 429:
                    raise ModelUnavailable('Free quota/rate limit reached; no paid fallback was attempted.')
                if response.status_code in (500, 502, 503, 504) and attempt == 0:
                    event['latency_seconds'] = self.clock() - started
                    self.events.append(event)
                    self.sleep(.5)
                    continue
                if response.status_code != 200:
                    raise ModelUnavailable(f'Model request failed with HTTP {response.status_code}.')
                data = response.json()
                choice = data['choices'][0]
                if choice.get('finish_reason') in ('length', 'content_filter'):
                    raise ModelUnavailable('Model response was truncated or filtered.')
                message = choice['message']
                if message.get('refusal'):
                    raise ModelUnavailable('Model refused the request.')
                usage = data.get('usage') or {}
                event.update(success=True, input_tokens=usage.get('prompt_tokens'),
                             output_tokens=usage.get('completion_tokens'),
                             latency_seconds=self.clock() - started)
                self.events.append(event)
                self.failures = 0
                return {'role': 'assistant', 'content': message.get('content'),
                        **({'tool_calls': message['tool_calls']} if message.get('tool_calls') else {})}
            except (httpx.TimeoutException, httpx.TransportError):
                event['latency_seconds'] = self.clock() - started
                self.events.append(event)
                if attempt == 0:
                    self.sleep(.5)
                    continue
                break
            except (ModelUnavailable, ValueError, KeyError, IndexError, TypeError) as exc:
                event['latency_seconds'] = self.clock() - started
                self.events.append(event)
                self._failure()
                if isinstance(exc, ModelUnavailable):
                    raise
                raise ModelUnavailable('Malformed model response.') from exc
        self._failure()
        raise ModelUnavailable('Model transport failed after two attempts.')

    def _failure(self):
        self.failures += 1
        if self.failures >= 3:
            self.open_until = self.clock() + 30
