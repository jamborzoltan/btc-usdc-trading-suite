<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

const WEBAUTHN_CHALLENGE_SECONDS = 120;

function webAuthnServer(array $config): object
{
    $libraryRoot = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'vendor' . DIRECTORY_SEPARATOR
        . 'lbuchs' . DIRECTORY_SEPARATOR . 'webauthn' . DIRECTORY_SEPARATOR . 'src';
    $libraryFile = $libraryRoot . DIRECTORY_SEPARATOR . 'WebAuthn.php';
    if (!is_file($libraryFile)) {
        respondJson(503, array('error' => 'A WebAuthn könyvtár hiányzik a webtárhelyről.'));
    }
    set_include_path($libraryRoot . PATH_SEPARATOR . get_include_path());
    require_once $libraryFile;

    $rpId = strtolower(trim((string) ($config['auth_rp_id'] ?? '')));
    $rpId = preg_replace('/:\d+$/', '', $rpId) ?? '';
    if ($rpId === '' || !preg_match('/^[a-z0-9.-]+$/', $rpId)) {
        respondJson(503, array('error' => 'Érvénytelen WebAuthn domainbeállítás.'));
    }
    $requestHost = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));
    $requestHost = preg_replace('/:\d+$/', '', $requestHost) ?? '';
    if ($requestHost !== $rpId && !str_ends_with($requestHost, '.' . $rpId)) {
        respondJson(503, array('error' => 'A WebAuthn domain nem egyezik a megnyitott webhellyel.'));
    }
    $rpName = trim((string) ($config['auth_rp_name'] ?? 'BTC/USDC robot'));
    return new \lbuchs\WebAuthn\WebAuthn($rpName, $rpId, array('none'), true);
}

function userHandleFor(string $stateKey, string $username): string
{
    return substr(hash('sha256', 'btc-usdc-passkey:' . $stateKey . ':' . $username, true), 0, 32);
}

function storeWebAuthnChallenge(string $key, object $webAuthn): void
{
    $challenge = $webAuthn->getChallenge();
    $_SESSION[$key] = array(
        'value' => base64_encode($challenge->getBinaryString()),
        'expires_at' => time() + WEBAUTHN_CHALLENGE_SECONDS,
    );
}

function consumeWebAuthnChallenge(string $key): string
{
    $stored = $_SESSION[$key] ?? null;
    unset($_SESSION[$key]);
    if (!is_array($stored) || (int) ($stored['expires_at'] ?? 0) < time()) {
        respondJson(410, array('error' => 'A Face ID-kérés lejárt. Indítsd újra a belépést.'));
    }
    $challenge = base64_decode((string) ($stored['value'] ?? ''), true);
    if ($challenge === false || strlen($challenge) < 16) {
        respondJson(410, array('error' => 'A Face ID-kérés érvénytelen. Indítsd újra a belépést.'));
    }
    return $challenge;
}

