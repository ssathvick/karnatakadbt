"""Issuer-controlled data providers; wallet input never selects a source or query."""
import copy
import csv
import datetime
import decimal
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, quote

import httpx
import psycopg2
import jwt
from psycopg2.extras import RealDictCursor

from native_certify_authorization import CredentialAuthorizationFailure
from native_certify_identity_provider import exchange as identity_exchange


def json_value(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise ValueError('Unsupported provider value')


class CredentialProviders:
    def __init__(self, settings=None):
        self.settings = settings or {}

    def fetch(self, configuration, protected_claims):
        """Mappings and credentials come only from protected deployment settings.

        Pre-authorized claims preserve the deployed provider's semantics. CSV and
        SQL adapters require an explicit per-configuration mapping; a configuration
        posted through the administrative API cannot grant database/file access.
        """
        mapping = self.settings.get('configurations', {}).get(configuration['credential_config_key_id'])
        if mapping is None:
            return copy.deepcopy(protected_claims)
        try:
            subject = protected_claims[mapping['subject_claim']]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 4096:
                raise ValueError()
            if mapping['kind'] == 'csv':
                result = self.csv(mapping, subject)
            elif mapping['kind'] == 'postgres':
                result = self.postgres(mapping, subject)
            elif mapping['kind'] == 'http_registry':
                result = self.http_registry(mapping, subject)
            elif mapping['kind'] == 'oidc_userinfo':
                result = identity_exchange(mapping, protected_claims, subject,
                    allow_loopback=self.settings.get('allow_loopback_http_for_acceptance') is True)
            else:
                raise ValueError()
            if not isinstance(result, dict) or not result:
                raise ValueError()
            encoded = json.dumps(result, default=json_value, allow_nan=False)
            if len(encoded.encode()) > 512 * 1024:
                raise ValueError()
            return json.loads(encoded)
        except (ValueError, KeyError, TypeError, OSError, csv.Error, psycopg2.Error, httpx.HTTPError, jwt.PyJWTError):
            # Never expose connection details, statements, paths or identity data.
            raise CredentialAuthorizationFailure('credential_data_unavailable', status=503) from None

    def http_registry(self, mapping, subject):
        """Fixed issuer-owned registry endpoint; native signing stays local.

        Implements retained registry GET and PSUT equality-search contracts.
        Responses, headers and URLs are never chosen by wallet input. Registry
        credentials are protected configuration, not administrative API fields.
        """
        origin = urlsplit(mapping['origin'])
        test_loopback = self.settings.get('allow_loopback_http_for_acceptance') is True and origin.hostname in ['127.0.0.1', '::1']
        if origin.scheme != 'https' and not (test_loopback and origin.scheme == 'http'):
            raise ValueError()
        if not origin.netloc or origin.username or origin.password or origin.path not in ['', '/'] or origin.query or origin.fragment:
            raise ValueError()
        mode, path = mapping['mode'], mapping['path']
        if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or len(path) > 2048 or any(value in path for value in ['?', '#', '\\']):
            raise ValueError()
        body = None
        if mode == 'get':
            if path.count('{subject}') != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', subject):
                raise ValueError()
            path = path.replace('{subject}', quote(subject, safe=''))
            method = 'GET'
        elif mode == 'psut_search':
            if '{' in path or '}' in path:
                raise ValueError()
            method = 'POST'
            body = {'offset': 0, 'limit': 2, 'filters': {'psut': {'eq': subject}}}
        else:
            raise ValueError()
        headers = mapping.get('headers', {})
        if not isinstance(headers, dict) or set(name.lower() for name in headers) - {'authorization', 'x-api-key'} or any(not isinstance(value, str) or '\r' in value or '\n' in value for value in headers.values()):
            raise ValueError()
        columns = mapping['columns']
        if not isinstance(columns, list) or not columns or len(columns) > 128 or any(not isinstance(name, str) or not name for name in columns):
            raise ValueError()
        with httpx.Client(trust_env=False, timeout=5, follow_redirects=False) as client:
            with client.stream(method, origin.geturl().rstrip('/') + path, headers=headers, json=body) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError()
                raw = bytearray()
                deadline = time.monotonic() + 5
                for chunk in response.iter_bytes(chunk_size=65536):
                    raw.extend(chunk)
                    if len(raw) > 512 * 1024 or time.monotonic() > deadline:
                        raise ValueError()
        value = json.loads(raw)
        if mode == 'psut_search':
            if not isinstance(value, list) or len(value) != 1:
                raise ValueError()
            value = value[0]
        if not isinstance(value, dict):
            raise ValueError()
        return {name: value[name] for name in columns}

    def csv(self, mapping, subject):
        root = Path(self.settings['csv_root']).resolve(strict=True)
        path = Path(mapping['path']).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError()
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames
            if not fields or len(fields) != len(set(fields)) or mapping['identifier_column'] not in fields:
                raise ValueError()
            matches = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError()
                if row[mapping['identifier_column']] == subject:
                    matches.append(row)
                    if len(matches) > 1:
                        raise ValueError()
        if len(matches) != 1:
            raise ValueError()
        columns = mapping['columns']
        if not isinstance(columns, list) or not columns:
            raise ValueError()
        return {name: matches[0][name] for name in columns}

    def postgres(self, mapping, subject):
        query = mapping['query']
        # Match the retained plugin's :id binding without concatenating identity
        # values into SQL. Connections and scope/query mappings are issuer-owned.
        if not isinstance(query, str) or len(query) > 16384 or not re.match(r'^\s*SELECT\s', query, re.I):
            raise ValueError()
        if any(value in query for value in [';', '--', '/*', '%']) or len(re.findall(r'(?<!:):id\b', query)) != 1:
            raise ValueError()
        query = re.sub(r'(?<!:):id\b', '%s', query)
        connection_settings = self.settings['connections'][mapping['connection']]
        with psycopg2.connect(**connection_settings) as connection:
            connection.set_session(readonly=True)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout='3000ms'")
                cursor.execute(query, (subject,))
                rows = cursor.fetchmany(2)
                if len(rows) != 1 or len(cursor.description) != len({column.name for column in cursor.description}):
                    raise ValueError()
                columns = mapping['columns']
                if not isinstance(columns, list) or not columns:
                    raise ValueError()
                return {name: rows[0][name] for name in columns}
