<?php
declare(strict_types=1);

/*
 * Közös hitelesítési és munkamenet-segédek.
 * A böngésző PHP-sessiont és CSRF tokent, a mini PC külön robot-tokent használ.
 */

function respondJson(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function sendApiHeaders(): void
{
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store, max-age=0');
    header('Pragma: no-cache');
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: no-referrer');
    header('X-Frame-Options: DENY');
    header("Permissions-Policy: publickey-credentials-get=(self), publickey-credentials-create=(self)");
}

function loadAppConfig(): array
{
    $configPath = __DIR__ . DIRECTORY_SEPARATOR . 'config.php';
    if (!is_file($configPath)) {
        respondJson(503, array('error' => 'A webapp konfigurációja még nincs beállítva.'));
    }
    $config = require $configPath;
    if (!is_array($config)) {
        respondJson(503, array('error' => 'Érvénytelen webapp-konfiguráció.'));
    }
    return $config;
}

function validatedStateKey(array $config): string
{
    $stateKey = (string) ($config['state_key'] ?? 'btc-usdc-sajat-robot');
    if (!preg_match('/^[A-Za-z0-9_.-]{1,64}$/', $stateKey)) {
        respondJson(503, array('error' => 'Érvénytelen közös állapotazonosító.'));
    }
    return $stateKey;
}

function openDatabase(array $config): mysqli
{
    mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
    $connection = new mysqli(
        (string) ($config['db_host'] ?? ''),
        (string) ($config['db_user'] ?? ''),
        (string) ($config['db_password'] ?? ''),
        (string) ($config['db_name'] ?? ''),
        (int) ($config['db_port'] ?? 3306)
    );
    $connection->set_charset('utf8mb4');
    // A robot ISO 8601 UTC időpontokat küld; így a DATETIME/TIMESTAMP mezők és
    // az API-ba visszaalakított időpontok tárhely-időzónától függetlenek.
    $connection->query("SET time_zone = '+00:00'");
    return $connection;
}

function isPwaRequest(): bool
{
    return strtolower((string) ($_SERVER['HTTP_X_APP_MODE'] ?? 'web')) === 'pwa';
}

function sessionDurations(array $config, string $method = 'password', bool $pwa = false): array
{
    $webIdle = max(300, min(3600, (int) ($config['web_session_idle_seconds'] ?? 900)));
    $webAbsolute = max($webIdle, min(14400, (int) ($config['web_session_absolute_seconds'] ?? 3600)));
    $pwaIdle = max(900, min(86400, (int) ($config['pwa_session_idle_seconds'] ?? 43200)));
    $pwaAbsolute = max($pwaIdle, min(604800, (int) ($config['pwa_session_absolute_seconds'] ?? 86400)));

    // Hosszabb munkamenetet kizárólag sikeres passkey-belépés és telepített PWA kérhet.
    if ($method === 'passkey' && $pwa) {
        return array('idle' => $pwaIdle, 'absolute' => $pwaAbsolute, 'profile' => 'pwa_passkey');
    }
    return array('idle' => $webIdle, 'absolute' => $webAbsolute, 'profile' => 'short_web');
}

function startSecureSession(array $config): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $maximum = sessionDurations($config, 'passkey', true)['absolute'];
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    ini_set('session.cookie_httponly', '1');
    ini_set('session.cookie_secure', '1');
    ini_set('session.cookie_samesite', 'Strict');
    ini_set('session.gc_maxlifetime', (string) $maximum);
    session_name('BTCUSDCSESSID');
    session_set_cookie_params(array(
        'lifetime' => isPwaRequest() ? $maximum : 0,
        'path' => '/',
        'secure' => true,
        'httponly' => true,
        'samesite' => 'Strict',
    ));
    session_start();
}

function destroySession(): void
{
    $_SESSION = array();
    if (session_status() === PHP_SESSION_ACTIVE) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', array(
            'expires' => time() - 42000,
            'path' => $params['path'] ?: '/',
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Strict',
        ));
        session_destroy();
    }
}