function loadCredentialIds(mysqli $connection, string $stateKey): array
{
    $statement = $connection->prepare(
        'SELECT credential_id FROM btc_usdc_passkeys WHERE state_key = ? ORDER BY created_at'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result($credentialId);
    $ids = array();
    while ($statement->fetch()) {
        try {
            $ids[] = base64UrlDecode((string) $credentialId);
        } catch (InvalidArgumentException $exception) {
            // Egy sérült rekord nem teheti használhatatlanná a többi passkey-t.
        }
    }
    $statement->close();
    return $ids;
}

function readPasskey(mysqli $connection, string $stateKey, string $credentialId): ?array
{
    $credentialHash = hash('sha256', $credentialId);
    $statement = $connection->prepare(
        'SELECT p.credential_id, p.user_handle, p.public_key, p.sign_count, u.username '
        . 'FROM btc_usdc_passkeys p INNER JOIN btc_usdc_auth_users u ON u.state_key = p.state_key '
        . 'WHERE p.state_key = ? AND p.credential_hash = ? LIMIT 1'
    );
    $statement->bind_param('ss', $stateKey, $credentialHash);
    $statement->execute();
    $statement->bind_result($storedCredentialId, $userHandle, $publicKey, $signCount, $username);
    $found = $statement->fetch();
    $statement->close();
    if (!$found || !hash_equals((string) $storedCredentialId, $credentialId)) {
        return null;
    }
    return array(
        'credential_hash' => $credentialHash,
        'user_handle' => (string) $userHandle,
        'public_key' => (string) $publicKey,
        'sign_count' => (int) $signCount,
        'username' => (string) $username,
    );
}

function requireFreshPasswordLogin(array $config): array
{
    $session = requireUserSession($config, true);
    if ($session['method'] !== 'password' || time() - $session['authenticated_at'] > 300) {
        respondJson(403, array('error' => 'Face ID beállításához jelentkezz be újra a jelszóval.'));
    }
    return $session;
}

$config = loadAppConfig();
$stateKey = validatedStateKey($config);
if (strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'POST') {
    header('Allow: POST');
    respondJson(405, array('error' => 'Csak POST kérés engedélyezett.'));
}

try {
    $request = readJsonRequest(65536);
    $action = strtolower((string) ($request['action'] ?? ''));
    $connection = openDatabase($config);
    $webAuthn = webAuthnServer($config);

    if ($action === 'register_options') {
        $session = requireFreshPasswordLogin($config);
        $userHandle = userHandleFor($stateKey, $session['username']);
        $existingIds = loadCredentialIds($connection, $stateKey);
        $options = $webAuthn->getCreateArgs(
            $userHandle,
            $session['username'],
            $session['username'],
            60,
            true,
            'required',
            false,
            $existingIds
        );
        storeWebAuthnChallenge('webauthn_register_challenge', $webAuthn);
        respondJson(200, array('options' => $options));
    }

    if ($action === 'register_verify') {
        $session = requireFreshPasswordLogin($config);
        $challenge = consumeWebAuthnChallenge('webauthn_register_challenge');
        $clientData = base64UrlDecode((string) ($request['clientDataJSON'] ?? ''));
        $attestation = base64UrlDecode((string) ($request['attestationObject'] ?? ''));
        $registration = $webAuthn->processCreate($clientData, $attestation, $challenge, true, true, false);
        $credentialId = base64UrlEncode((string) $registration->credentialId);
        $credentialHash = hash('sha256', $credentialId);
        $userHandle = base64UrlEncode(userHandleFor($stateKey, $session['username']));
        $publicKey = (string) $registration->credentialPublicKey;
        $signCount = (int) ($registration->signatureCounter ?? 0);
        $label = trim((string) ($request['label'] ?? 'Face ID / passkey'));
        $label = function_exists('mb_substr') ? mb_substr($label, 0, 64, 'UTF-8') : substr($label, 0, 64);
        $transports = json_encode($request['transports'] ?? array(), JSON_UNESCAPED_SLASHES);
        if (!is_string($transports) || strlen($transports) > 512) {
            $transports = '[]';
        }
        $statement = $connection->prepare(
            'INSERT INTO btc_usdc_passkeys '
            . '(state_key, credential_hash, credential_id, user_handle, public_key, sign_count, label, transports) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $statement->bind_param(
            'sssssiss',
            $stateKey,
            $credentialHash,
            $credentialId,
            $userHandle,
            $publicKey,
            $signCount,
            $label,
            $transports
        );
        $statement->execute();
        $statement->close();
        respondJson(201, array('ok' => true, 'message' => 'A Face ID/passkey sikeresen beállítva.'));
    }

    if ($action === 'login_options') {
        startSecureSession($config);
        $options = $webAuthn->getGetArgs(array(), 60, false, false, false, true, true, 'required');
        storeWebAuthnChallenge('webauthn_login_challenge', $webAuthn);
        respondJson(200, array('options' => $options));
    }

    if ($action !== 'login_verify') {
        respondJson(422, array('error' => 'Ismeretlen WebAuthn művelet.'));
    }

    startSecureSession($config);
    $challenge = consumeWebAuthnChallenge('webauthn_login_challenge');
    $credentialId = (string) ($request['id'] ?? '');
    $credential = readPasskey($connection, $stateKey, $credentialId);
    if ($credential === null) {
        usleep(250000);
        respondJson(401, array('error' => 'Ez a passkey nincs regisztrálva.'));
    }
    $providedUserHandle = (string) ($request['userHandle'] ?? '');
    if ($providedUserHandle === '' || !hash_equals($credential['user_handle'], $providedUserHandle)) {
        usleep(250000);
        respondJson(401, array('error' => 'A passkey nem ehhez a felhasználóhoz tartozik.'));
    }
    $clientData = base64UrlDecode((string) ($request['clientDataJSON'] ?? ''));
    $authenticatorData = base64UrlDecode((string) ($request['authenticatorData'] ?? ''));
    $signature = base64UrlDecode((string) ($request['signature'] ?? ''));
    $webAuthn->processGet(
        $clientData,
        $authenticatorData,
        $signature,
        $credential['public_key'],
        $challenge,
        $credential['sign_count'],
        true,
        true
    );
    $newSignCount = $webAuthn->getSignatureCounter();
    $storedSignCount = $newSignCount === null ? $credential['sign_count'] : $newSignCount;
    $statement = $connection->prepare(
        'UPDATE btc_usdc_passkeys SET sign_count = ?, last_used_at = CURRENT_TIMESTAMP '
        . 'WHERE state_key = ? AND credential_hash = ?'
    );
    $statement->bind_param('iss', $storedSignCount, $stateKey, $credential['credential_hash']);
    $statement->execute();
    $statement->close();

    $username = $credential['username'];
    $session = establishUserSession($config, $username, 'passkey', isPwaRequest());
    respondJson(200, array(
        'authenticated' => true,
        'username' => $username,
        'method' => 'passkey',
        'sessionProfile' => $session['profile'],
        'expiresIn' => $session['expires_in'],
        'csrfToken' => $session['csrf_token'],
        'passkeyAvailable' => true,
        'canRegisterPasskey' => false,
    ));
} catch (mysqli_sql_exception $exception) {
    if ((int) $exception->getCode() === 1062) {
        respondJson(409, array('error' => 'Ez a passkey már regisztrálva van.'));
    }
    error_log('BTC/USDC WebAuthn adatbázishiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A Face ID/passkey adatbázisa most nem érhető el.'));
} catch (InvalidArgumentException $exception) {
    respondJson(400, array('error' => 'Érvénytelen Face ID/passkey válasz.'));
} catch (Throwable $exception) {
    error_log('BTC/USDC WebAuthn hiba: ' . $exception->getMessage());
    respondJson(401, array('error' => 'A Face ID/passkey ellenőrzése nem sikerült.'));
}
