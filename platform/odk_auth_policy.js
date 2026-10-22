'use strict';
// Deployment policy for upstream ODK, independent of the former distributor.
// This adjusts discovery metadata only. ODK still validates the signed token,
// PKCE, state, issuer, audience and the actual verified-email UserInfo claim.
const config = require('config');
function basicAllowed() {
  if (config.has('default.basicAuthApisEnabled')) return config.get('default.basicAuthApisEnabled') === true;
  return !(config.has('default.oidc.enabled') && config.get('default.oidc.enabled') === true);
}
function discoveryClaims(issuer) {
  const approved = ['http://commons-keycloak/realms/staff', 'https://localhost:8444/realms/staff'];
  const enabled = config.has('default.oidc.karnatakaKeycloakMetadataCompatibility') && config.get('default.oidc.karnatakaKeycloakMetadataCompatibility') === true;
  return enabled && approved.includes(issuer) ? ['email'] : ['email', 'email_verified'];
}
module.exports = { basicAllowed, discoveryClaims };
