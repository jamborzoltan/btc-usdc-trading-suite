<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

const LOGIN_WINDOW_SECONDS = 900;
const LOGIN_MAX_FAILURES = 5;
const LOGIN_LOCK_SECONDS = 900;

function readAuthUser(mysqli $connection, string $username): ?array
{
    $statement = $connection->prepare(
        'SELECT state_key, username, password_hash, is_admin, disabled '
        . 'FROM btc_usdc_auth_users WHERE username = ? LIMIT 1'
    );
    $statement->bind_param('s', $username);
    $statement->execute();
    $statement->bind_result($stateKey, $storedUsername, $passwordHash, $isAdmin, $disabled);
    $found = $statement->fetch();
    $statement->close();
    return $found ? array(
        'state_key' => (string) $stateKey,
        'username' => (string) $storedUsername,
        'password_hash' => (string) $passwordHash,
        'is_admin' => (bool) $isAdmin,
        'disabled' => (bool) $disabled,
    ) : null;
}

function authUserCount(mysqli $connection): int
{
    $result = $connection->query('SELECT COUNT(*) FROM btc_usdc_auth_users');
    $row = $result->fetch_row();
    $result->free();
    return (int) ($row[0] ?? 0);
}

function totalPasskeyCount(mysqli $connection): int
{
    $result = $connection->query('SELECT COUNT(*) FROM btc_usdc_passkeys');
    $row = $result->fetch_row();
    $result->free();
    return (int) ($row[0] ?? 0);
}

function refreshSessionAccount(mysqli $connection, array $config, ?array $session): ?array
{
    if ($session === null) {
        return null;
    }
    $user = readAuthUser($connection, $session['username']);
    if ($user === null || $user['disabled']) {
        destroySession();
        return null;
    }
    $_SESSION['auth_state_key'] = $user['state_key'];
    $_SESSION['auth_is_admin'] = $user['is_admin'];
    return currentUserSession($config, false);
}

function passkeyCount(mysqli $connection, string $stateKey): int
{
    $statement = $connection->prepare(
        'SELECT COUNT(*) FROM btc_usdc_passkeys WHERE state_key = ?'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result($count);
    $statement->fetch();
    $statement->close();
    return (int) $count;
}

function clientFingerprint(): string
{
    return hash('sha256', (string) ($_SERVER['REMOTE_ADDR'] ?? 'unknown'));
}

function loginAttemptState(mysqli $connection, string $stateKey): ?array
{
    $clientHash = clientFingerprint();
    $statement = $connection->prepare(
        'SELECT failures, UNIX_TIMESTAMP(first_attempt_at), UNIX_TIMESTAMP(locked_until) '
        . 'FROM btc_usdc_auth_attempts WHERE state_key = ? AND client_hash = ? LIMIT 1'
    );
    $statement->bind_param('ss', $stateKey, $clientHash);
    $statement->execute();
    $statement->bind_result($failures, $firstAttempt, $lockedUntil);
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }
    return array(
        'failures' => (int) $failures,
        'first_attempt' => (int) $firstAttempt,
        'locked_until' => $lockedUntil === null ? 0 : (int) $lockedUntil,
    );
}

function enforceLoginLimit(mysqli $connection, string $stateKey): void
{
    $attempt = loginAttemptState($connection, $stateKey);
    $now = time();
    if ($attempt !== null && $attempt['locked_until'] > $now) {
        respondJson(429, array(
            'error' => 'Túl sok sikertelen próbálkozás. Próbáld újra később.',
            'retryAfter' => $attempt['locked_until'] - $now,
        ));
    }
}

function recordLoginFailure(mysqli $connection, string $stateKey): void
{
    $now = time();
    $clientHash = clientFingerprint();
    $attempt = loginAttemptState($connection, $stateKey);
    if ($attempt === null || $now - $attempt['first_attempt'] > LOGIN_WINDOW_SECONDS) {
        $failures = 1;
        $firstAttempt = $now;
    } else {
        $failures = $attempt['failures'] + 1;
        $firstAttempt = $attempt['first_attempt'];
    }
    $lockedUntil = $failures >= LOGIN_MAX_FAILURES ? $now + LOGIN_LOCK_SECONDS : null;
    $statement = $connection->prepare(
        'INSERT INTO btc_usdc_auth_attempts '
        . '(state_key, client_hash, failures, first_attempt_at, locked_until) '
        . 'VALUES (?, ?, ?, FROM_UNIXTIME(?), FROM_UNIXTIME(?)) '
        . 'ON DUPLICATE KEY UPDATE failures = VALUES(failures), '
        . 'first_attempt_at = VALUES(first_attempt_at), locked_until = VALUES(locked_until)'
    );
    $statement->bind_param('ssiii', $stateKey, $clientHash, $failures, $firstAttempt, $lockedUntil);
    $statement->execute();
    $statement->close();
}

function clearLoginFailures(mysqli $connection, string $stateKey): void
{
    $clientHash = clientFingerprint();
    $statement = $connection->prepare(
        'DELETE FROM btc_usdc_auth_attempts WHERE state_key = ? AND client_hash = ?'
    );
    $statement->bind_param('ss', $stateKey, $clientHash);
    $statement->execute();
    $statement->close();
}

function validateNewPassword(string $password): void
{
    validateAccountPassword($password);
}

