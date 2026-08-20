(() => {
  "use strict";

  const AUTH_URL = "api/auth.php";
  const WEBAUTHN_URL = "api/webauthn.php";
  const USERS_URL = "api/users.php";
  const isPwa = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const appMode = isPwa ? "pwa" : "web";
  const supportsPasskeys = Boolean(window.PublicKeyCredential && navigator.credentials);
  const AUTO_PASSKEY_KEY = "btc-usdc-auto-passkey-v1";
  const SKIP_AUTO_PASSKEY_KEY = "btc-usdc-skip-auto-passkey-once";
  let csrfToken = "";
  let authenticationState = null;
  let gatePromise = null;
  let resolveGate = null;
  let applicationStarted = false;
  let eventsBound = false;
  let automaticPasskeyAttempted = false;

  const byId = id => document.getElementById(id);

  function autoPasskeyEnabled() {
    try { return localStorage.getItem(AUTO_PASSKEY_KEY) === "1"; } catch { return false; }
  }

  function setAutoPasskeyEnabled(enabled) {
    try { localStorage.setItem(AUTO_PASSKEY_KEY, enabled ? "1" : "0"); } catch { /* A belépés ettől még működik. */ }
    renderAutoPasskeySetting();
  }

  function renderAutoPasskeySetting() {
    const available = isPwa && supportsPasskeys && Boolean(authenticationState?.passkeyAvailable);
    const enabled = autoPasskeyEnabled();
    const control = byId("autoPasskeyControl");
    const checkbox = byId("autoPasskeyCheckbox");
    const button = byId("autoPasskeyButton");
    if (control) control.hidden = !available || Boolean(authenticationState?.authenticated);
    if (checkbox) checkbox.checked = enabled;
    if (button) {
      button.hidden = !available || !authenticationState?.authenticated;
      button.textContent = `Auto Face ID: ${enabled ? "be" : "ki"}`;
      button.classList.toggle("enabled", enabled);
      button.setAttribute("aria-pressed", enabled ? "true" : "false");
    }
  }

  function setMessage(message, error = false) {
    const node = byId("authMessage");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("error", error);
  }

  function setBusy(busy) {
    document.querySelectorAll("#authGate button, #authGate input, #authToolbar button, #userManagementPanel button, #userManagementPanel input")
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
    const userManagementButton = byId("userManagementButton");

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
      if (userManagementButton) userManagementButton.hidden = false;
      setMessage("");
    } else {
      csrfToken = "";
      if (registerButton) registerButton.hidden = true;
      if (userManagementButton) userManagementButton.hidden = true;
      closeUserManagement();
      const username = setupRequired ? byId("setupUsername") : byId("loginUsername");
      window.setTimeout(() => username?.focus(), 50);
    }
    renderAutoPasskeySetting();
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

  function setUserManagementMessage(message, error = false) {
    const node = byId("userManagementMessage");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("error", error);
  }

  function closeUserManagement() {
    const panel = byId("userManagementPanel");
    if (panel) panel.hidden = true;
    const result = byId("robotTokenResult");
    const config = byId("robotTokenConfig");
    if (result) result.hidden = true;
    if (config) config.textContent = "";
    setUserManagementMessage("");
  }

  function showRobotToken(result) {
    const stateUrl = new URL("api/state.php", document.baseURI).href;
    const runtimeUrl = new URL("api/robot-runtime.php", document.baseURI).href;
    const config = [
      "[web_state]",
      `url = ${stateUrl}`,
      `runtime_url = ${runtimeUrl}`,
      `runtime_token = ${result.robotToken}`,
    ].join("\n");
    byId("robotTokenTitle").textContent = `${result.username} robot-konfigurációja`;
    byId("robotTokenConfig").textContent = config;
    byId("robotTokenResult").hidden = false;
  }

  function renderManagedUsers(data) {
    const createForm = byId("createUserForm");
    if (createForm) createForm.hidden = !data.isAdmin;
    const body = byId("managedUsers");
    if (!body) return;
    body.replaceChildren();
    (data.users || []).forEach(user => {
      const row = document.createElement("tr");
      const username = document.createElement("td");
      const role = document.createElement("td");
      const status = document.createElement("td");
      const action = document.createElement("td");
      username.textContent = user.username;
      role.textContent = user.isAdmin ? "Admin" : "Felhasználó";
      status.textContent = user.disabled ? "Tiltva" : (user.robotConfigured ? "Token kész" : "Nincs token");
      status.className = `managed-user-status ${user.disabled ? "inactive" : (user.robotConfigured ? "configured" : "missing")}`;
      if (!user.disabled) {
        const rotateButton = document.createElement("button");
        rotateButton.type = "button";
        rotateButton.textContent = "Token cseréje";
        rotateButton.addEventListener("click", () => rotateRobotToken(user.username));
        action.append(rotateButton);
      } else {
        action.textContent = "—";
      }
      row.append(username, role, status, action);
      body.append(row);
    });
    if (!body.children.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.className = "empty";
      cell.textContent = "Nincs megjeleníthető felhasználó.";
      row.append(cell);
      body.append(row);
    }
  }

  async function loadManagedUsers() {
    const data = await authRequest(USERS_URL);
    renderManagedUsers(data);
    return data;
  }

  async function openUserManagement() {
    const panel = byId("userManagementPanel");
    if (!panel) return;
    panel.hidden = false;
    setBusy(true);
    setUserManagementMessage("Felhasználók betöltése…");
    try {
      await loadManagedUsers();
      setUserManagementMessage("");
    } catch (error) {
      setUserManagementMessage(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function createManagedUser(event) {
    event.preventDefault();
    setBusy(true);
    setUserManagementMessage("Külön felhasználó és robot-hozzáférés létrehozása…");
    try {
      const result = await authRequest(USERS_URL, {
        action:"create",
        username:byId("managedUsername").value,
        password:byId("managedPassword").value,
      }, true);
      byId("managedPassword").value = "";
      byId("managedUsername").value = "";
      showRobotToken(result);
      await loadManagedUsers();
      setUserManagementMessage(result.message);
    } catch (error) {
      byId("managedPassword").value = "";
      setUserManagementMessage(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function rotateRobotToken(username) {
    if (!window.confirm(`${username}: az előző robot-token azonnal érvénytelen lesz. Folytatod?`)) return;
    setBusy(true);
    setUserManagementMessage("Új robot-token készítése…");
    try {
      const result = await authRequest(USERS_URL, {
        action:"rotate_robot_token",
        username,
        confirm:true,
      }, true);
      showRobotToken(result);
      await loadManagedUsers();
      setUserManagementMessage(result.message);
    } catch (error) {
      setUserManagementMessage(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function copyRobotConfiguration() {
    const config = byId("robotTokenConfig")?.textContent || "";
    if (!config) return;
    try {
      await navigator.clipboard.writeText(config);
      setUserManagementMessage("A robot-konfiguráció a vágólapra került.");
    } catch {
      setUserManagementMessage("A böngésző nem engedte a másolást; jelöld ki kézzel a konfigurációt.", true);
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
    try { sessionStorage.setItem(SKIP_AUTO_PASSKEY_KEY, "1"); } catch { /* Nem kritikus. */ }
    window.location.reload();
  }

  function toggleAutoPasskey() {
    setAutoPasskeyEnabled(!autoPasskeyEnabled());
  }

  function bindEvents() {
    if (eventsBound) return;
    eventsBound = true;
    byId("loginForm")?.addEventListener("submit", passwordLogin);
    byId("setupForm")?.addEventListener("submit", setupLogin);
    byId("passkeyLoginButton")?.addEventListener("click", passkeyLogin);
    byId("autoPasskeyCheckbox")?.addEventListener("change", event => setAutoPasskeyEnabled(event.target.checked));
    byId("autoPasskeyButton")?.addEventListener("click", toggleAutoPasskey);
    byId("registerPasskeyButton")?.addEventListener("click", registerPasskey);
    byId("userManagementButton")?.addEventListener("click", openUserManagement);
    byId("closeUserManagementButton")?.addEventListener("click", closeUserManagement);
    byId("createUserForm")?.addEventListener("submit", createManagedUser);
    byId("copyRobotTokenButton")?.addEventListener("click", copyRobotConfiguration);
    byId("userManagementPanel")?.addEventListener("click", event => {
      if (event.target === byId("userManagementPanel")) closeUserManagement();
    });
    byId("logoutButton")?.addEventListener("click", logout);
  }

  async function requireAuthentication() {
    bindEvents();
    if (!gatePromise) gatePromise = new Promise(resolve => { resolveGate = resolve; });
    const state = await refreshAuthentication();
    if (state?.authenticated) completeAuthentication(state);
    else if (state?.passkeyAvailable && isPwa && supportsPasskeys && autoPasskeyEnabled() && !automaticPasskeyAttempted) {
      automaticPasskeyAttempted = true;
      let skipOnce = false;
      try {
        skipOnce = sessionStorage.getItem(SKIP_AUTO_PASSKEY_KEY) === "1";
        sessionStorage.removeItem(SKIP_AUTO_PASSKEY_KEY);
      } catch { /* Nem kritikus. */ }
      if (!skipOnce) await passkeyLogin();
    }
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

  function currentAccount() {
    if (!authenticationState?.authenticated) return null;
    return Object.freeze({
      username:String(authenticationState.username || ""),
      isAdmin:Boolean(authenticationState.isAdmin),
      isLegacyAccount:Boolean(authenticationState.isLegacyAccount),
    });
  }

  window.BtcAuth = Object.freeze({ requireAuthentication, secureFetch, currentAccount });
})();
