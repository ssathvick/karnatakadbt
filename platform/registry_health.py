"""Explicit public GET liveness contract; no beneficiary or operational data."""
import json
from pathlib import Path
from registry_route_auth import required_permissions

HEALTH_PATHS=frozenset(['/ping'])

def install_health(app):
    contract=json.loads(Path(__file__).with_name('registry_full_contract.json').read_text())
    required_permissions('/ping',contract,method='GET')
    # Public liveness is intentionally independent of business audit/database
    # availability, matching the existing service's literal pong response.
    @app.get('/ping',tags=['ping'],summary='Get Ping',operation_id='get_ping_ping_get')
    def get_ping():return 'pong'
