<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

/*
 * Strukturált, egyfelhasználós robotbeállítás-API.
 *
 * A kliensszerződés továbbra is {portfolio, revision}, de a stabil botmezők
 * külön MySQL-oszlopokba kerülnek. A régi btc_usdc_robot_state.payload tábla
 * csak olvasott migrációs forrás; sikeres átvétel után már nem írjuk.
 */

const MAX_STATE_REQUEST_BYTES = 65536;
const BOT_STRATEGIES = array('trend', 'momentum', 'mean_reversion', 'trend_impulse');

function stateTableExists(mysqli $connection, string $tableName): bool
{
    $statement = $connection->prepare(
        'SELECT 1 FROM information_schema.tables '
        . 'WHERE table_schema = DATABASE() AND table_name = ? LIMIT 1'
    );
    $statement->bind_param('s', $tableName);
    $statement->execute();
    $statement->bind_result($exists);
    $found = $statement->fetch();
    $statement->close();
    return (bool) $found;
}

function invalidBotState(bool $strict, string $message): void
{
    if ($strict) {
        respondJson(422, array('error' => $message));
    }
    throw new RuntimeException($message);
}

function botNumber(
    array $bot,
    string $key,
    float $default,
    float $minimum,
    float $maximum,
    bool $strict
): float {
    $value = $bot[$key] ?? $default;
    if (!is_int($value) && !is_float($value)) {
        if ($strict) {
            invalidBotState(true, 'A(z) ' . $key . ' mező nem szám.');
        }
        $value = $default;
    }
    $number = (float) $value;
    if (!is_finite($number) || $number < $minimum || $number > $maximum) {
        if ($strict) {
            invalidBotState(true, 'A(z) ' . $key . ' mező kívül esik az engedélyezett tartományon.');
        }
        $number = max($minimum, min($maximum, is_finite($number) ? $number : $default));
    }
    return $number;
}

function botInteger(
    array $bot,
    string $key,
    int $default,
    int $minimum,
    int $maximum,
    bool $strict
): int {
    $value = $bot[$key] ?? $default;
    if (!is_int($value) && !(is_float($value) && floor($value) === $value)) {
        if ($strict) {
            invalidBotState(true, 'A(z) ' . $key . ' mező nem egész szám.');
        }
        $value = $default;
    }
    $number = (int) $value;
    if ($number < $minimum || $number > $maximum) {
        if ($strict) {
            invalidBotState(true, 'A(z) ' . $key . ' mező kívül esik az engedélyezett tartományon.');
        }
        $number = max($minimum, min($maximum, $number));
    }
    return $number;
}

