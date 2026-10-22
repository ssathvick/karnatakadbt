"""Private, bounded HTTP transport for durable presentation recovery.

The capability is a deployment secret. This listener binds loopback only and
must never be reverse-proxied onto a public issuer or registration route.
"""
import hmac
import json
import logging
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from native_certify_authorization import CredentialAuthorizationFailure
from native_remaining_three_fence import active as producers_fenced


def recovery_server(core, capability, *, port=18151):
    if not isinstance(capability, str) or not re.fullmatch(r'[A-Za-z0-9_-]{48,128}', capability):
        raise ValueError('Strong private recovery capability required')
    lock = threading.Lock()
    counters = {'accepted': 0, 'rejected': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            self.wfile.write(raw)

        def route(self):
            parsed = urlsplit(self.path)
            parts = parsed.path.split('/')
            try:
                valid = len(parts) >= 3 and hmac.compare_digest(parts[1].encode('ascii'), capability.encode('ascii'))
            except UnicodeError:
                valid = False
            if parsed.query or parsed.fragment or not valid:
                self.respond(404, {'error': 'not_found'})
                return None
            if producers_fenced():
                self.respond(503, {'error': 'temporarily_unavailable'})
                return None
            return '/'.join(parts[2:])

        def do_POST(self):
            route = self.route()
            if route is None:
                return
            try:
                if route != 'submit':
                    self.respond(404, {'error': 'not_found'})
                    return
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ValueError()
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
                    raise ValueError()
                size = int(self.headers['Content-Length'])
                if not 0 < size <= 768 * 1024:
                    raise ValueError()
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError()
                data = parse_qs(raw.decode('utf-8'), strict_parsing=True, keep_blank_values=True, max_num_fields=3)
                if set(data) != {'state', 'vp_token', 'presentation_submission'} or any(len(v) != 1 or not v[0] for v in data.values()):
                    raise ValueError()
                core.submit(data['state'][0], data['vp_token'][0], data['presentation_submission'][0])
                with lock:
                    counters['accepted'] += 1
                self.respond(200, {'accepted': True})
            except (ValueError, UnicodeError, KeyError, CredentialAuthorizationFailure, socket.timeout) as error:
                category=getattr(error,'error',type(error).__name__)
                if category not in {'invalid_session','invalid_presentation','invalid_presentation_submission','ValueError','UnicodeDecodeError','KeyError','TimeoutError'}:
                    category='rejected'
                logging.getLogger(__name__).warning('Private recovery submission rejected: %s',category)
                with lock:
                    counters['rejected'] += 1
                self.respond(400, {'error': 'invalid_presentation'})

        def do_GET(self):
            route = self.route()
            if route is None:
                return
            if not route.startswith('result/') or route.count('/') != 1:
                self.respond(404, {'error': 'not_found'})
                return
            try:
                self.respond(200, core.result(route[7:]))
            except (ValueError, CredentialAuthorizationFailure):
                self.respond(400, {'error': 'invalid_session'})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False
        request_queue_size = 16
        slots = threading.BoundedSemaphore(8)

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

        def handle_error(self, request, client_address):
            # Never log a callback path, capability, presentation or identity.
            pass

    server = Server(('127.0.0.1', port), Handler)
    server.recovery_counters = counters
    return server


if __name__ == '__main__':
    import os
    from pathlib import Path
    from native_certify_service import build
    from native_certify_presentation_recovery import PresentationRecovery

    path = Path(os.environ['KDBT_CERTIFY_RECOVERY_SETTINGS'])
    settings = json.loads(path.read_text())
    app = build(json.loads(Path(settings['certify_settings']).read_text()))
    server = recovery_server(PresentationRecovery(app.state.interactive),
                             Path(settings['capability_file']).read_text().strip(), port=settings['port'])
    server.serve_forever()
