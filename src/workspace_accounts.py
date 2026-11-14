"""Local role credentials. The workspace key bootstraps the administrator."""
import base64
import hashlib
import hmac
import json
import secrets
import time


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                        n=16384, r=8, p=1).hex()


def verify_password(password, encoded):
    salt = encoded.split(':', 1)[0]
    return hmac.compare_digest(password_hash(password, salt), encoded)


def issue_session(username, key):
    payload = base64.urlsafe_b64encode(json.dumps([username, int(time.time())]).encode()).decode()
    return payload + '.' + hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def session_user(token, key):
    try:
        payload, signature = token.split('.', 1)
        expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        username, issued = json.loads(base64.urlsafe_b64decode(payload))
        if isinstance(username, str) and 0 <= time.time()-issued <= 3600:
            return username
    except (ValueError, TypeError):
        pass
    return None