function normalizeBotPortfolio(array $portfolio, bool $strict): array
{
    $bot = $portfolio['bot'] ?? null;
    if (!is_array($bot)) {
        invalidBotState($strict, 'Hiányzó vagy érvénytelen robotbeállítás.');
    }

    $strategyType = (string) ($bot['strategyType'] ?? 'trend');
    if (!in_array($strategyType, BOT_STRATEGIES, true)) {
        if ($strict) {
            invalidBotState(true, 'Ismeretlen stratégia.');
        }
        $strategyType = 'trend';
    }

    $strategyInterval = botInteger($bot, 'strategyInterval', 60, 15, 60, $strict);
    if ($strategyInterval !== 15 && $strategyInterval !== 60) {
        if ($strict) {
            invalidBotState(true, 'A stratégia idősíkja csak 15 vagy 60 perc lehet.');
        }
        $strategyInterval = 60;
    }

    $botVersion = botInteger($bot, 'version', 8, 1, 9, $strict);
    $leverage = botInteger($bot, 'leverage', 1, 1, 125, $strict);

    // Régi böngészőcache vagy legacy payload még marginPercent mezőt küldhet.
    // A százalék összegegyenértéke számlaegyenleg nélkül nem számítható ki,
    // ezért egyszeri kezdőértékként ugyanazt a numerikus értéket vesszük át.
    if (!array_key_exists('marginUsdc', $bot) && array_key_exists('marginPercent', $bot)) {
        $bot['marginUsdc'] = $bot['marginPercent'];
    }

    if ($botVersion < 9) {
        $legacyStopPricePercent = botNumber($bot, 'stopLossPercent', 2, 0.25, 20, $strict);
        $stopLossPercent = max(1, min(100, $legacyStopPricePercent * $leverage));
    } else {
        $stopLossPercent = botNumber($bot, 'stopLossPercent', 50, 1, 100, $strict);
    }

    $enabled = $bot['enabled'] ?? false;
    $stopOnCandleClose = $bot['stopOnCandleClose'] ?? true;
    if (!is_bool($enabled)) {
        if ($strict) {
            invalidBotState(true, 'Az enabled mező nem logikai érték.');
        }
        $enabled = (bool) $enabled;
    }
    if (!is_bool($stopOnCandleClose)) {
        if ($strict) {
            invalidBotState(true, 'A stopOnCandleClose mező nem logikai érték.');
        }
        $stopOnCandleClose = (bool) $stopOnCandleClose;
    }

    return array('bot' => array(
        'version' => 9,
        'enabled' => $enabled,
        'strategyType' => $strategyType,
        'strategyInterval' => $strategyInterval,
        'leverage' => $leverage,
        'marginUsdc' => round(botNumber($bot, 'marginUsdc', 20, 0.01, 100000000, $strict), 2),
        'stopLossPercent' => $stopLossPercent,
        'trailingStopPercent' => botNumber($bot, 'trailingStopPercent', 1.5, 0.25, 20, $strict),
        'partialTakeProfitPercent' => botNumber($bot, 'partialTakeProfitPercent', 0, 0, 20, $strict),
        'partialClosePercent' => botNumber($bot, 'partialClosePercent', 50, 10, 90, $strict),
        'profitFadePercent' => botNumber($bot, 'profitFadePercent', 1, 0, 10, $strict),
        'profitFadeClosePercent' => botNumber($bot, 'profitFadeClosePercent', 100, 10, 100, $strict),
        'stopOnCandleClose' => $stopOnCandleClose,
    ));
}

function readStructuredState(mysqli $connection, string $stateKey): ?array
{
    $statement = $connection->prepare(
        'SELECT bot_version, enabled, strategy_type, strategy_interval, leverage, '
        . 'margin_usdc, stop_loss_percent, trailing_stop_percent, '
        . 'partial_take_profit_percent, partial_close_percent, profit_fade_percent, '
        . 'profit_fade_close_percent, stop_on_candle_close, revision '
        . 'FROM btc_usdc_bot_settings WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $botVersion,
        $enabled,
        $strategyType,
        $strategyInterval,
        $leverage,
        $marginUsdc,
        $stopLossPercent,
        $trailingStopPercent,
        $partialTakeProfitPercent,
        $partialClosePercent,
        $profitFadePercent,
        $profitFadeClosePercent,
        $stopOnCandleClose,
        $revision
    );
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }

    $portfolio = normalizeBotPortfolio(array('bot' => array(
            'version' => (int) $botVersion,
            'enabled' => (bool) $enabled,
            'strategyType' => (string) $strategyType,
            'strategyInterval' => (int) $strategyInterval,
            'leverage' => (int) $leverage,
            'marginUsdc' => (float) $marginUsdc,
            'stopLossPercent' => (float) $stopLossPercent,
            'trailingStopPercent' => (float) $trailingStopPercent,
            'partialTakeProfitPercent' => (float) $partialTakeProfitPercent,
            'partialClosePercent' => (float) $partialClosePercent,
            'profitFadePercent' => (float) $profitFadePercent,
            'profitFadeClosePercent' => (float) $profitFadeClosePercent,
            'stopOnCandleClose' => (bool) $stopOnCandleClose,
        )), false);

    return array(
        'portfolio' => $portfolio,
        'revision' => (int) $revision,
    );
}

