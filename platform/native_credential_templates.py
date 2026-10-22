"""Bounded, standalone Velocity compatibility; only data crosses the process boundary."""
import base64
import json
import math
import struct
import subprocess
from pathlib import Path


class CredentialTemplateFailure(ValueError):
    pass


def string(value):
    raw = value.encode('utf-8')
    return struct.pack('>I', len(raw)) + raw


def encode(value, depth=0):
    if depth > 24:
        raise CredentialTemplateFailure('Template input too deep')
    if value is None:
        return b'\0'
    if isinstance(value, str):
        return b'\1' + string(value)
    if isinstance(value, bool):
        return b'\3' + bytes([value])
    if type(value) in [int, float] and math.isfinite(value):
        return b'\2' + string(str(value))
    if isinstance(value, list) and len(value) <= 10000:
        return b'\4' + struct.pack('>I', len(value)) + b''.join(encode(item, depth + 1) for item in value)
    if isinstance(value, dict) and len(value) <= 10000 and all(isinstance(key, str) for key in value):
        return b'\5' + struct.pack('>I', len(value)) + b''.join(string(key) + encode(item, depth + 1) for key, item in value.items())
    raise CredentialTemplateFailure('Invalid template input')


class CredentialTemplates:
    def __init__(self, settings):
        folder = Path(settings['runtime']).resolve()
        self.classpath = str(folder / 'classes') + ':' + ':'.join(str(path) for path in sorted((folder / 'lib').glob('*.jar')))

    def render(self, encoded_template, context, *, array=False):
        try:
            if not isinstance(encoded_template, str) or len(encoded_template) > 1024 * 1024:
                raise ValueError()
            template = base64.b64decode(encoded_template, validate=True).decode('utf-8')
            raw = string(template) + encode(context)
            if len(raw) > 1024 * 1024:
                raise ValueError()
            result = subprocess.run(['java', '-Xmx64m', '-Xss256k', '-Duser.timezone=UTC', '-cp', self.classpath,
                                     'NativeCredentialTemplate'], input=raw, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=5)
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise ValueError()
            document = json.loads(result.stdout)
            if not isinstance(document, list if array else dict):
                raise ValueError()
            return document
        except (ValueError, TypeError, OSError, subprocess.SubprocessError):
            raise CredentialTemplateFailure('invalid_credential_template') from None
