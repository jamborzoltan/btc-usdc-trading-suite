<?php
declare(strict_types=1);

require_once __DIR__ . DIRECTORY_SEPARATOR . 'auth-common.php';

/*
 * A mini PC strukturált, rövid életű futási pillanatképe.
 *
 * A státusz, stratégia, divergenciák, Binance-számla és pozíciók külön
 * táblákban vannak, miközben a HTTP API továbbra is a robot és a webapp által
 * ismert runtime objektumot fogadja és adja vissza.
 */

const MAX_RUNTIME_BYTES = 65536;
const MAX_OPEN_POSITIONS = 20;

function runtimeTableExists(mysqli $connection, string $tableName): bool
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

function readRuntimeRequest(): array
{
    $contentLength = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($contentLength > MAX_RUNTIME_BYTES) {
        respondJson(413, array('error' => 'Túl nagy robot-státusz kérés.'));
    }
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
    $positions = $request['runtime']['account']['positions'] ?? array();
    if (!is_array($positions) || count($positions) > MAX_OPEN_POSITIONS) {
        respondJson(422, array('error' => 'Érvénytelen vagy túl sok nyitott pozíció.'));
    }
    return $request['runtime'];
}

function runtimeString(array $source, string $key, string $default, int $maximum): string
{
    $value = trim((string) ($source[$key] ?? $default));
    if ($value === '') {
        $value = $default;
    }
    return function_exists('mb_substr')
        ? mb_substr($value, 0, $maximum, 'UTF-8')
        : substr($value, 0, $maximum);
}

function runtimeNumber(array $source, string $key, ?float $default = null): ?float
{
    $value = $source[$key] ?? null;
    if (!is_int($value) && !is_float($value)) {
        return $default;
    }
    $number = (float) $value;
    return is_finite($number) ? $number : $default;
}

function runtimeInteger(array $source, string $key, int $default = 0): int
{
    $value = $source[$key] ?? $default;
    if (!is_int($value) && !(is_float($value) && floor($value) === $value)) {
        return $default;
    }
    return (int) $value;
}

function runtimeDateTime(array $source, string $key): ?string
{
    $value = trim((string) ($source[$key] ?? ''));
    if ($value === '') {
        return null;
    }
    try {
        return (new DateTimeImmutable($value))
            ->setTimezone(new DateTimeZone('UTC'))
            ->format('Y-m-d H:i:s');
    } catch (Throwable $exception) {
        return null;
    }
}

function runtimeIsoDate(?string $mysqlDate): ?string
{
    if ($mysqlDate === null || $mysqlDate === '') {
        return null;
    }
    return str_replace(' ', 'T', $mysqlDate) . 'Z';
}

function writeRobotStatus(mysqli $connection, string $stateKey, array $runtime): void
{
    $statement = $connection->prepare(
        'INSERT INTO btc_usdc_robot_status '
        . '(state_key, runtime_version, mode, execution_state, status, heartbeat_at, '
        . 'poll_seconds, price, change_24h, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        . 'ON DUPLICATE KEY UPDATE runtime_version = VALUES(runtime_version), mode = VALUES(mode), '
        . 'execution_state = VALUES(execution_state), status = VALUES(status), '
        . 'heartbeat_at = VALUES(heartbeat_at), poll_seconds = VALUES(poll_seconds), '
        . 'price = VALUES(price), change_24h = VALUES(change_24h), message = VALUES(message), '
        . 'updated_at = CURRENT_TIMESTAMP'
    );
    $version = max(1, runtimeInteger($runtime, 'version', 2));
    $mode = runtimeString($runtime, 'mode', 'live_read_only', 32);
    $execution = runtimeString($runtime, 'execution', 'locked', 32);
    $status = runtimeString($runtime, 'status', 'unknown', 32);
    $heartbeatAt = runtimeDateTime($runtime, 'heartbeat_at');
    $pollSeconds = max(0.1, runtimeNumber($runtime, 'poll_seconds', 5.0) ?? 5.0);
    $price = runtimeNumber($runtime, 'price');
    $change24h = runtimeNumber($runtime, 'change_24h');
    $message = runtimeString($runtime, 'message', '', 4096);
    $statement->bind_param(
        'sissssddds',
        $stateKey,
        $version,
        $mode,
        $execution,
        $status,
        $heartbeatAt,
        $pollSeconds,
        $price,
        $change24h,
        $message
    );
    $statement->execute();
    $statement->close();
}