function authPayload(?array $session, bool $configured, int $passkeys): array
{
    if ($session === null) {
        return array(
            'authenticated' => false,
            'configured' => $configured,
            'setupRequired' => !$configured,
            'passkeyAvailable' => $passkeys > 0,
        );
    }
    return array(
        'authenticated' => true,
        'configured' => true,
        'username' => $session['username'],
        'isAdmin' => $session['is_admin'],
        'isLegacyAccount' => $session['is_legacy_account'],
        'method' => $session['method'],
        'sessionProfile' => $session['profile'],
        'expiresIn' => $session['expires_in'],
        'csrfToken' => $session['csrf_token'],
        'passkeyAvailable' => $passkeys > 0,
        'passkeyCount' => $passkeys,
        'canRegisterPasskey' => $session['method'] === 'password'
            && time() - $session['authenticated_at'] <= 300,
    );
}

$config = loadAppConfig();
$stateKey = validatedStateKey($config);
$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));

try {
    $connection = openDatabase($config);
    ensureLegacyUserSecurity($connection, $config);
    $configured = authUserCount($connection) > 0;
    $session = refreshSessionAccount($connection, $config, currentUserSession($config));
    $passkeys = $session !== null
        ? passkeyCount($connection, $session['state_key'])
        : totalPasskeyCount($connection);

    if ($method === 'GET') {
        respondJson(200, authPayload($session, $configured, $passkeys));
    }
    if ($method !== 'POST') {
        header('Allow: GET, POST');
        respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
    }

    $request = readJsonRequest();
    $action = strtolower((string) ($request['action'] ?? ''));

    if ($action === 'logout') {
        requireUserSession($config, true);
        destroySession();
        respondJson(200, array('ok' => true, 'authenticated' => false));
    }

    if ($action === 'setup') {
        if ($configured) {
            respondJson(409, array('error' => 'A belépés már be van állítva.'));
        }
        enforceLoginLimit($connection, $stateKey);
        $expectedSetupToken = (string) ($config['auth_setup_token'] ?? '');
        $providedSetupToken = (string) ($request['setupToken'] ?? '');
        $expectedUsername = trim((string) ($config['auth_username'] ?? 'admin'));
        $username = validateAccountUsername((string) ($request['username'] ?? ''));
        $password = (string) ($request['password'] ?? '');
        validateNewPassword($password);
        if (strlen($expectedSetupToken) < 32
            || $providedSetupToken === ''
            || !hash_equals($expectedSetupToken, $providedSetupToken)
            || !hash_equals($expectedUsername, $username)) {
            recordLoginFailure($connection, $stateKey);
            usleep(350000);
            respondJson(401, array('error' => 'Az első beállítás adatai hibásak.'));
        }
        $passwordHash = password_hash($password, PASSWORD_DEFAULT);
        if (!is_string($passwordHash) || $passwordHash === '') {
            throw new RuntimeException('A jelszó biztonságos hashelése nem sikerült.');
        }
        $configuredRobotToken = (string) ($config['robot_runtime_token'] ?? '');
        $robotTokenHash = strlen($configuredRobotToken) >= 24
            ? hash('sha256', $configuredRobotToken)
            : null;
        $isAdmin = 1;
        $statement = $connection->prepare(
            'INSERT INTO btc_usdc_auth_users '
            . '(state_key, username, password_hash, robot_token_hash, is_admin) '
            . 'VALUES (?, ?, ?, ?, ?)'
        );
        $statement->bind_param('ssssi', $stateKey, $username, $passwordHash, $robotTokenHash, $isAdmin);
        $statement->execute();
        $statement->close();
        clearLoginFailures($connection, $stateKey);
        $session = establishUserSession($config, $stateKey, $username, true, 'password', false);
        respondJson(201, authPayload($session, true, 0));
    }

    if ($action !== 'login') {
        respondJson(422, array('error' => 'Ismeretlen hitelesítési művelet.'));
    }
    if (!$configured) {
        respondJson(503, array('error' => 'Előbb végezd el az egyszeri belépési beállítást.', 'setupRequired' => true));
    }

    enforceLoginLimit($connection, $stateKey);
    $username = trim((string) ($request['username'] ?? ''));
    $password = (string) ($request['password'] ?? '');
    $user = preg_match('/^[A-Za-z0-9_.-]{3,64}$/', $username)
        ? readAuthUser($connection, $username)
        : null;
    $comparisonHash = $user['password_hash'] ?? password_hash('invalid-login-placeholder', PASSWORD_DEFAULT);
    $passwordMatches = is_string($comparisonHash) && password_verify($password, $comparisonHash);
    if ($user === null || $user['disabled'] || !$passwordMatches) {
        recordLoginFailure($connection, $stateKey);
        usleep(350000);
        respondJson(401, array('error' => 'Hibás felhasználónév vagy jelszó.'));
    }

    if (password_needs_rehash($user['password_hash'], PASSWORD_DEFAULT)) {
        $newHash = password_hash($password, PASSWORD_DEFAULT);
        if (is_string($newHash) && $newHash !== '') {
            $userStateKey = $user['state_key'];
            $statement = $connection->prepare(
                'UPDATE btc_usdc_auth_users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP '
                . 'WHERE state_key = ?'
            );
            $statement->bind_param('ss', $newHash, $userStateKey);
            $statement->execute();
            $statement->close();
        }
    }
    clearLoginFailures($connection, $stateKey);
    $session = establishUserSession(
        $config,
        $user['state_key'],
        $user['username'],
        $user['is_admin'],
        'password',
        false
    );
    respondJson(200, authPayload($session, true, passkeyCount($connection, $user['state_key'])));
} catch (mysqli_sql_exception $exception) {
    error_log('BTC/USDC hitelesítési adatbázishiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A belépési adatbázis most nem érhető el. Ellenőrizd az új séma importálását.'));
} catch (Throwable $exception) {
    error_log('BTC/USDC hitelesítési hiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A belépés most nem érhető el.'));
}
