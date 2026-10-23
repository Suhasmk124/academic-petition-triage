"""Service configuration: hosted inference is intentionally unavailable through this API."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ExecutionMode = Literal['stub', 'deterministic']

@dataclass(frozen=True)
class ServiceSettings:
    db_path: Path = ROOT / 'data/runtime/service.sqlite3'
    mode: ExecutionMode = 'stub'
    queue_capacity: int = 100
    lease_seconds: float = 120
    stub_delay_seconds: float = .15
    max_body_bytes: int = 16384

    def __post_init__(self):
        if self.mode not in ('stub', 'deterministic'):
            raise ValueError('Service mode must be stub or deterministic; hosted mode is not enabled.')
        if self.queue_capacity < 1 or self.lease_seconds < 1 or not 0 <= self.stub_delay_seconds <= 10 or self.max_body_bytes < 256:
            raise ValueError('Invalid service limits')

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / '.env', override=False, encoding='utf-8-sig')
        return cls(db_path=Path(os.getenv('TRIAGE_DB_PATH') or str(ROOT / 'data/runtime/service.sqlite3')),
                   mode=os.getenv('TRIAGE_MODE', 'stub'),
                   queue_capacity=int(os.getenv('TRIAGE_QUEUE_CAPACITY', '100')),
                   lease_seconds=float(os.getenv('TRIAGE_LEASE_SECONDS', '120')),
                   stub_delay_seconds=float(os.getenv('TRIAGE_STUB_DELAY_SECONDS', '.15')))
