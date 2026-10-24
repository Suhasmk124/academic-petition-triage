"""Optional shared-team API key with expiring HttpOnly browser sessions."""
import hashlib
import hmac
import secrets
import time
from runtime_config import secret


def key_matches(candidate):
    configured = secret()
    return bool(configured and candidate and hmac.compare_digest(configured, candidate))


def session_cookie():
    payload = f'{int(time.time())}.{secrets.token_hex(16)}'
    signature = hmac.new(secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature


def authenticated(request):
    if not secret():
        return True
    authorization = request.headers.get('authorization', '')
    if authorization.startswith('Bearer ') and key_matches(authorization[7:]):
        return True
    cookie = request.cookies.get('triage_session', '')
    try:
        timestamp, nonce, signature = cookie.split('.')
        age = time.time()-int(timestamp)
        expected = hmac.new(secret().encode(), f'{timestamp}.{nonce}'.encode(), hashlib.sha256).hexdigest()
        return 0 <= age <= 3600 and hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        return False
