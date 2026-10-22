"""Hold native ownership until the complete ASGI response has finished."""
from pathlib import Path
import json
import hashlib
import re
import anyio
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from native_administration_ownership import AdministrationOwnership
from registry_native_write_capture import bind_engine


def configure_writer(engine, settings, profile):
    """No writable runtime without a private, persistent recovery credential."""
    if settings.get('business_writes_enabled') is not True:
        return None
    if settings.get('writer_ownership_scope') != profile:
        raise ValueError('Explicit administration ownership scope required')
    path = Path(settings['native_recovery_settings_path'])
    if path.stat().st_mode & 0o077:
        raise ValueError('Administration recovery settings must be private')
    recovery = json.loads(path.read_text())
    key = recovery['capture_key']
    if recovery.get('complete') is not True or recovery.get('profile') != profile:
        raise ValueError('Completed matching administration recovery required')
    schema = recovery['capture_schema']
    if not re.fullmatch('kdbt_admin_'+profile+'_native_capture', schema):
        raise ValueError('Pinned administration capture schema required')
    with engine.connect() as connection:
        database = connection.execute(text('SELECT current_database()')).scalar_one()
        source = connection.execute(text('SELECT source_id::text FROM kdbt_administration_control.ownership WHERE profile=:profile'), {'profile': profile}).scalar_one()
        digest = connection.execute(text('SELECT key_digest FROM '+schema+'.control WHERE singleton')).scalar_one()
    if database != recovery['native_identity']['database'] or source != recovery['source_id'] or digest != hashlib.sha256(key.encode()).hexdigest():
        raise ValueError('Administration recovery identity or key differs')
    if profile == 'iam' and not settings.get('identity_recovery_settings_path'):
        raise ValueError('Recoverable identity effects required for writable IAM')
    bind_engine(engine, key, writer='native-api')
    return AdministrationOwnership(engine, profile)


class AdministrationWriterAdmission:
    """Gate reads too: consent GETs can commit expiry and audit records.

    A pure ASGI wrapper retains the lock through streaming response completion
    and background work, rather than releasing it after response headers.
    """
    def __init__(self, app, ownership):
        self.app, self.ownership = app, ownership

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') == '/health':
            return await self.app(scope, receive, send)
        guard = self.ownership.admission('NATIVE')
        try:
            await run_in_threadpool(guard.__enter__)
        except ValueError:
            return await JSONResponse(
                {'error': 'Native administration writer ownership is fenced'},
                status_code=503, headers={'cache-control': 'no-store', 'retry-after': '5'}
            )(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            # Business exceptions must still release the admission transaction.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(guard.__exit__, None, None, None)
