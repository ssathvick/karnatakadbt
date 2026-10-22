"""Lossless, conflict-rejecting merge of compatible encrypted signing vaults."""
from contextlib import ExitStack
from pathlib import Path

from native_auth_signing import NativeSigningAuthority


def merge_signing_vault(source_settings, destination_settings):
    if source_settings['scope'] != destination_settings['scope']:
        raise ValueError('Signing scopes differ')
    source, destination = NativeSigningAuthority(source_settings), NativeSigningAuthority(destination_settings)
    paths = [Path(source_settings['directory']).resolve(), Path(destination_settings['directory']).resolve()]
    if paths[0] == paths[1]:
        raise ValueError('Distinct signing authorities required')
    with ExitStack() as stack:
        locked = {}
        for path, authority in sorted(zip(paths, [source, destination]), key=lambda item: str(item[0])):
            locked[path] = stack.enter_context(authority.locked())
        incoming, retained = locked[paths[0]], locked[paths[1]]
        common = set(incoming) & set(retained)
        if any(incoming[key] != retained[key] for key in common):
            raise ValueError('Signing material conflict; rotation requires explicit reconciliation')
        combined = {**retained, **incoming}
        destination.write(combined)
        if destination.read() != combined:
            raise ValueError('Signing vault merge verification failed')
        return {'source_entries': len(incoming), 'retained_entries': len(retained),
                'merged_entries': len(combined), 'added_entries': len(set(incoming) - set(retained)),
                'existing_entries_preserved': True}
