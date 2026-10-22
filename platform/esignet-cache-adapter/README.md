# Transitional eSignet cache adapter

This adapter modifies the two individual-identifier encryption methods in the
retained eSignet 1.4.1 Java service. It is an integration bridge, not a replacement
for eSignet, its login UI, or the remaining MOSIP services.

New writes use AES-256-GCM with a random 96-bit nonce and an authenticated role
binding. `KDBTCACHE1.` identifies the new format. The existing method signature
does not carry a session identifier, so this Java envelope is role-bound, not
bound to an individual Redis key. Legacy ciphertext is read using the original
HSM method. Authentication failures in native envelopes fail closed; they never
fall back to legacy decryption.

`PatchCacheHelper.java` performs a pinned build-time transformation. It preserves
the original methods and adds format-dispatch wrappers. JDK-internal ASM is used
only at build time. The native adapter has no runtime ASM dependency. Packaging
preserves the executable Spring Boot archive's nested-library storage metadata.

`NativeCacheBridgeConfiguration` captures the actual Spring helper and exposes a
token-authenticated POST probe on container loopback port 18139. It tests only
synthetic identifiers and returns boolean results. The Kubernetes Service does
not expose this port. Probe mode is confined to the request thread and cleared
in a finally block.

## Production state and recovery

The installation and byte-verified recovery directories are recorded in
`backend/mosip-esignet-cache-adapter-activation.json` and
`backend/mosip-esignet-cache-adapter-recovery.json`. They contain sensitive keys
and configuration and must not be published. The mounted directory contains a
wrapped software key and its wrapping key; both are accessible to the authorized
application user. This does not provide hardware HSM isolation. Deployment uses
node-local hostPath mounts; relocation to another node requires provisioning the
same protected recovery material first.

The operator-controlled `write-mode` file accepts `NATIVE` or `LEGACY`. Replace
the file atomically, retaining its application UID/GID and permissions. Missing
or invalid mode fails writes closed. Switching to LEGACY stops new native writes
while the dual-format adapter continues to read existing native values.

Do not restore the original unpatched Java binary while native ciphertext remains
in any affected cache. First fence new native writes and either drain sessions
under an accepted maintenance policy or reverse migrate their current values
using the original HSM, preserving TTL and concurrent updates. Do not replace the
key files in place: existing native ciphertext depends on this exact key. A
future key rotation requires a new envelope version and retained readers.

The activation proof covers the actual Spring helper, legacy HSM reads, native
round trips, tamper rejection, reversal of a synthetic native value, writer-mode
rollback, and health/discovery. It does not prove full OIDC login, token, userinfo,
business-session continuity, or restoration of the original binary after real
native session writes. Those remain explicit acceptance gates. SoftHSM remains
required for legacy reads and other existing workloads.

## OIDC acceptance follow-up

`backend/mosip-full-oidc-acceptance.json` records the subsequent successful full
API flow using an isolated synthetic mock identity. It checks native encrypted
session bytes and decreasing expiry across an actual eSignet restart, followed
by authorization-code creation across writer-mode rollback, private-key JWT
client authentication, ID-token signature/issuer/audience/nonce checks, callback
state preservation, signed userinfo and subject/claim consistency, repeated
userinfo access, and code replay rejection with a fresh client assertion.
Userinfo is signed by the retained key bound to the mock-authentication scope;
it is verified against that pinned public key rather than assuming the ID-token
JWKS contains the mock key. Browser UI and real citizen identity flows were not
exercised. Full restoration of the original binary remains a separate gate.

The initial `invalid_transaction` failure was in the acceptance caller: eSignet
requires `oauth-details-key` (transaction ID) and `oauth-details-hash` (unpadded
base64url SHA-256 of the complete compact oauth-details response JSON). These
headers were added without bypassing the production validation filter. The
test negotiates PIN/number and consent scopes from the actual server contract.

Restart testing also exposed a real external dependency in token creation:
`mosip_esignet_amrAcrMappingFileUrl` referenced an unavailable GitHub URL. The
deployment now uses a hash-identical copy of the mounted mapping served through
the native artifact service. See
`backend/mosip-esignet-local-acr-mapping-fix.json`. Retain this local override
when restoring deployment configuration; the accepted deployment including it
is preserved in the private cache-adapter recovery directory.

## Browser and original-binary rollback follow-up

The later evidence in `backend/mosip-browser-original-binary-acceptance.json`
supersedes the earlier browser/original-binary acceptance gaps above for the
tested synthetic OIDC flow. The actual browser login, claim-consent screen and
public callback completed, followed by token exchange, signed userinfo checks
and replay rejection. A missing public eSignet host route was added to the
Karnataka public proxy. An empty-theme JavaScript error was guarded, and the
theme-script URL was versioned to prevent browsers retaining the old script.
Only the login/consent/callback flow was exercised, not every UI feature.

`backend/scripts/esignet-original-binary-rollback.py` fences eSignet writers by
waiting for zero pods, reverse migrates authenticated native cache strings with
the retained HSM key, and preserves absolute expiry using compare-and-swap. It
only accepts the observed Java serialization/TC_STRING format and fails closed
on unexpected encodings. Private before/after recovery snapshots are retained.
The test verified the exact original Java artifact hash and completed code,
token and userinfo operations for the same session on that original binary.
The native deployment was then restored before native writes resumed.

This is an eSignet OIDC/session rollback proof, not a rollback proof for every
microservice or every possible cached object type. SoftHSM was required during
the reversal and remains required by legacy signing and decryption paths.
`backend/mosip-softhsm-removal-readiness.json` records the two remaining direct
consumers and five retained private signing-key aliases. Do not remove SoftHSM
on the basis of these successful tests: native production signer integration,
controlled signing-key activation and HSM-independent acceptance remain gates.

## Verification

Run `backend/scripts/verify-esignet-cache-integration.py` inside the KarnatakaDBT
network namespace. It checks the exact deployed artifact hash, actual mounted
mode, live helper probe, health/discovery, client count, and Redis sizes. Empty
Redis snapshots are observations, not an atomic drain proof. Preparation and
activation scripts refuse to overwrite retained recovery material.