function readLegacyState(mysqli $connection, string $stateKey): ?array
{
    if (!stateTableExists($connection, 'btc_usdc_robot_state')) {
        return null;
    }
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
    $portfolio = json_decode((string) $payload, true);
    if (!is_array($portfolio)) {
        throw new RuntimeException('A régi robotállapot payload mezője sérült.');
    }
    return array(
        'portfolio' => normalizeBotPortfolio($portfolio, false),
        'revision' => max(1, (int) $revision),
    );
}

function insertStructuredState(
    mysqli $connection,
    string $stateKey,
    array $portfolio,
    int $revision,
    bool $ignoreDuplicate = false
): bool {
    $bot = $portfolio['bot'];
    $sql = 'INSERT ' . ($ignoreDuplicate ? 'IGNORE ' : '') . 'INTO btc_usdc_bot_settings '
        . '(state_key, bot_version, enabled, strategy_type, strategy_interval, leverage, '
        . 'margin_usdc, stop_loss_percent, trailing_stop_percent, partial_take_profit_percent, '
        . 'partial_close_percent, profit_fade_percent, profit_fade_close_percent, '
        . 'stop_on_candle_close, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)';
    $statement = $connection->prepare($sql);
    $botVersion = (int) $bot['version'];
    $enabled = $bot['enabled'] ? 1 : 0;
    $strategyType = (string) $bot['strategyType'];
    $strategyInterval = (int) $bot['strategyInterval'];
    $leverage = (int) $bot['leverage'];
    $marginUsdc = (float) $bot['marginUsdc'];
    $stopLossPercent = (float) $bot['stopLossPercent'];
    $trailingStopPercent = (float) $bot['trailingStopPercent'];
    $partialTakeProfitPercent = (float) $bot['partialTakeProfitPercent'];
    $partialClosePercent = (float) $bot['partialClosePercent'];
    $profitFadePercent = (float) $bot['profitFadePercent'];
    $profitFadeClosePercent = (float) $bot['profitFadeClosePercent'];
    $stopOnCandleClose = $bot['stopOnCandleClose'] ? 1 : 0;
    $statement->bind_param(
        'siisiidddddddii',
        $stateKey,
        $botVersion,
        $enabled,
        $strategyType,
        $strategyInterval,
        $leverage,
        $marginUsdc,
        $stopLossPercent,
        $trailingStopPercent,
        $partialTakeProfitPercent,
        $partialClosePercent,
        $profitFadePercent,
        $profitFadeClosePercent,
        $stopOnCandleClose,
        $revision
    );
    $statement->execute();
    $inserted = $statement->affected_rows === 1;
    $statement->close();
    return $inserted;
}

function readCurrentState(mysqli $connection, string $stateKey): ?array
{
    $state = readStructuredState($connection, $stateKey);
    if ($state !== null) {
        return $state;
    }

    $legacy = readLegacyState($connection, $stateKey);
    if ($legacy === null) {
        return null;
    }
    insertStructuredState(
        $connection,
        $stateKey,
        $legacy['portfolio'],
        $legacy['revision'],
        true
    );
    return readStructuredState($connection, $stateKey);
}

function readStateRequest(): array
{
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > MAX_STATE_REQUEST_BYTES) {
        respondJson(413, array('error' => 'Túl nagy mentési kérés.'));
    }
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || strlen($rawBody) > MAX_STATE_REQUEST_BYTES) {
        respondJson(413, array('error' => 'Túl nagy mentési kérés.'));
    }
    try {
        $request = json_decode($rawBody, true, 16, JSON_THROW_ON_ERROR);
    } catch (JsonException $exception) {
        respondJson(400, array('error' => 'Érvénytelen JSON kérés.'));
    }
    if (!is_array($request) || !isset($request['portfolio']) || !is_array($request['portfolio'])) {
        respondJson(422, array('error' => 'Hiányzó vagy érvénytelen portfólióadat.'));
    }
    if (!array_key_exists('revision', $request) || !is_int($request['revision']) || $request['revision'] < 0) {
        respondJson(422, array('error' => 'Hiányzó vagy érvénytelen állapotverzió.'));
    }
    return array(
        'portfolio' => normalizeBotPortfolio($request['portfolio'], true),
        'revision' => $request['revision'],
    );
}

