"""Production admission requires a protected, release-bound handoff receipt."""
import hashlib
import json
from pathlib import Path


REQUIRED = ('feature_acceptance', 'live_administrator_authentication', 'production_callbacks',
            'fenced_state_export', 'reverse_state_projection', 'coordinated_rollback_rehearsal',
            'writer_worker_fencing', 'restorable_backups')
ROOT = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three/production-cutover')


def release_hashes(directory):
    files = {path.name: path for pattern in ['*.py']
             for path in Path(directory).glob(pattern)}
    for path in (Path(directory)/'credential-console').glob('*'):
        if path.is_file():files['credential-console/'+path.name]=path
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}


def admit(settings, directory):
    mode = settings.get('environment')
    from native_remaining_three_rehearsal import admission
    rehearsal = admission(settings, directory, 'certify')
    if rehearsal:
        if not settings.get('staff_administrator') or not all(settings.get(k) for k in ['business', 'authorization', 'issuance']):
            raise ValueError('Complete native credential runtime required for rehearsal')
        return rehearsal
    if mode == 'CANDIDATE':
        return
    if mode != 'NATIVE' or not settings.get('staff_administrator') or not all(settings.get(k) for k in ['business', 'authorization', 'issuance']):
        raise ValueError('Explicit complete native credential runtime required')
    if not isinstance(settings.get('activation_receipt'), str):
        raise ValueError('Protected production handoff receipt required')
    try:
        path = Path(settings['activation_receipt']).resolve(strict=True)
        if not path.is_relative_to(ROOT) or path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
            raise ValueError('Private root-owned production receipt required')
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or not isinstance(receipt.get('checks'), dict):
            raise ValueError('Structured production handoff receipt required')
        if receipt.get('component') != 'certify' or type(receipt.get('generation')) is not int or receipt['generation'] < 1:
            raise ValueError('Explicit handoff generation required')
        if not all(receipt.get('checks', {}).get(name) is True for name in REQUIRED):
            raise ValueError('Incomplete production handoff acceptance')
        if receipt.get('release_sha256') != release_hashes(directory):
            raise ValueError('Production acceptance does not match deployed release')
        selected = {key: value for key, value in settings.items() if key != 'activation_receipt'}
        fingerprint = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if receipt.get('settings_sha256') != fingerprint:
            raise ValueError('Production acceptance does not match runtime settings')
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('Invalid production handoff receipt') from error