function currentUserSession(array $config, bool $touch = true): ?array
{
    startSecureSession($config);
    if (empty($_SESSION['authenticated']) || !isset($_SESSION['auth_created_at'], $_SESSION['auth_last_seen'])) {
        return null;
    }

    $method = (string) ($_SESSION['auth_method'] ?? 'password');
    $pwa = !empty($_SESSION['auth_pwa']);
    $durations = sessionDurations($config, $method, $pwa);
    $now = time();
    $createdAt = (int) $_SESSION['auth_created_at'];
    $lastSeen = (int) $_SESSION['auth_last_seen'];
    if ($now - $lastSeen > $durations['idle'] || $now - $createdAt > $durations['absolute']) {
        destroySession();
        return null;
    }
    if ($touch) {
        $_SESSION['auth_last_seen'] = $now;
        $lastSeen = $now;
    }
    if (empty($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }

    $idleRemaining = max(0, $durations['idle'] - ($now - $lastSeen));
    $absoluteRemaining = max(0, $durations['absolute'] - ($now - $createdAt));
    return array(
        'username' => (string) ($_SESSION['auth_username'] ?? ''),
        'method' => $method,
        'pwa' => $pwa,
        'profile' => $durations['profile'],
        'csrf_token' => (string) $_SESSION['csrf_token'],
        'expires_in' => min($idleRemaining, $absoluteRemaining),
        'authenticated_at' => (int) ($_SESSION['authenticated_at'] ?? $createdAt),
    );
}

function establishUserSession(array $config, string $username, string $method, bool $pwa): array
{
    startSecureSession($config);
    session_regenerate_id(true);
    $now = time();
    $_SESSION = array(
        'authenticated' => true,
        'auth_username' => $username,
        'auth_method' => $method,
        'auth_pwa' => $method === 'passkey' && $pwa,
        'auth_created_at' => $now,
        'auth_last_seen' => $now,
        'authenticated_at' => $now,
        'csrf_token' => bin2hex(random_bytes(32)),
    );
    return currentUserSession($config, false) ?? array();
}

function requireUserSession(array $config, bool $requireCsrf = false): array
{
    $session = currentUserSession($config);
    if ($session === null) {
        respondJson(401, array('error' => 'A munkamenet lejárt vagy nincs bejelentkezve.', 'authenticated' => false));
    }
    if ($requireCsrf) {
        $provided = (string) ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
        if ($provided === '' || !hash_equals($session['csrf_token'], $provided)) {
            respondJson(403, array('error' => 'Érvénytelen biztonsági token. Frissítsd az oldalt.'));
        }
    }
    return $session;
}

function hasValidRobotToken(array $config): bool
{
    $expected = (string) ($config['robot_runtime_token'] ?? '');
    $provided = (string) ($_SERVER['HTTP_X_ROBOT_TOKEN'] ?? '');
    return strlen($expected) >= 24 && $provided !== '' && hash_equals($expected, $provided);
}

function requireRobotToken(array $config): void
{
    if (!hasValidRobotToken($config)) {
        respondJson(403, array('error' => 'Érvénytelen robot-hitelesítés.'));
    }
}

function readJsonRequest(int $maximumBytes = 16384): array
{
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > $maximumBytes) {
        respondJson(413, array('error' => 'Túl nagy kérés.'));
    }
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || strlen($rawBody) > $maximumBytes) {
        respondJson(413, array('error' => 'Túl nagy kérés.'));
    }
    try {
        $request = json_decode($rawBody, true, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException $exception) {
        respondJson(400, array('error' => 'Érvénytelen JSON kérés.'));
    }
    if (!is_array($request)) {
        respondJson(400, array('error' => 'Érvénytelen kérés.'));
    }
    return $request;
}

function base64UrlEncode(string $binary): string
{
    return rtrim(strtr(base64_encode($binary), '+/', '-_'), '=');
}

function base64UrlDecode(string $encoded): string
{
    if (!preg_match('/^[A-Za-z0-9_-]*$/', $encoded)) {
        throw new InvalidArgumentException('Érvénytelen base64url adat.');
    }
    $padding = (4 - strlen($encoded) % 4) % 4;
    $decoded = base64_decode(strtr($encoded . str_repeat('=', $padding), '-_', '+/'), true);
    if ($decoded === false) {
        throw new InvalidArgumentException('Érvénytelen base64url adat.');
    }
    return $decoded;
}

sendApiHeaders();
