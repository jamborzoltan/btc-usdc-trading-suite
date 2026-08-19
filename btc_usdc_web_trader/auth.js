(() => {
  "use strict";

  const AUTH_URL = "api/auth.php";
  const WEBAUTHN_URL = "api/webauthn.php";
  const isPwa = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const appMode = isPwa ? "pwa" : "web";
  const supportsPasskeys = Boolean(window.PublicKeyCredential && navigator.credentials);
  let csrfToken = "";
  let authenticationState = null;
  let gatePromise = null;
  let resolveGate = null;
  let applicationStarted = false;
  let eventsBound = false;

  const byId = id => document.getElementById(id);

  function setMessage(message, error = false) {
    const node = byId("authMessage");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("error", error);
  }

  function setBusy(busy) {
    document.querySelectorAll("#authGate button, #authGate input, #authToolbar button")
      .forEach(node => { node.disabled = busy; });
  }

  function authHeaders(headers = {}) {
    const result = new Headers(headers);
    result.set("Accept", "application/json");
    result.set("X-App-Mode", appMode);
    return result;
  }

  async function authRequest(url, payload = null, includeCsrf = false) {
    const headers = authHeaders();
    const options = { method: payload === null ? "GET" : "POST", credentials:"same-origin", cache:"no-store", headers };
    if (payload !== null) {
      headers.set("Content-Type", "application/json");
      if (includeCsrf && csrfToken) headers.set("X-CSRF-Token", csrfToken);
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function sessionLabel(state) {
    if (state.sessionProfile === "pwa_passkey") return `${state.username} · Face ID/passkey · PWA`;
    return `${state.username} · rövid webes munkamenet`;
  }

  function renderAuthentication(state) {
    authenticationState = state;
    const authenticated = Boolean(state?.authenticated);
    const setupRequired = Boolean(state?.setupRequired);
    const passkeyAvailable = Boolean(state?.passkeyAvailable && supportsPasskeys);
    const loginForm = byId("loginForm");
    const setupForm = byId("setupForm");
    const passkeyButton = byId("passkeyLoginButton");
    const toolbar = byId("authToolbar");
    const registerButton = byId("registerPasskeyButton");

    document.body.classList.remove("auth-pending", "auth-ready", "auth-locked");
    document.body.classList.add(authenticated ? "auth-ready" : "auth-locked");
    if (loginForm) loginForm.hidden = authenticated || setupRequired;
    if (setupForm) setupForm.hidden = authenticated || !setupRequired;
    if (passkeyButton) passkeyButton.hidden = authenticated || setupRequired || !passkeyAvailable;
    if (toolbar) toolbar.hidden = !authenticated;
    if (authenticated) {
      csrfToken = String(state.csrfToken || "");
      byId("authSessionLabel").textContent = sessionLabel(state);
      if (registerButton) registerButton.hidden = !supportsPasskeys || !state.canRegisterPasskey;
      setMessage("");
    } else {
      csrfToken = "";
      if (registerButton) registerButton.hidden = true;
      const username = setupRequired ? byId("setupUsername") : byId("loginUsername");
      window.setTimeout(() => username?.focus(), 50);
    }
  }

  function completeAuthentication(state) {
    renderAuthentication(state);
    if (applicationStarted) {
      window.location.reload();
      return;
    }
    applicationStarted = true;
    if (resolveGate) {
      resolveGate(true);
      resolveGate = null;
    }
  }

  async function refreshAuthentication() {
    try {
      const state = await authRequest(AUTH_URL);
      renderAuthentication(state);
      return state;
    } catch (error) {
      renderAuthentication({ authenticated:false, configured:true });
      setMessage(error.message || "A belépési szolgáltatás nem érhető el.", true);
      return null;
    }
  }

  function toBase64Url(value) {
    const bytes = new Uint8Array(value);
    let binary = "";
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function fromBase64Url(value) {
    const normalized = String(value).replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(normalized + "=".repeat((4 - normalized.length % 4) % 4));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  }

  function creationOptions(options) {
    const publicKey = options.publicKey || options;
    publicKey.challenge = fromBase64Url(publicKey.challenge);
    publicKey.user.id = fromBase64Url(publicKey.user.id);
    if (Array.isArray(publicKey.excludeCredentials)) {
      publicKey.excludeCredentials = publicKey.excludeCredentials.map(item => ({ ...item, id:fromBase64Url(item.id) }));
    }
    return { publicKey };
  }

  function requestOptions(options) {
    const publicKey = options.publicKey || options;
    publicKey.challenge = fromBase64Url(publicKey.challenge);
    if (Array.isArray(publicKey.allowCredentials)) {
      publicKey.allowCredentials = publicKey.allowCredentials.map(item => ({ ...item, id:fromBase64Url(item.id) }));
    }
    return { publicKey };
  }

  async function passwordLogin(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("Bejelentkezés…");
    try {
      const state = await authRequest(AUTH_URL, {
        action:"login",
        username:byId("loginUsername").value,
        password:byId("loginPassword").value,
      });
      byId("loginPassword").value = "";
      completeAuthentication(state);
    } catch (error) {
      byId("loginPassword").value = "";
      setMessage(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function setupLogin(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("Biztonságos belépés létrehozása…");
    try {
      const state = await authRequest(AUTH_URL, {
        action:"setup",
        username:byId("setupUsername").value,
        password:byId("setupPassword").value,
        setupToken:byId("setupToken").value,
      });
      byId("setupPassword").value = "";
      byId("setupToken").value = "";
      completeAuthentication(state);
    } catch (error) {
      byId("setupPassword").value = "";
      byId("setupToken").value = "";
      setMessage(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function passkeyLogin() {
    if (!supportsPasskeys) return setMessage("Ezen az eszközön a passkey nem érhető el.", true);
    setBusy(true);
    setMessage("Face ID/passkey ellenőrzése…");
    try {
      const challenge = await authRequest(WEBAUTHN_URL, { action:"login_options" });
      const credential = await navigator.credentials.get(requestOptions(challenge.options));
      if (!credential) throw new Error("A Face ID/passkey belépés megszakadt.");
      const state = await authRequest(WEBAUTHN_URL, {
        action:"login_verify",
        id:toBase64Url(credential.rawId),
        clientDataJSON:toBase64Url(credential.response.clientDataJSON),
        authenticatorData:toBase64Url(credential.response.authenticatorData),
        signature:toBase64Url(credential.response.signature),
        userHandle:credential.response.userHandle ? toBase64Url(credential.response.userHandle) : "",
      });
      completeAuthentication(state);
    } catch (error) {
      const message = error?.name === "NotAllowedError"
        ? "A Face ID/passkey belépés megszakadt vagy lejárt."
        : error.message;
      setMessage(message, true);
    } finally {
      setBusy(false);
    }
  }

  async function registerPasskey() {
    setBusy(true);
    setMessage("Face ID/passkey beállítása…");
    try {
      const challenge = await authRequest(WEBAUTHN_URL, { action:"register_options" }, true);
      const credential = await navigator.credentials.create(creationOptions(challenge.options));
      if (!credential) throw new Error("A Face ID/passkey beállítása megszakadt.");
      const transports = typeof credential.response.getTransports === "function"
        ? credential.response.getTransports()
        : [];
      await authRequest(WEBAUTHN_URL, {
        action:"register_verify",
        clientDataJSON:toBase64Url(credential.response.clientDataJSON),
        attestationObject:toBase64Url(credential.response.attestationObject),
        transports,
        label:isPwa ? "Telefon Face ID / passkey" : "Böngésző passkey",
      }, true);
      const state = await refreshAuthentication();
      if (state?.authenticated) setMessage("A Face ID/passkey sikeresen beállítva.");
    } catch (error) {
      const message = error?.name === "NotAllowedError"
        ? "A Face ID/passkey beállítása megszakadt."
        : error.message;
      setMessage(message, true);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    try {
      await authRequest(AUTH_URL, { action:"logout" }, true);
    } catch {
      // A helyi felületet akkor is lezárjuk, ha a session már lejárt.
    }
    csrfToken = "";
    window.location.reload();
  }

  function bindEvents() {
    if (eventsBound) return;
    eventsBound = true;
    byId("loginForm")?.addEventListener("submit", passwordLogin);
    byId("setupForm")?.addEventListener("submit", setupLogin);
    byId("passkeyLoginButton")?.addEventListener("click", passkeyLogin);
    byId("registerPasskeyButton")?.addEventListener("click", registerPasskey);
    byId("logoutButton")?.addEventListener("click", logout);
  }

  async function requireAuthentication() {
    bindEvents();
    if (!gatePromise) gatePromise = new Promise(resolve => { resolveGate = resolve; });
    const state = await refreshAuthentication();
    if (state?.authenticated) completeAuthentication(state);
    return gatePromise;
  }

  async function secureFetch(url, options = {}) {
    const headers = authHeaders(options.headers || {});
    const method = String(options.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD" && csrfToken) headers.set("X-CSRF-Token", csrfToken);
    const response = await fetch(url, { ...options, method, headers, credentials:"same-origin" });
    if (response.status === 401) {
      renderAuthentication({ authenticated:false, configured:true, passkeyAvailable:authenticationState?.passkeyAvailable });
      setMessage("A munkamenet lejárt. Jelentkezz be újra.", true);
    }
    return response;
  }

  window.BtcAuth = Object.freeze({ requireAuthentication, secureFetch });
})();
