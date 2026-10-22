"""Durable maintenance barrier shared by remaining-three runtime transports."""
from pathlib import Path

MARKER = Path('/opt/karnatakadbt/private/mosip-migration/remaining-three/production-cutover/producer-fence.json')


def active():
    # Any marker blocks traffic, including a malformed marker. Only its owning
    # runtime adapter may validate and remove it after observed restoration.
    return MARKER.exists() or MARKER.is_symlink()