function writeStrategySnapshot(mysqli $connection, string $stateKey, mixed $value): void
{
    if (!is_array($value)) {
        $statement = $connection->prepare('DELETE FROM btc_usdc_strategy_snapshot WHERE state_key = ?');
        $statement->bind_param('s', $stateKey);
        $statement->execute();
        $statement->close();
        return;
    }

    $statement = $connection->prepare(
        'INSERT INTO btc_usdc_strategy_snapshot '
        . '(state_key, strategy_type, strategy_label, candle_interval, price, candle_time, '
        . 'trade_signal, reason, market_context, fast_ema, slow_ema, momentum_percent, '
        . 'middle_band, lower_band, upper_band, signal_key) '
        . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        . 'ON DUPLICATE KEY UPDATE strategy_type = VALUES(strategy_type), '
        . 'strategy_label = VALUES(strategy_label), candle_interval = VALUES(candle_interval), '
        . 'price = VALUES(price), candle_time = VALUES(candle_time), '
        . 'trade_signal = VALUES(trade_signal), '
        . 'reason = VALUES(reason), market_context = VALUES(market_context), '
        . 'fast_ema = VALUES(fast_ema), slow_ema = VALUES(slow_ema), '
        . 'momentum_percent = VALUES(momentum_percent), middle_band = VALUES(middle_band), '
        . 'lower_band = VALUES(lower_band), upper_band = VALUES(upper_band), '
        . 'signal_key = VALUES(signal_key), updated_at = CURRENT_TIMESTAMP'
    );
    $strategyType = runtimeString($value, 'strategy_type', 'unknown', 32);
    $strategyLabel = runtimeString($value, 'strategy_label', $strategyType, 64);
    $interval = max(1, runtimeInteger($value, 'interval', 60));
    $price = runtimeNumber($value, 'price', 0.0) ?? 0.0;
    $candleTime = max(0, runtimeInteger($value, 'candle_time'));
    $signal = runtimeString($value, 'signal', 'hold', 16);
    $reason = runtimeString($value, 'reason', '', 4096);
    $context = runtimeString($value, 'context', 'unknown', 32);
    $fastEma = runtimeNumber($value, 'fast_ema');
    $slowEma = runtimeNumber($value, 'slow_ema');
    $momentumPercent = runtimeNumber($value, 'momentum_percent');
    $middleBand = runtimeNumber($value, 'middle_band');
    $lowerBand = runtimeNumber($value, 'lower_band');
    $upperBand = runtimeNumber($value, 'upper_band');
    $signalKey = runtimeString($value, 'signal_key', '', 255);
    $statement->bind_param(
        'sssidisssdddddds',
        $stateKey,
        $strategyType,
        $strategyLabel,
        $interval,
        $price,
        $candleTime,
        $signal,
        $reason,
        $context,
        $fastEma,
        $slowEma,
        $momentumPercent,
        $middleBand,
        $lowerBand,
        $upperBand,
        $signalKey
    );
    $statement->execute();
    $statement->close();
}

