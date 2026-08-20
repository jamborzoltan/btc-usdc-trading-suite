<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

function readManagedUsers(mysqli $connection, array $session): array
{
    if ($session['is_admin']) {
        $statement = $connection->prepare(
            'SELECT username, is_admin, disabled, robot_token_hash IS NOT NULL, created_at '
            . 'FROM btc_usdc_auth_users ORDER BY username'
        );
    } else {
        $stateKey = $session['state_key'];
        $statement = $connection->prepare(
            'SELECT username, is_admin, disabled, robot_token_hash IS NOT NULL, created_at '
            . 'FROM btc_usdc_auth_users WHERE state_key = ? LIMIT 1'
        );
        $statement->bind_param('s', $stateKey);
    }
    $statement->execute();
    $statement->bind_result($username, $isAdmin, $disabled, $robotConfigured, $createdAt);
    $users = array();
    while ($statement->fetch()) {
        $users[] = array(
            'username' => (string) $username,
            'isAdmin' => (bool) $isAdmin,
            'disabled' => (bool) $disabled,
            'robotConfigured' => (bool) $robotConfigured,
            'createdAt' => (string) $createdAt,
        );
    }
    $statement->close();
    return $users;
}

function createRobotToken(): string
{
    return base64UrlEncode(random_bytes(32));
}

function requireAdministrator(array $session): void
{
    if (!$session['is_admin']) {
        respondJson(403, array('error' => 'Ehhez rendszergazdai jogosultság szükséges.'));
    }
}

$config = loadAppConfig();
$requestMethod = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
if ($requestMethod !== 'GET' && $requestMethod !== 'POST') {
    header('Allow: GET, POST');
    respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
}

try {
    $connection = openDatabase($config);
    ensureLegacyUserSecurity($connection, $config);
    $session = requireUserSession($config, $requestMethod === 'POST');

    if ($requestMethod === 'GET') {
        respondJson(200, array(
            'username' => $session['username'],
            'isAdmin' => $session['is_admin'],
            'users' => readManagedUsers($connection, $session),
        ));
    }

    $request = readJsonRequest();
    $action = strtolower(trim((string) ($request['action'] ?? '')));

    if ($action === 'create') {
        requireAdministrator($session);
        $username = validateAccountUsername((string) ($request['username'] ?? ''));
        $password = (string) ($request['password'] ?? '');
        validateAccountPassword($password);
        $passwordHash = password_hash($password, PASSWORD_DEFAULT);
        if (!is_string($passwordHash) || $passwordHash === '') {
            throw new RuntimeException('A jelszó biztonságos hashelése nem sikerült.');
        }

        $stateKey = 'user-' . bin2hex(random_bytes(16));
        $robotToken = createRobotToken();
        $robotTokenHash = hash('sha256', $robotToken);
        $statement = $connection->prepare(
            'INSERT INTO btc_usdc_auth_users '
            . '(state_key, username, password_hash, robot_token_hash, is_admin, disabled) '
            . 'VALUES (?, ?, ?, ?, 0, 0)'
        );
        $statement->bind_param('ssss', $stateKey, $username, $passwordHash, $robotTokenHash);
        $statement->execute();
        $statement->close();
        respondJson(201, array(
            'ok' => true,
            'username' => $username,
            'robotToken' => $robotToken,
            'message' => 'A felhasználó és a külön robot-hozzáférés elkészült. A tokent most mentsd el, később nem kérhető le.',
        ));
    }

    if ($action === 'rotate_robot_token') {
        if (($request['confirm'] ?? false) !== true) {
            respondJson(422, array('error' => 'A robot-token cseréjét külön meg kell erősíteni.'));
        }
        $targetUsername = trim((string) ($request['username'] ?? $session['username']));
        if (!$session['is_admin'] && !hash_equals($session['username'], $targetUsername)) {
            respondJson(403, array('error' => 'Csak a saját robot-tokened cserélhető.'));
        }
        if (!preg_match('/^[A-Za-z0-9_.-]{3,64}$/', $targetUsername)) {
            respondJson(422, array('error' => 'Érvénytelen felhasználónév.'));
        }

        $robotToken = createRobotToken();
        $robotTokenHash = hash('sha256', $robotToken);
        $statement = $connection->prepare(
            'UPDATE btc_usdc_auth_users SET robot_token_hash = ? '
            . 'WHERE username = ? AND disabled = 0'
        );
        $statement->bind_param('ss', $robotTokenHash, $targetUsername);
        $statement->execute();
        $updated = $statement->affected_rows === 1;
        $statement->close();
        if (!$updated) {
            respondJson(404, array('error' => 'Az aktív felhasználó nem található.'));
        }
        respondJson(200, array(
            'ok' => true,
            'username' => $targetUsername,
            'robotToken' => $robotToken,
            'message' => 'Az előző robot-token azonnal érvénytelen lett. Az új tokent most mentsd el.',
        ));
    }

    respondJson(422, array('error' => 'Ismeretlen felhasználókezelési művelet.'));
} catch (mysqli_sql_exception $exception) {
    if ((int) $exception->getCode() === 1062) {
        respondJson(409, array('error' => 'Ez a felhasználónév már foglalt.'));
    }
    error_log('BTC/USDC felhasználókezelési adatbázishiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A felhasználókezelés adatbázisa most nem érhető el. Ellenőrizd az új séma importálását.'));
} catch (Throwable $exception) {
    error_log('BTC/USDC felhasználókezelési hiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A felhasználókezelés most nem érhető el.'));
}
