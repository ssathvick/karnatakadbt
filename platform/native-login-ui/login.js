'use strict';

const servicePrefix = document.body.dataset.servicePrefix || '';
const $ = (id) => document.getElementById(id);
const words = {
  en: {secure:'Secure programme access',language:'Language',welcome:'YOUR IDENTITY. YOUR CHOICE.',headline:'One secure sign in.\nAccess that belongs to you.',intro:'Sign in to the programme you chose. Review the information you share before continuing.',assurance:'Your sign-in details stay private. This page does not save your identity information on this device.',step1:'Verify your identity',step2:'Review access',step3:'Continue securely',signin:'Sign in',loading:'Preparing your secure sign in…',identityHint:'Use the identity enrolled by your institution.',identity:'Identity number',method:'Verification method',verify:'Verify and continue',wallet:'Use a linked wallet',walletHeading:'Continue in your wallet',walletHint:'Scan this code with your enrolled wallet. Keep this page open while you approve access.',back:'Back to sign in',consentHint:'Review what this application can receive. Required information is marked.',claims:'Identity information',permissions:'Programme permissions and credentials',consentNote:'Continue only if you recognize this application and agree to this access.',continue:'Allow and continue',cancel:'Cancel',unavailable:'This sign-in request cannot continue',returnHint:'Return to the programme and start sign in again. Your application will create a fresh secure request.',footer:'Encrypted connection · You control your access',PIN:'PIN',OTP:'One-time code',BIO:'Biometric device',PWD:'Password',KBA:'Identity questions',WLA:'Linked wallet',show:'Show',hide:'Hide',sendOtp:'Send verification code',otpSent:'Verification code requested. Check your registered email or phone.',required:'Required',waiting:'Waiting for approval in your wallet…',expired:'This secure request has expired. Return to the programme and start again.',authFailed:'We could not verify those details. Check them and try again.',failed:'We could not complete this request. Please try again.',device:'Connect your enrolled biometric device and choose Capture.',capture:'Capture biometrics',deviceFailed:'No available biometric device was found. Connect your device and try again.',share:'Review access',connecting:'Continuing securely…',name:'Name',email:'Email address',phone_number:'Phone number',birthdate:'Date of birth',gender:'Gender',picture:'Profile photo',individual_id:'Identity number',address:'Address'},
  kn: {secure:'ಸುರಕ್ಷಿತ ಯೋಜನಾ ಪ್ರವೇಶ',language:'ಭಾಷೆ',welcome:'ನಿಮ್ಮ ಗುರುತು. ನಿಮ್ಮ ಆಯ್ಕೆ.',headline:'ಒಂದು ಸುರಕ್ಷಿತ ಪ್ರವೇಶ.\nನಿಮಗಾಗಿ ಇರುವ ಸೇವೆಗಳು.',intro:'ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಯೋಜನೆಗೆ ಪ್ರವೇಶಿಸಿ. ಮುಂದುವರಿಯುವ ಮೊದಲು ಹಂಚಿಕೊಳ್ಳುವ ಮಾಹಿತಿಯನ್ನು ಪರಿಶೀಲಿಸಿ.',assurance:'ನಿಮ್ಮ ಪ್ರವೇಶದ ವಿವರಗಳು ಖಾಸಗಿಯಾಗಿರುತ್ತವೆ. ಈ ಪುಟವು ನಿಮ್ಮ ಗುರುತಿನ ಮಾಹಿತಿಯನ್ನು ಈ ಸಾಧನದಲ್ಲಿ ಉಳಿಸುವುದಿಲ್ಲ.',step1:'ಗುರುತನ್ನು ದೃಢೀಕರಿಸಿ',step2:'ಅನುಮತಿ ಪರಿಶೀಲಿಸಿ',step3:'ಸುರಕ್ಷಿತವಾಗಿ ಮುಂದುವರಿಯಿರಿ',signin:'ಪ್ರವೇಶಿಸಿ',loading:'ನಿಮ್ಮ ಸುರಕ್ಷಿತ ಪ್ರವೇಶವನ್ನು ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ…',identityHint:'ನಿಮ್ಮ ಸಂಸ್ಥೆಯಲ್ಲಿ ನೋಂದಾಯಿಸಿದ ಗುರುತನ್ನು ಬಳಸಿ.',identity:'ಗುರುತಿನ ಸಂಖ್ಯೆ',method:'ದೃಢೀಕರಣ ವಿಧಾನ',verify:'ದೃಢೀಕರಿಸಿ ಮತ್ತು ಮುಂದುವರಿಯಿರಿ',wallet:'ನೋಂದಾಯಿತ ವಾಲೆಟ್ ಬಳಸಿ',walletHeading:'ನಿಮ್ಮ ವಾಲೆಟ್‌ನಲ್ಲಿ ಮುಂದುವರಿಯಿರಿ',walletHint:'ನಿಮ್ಮ ನೋಂದಾಯಿತ ವಾಲೆಟ್‌ನಿಂದ ಈ ಸಂಕೇತವನ್ನು ಸ್ಕ್ಯಾನ್ ಮಾಡಿ. ಅನುಮೋದನೆ ನೀಡುವವರೆಗೆ ಈ ಪುಟ ತೆರೆದಿರಲಿ.',back:'ಪ್ರವೇಶ ಪುಟಕ್ಕೆ ಹಿಂತಿರುಗಿ',consentHint:'ಈ ಅಪ್ಲಿಕೇಶನ್ ಪಡೆಯಬಹುದಾದ ಮಾಹಿತಿಯನ್ನು ಪರಿಶೀಲಿಸಿ. ಅಗತ್ಯ ಮಾಹಿತಿಯನ್ನು ಗುರುತಿಸಲಾಗಿದೆ.',claims:'ಗುರುತಿನ ಮಾಹಿತಿ',permissions:'ಯೋಜನೆಯ ಅನುಮತಿಗಳು ಮತ್ತು ಪ್ರಮಾಣಪತ್ರಗಳು',consentNote:'ಈ ಅಪ್ಲಿಕೇಶನ್ ನಿಮಗೆ ತಿಳಿದಿದ್ದು, ಮಾಹಿತಿ ಹಂಚಿಕೊಳ್ಳಲು ಒಪ್ಪಿದರೆ ಮಾತ್ರ ಮುಂದುವರಿಯಿರಿ.',continue:'ಅನುಮತಿಸಿ ಮತ್ತು ಮುಂದುವರಿಯಿರಿ',cancel:'ರದ್ದುಮಾಡಿ',unavailable:'ಈ ಪ್ರವೇಶ ವಿನಂತಿಯನ್ನು ಮುಂದುವರಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ',returnHint:'ಯೋಜನೆಯ ಪುಟಕ್ಕೆ ಹಿಂತಿರುಗಿ ಮತ್ತೆ ಪ್ರವೇಶ ಪ್ರಾರಂಭಿಸಿ. ಹೊಸ ಸುರಕ್ಷಿತ ವಿನಂತಿಯನ್ನು ರಚಿಸಲಾಗುತ್ತದೆ.',footer:'ಎನ್‌ಕ್ರಿಪ್ಟ್ ಮಾಡಿದ ಸಂಪರ್ಕ · ಪ್ರವೇಶ ನಿಮ್ಮ ನಿಯಂತ್ರಣದಲ್ಲಿ',PIN:'ಪಿನ್',OTP:'ಒಂದು ಬಾರಿ ಬಳಕೆಯ ಸಂಕೇತ',BIO:'ಬಯೋಮೆಟ್ರಿಕ್ ಸಾಧನ',PWD:'ಗುಪ್ತಪದ',KBA:'ಗುರುತಿನ ಪ್ರಶ್ನೆಗಳು',WLA:'ನೋಂದಾಯಿತ ವಾಲೆಟ್',show:'ತೋರಿಸಿ',hide:'ಮರೆಮಾಡಿ',sendOtp:'ದೃಢೀಕರಣ ಸಂಕೇತ ಕಳುಹಿಸಿ',otpSent:'ದೃಢೀಕರಣ ಸಂಕೇತ ಕೋರಲಾಗಿದೆ. ನಿಮ್ಮ ನೋಂದಾಯಿತ ಇಮೇಲ್ ಅಥವಾ ಫೋನ್ ಪರಿಶೀಲಿಸಿ.',required:'ಅಗತ್ಯ',waiting:'ನಿಮ್ಮ ವಾಲೆಟ್‌ನಲ್ಲಿ ಅನುಮೋದನೆಗಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ…',expired:'ಈ ಸುರಕ್ಷಿತ ವಿನಂತಿಯ ಅವಧಿ ಮುಗಿದಿದೆ. ಯೋಜನೆಯ ಪುಟಕ್ಕೆ ಹಿಂತಿರುಗಿ ಮತ್ತೆ ಪ್ರಾರಂಭಿಸಿ.',authFailed:'ಈ ವಿವರಗಳನ್ನು ದೃಢೀಕರಿಸಲಾಗಲಿಲ್ಲ. ಪರಿಶೀಲಿಸಿ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.',failed:'ಈ ವಿನಂತಿಯನ್ನು ಪೂರ್ಣಗೊಳಿಸಲಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.',device:'ನಿಮ್ಮ ನೋಂದಾಯಿತ ಬಯೋಮೆಟ್ರಿಕ್ ಸಾಧನವನ್ನು ಸಂಪರ್ಕಿಸಿ ಮತ್ತು ಸೆರೆಹಿಡಿಯಿರಿ ಆಯ್ಕೆಮಾಡಿ.',capture:'ಬಯೋಮೆಟ್ರಿಕ್ ಸೆರೆಹಿಡಿಯಿರಿ',deviceFailed:'ಬಯೋಮೆಟ್ರಿಕ್ ಸಾಧನ ಲಭ್ಯವಿಲ್ಲ. ನಿಮ್ಮ ಸಾಧನವನ್ನು ಸಂಪರ್ಕಿಸಿ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.',share:'ಅನುಮತಿ ಪರಿಶೀಲಿಸಿ',connecting:'ಸುರಕ್ಷಿತವಾಗಿ ಮುಂದುವರಿಯಲಾಗುತ್ತಿದೆ…',name:'ಹೆಸರು',email:'ಇಮೇಲ್ ವಿಳಾಸ',phone_number:'ದೂರವಾಣಿ ಸಂಖ್ಯೆ',birthdate:'ಜನ್ಮ ದಿನಾಂಕ',gender:'ಲಿಂಗ',picture:'ಭಾವಚಿತ್ರ',individual_id:'ಗುರುತಿನ ಸಂಖ್ಯೆ',address:'ವಿಳಾಸ'}
};
const query = new URLSearchParams(location.search);
let locale = (query.get('ui_locales') || '').startsWith('kn') ? 'kn' : 'en';
let details, csrf, bindingHash, group = [], busy = false, walletActive = false;
let messageKey = '', titleKey = 'signin';
const t = (key) => words[locale][key] || words.en[key] || key;
function message(key) { messageKey = key; $('message').textContent = key ? t(key) : ''; }
function translate() {
  document.documentElement.lang = locale;
  document.querySelectorAll('[data-i18n]').forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.querySelector('[data-i18n="headline"]').style.whiteSpace = 'pre-line';
  $('language').value = locale;
  $('card-title').textContent = t(titleKey);
  message(messageKey);
  if (details) { clientName(); if (!$('identity-form').hidden) renderMethods(); }
}
function clientName() {
  const names = details.clientName;
  $('client-name').textContent = names && typeof names === 'object' ? (names[locale] || names['@none'] || Object.values(names)[0] || '') : (names || 'AI in e-Governance');
}
function show(panel, title) {
  titleKey = title;
  for (const id of ['loading','identity-form','consent-form','wallet-panel','unavailable']) $(id).hidden = id !== panel;
  $('card-title').textContent = t(title);
  $('progress-fill').style.width = panel === 'consent-form' ? '70%' : panel === 'unavailable' ? '100%' : '30%';
}
function errorKey(error) {
  return ['invalid_transaction','link_code_expired','invalid_link_code'].includes(error.code) ? 'expired' : ['auth_failed','invalid_otp','invalid_wla_token'].includes(error.code) ? 'authFailed' : 'failed';
}
async function api(path, request) {
  const headers = {'Content-Type':'application/json'};
  if (csrf) headers[csrf.headerName || 'X-XSRF-TOKEN'] = csrf.token;
  if (details && bindingHash) { headers['oauth-details-key'] = details.transactionId; headers['oauth-details-hash'] = bindingHash; }
  const response = await fetch(servicePrefix + '/v1/esignet' + path, {method:'POST',headers,credentials:'same-origin',cache:'no-store',body:JSON.stringify({requestTime:new Date().toISOString(),request})});
  const value = await response.json();
  if (!response.ok || value.errors?.length) { const error = new Error('Request rejected'); error.code = value.errors?.[0]?.errorCode || 'request_failed'; throw error; }
  return value.response;
}
function lock(value) { busy = value; document.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = value; }); }
function renderMethods() {
  const selected = $('factor').value;
  $('factor').replaceChildren();
  (details.authFactors || []).forEach((factors, index) => {
    const option = document.createElement('option'); option.value = String(index); option.textContent = factors.map((item) => t(item.type)).join(' + '); $('factor').append(option);
  });
  if (selected && [...$('factor').options].some((item) => item.value === selected)) $('factor').value = selected;
  renderChallenges();
}
function renderChallenges() {
  group = details.authFactors[Number($('factor').value)] || [];
  $('challenges').replaceChildren();
  const walletOnly = group.some((item) => item.type === 'WLA');
  $('verify').hidden = walletOnly;
  $('individual').required = !walletOnly;
  $('wallet-button').hidden = !(details.authFactors || []).some((items) => items.some((item) => item.type === 'WLA'));
  for (const factor of group) {
    if (factor.type === 'WLA') continue;
    const label = document.createElement('label'); label.htmlFor = 'challenge-' + factor.type; label.textContent = t(factor.type);
    const input = document.createElement('input'); input.id = label.htmlFor; input.required = true; input.maxLength = factor.type === 'OTP' ? 12 : 256;
    input.autocomplete = factor.type === 'OTP' ? 'one-time-code' : 'current-password'; input.type = 'password';
    if (['PIN','OTP'].includes(factor.type)) input.inputMode = 'numeric';
    $('challenges').append(label);
    const wrap = document.createElement('div'); wrap.className = 'password-wrap'; wrap.append(input);
    const toggle = document.createElement('button'); toggle.type = 'button'; toggle.textContent = t('show');
    toggle.addEventListener('click', () => { const visible = input.type === 'text'; input.type = visible ? 'password' : 'text'; toggle.textContent = t(visible ? 'show' : 'hide'); });
    if (factor.type !== 'BIO') wrap.append(toggle);
    $('challenges').append(wrap);
    if (factor.type === 'OTP') {
      const otp = document.createElement('button'); otp.type = 'button'; otp.className = 'secondary otp-button'; otp.textContent = t('sendOtp');
      otp.addEventListener('click', async () => {
        if (!$('individual').reportValidity()) return;
        otp.disabled = true; message('');
        try { await api('/authorization/send-otp',{transactionId:details.transactionId,individualId:$('individual').value,otpChannels:details.configs?.['send-otp-channels'] || ['email','phone']}); message('otpSent'); }
        catch (error) { message(errorKey(error)); }
        finally { otp.disabled = false; }
      });
      $('challenges').append(otp);
    }
    if (factor.type === 'BIO') {
      input.type = 'hidden'; input.required = false;
      const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = t('device'); $('challenges').append(hint);
      const capture = document.createElement('button'); capture.type = 'button'; capture.className = 'secondary'; capture.textContent = t('capture');
      capture.addEventListener('click', async () => { capture.disabled = true; try { await captureBiometric(input); message(''); } catch { message('deviceFailed'); } finally { capture.disabled = false; } });
      $('challenges').append(capture);
    }
  }
}
async function captureBiometric(input) {
  const range = String(details.configs?.['sbi.port.range'] || '4501-4600').split('-').map(Number);
  const configured = details.configs?.['sbi.device.base-url'];
  const bases = [];
  if (configured) {
    const gateway = new URL(configured, location.origin);
    if (gateway.origin !== location.origin || gateway.protocol !== 'https:' || gateway.search || gateway.hash) throw new Error('Invalid device gateway');
    bases.push(gateway.href.replace(/\/$/, ''));
  } else {
    for (let port = range[0]; Number.isInteger(port) && port > 0 && port <= 65535 && port <= Math.min(range[1],range[0]+99); port++) bases.push(`http://127.0.0.1:${port}`);
  }
  for (const base of bases) {
    try {
      const devices = await fetch(base + '/device', {method:'MOSIPDISC',body:JSON.stringify({type:'Biometric Device'}),signal:AbortSignal.timeout(configured ? 3000 : 300)}).then((response) => response.json());
      const device = Array.isArray(devices) ? devices.find((item) => item.deviceStatus === 'Ready') : null;
      if (!device) continue;
      const body = {env:'Staging',purpose:'Auth',specVersion:'0.9.5',timeout:30000,captureTime:new Date().toISOString(),transactionId:details.transactionId,bio:[{type:device.deviceType,count:1,bioSubType:['UNKNOWN'],requestedScore:'70',deviceId:device.deviceId,deviceSubId:'0',previousHash:''}]};
      const captured = await fetch(base + '/capture', {method:'CAPTURE',body:JSON.stringify(body),signal:AbortSignal.timeout(35000)}).then((response) => response.json());
      if (!captured.biometrics?.length) continue;
      input.value = btoa(unescape(encodeURIComponent(JSON.stringify(captured)))); return;
    } catch { /* Try the next configured local device port. */ }
  }
  throw new Error('No biometric device');
}
function addOption(parent, name, required, kind) {
  const label = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; input.name = kind; input.value = name; input.checked = true; input.disabled = required;
  const text = document.createElement('span'), caption = document.createElement('span');
  caption.dataset.i18n = name; caption.textContent = t(name); text.append(caption);
  if (required) {
    const note = document.createElement('small'), requiredLabel = document.createElement('span');
    requiredLabel.dataset.i18n = 'required'; requiredLabel.textContent = t('required');
    note.append(' · ', requiredLabel); text.append(note);
  }
  label.append(input,text); parent.append(label);
}
function consent() {
  $('claim-options').replaceChildren(); $('scope-options').replaceChildren();
  for (const claim of details.essentialClaims || []) addOption($('claim-options'),claim,true,'claim');
  for (const claim of details.voluntaryClaims || []) addOption($('claim-options'),claim,false,'claim');
  for (const scope of [...(details.authorizeScopes || []),...(details.credentialScopes || [])]) addOption($('scope-options'),scope,false,'scope');
  $('scope-fieldset').hidden = !$('scope-options').children.length;
  $('challenges').querySelectorAll('input').forEach((input) => { input.value = ''; });
  show('consent-form','share');
}
function redirect(value) {
  if (value.redirectUri !== details.redirectUri || (value.state ?? null) !== query.get('state')) throw new Error('Invalid redirect binding');
  const url = new URL(value.redirectUri);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1','localhost','[::1]'].includes(url.hostname))) throw new Error('Invalid redirect');
  url.searchParams.set('code',value.code); if (value.state != null) url.searchParams.set('state',value.state);
  $('progress-fill').style.width = '100%'; message('connecting'); location.assign(url.href);
}
$('identity-form').addEventListener('submit', async (event) => {
  event.preventDefault(); if (busy) return; lock(true); message('');
  try {
    const formats = {PIN:'number',OTP:'alpha-numeric',BIO:'encoded-json',PWD:'alpha-numeric',KBA:'base64-json'};
    const challengeList = group.map((factor) => ({authFactorType:factor.type,challenge:$('challenge-'+factor.type).value,format:formats[factor.type]}));
    if (challengeList.some((item) => item.authFactorType === 'BIO' && !item.challenge)) { message('device'); return; }
    if (challengeList.some((item) => !item.challenge)) throw new Error('Missing proof');
    await api('/authorization/v3/authenticate',{transactionId:details.transactionId,individualId:$('individual').value,challengeList}); consent();
  } catch (error) { message(errorKey(error)); } finally { lock(false); }
});
$('consent-form').addEventListener('submit', async (event) => {
  event.preventDefault(); if (busy) return; lock(true); message('');
  try { redirect(await api('/authorization/auth-code',{transactionId:details.transactionId,acceptedClaims:[...document.querySelectorAll('input[name="claim"]:checked')].map((input) => input.value),permittedAuthorizeScopes:[...document.querySelectorAll('input[name="scope"]:checked')].map((input) => input.value)})); }
  catch (error) { message(errorKey(error)); lock(false); }
});
$('wallet-button').addEventListener('click', async () => {
  if (busy) return; walletActive = true; message(''); show('wallet-panel','walletHeading');
  try {
    const link = await api('/linked-authorization/link-code',{transactionId:details.transactionId});
    const template = String(details.configs?.['wallet.link.uri'] || 'inji://wallet?linkCode=LINK_CODE');
    const uri = template.includes('LINK_CODE') ? template.replace('LINK_CODE',encodeURIComponent(link.linkCode)) : 'inji://wallet?linkCode='+encodeURIComponent(link.linkCode);
    $('wallet-qr').src = servicePrefix+'/_native/qr?text='+encodeURIComponent(uri); $('wallet-state').textContent = t('waiting');
    const expires = Date.parse(link.expireDateTime);
    while (walletActive && Date.now() < expires) {
      try { const status = await api('/linked-authorization/link-status',{transactionId:details.transactionId,linkCode:link.linkCode}); if (!status || status.linkStatus !== 'LINKED') { await new Promise((resolve) => setTimeout(resolve,750)); continue; } }
      catch (error) { if (Date.now() < expires && error.code === 'link_code_expired') continue; throw error; }
      const code = await api('/linked-authorization/link-auth-code',{transactionId:details.transactionId,linkedCode:link.linkCode});
      if (!code) { await new Promise((resolve) => setTimeout(resolve,750)); continue; }
      if (walletActive) redirect(code); return;
    }
    if (walletActive) message('expired');
  } catch (error) { if (walletActive) message(errorKey(error)); }
});
$('wallet-back').addEventListener('click', () => { walletActive=false; location.reload(); });
$('cancel').addEventListener('click', () => {
  const url = new URL(details.redirectUri); url.searchParams.set('error','access_denied'); if (query.has('state')) url.searchParams.set('state',query.get('state')); location.assign(url.href);
});
$('factor').addEventListener('change',renderChallenges);
$('language').addEventListener('change', () => { locale=$('language').value; translate(); });
async function initialize() {
  translate();
  if (!query.get('client_id') || !query.get('redirect_uri')) { show('unavailable','unavailable'); return; }
  try {
    csrf = await fetch(servicePrefix + '/v1/esignet/csrf/token',{credentials:'same-origin',cache:'no-store'}).then((response) => response.json());
    const request = {clientId:query.get('client_id'),redirectUri:query.get('redirect_uri'),responseType:query.get('response_type') || 'code',scope:query.get('scope') || 'openid',state:query.get('state'),nonce:query.get('nonce'),acrValues:query.get('acr_values') || undefined,claims:query.has('claims') ? JSON.parse(query.get('claims')) : undefined,claimsLocales:query.get('claims_locales') || undefined,prompt:query.get('prompt') || undefined,display:query.get('display') || undefined};
    if (query.has('code_challenge')) { request.codeChallenge=query.get('code_challenge'); request.codeChallengeMethod=query.get('code_challenge_method'); }
    if (query.has('max_age')) { if (!/^\d{1,10}$/.test(query.get('max_age'))) throw new Error('Invalid authentication age'); request.maxAge=Number(query.get('max_age')); }
    if (query.has('login_hint')) { request.loginHint=query.get('login_hint'); if (request.loginHint.length <= 256) $('individual').value=request.loginHint; }
    details = await api('/authorization/v2/oauth-details',request);
    const digest = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(details)));
    bindingHash = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    clientName(); renderMethods(); show('identity-form','signin');
  } catch (error) { show('unavailable','unavailable'); message(errorKey(error)); }
}
initialize();
