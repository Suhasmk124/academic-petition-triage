"""Generate local deployment secrets once. Never print their values."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
directory = root / '.secrets'
directory.mkdir(exist_ok=True)
directory.chmod(0o700)
for name in ('triage_key','grafana_key'):
    target = directory / name
    if not target.exists():
        target.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        target.chmod(0o444)
print('Deployment secrets are ready in .secrets/. Keep this folder private; each teammate generates their own.')