function writeDivergenceSnapshots(mysqli $connection, string $stateKey, mixed $value): void
{
    $delete = $connection->prepare('DELETE FROM btc_usdc_divergence_snapshot WHERE state_key = ?');
    $delete->bind_param('s', $stateKey);
    $delete->execute();
    $delete->close();
    if (!is_array($value)) {
        return;
    }

    foreach (array_slice(array_values($value), 0, 2) as $item) {
        if (!is_array($item)) {
            continue;
        }
        $interval = runtimeInteger($item, 'interval');
        if ($interval !== 60 && $interval !== 1440) {
            continue;
        }
        $signal = runtimeString($item, 'signal', 'none', 16);
        if (!in_array($signal, array('none', 'bullish', 'bearish'), true)) {
            $signal = 'none';
        }
        $statement = $connection->prepare(
            'INSERT INTO btc_usdc_divergence_snapshot '
            . '(state_key, candle_interval, divergence_signal, rsi_period, current_rsi, '
            . 'price_from, price_to, rsi_from, rsi_to, pivot_from_time, pivot_to_time, '
            . 'age_candles, candle_time, reason) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $rsiPeriod = max(2, runtimeInteger($item, 'rsi_period', 14));
        $currentRsi = runtimeNumber($item, 'current_rsi');
        $priceFrom = runtimeNumber($item, 'price_from');
        $priceTo = runtimeNumber($item, 'price_to');
        $rsiFrom = runtimeNumber($item, 'rsi_from');
        $rsiTo = runtimeNumber($item, 'rsi_to');
        $pivotFromTime = max(0, runtimeInteger($item, 'pivot_from_time'));
        $pivotToTime = max(0, runtimeInteger($item, 'pivot_to_time'));
        $ageCandlesValue = runtimeInteger($item, 'age_candles', -1);
        $ageCandles = $ageCandlesValue < 0 ? null : $ageCandlesValue;
        $candleTime = max(0, runtimeInteger($item, 'candle_time'));
        $reason = runtimeString($item, 'reason', '', 4096);
        $statement->bind_param(
            'sisidddddiiiis',
            $stateKey,
            $interval,
            $signal,
            $rsiPeriod,
            $currentRsi,
            $priceFrom,
            $priceTo,
            $rsiFrom,
            $rsiTo,
            $pivotFromTime,
            $pivotToTime,
            $ageCandles,
            $candleTime,
            $reason
        );
        $statement->execute();
        $statement->close();
    }
}

function deleteAccountSnapshot(mysqli $connection, string $stateKey): void
{
    $statement = $connection->prepare('DELETE FROM btc_usdc_open_positions WHERE state_key = ?');
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->close();
    $statement = $connection->prepare('DELETE FROM btc_usdc_binance_account WHERE state_key = ?');
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->close();
}

function writeAccountSnapshot(mysqli $connection, string $stateKey, mixed $value): void
{
    if (!is_array($value)) {
        deleteAccountSnapshot($connection, $stateKey);
        return;
    }

    $statement = $connection->prepare(
        'INSERT INTO btc_usdc_binance_account '
        . '(state_key, connected, source, balance_asset, quote_asset, credit_mode, symbol, '
        . 'wallet_balance, available_balance, cross_wallet_balance, unrealized_pnl, '
        . 'margin_balance, max_withdraw_amount, margin_available, can_trade, position_mode, '
        . 'multi_assets_margin, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        . 'ON DUPLICATE KEY UPDATE connected = VALUES(connected), source = VALUES(source), '
        . 'balance_asset = VALUES(balance_asset), quote_asset = VALUES(quote_asset), '
        . 'credit_mode = VALUES(credit_mode), symbol = VALUES(symbol), '
        . 'wallet_balance = VALUES(wallet_balance), available_balance = VALUES(available_balance), '
        . 'cross_wallet_balance = VALUES(cross_wallet_balance), unrealized_pnl = VALUES(unrealized_pnl), '
        . 'margin_balance = VALUES(margin_balance), max_withdraw_amount = VALUES(max_withdraw_amount), '
        . 'margin_available = VALUES(margin_available), can_trade = VALUES(can_trade), '
        . 'position_mode = VALUES(position_mode), multi_assets_margin = VALUES(multi_assets_margin), '
        . 'fetched_at = VALUES(fetched_at), updated_at = CURRENT_TIMESTAMP'
    );
    $connected = !empty($value['connected']) ? 1 : 0;
    $source = runtimeString($value, 'source', 'binance-usdm', 32);
    $balanceAsset = strtoupper(runtimeString($value, 'asset', 'USDC', 16));
    $quoteAsset = strtoupper(runtimeString($value, 'quote_asset', 'USDC', 16));
    $creditMode = !empty($value['credit_mode']) ? 1 : 0;
    $symbol = strtoupper(runtimeString($value, 'symbol', 'BTCUSDC', 32));
    $walletBalance = runtimeNumber($value, 'wallet_balance', 0.0) ?? 0.0;
    $availableBalance = runtimeNumber($value, 'available_balance', 0.0) ?? 0.0;
    $crossWalletBalance = runtimeNumber($value, 'cross_wallet_balance', 0.0) ?? 0.0;
    $unrealizedPnl = runtimeNumber($value, 'unrealized_pnl', 0.0) ?? 0.0;
    $marginBalance = runtimeNumber($value, 'margin_balance', 0.0) ?? 0.0;
    $maxWithdrawAmount = runtimeNumber($value, 'max_withdraw_amount', 0.0) ?? 0.0;
    $marginAvailable = !array_key_exists('margin_available', $value) || !empty($value['margin_available']) ? 1 : 0;
    $canTrade = !empty($value['can_trade']) ? 1 : 0;
    $positionMode = runtimeString($value, 'position_mode', 'one_way', 16);
    $multiAssetsMargin = !empty($value['multi_assets_margin']) ? 1 : 0;
    $fetchedAt = runtimeDateTime($value, 'fetched_at');
    $statement->bind_param(
        'sisssisddddddiisis',
        $stateKey,
        $connected,
        $source,
        $balanceAsset,
        $quoteAsset,
        $creditMode,
        $symbol,
        $walletBalance,
        $availableBalance,
        $crossWalletBalance,
        $unrealizedPnl,
        $marginBalance,
        $maxWithdrawAmount,
        $marginAvailable,
        $canTrade,
        $positionMode,
        $multiAssetsMargin,
        $fetchedAt
    );
    $statement->execute();
    $statement->close();

    $statement = $connection->prepare('DELETE FROM btc_usdc_open_positions WHERE state_key = ?');
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->close();

    $positions = $value['positions'] ?? array();
    foreach ($positions as $position) {
        if (!is_array($position)) {
            continue;
        }
        $statement = $connection->prepare(
            'INSERT INTO btc_usdc_open_positions '
            . '(state_key, symbol, position_side, side, quantity, signed_quantity, entry_price, '
            . 'break_even_price, mark_price, liquidation_price, unrealized_pnl, notional, '
            . 'initial_margin, isolated_margin, leverage, margin_type, margin_asset, pnl_asset, '
            . 'exchange_update_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $positionSymbol = strtoupper(runtimeString($position, 'symbol', $symbol, 32));
        $positionSide = strtoupper(runtimeString($position, 'position_side', 'BOTH', 16));
        $side = runtimeString($position, 'side', 'long', 8);
        $quantity = runtimeNumber($position, 'quantity', 0.0) ?? 0.0;
        $signedQuantity = runtimeNumber($position, 'signed_quantity', 0.0) ?? 0.0;
        $entryPrice = runtimeNumber($position, 'entry_price', 0.0) ?? 0.0;
        $breakEvenPrice = runtimeNumber($position, 'break_even_price', 0.0) ?? 0.0;
        $markPrice = runtimeNumber($position, 'mark_price', 0.0) ?? 0.0;
        $liquidationPrice = runtimeNumber($position, 'liquidation_price', 0.0) ?? 0.0;
        $positionPnl = runtimeNumber($position, 'unrealized_pnl', 0.0) ?? 0.0;
        $notional = runtimeNumber($position, 'notional', 0.0) ?? 0.0;
        $initialMargin = runtimeNumber($position, 'initial_margin', 0.0) ?? 0.0;
        $isolatedMargin = runtimeNumber($position, 'isolated_margin', 0.0) ?? 0.0;
        $leverage = max(1, runtimeInteger($position, 'leverage', 1));
        $marginType = runtimeString($position, 'margin_type', '', 16);
        $marginAsset = strtoupper(runtimeString($position, 'margin_asset', 'USDC', 16));
        $pnlAsset = strtoupper(runtimeString($position, 'pnl_asset', $balanceAsset, 16));
        $exchangeUpdateTime = max(0, runtimeInteger($position, 'update_time'));
        $statement->bind_param(
            'ssssddddddddddisssi',
            $stateKey,
            $positionSymbol,
            $positionSide,
            $side,
            $quantity,
            $signedQuantity,
            $entryPrice,
            $breakEvenPrice,
            $markPrice,
            $liquidationPrice,
            $positionPnl,
            $notional,
            $initialMargin,
            $isolatedMargin,
            $leverage,
            $marginType,
            $marginAsset,
            $pnlAsset,
            $exchangeUpdateTime
        );
        $statement->execute();
        $statement->close();
    }
}

function readStrategySnapshot(mysqli $connection, string $stateKey): ?array
{
    $statement = $connection->prepare(
        'SELECT strategy_type, strategy_label, candle_interval, price, candle_time, trade_signal, '
        . 'reason, market_context, fast_ema, slow_ema, momentum_percent, middle_band, '
        . 'lower_band, upper_band, signal_key FROM btc_usdc_strategy_snapshot '
        . 'WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $strategyType,
        $strategyLabel,
        $interval,
        $price,
        $candleTime,
        $signal,
        $reason,
        $context,
        $fastEma,
        $slowEma,
        $momentumPercent,
        $middleBand,
        $lowerBand,
        $upperBand,
        $signalKey
    );
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }
    $strategy = array(
        'strategy_type' => (string) $strategyType,
        'strategy_label' => (string) $strategyLabel,
        'interval' => (int) $interval,
        'price' => (float) $price,
        'candle_time' => (int) $candleTime,
        'signal' => (string) $signal,
        'reason' => (string) $reason,
        'context' => (string) $context,
        'signal_key' => (string) $signalKey,
    );
    foreach (array(
        'fast_ema' => $fastEma,
        'slow_ema' => $slowEma,
        'momentum_percent' => $momentumPercent,
        'middle_band' => $middleBand,
        'lower_band' => $lowerBand,
        'upper_band' => $upperBand,
    ) as $key => $value) {
        if ($value !== null) {
            $strategy[$key] = (float) $value;
        }
    }
    return $strategy;
}

function readDivergenceSnapshots(mysqli $connection, string $stateKey): array
{
    $statement = $connection->prepare(
        'SELECT candle_interval, divergence_signal, rsi_period, current_rsi, price_from, '
        . 'price_to, rsi_from, rsi_to, pivot_from_time, pivot_to_time, age_candles, '
        . 'candle_time, reason FROM btc_usdc_divergence_snapshot '
        . 'WHERE state_key = ? ORDER BY candle_interval'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $interval,
        $signal,
        $rsiPeriod,
        $currentRsi,
        $priceFrom,
        $priceTo,
        $rsiFrom,
        $rsiTo,
        $pivotFromTime,
        $pivotToTime,
        $ageCandles,
        $candleTime,
        $reason
    );
    $results = array();
    while ($statement->fetch()) {
        $results[] = array(
            'interval' => (int) $interval,
            'timeframe' => (int) $interval === 60 ? '1 órás' : '1 napos',
            'signal' => (string) $signal,
            'rsi_period' => (int) $rsiPeriod,
            'current_rsi' => $currentRsi === null ? null : (float) $currentRsi,
            'price_from' => $priceFrom === null ? null : (float) $priceFrom,
            'price_to' => $priceTo === null ? null : (float) $priceTo,
            'rsi_from' => $rsiFrom === null ? null : (float) $rsiFrom,
            'rsi_to' => $rsiTo === null ? null : (float) $rsiTo,
            'pivot_from_time' => (int) $pivotFromTime,
            'pivot_to_time' => (int) $pivotToTime,
            'age_candles' => $ageCandles === null ? null : (int) $ageCandles,
            'candle_time' => (int) $candleTime,
            'reason' => (string) $reason,
        );
    }
    $statement->close();
    return $results;
}

function readPositions(mysqli $connection, string $stateKey): array
{
    $statement = $connection->prepare(
        'SELECT symbol, position_side, side, quantity, signed_quantity, entry_price, '
        . 'break_even_price, mark_price, liquidation_price, unrealized_pnl, notional, '
        . 'initial_margin, isolated_margin, leverage, margin_type, margin_asset, pnl_asset, '
        . 'exchange_update_time FROM btc_usdc_open_positions WHERE state_key = ? '
        . 'ORDER BY symbol, position_side'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $symbol,
        $positionSide,
        $side,
        $quantity,
        $signedQuantity,
        $entryPrice,
        $breakEvenPrice,
        $markPrice,
        $liquidationPrice,
        $unrealizedPnl,
        $notional,
        $initialMargin,
        $isolatedMargin,
        $leverage,
        $marginType,
        $marginAsset,
        $pnlAsset,
        $exchangeUpdateTime
    );
    $positions = array();
    while ($statement->fetch()) {
        $positions[] = array(
            'symbol' => (string) $symbol,
            'side' => (string) $side,
            'position_side' => (string) $positionSide,
            'quantity' => (float) $quantity,
            'signed_quantity' => (float) $signedQuantity,
            'entry_price' => (float) $entryPrice,
            'break_even_price' => (float) $breakEvenPrice,
            'mark_price' => (float) $markPrice,
            'liquidation_price' => (float) $liquidationPrice,
            'unrealized_pnl' => (float) $unrealizedPnl,
            'notional' => (float) $notional,
            'initial_margin' => (float) $initialMargin,
            'isolated_margin' => (float) $isolatedMargin,
            'leverage' => (int) $leverage,
            'margin_type' => (string) $marginType,
            'margin_asset' => (string) $marginAsset,
            'pnl_asset' => (string) $pnlAsset,
            'update_time' => (int) $exchangeUpdateTime,
        );
    }
    $statement->close();
    return $positions;
}

function readAccountSnapshot(mysqli $connection, string $stateKey): ?array
{
    $statement = $connection->prepare(
        'SELECT connected, source, balance_asset, quote_asset, credit_mode, symbol, '
        . 'wallet_balance, available_balance, cross_wallet_balance, unrealized_pnl, '
        . 'margin_balance, max_withdraw_amount, margin_available, can_trade, position_mode, '
        . 'multi_assets_margin, fetched_at FROM btc_usdc_binance_account '
        . 'WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $connected,
        $source,
        $balanceAsset,
        $quoteAsset,
        $creditMode,
        $symbol,
        $walletBalance,
        $availableBalance,
        $crossWalletBalance,
        $unrealizedPnl,
        $marginBalance,
        $maxWithdrawAmount,
        $marginAvailable,
        $canTrade,
        $positionMode,
        $multiAssetsMargin,
        $fetchedAt
    );
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }
    return array(
        'connected' => (bool) $connected,
        'source' => (string) $source,
        'asset' => (string) $balanceAsset,
        'quote_asset' => (string) $quoteAsset,
        'credit_mode' => (bool) $creditMode,
        'symbol' => (string) $symbol,
        'wallet_balance' => (float) $walletBalance,
        'available_balance' => (float) $availableBalance,
        'cross_wallet_balance' => (float) $crossWalletBalance,
        'unrealized_pnl' => (float) $unrealizedPnl,
        'margin_balance' => (float) $marginBalance,
        'max_withdraw_amount' => (float) $maxWithdrawAmount,
        'margin_available' => (bool) $marginAvailable,
        'can_trade' => (bool) $canTrade,
        'position_mode' => (string) $positionMode,
        'multi_assets_margin' => (bool) $multiAssetsMargin,
        'positions' => readPositions($connection, $stateKey),
        'fetched_at' => runtimeIsoDate($fetchedAt),
    );
}

