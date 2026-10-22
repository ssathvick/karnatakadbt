# Native signing and SoftHSM retirement

The eSignet and mock identity services now select
`org.karnatakadbt.crypto.NativeEncryptedKeyStore` through their existing Java
key-store interface. This is an encrypted **software vault**, not a hardware HSM.
The upstream business services themselves have not been replaced.

## Production transition

- Five non-exportable legacy signing keys were replaced through controlled
  rotation. Their private material was never requested through PKCS11.
- Each service has a separate vault and wrapping key. AES-256-GCM authenticates
  vault contents with service-specific associated data. Updates lock, fsync and
  atomically replace the encrypted file.
- Historical certificates remain verification-only. Original issuer JWKS and
  certificate validity are retained. New signing aliases have distinct version
  identifiers; historical identifiers remain intact.
- eSignet cache encryption uses the existing native AES-GCM adapter exclusively.
  Legacy cache methods and fallback were removed. Both writers were fenced and
  all 16 Redis databases were empty before native-only activation. Durable key
  stores and application records requiring legacy decryption were also empty.
- The health-check AES key is a newly generated native key; it is not the old
  HSM AES key.

## Acceptance evidence

Public reports under `backend/` record adapter tests, production key recovery,
SoftHSM-off cold starts, browser login/consent/callback, token/userinfo verification,
replay rejection, and actual session persistence across restart and rollback.
All identities used for acceptance were synthetic; Aadhaar remains disabled.

`verify-native-signing-live.py` checks deployed artifact hashes, native provider
configuration, both services' health, retained JWKS, workload dependencies and
test-fixture cleanup. `verify-esignet-cache-integration.py` delegates to it when
the native signing provider is active.

## Recovery boundary

`native-signing-binary-rollback.py` supports original business JARs with explicit
native crypto compatibility plugins. Plugins provide the native SPI, cache helper,
cache codec, acceptance probe and JWKS compatibility classes. The coordinator
records every compatibility class and original artifact hash. This is not a
claim that the retired PKCS11 stack runs without SoftHSM.

During the tested rollback, both services were fenced, the committed native vaults
were restored from fresh backups, the original business artifacts were activated,
an existing native session continued, tokens were issued, and that committed
session continued after native deployment restoration. Database and Redis state
were not reverted to earlier snapshots. SoftHSM remained stopped throughout.

Native vault master keys, encrypted files, cache master/wrapped keys and manifests
are required recovery material. Preserve their current ownership and restrictive
permissions. Never regenerate an empty vault to fix a missing mount.

The stopped original HSM volume was archived and verified against source hashes
before its Deployment and Service were removed. The PVC, manifests and private
offline recovery copies remain retained. Historical archives encrypted under old
HSM keys may still require that offline material; public certificates cannot
decrypt such archives. Do not delete those recovery copies.

An old PKCS11 rollback coordinator remains as historical tooling. Do not run it
against the rotated production aliases. Use the native-compatible coordinator.
