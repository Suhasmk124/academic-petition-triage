"""Validate the upload envelope; file contents are for human review only."""
import base64
import binascii

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 4 * ((MAX_FILE_BYTES + 2) // 3) + 64 * 1024


def decode_attachment(encoded):
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid attachment encoding') from exc
    if not 0 < len(content) <= MAX_FILE_BYTES:
        raise ValueError('Invalid attachment size')
    for prefix, extension in ((b'%PDF-', 'pdf'), (b'\x89PNG\r\n\x1a\n', 'png'), (b'\xff\xd8\xff', 'jpg')):
        if content.startswith(prefix):
            return extension, content
    raise ValueError('Unsupported attachment type')


def hosted_policy_query(category):
    """Only these fixed policy questions may leave the private workspace."""
    return {
        'ATTENDANCE': 'What are the attendance threshold, CMO certification requirements, and SLCM medical leave deadline?',
        'TERMINAL_MEDICAL': 'What rules apply to a terminal exam missed due to illness, including medical leave and the X-grade process?',
        'X_GRADE': 'What are the handbook rules on X grade eligibility, retest deadlines, and summer term restrictions?',
    }.get(category)