function readStructuredRuntime(mysqli $connection, string $stateKey): ?array
{
    $statement = $connection->prepare(
        'SELECT runtime_version, mode, execution_state, status, heartbeat_at, poll_seconds, '
        . 'price, change_24h, message, updated_at FROM btc_usdc_robot_status '
        . 'WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result(
        $version,
        $mode,
        $execution,
        $status,
        $heartbeatAt,
        $pollSeconds,
        $price,
        $change24h,
        $message,
        $updatedAt
    );
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }
    return array(
        'runtime' => array(
            'version' => (int) $version,
            'mode' => (string) $mode,
            'execution' => (string) $execution,
            'status' => (string) $status,
            'heartbeat_at' => runtimeIsoDate($heartbeatAt),
            'poll_seconds' => (float) $pollSeconds,
            'price' => $price === null ? null : (float) $price,
            'change_24h' => $change24h === null ? null : (float) $change24h,
            'strategy' => readStrategySnapshot($connection, $stateKey),
            'divergences' => readDivergenceSnapshots($connection, $stateKey),
            'account' => readAccountSnapshot($connection, $stateKey),
            'message' => (string) $message,
        ),
        'updatedAt' => (string) $updatedAt,
    );
}

function readLegacyRuntime(mysqli $connection, string $stateKey): ?array
{
    if (!runtimeTableExists($connection, 'btc_usdc_robot_runtime')) {
        return null;
    }
    $statement = $connection->prepare(
        'SELECT payload, updated_at FROM btc_usdc_robot_runtime WHERE state_key = ? LIMIT 1'
    );
    $statement->bind_param('s', $stateKey);
    $statement->execute();
    $statement->bind_result($payload, $updatedAt);
    $found = $statement->fetch();
    $statement->close();
    if (!$found) {
        return null;
    }
    $runtime = json_decode((string) $payload, true);
    if (!is_array($runtime)) {
        throw new RuntimeException('A régi robot runtime payload mezője sérült.');
    }
    return array('runtime' => $runtime, 'updatedAt' => (string) $updatedAt);
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
} else {
    requireRobotToken($config);
}