function updateStructuredState(
    mysqli $connection,
    string $stateKey,
    array $portfolio,
    int $expectedRevision
): bool {
    $bot = $portfolio['bot'];
    $statement = $connection->prepare(
        'UPDATE btc_usdc_bot_settings SET bot_version = ?, enabled = ?, strategy_type = ?, '
        . 'strategy_interval = ?, leverage = ?, margin_usdc = ?, stop_loss_percent = ?, '
        . 'trailing_stop_percent = ?, partial_take_profit_percent = ?, partial_close_percent = ?, '
        . 'profit_fade_percent = ?, profit_fade_close_percent = ?, stop_on_candle_close = ?, '
        . 'revision = revision + 1 WHERE state_key = ? AND revision = ?'
    );
    $botVersion = (int) $bot['version'];
    $enabled = $bot['enabled'] ? 1 : 0;
    $strategyType = (string) $bot['strategyType'];
    $strategyInterval = (int) $bot['strategyInterval'];
    $leverage = (int) $bot['leverage'];
    $marginUsdc = (float) $bot['marginUsdc'];
    $stopLossPercent = (float) $bot['stopLossPercent'];
    $trailingStopPercent = (float) $bot['trailingStopPercent'];
    $partialTakeProfitPercent = (float) $bot['partialTakeProfitPercent'];
    $partialClosePercent = (float) $bot['partialClosePercent'];
    $profitFadePercent = (float) $bot['profitFadePercent'];
    $profitFadeClosePercent = (float) $bot['profitFadeClosePercent'];
    $stopOnCandleClose = $bot['stopOnCandleClose'] ? 1 : 0;
    $statement->bind_param(
        'iisiidddddddisi',
        $botVersion,
        $enabled,
        $strategyType,
        $strategyInterval,
        $leverage,
        $marginUsdc,
        $stopLossPercent,
        $trailingStopPercent,
        $partialTakeProfitPercent,
        $partialClosePercent,
        $profitFadePercent,
        $profitFadeClosePercent,
        $stopOnCandleClose,
        $stateKey,
        $expectedRevision
    );
    $statement->execute();
    $updated = $statement->affected_rows === 1;
    $statement->close();
    return $updated;
}

$config = loadAppConfig();
$stateKey = validatedStateKey($config);
$requestMethod = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
if ($requestMethod !== 'GET' && $requestMethod !== 'POST') {
    header('Allow: GET, POST');
    respondJson(405, array('error' => 'Csak GET és POST kérés engedélyezett.'));
}
if ($requestMethod === 'GET') {
    if (!hasValidRobotToken($config)) {
        requireUserSession($config);
    }
} else {
    requireUserSession($config, true);
}

try {
    $connection = openDatabase($config);
    if ($requestMethod === 'GET') {
        $state = readCurrentState($connection, $stateKey);
        respondJson(200, array(
            'portfolio' => $state['portfolio'] ?? null,
            'revision' => $state['revision'] ?? 0,
        ));
    }

    $request = readStateRequest();
    $expectedRevision = $request['revision'];
    $current = readCurrentState($connection, $stateKey);
    $updated = false;
    if ($current === null && $expectedRevision === 0) {
        try {
            $updated = insertStructuredState($connection, $stateKey, $request['portfolio'], 1);
        } catch (mysqli_sql_exception $exception) {
            if ((int) $exception->getCode() !== 1062) {
                throw $exception;
            }
        }
    } elseif ($current !== null) {
        $updated = updateStructuredState($connection, $stateKey, $request['portfolio'], $expectedRevision);
    }

    if (!$updated) {
        $current = readCurrentState($connection, $stateKey);
        respondJson(409, array(
            'error' => 'A közös állapot közben megváltozott.',
            'portfolio' => $current['portfolio'] ?? null,
            'revision' => $current['revision'] ?? 0,
        ));
    }
    respondJson(200, array('ok' => true, 'revision' => $expectedRevision + 1));
} catch (Throwable $exception) {
    error_log('BTC/USDC strukturált állapothiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A strukturált MySQL állapot most nem érhető el. Ellenőrizd az új séma importálását.'));
}
