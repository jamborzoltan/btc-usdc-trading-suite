<?php
declare(strict_types=1);

/*
 * Közös, egyfelhasználós robotállapot API.
 * Minden adatbázis-művelet előkészített mysqli lekérdezést használ.
 */

const MAX_PAYLOAD_BYTES = 1048576;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');

function respondJson(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function readCurrentState(mysqli $connection, string $stateKey): ?array
{
    $statement = $connection->prepare(
        'SELECT payload, revision FROM btc_usdc_robot_state WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result($payload, $revision);
    $found = $statement->fetch();
    $statement->close();

    if (!$found) {
        return null;
    }

    $portfolio = json_decode($payload, true);
    if (!is_array($portfolio)) {
        throw new RuntimeException('A tárolt robotállapot sérült.');
    }

    return array('portfolio' => $portfolio, 'revision' => (int) $revision);
}

function readRequestPayload(): array
{
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > MAX_PAYLOAD_BYTES) {
        respondJson(413, array('error' => 'Túl nagy mentési kérés.'));
    }

    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || strlen($rawBody) > MAX_PAYLOAD_BYTES) {
        respondJson(413, array('error' => 'Túl nagy mentési kérés.'));
    }

    try {
        $request = json_decode($rawBody, true, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException $exception) {
        respondJson(400, array('error' => 'Érvénytelen JSON kérés.'));
    }

    if (!is_array($request) || !isset($request['portfolio']) || !is_array($request['portfolio'])) {
        respondJson(422, array('error' => 'Hiányzó vagy érvénytelen portfólióadat.'));
    }
    if (!array_key_exists('revision', $request) || !is_int($request['revision']) || $request['revision'] < 0) {
        respondJson(422, array('error' => 'Hiányzó vagy érvénytelen állapotverzió.'));
    }

    try {
        $portfolioJson = json_encode(
            $request['portfolio'],
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR
        );
    } catch (JsonException $exception) {
        respondJson(422, array('error' => 'A portfólió nem menthető JSON formátumban.'));
    }
    if (strlen($portfolioJson) > MAX_PAYLOAD_BYTES) {
        respondJson(413, array('error' => 'A portfólió túl nagy a mentéshez.'));
    }

    return array(
        'portfolio_json' => $portfolioJson,
        'revision' => $request['revision'],
    );
}

$configPath = __DIR__ . DIRECTORY_SEPARATOR . 'config.php';
if (!is_file($configPath)) {
    respondJson(503, array('error' => 'A közös MySQL tárolás még nincs beállítva.'));
}

$config = require $configPath;
if (!is_array($config)) {
    respondJson(503, array('error' => 'Érvénytelen MySQL konfiguráció.'));
}

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
        $state = readCurrentState($connection, $stateKey);
        respondJson(200, array(
            'portfolio' => $state['portfolio'] ?? null,
            'revision' => $state['revision'] ?? 0,
        ));
    }

    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        header('Allow: GET, POST');
        respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
    }

    $request = readRequestPayload();
    $expectedRevision = $request['revision'];
    $statement = $connection->prepare(
        'UPDATE btc_usdc_robot_state SET payload = ?, revision = revision + 1 WHERE state_key = ? AND revision = ?'
    );
    $statement->bind_param('ssi', $request['portfolio_json'], $stateKey, $expectedRevision);
    $statement->execute();
    $updated = $statement->affected_rows === 1;
    $statement->close();

    if (!$updated && $expectedRevision === 0) {
        try {
            $firstRevision = 1;
            $statement = $connection->prepare(
                'INSERT INTO btc_usdc_robot_state (state_key, payload, revision) VALUES (?, ?, ?)'
            );
            $statement->bind_param('ssi', $stateKey, $request['portfolio_json'], $firstRevision);
            $statement->execute();
            $updated = $statement->affected_rows === 1;
            $statement->close();
        } catch (mysqli_sql_exception $exception) {
            if ((int) $exception->getCode() !== 1062) {
                throw $exception;
            }
        }
    }

    if (!$updated) {
        $state = readCurrentState($connection, $stateKey);
        respondJson(409, array(
            'error' => 'A közös állapot közben megváltozott.',
            'portfolio' => $state['portfolio'] ?? null,
            'revision' => $state['revision'] ?? 0,
        ));
    }

    respondJson(200, array('ok' => true, 'revision' => $expectedRevision + 1));
} catch (Throwable $exception) {
    error_log('BTC/USDC közös állapot hiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A közös MySQL tárolás most nem érhető el.'));
}