try {
    $connection = openDatabase($config);
    if ($requestMethod === 'GET') {
        $connection->begin_transaction();
        try {
            $snapshot = readStructuredRuntime($connection, $stateKey)
                ?? readLegacyRuntime($connection, $stateKey);
            $connection->commit();
        } catch (Throwable $exception) {
            $connection->rollback();
            throw $exception;
        }
        respondJson(200, $snapshot ?? array('runtime' => null, 'updatedAt' => null));
    }

    $runtime = readRuntimeRequest();
    $connection->begin_transaction();
    try {
        writeRobotStatus($connection, $stateKey, $runtime);
        writeStrategySnapshot($connection, $stateKey, $runtime['strategy'] ?? null);
        writeDivergenceSnapshots($connection, $stateKey, $runtime['divergences'] ?? null);
        writeAccountSnapshot($connection, $stateKey, $runtime['account'] ?? null);
        $connection->commit();
    } catch (Throwable $exception) {
        $connection->rollback();
        throw $exception;
    }
    respondJson(200, array('ok' => true));
} catch (Throwable $exception) {
    error_log('BTC/USDC strukturált robot-státusz hiba: ' . $exception->getMessage());
    respondJson(500, array('error' => 'A strukturált robot-státusz most nem érhető el. Ellenőrizd az új séma importálását.'));
}
