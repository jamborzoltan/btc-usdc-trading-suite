<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

/*
 * A mini PC-n futó robot rövid életjelét külön rekordban tárolja.
 * Így az állapotfrissítés nem írhatja felül a webapp kapcsolóinak értékét.
 * Minden SQL-művelet prepared mysqli lekérdezés.
 */

const MAX_RUNTIME_BYTES = 65536;

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

$config = loadAppConfig();
$stateKey = validatedStateKey($config);
$requestMethod = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
if ($requestMethod !== 'GET' && $requestMethod !== 'POST') {
    header('Allow: GET, POST');
    respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
}
if ($requestMethod === 'GET') {
    requireUserSession($config);
} elseif ($requestMethod === 'POST') {
    requireRobotToken($config);
}

try {
    $connection = openDatabase($config);

    if ($requestMethod === 'GET') {
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
