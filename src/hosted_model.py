"""Hosted chat adapter with opt-in free-plan confirmation and bounded HTTP attempts."""
import os
import json
import math
import re
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
        self.token_remaining = None
        self.token_limit = None
        self.token_reset_at = 0.0

    def close(self):
        self.client.close()

    def complete(self, role, messages, tools):
        if self.clock() < self.open_until:
            raise ModelUnavailable('Model circuit is temporarily open.')
        first_action = not any(message.get('role')=='tool' for message in messages)
        choice = 'required' if first_action and tools and os.getenv('LLM_FORCE_TOOL_START','false')=='true' else 'auto'
        body = dict(model=self.settings.model, messages=messages,
                    tools=tools, tool_choice=choice, max_completion_tokens=self.settings.max_output_tokens)
        if os.getenv('LLM_REASONING_EFFORT'):
            body['reasoning_effort']=os.environ['LLM_REASONING_EFFORT']
        body['parallel_tool_calls']=False
        started = self.clock()
        estimated_tokens = math.ceil(len(json.dumps(body)) / 4) + self.settings.max_output_tokens
        pacing_seconds = 0.0
        if self.token_limit is not None and estimated_tokens > self.token_limit:
            raise ModelUnavailable('Request estimate exceeds the free token limit; reduce context/output size.')
        if self.token_remaining is not None and estimated_tokens > self.token_remaining:
            pacing_seconds = max(0.0, self.token_reset_at - self.clock()) + 1.0
            if pacing_seconds > 65:
                raise ModelUnavailable('Free token window requires a longer pause; retry later.')
            self.sleep(pacing_seconds)
            self.token_remaining = None
        for attempt in range(2):
            event = dict(agent=role, attempt=attempt + 1, success=False,
                         input_tokens=None, output_tokens=None, billed_cost_usd=None, pacing_seconds=round(pacing_seconds, 3))
            try:
                response = self.client.post(self.settings.base_url.rstrip('/') + '/chat/completions',
                                            headers={'Authorization': 'Bearer ' + self.settings.api_key},
                                            json=body, timeout=self.settings.timeout)
                event['http_status'] = response.status_code
                self._rate_headers(response.headers)
                # Do not retry free-quota exhaustion or switch provider/model automatically.
                if response.status_code == 429:
                    raise ModelUnavailable('Free quota/rate limit reached; no paid fallback was attempted.')
                if response.status_code in (500, 502, 503, 504) and attempt == 0:
                    event['latency_seconds'] = self.clock() - started
                    self.events.append(event)
                    self.sleep(.5)
                    continue
                if response.status_code != 200:
                    try:
                        error = response.json().get('error', {})
                        event['provider_error_code'] = str(error.get('code', ''))[:100]
                        event['provider_error_type'] = str(error.get('type', ''))[:100]
                        event['provider_error_message'] = str(error.get('message', '')).replace(self.settings.api_key, '[REDACTED]')[:600]
                    except (ValueError, AttributeError):
                        pass
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

    def _rate_headers(self, headers):
        try:
            self.token_remaining = int(headers['x-ratelimit-remaining-tokens'])
            self.token_limit = int(headers['x-ratelimit-limit-tokens'])
            duration = headers.get('x-ratelimit-reset-tokens', '0s')
            matches = re.findall(r'([0-9.]+)(ms|s|m|h)', duration)
            seconds = sum(float(number) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600}[unit]
                          for number, unit in matches)
            self.token_reset_at = self.clock() + seconds
        except (KeyError, ValueError, TypeError):
            self.token_remaining = None

    def _failure(self):
        self.failures += 1
        if self.failures >= 3:
            self.open_until = self.clock() + 30
