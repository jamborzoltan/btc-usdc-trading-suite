<?php
declare(strict_types=1);

/*
 * A mini PC-n futó robot rövid életjelét külön rekordban tárolja.
 * Így az állapotfrissítés nem írhatja felül a webapp kapcsolóinak értékét.
 * Minden SQL-művelet prepared mysqli lekérdezés.
 */

const MAX_RUNTIME_BYTES = 65536;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');

function respondJson(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function loadConfig(): array
{
    $configPath = __DIR__ . DIRECTORY_SEPARATOR . 'config.php';
    if (!is_file($configPath)) {
        respondJson(503, array('error' => 'A MySQL konfiguráció még nincs beállítva.'));
    }
    $config = require $configPath;
    if (!is_array($config)) {
        respondJson(503, array('error' => 'Érvénytelen MySQL konfiguráció.'));
    }
    return $config;
}

function readRuntimeRequest(): array
{
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || strlen($rawBody) > MAX_RUNTIME_BYTES) {
        respondJson(413, array('error' => 'Túl nagy robot-státusz kérés.'));
    }
    try {
        $request = json_decode($rawBody, true, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException $exception) {
        respondJson(400, array('error' => 'Érvénytelen JSON kérés.'));
    }
    if (!is_array($request) || !isset($request['runtime']) || !is_array($request['runtime'])) {
        respondJson(422, array('error' => 'Hiányzó vagy érvénytelen robot-státusz.'));
    }
    try {
        $runtimeJson = json_encode($request['runtime'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    } catch (JsonException $exception) {
        respondJson(422, array('error' => 'A robot-státusz nem menthető.'));
    }
    if (strlen($runtimeJson) > MAX_RUNTIME_BYTES) {
        respondJson(413, array('error' => 'A robot-státusz túl nagy.'));
    }
    return array('runtime_json' => $runtimeJson);
}

$config = loadConfig();
$stateKey = (string) ($config['state_key'] ?? 'btc-usdc-sajat-robot');
if (!preg_match('/^[A-Za-z0-9_.-]{1,64}$/', $stateKey)) {
    respondJson(503, array('error' => 'Érvénytelen közös állapotazonosító.'));
}

try {
    mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
    $connection = new mysqli(
        (string) ($config['db_host'] ?? ''),
        (string) ($config['db_user'] ?? ''),
        (string) ($config['db_password'] ?? ''),
        (string) ($config['db_name'] ?? ''),
        (int) ($config['db_port'] ?? 3306)
    );
    $connection->set_charset('utf8mb4');

    if ($_SERVER['REQUEST_METHOD'] === 'GET') {
        $statement = $connection->prepare(
            'SELECT payload, updated_at FROM btc_usdc_robot_runtime WHERE state_key = ? LIMIT 1'
        );
        $statement->bind_param('s', $stateKey);
        $statement->execute();
        $statement->bind_result($payload, $updatedAt);
        $found = $statement->fetch();
        $statement->close();
        if (!$found) {
            respondJson(200, array('runtime' => null, 'updatedAt' => null));
        }
        $runtime = json_decode($payload, true);
        if (!is_array($runtime)) {
            throw new RuntimeException('A tárolt robot-státusz sérült.');
        }
        respondJson(200, array('runtime' => $runtime, 'updatedAt' => $updatedAt));
    }

    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        header('Allow: GET, POST');
        respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
    }

    $expectedToken = (string) ($config['robot_runtime_token'] ?? '');
    $providedToken = (string) ($_SERVER['HTTP_X_ROBOT_TOKEN'] ?? '');
    if (strlen($expectedToken) < 24 || !hash_equals($expectedToken, $providedToken)) {
        respondJson(403, array('error' => 'Érvénytelen robot-státusz hitelesítés.'));
    }

    $request = readRuntimeRequest();
    $statement = $connection->prepare(
        'INSERT INTO btc_usdc_robot_runtime (state_key, payload) VALUES (?, ?) '
        . 'ON DUPLICATE KEY UPDATE payload = VALUES(payload), updated_at = CURRENT_TIMESTAMP'
    );
    $statement->bind_param('ss', $stateKey, $request['runtime_json']);
    $statement->execute();
    $statement->close();
    respondJson(200, array('ok' => true));
} catch (Throwable $exception) {
    error_log('BTC/USDC robot-státusz hiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A robot-státusz MySQL tárolása most nem érhető el.'));
}
