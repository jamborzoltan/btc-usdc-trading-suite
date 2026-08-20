from __future__ import annotations

from typing import Callable

from .market_data import candles


STRATEGY_LABELS = {
    "trend": "Trendkövető EMA",
    "momentum": "Momentum",
    "mean_reversion": "Mean reversion",
    "trend_impulse": "Trend + Momentum",
}


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"Legalább {period} érték szükséges az EMA-hoz.")
    multiplier = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * multiplier + result[-1] * (1 - multiplier))
    return result


def calculate(
    strategy_type: str,
    interval: int,
    current_price: float,
    candle_provider: Callable[[int], list[dict[str, float | int]]] = candles,
) -> dict[str, object]:
    if strategy_type not in STRATEGY_LABELS:
        raise ValueError("Ismeretlen stratégia.")
    if interval not in (15, 60):
        raise ValueError("A jelzési idősík 15 perc vagy 1 óra lehet.")

    closed_candles = candle_provider(interval)[:-1]
    closes = [float(candle["close"]) for candle in closed_candles]
    candle_time = int(closed_candles[-1]["time"])
    timeframe = "15 perces" if interval == 15 else "1 órás"
    result: dict[str, object] = {
        "strategy_type": strategy_type,
        "strategy_label": STRATEGY_LABELS[strategy_type],
        "interval": interval,
        "price": current_price,
        "closed_candle_price": closes[-1],
        "candle_time": candle_time,
    }

    if strategy_type == "trend":
        fast, slow = ema(closes, 20), ema(closes, 50)
        daily_closes = [float(candle["close"]) for candle in candle_provider(1440)[:-1]]
        daily_ema = ema(daily_closes, 50)[-1]
        daily_uptrend = daily_closes[-1] > daily_ema
        bullish_cross = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        bearish_cross = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        signal = "buy" if bullish_cross and daily_uptrend else "sell" if bearish_cross or not daily_uptrend else "hold"
        reason = (
            f"A {timeframe} EMA(20) felfelé keresztezte az EMA(50)-et, a napos trend emelkedő."
            if signal == "buy"
            else f"A {timeframe} trend lefelé fordult vagy a napos trendszűrő negatív."
            if signal == "sell"
            else "Nincs új EMA-kereszteződési jel."
        )
        result.update({"signal": signal, "reason": reason, "context": "up" if daily_uptrend else "down", "fast_ema": fast[-1], "slow_ema": slow[-1]})

    elif strategy_type == "momentum":
        momentum = (current_price / closes[-11] - 1) * 100
        average = ema(closes, 20)[-1]
        signal = "buy" if momentum >= 0.5 and current_price > average else "sell" if momentum <= -0.5 and current_price < average else "hold"
        result.update({"signal": signal, "reason": f"{timeframe} 10 gyertyás momentum: {momentum:.2f}%.", "context": "up" if current_price > average else "down", "momentum_percent": momentum, "fast_ema": average})

    elif strategy_type == "trend_impulse":
        momentum = (current_price / closes[-11] - 1) * 100
        entry_ema = ema(closes, 20)[-1]
        trend_interval = 60 if interval == 15 else 1440
        trend_closes = [float(candle["close"]) for candle in candle_provider(trend_interval)[:-1]]
        trend_fast, trend_slow = ema(trend_closes, 20)[-1], ema(trend_closes, 50)[-1]
        direction = "up" if trend_fast > trend_slow else "down" if trend_fast < trend_slow else "neutral"
        positive = momentum >= 0.5 and current_price > entry_ema
        negative = momentum <= -0.5 and current_price < entry_ema
        signal = "buy" if direction == "up" and positive else "sell" if direction == "down" and negative else "hold"
        trend_label = "1 órás" if trend_interval == 60 else "napos"
        result.update({"signal": signal, "reason": f"{trend_label.capitalize()} EMA-trend: {direction}; {timeframe} momentum: {momentum:.2f}%.", "context": direction, "momentum_percent": momentum, "fast_ema": entry_ema, "trend_fast_ema": trend_fast, "trend_slow_ema": trend_slow, "trend_interval": trend_interval})

    else:
        middle = sum(closes[-20:]) / 20
        variance = sum((value - middle) ** 2 for value in closes[-20:]) / 20
        deviation = variance**0.5
        lower, upper = middle - 2 * deviation, middle + 2 * deviation
        signal = "buy" if current_price <= lower else "sell" if current_price >= upper else "hold"
        result.update({"signal": signal, "reason": f"{timeframe} Bollinger-sáv jelzés: {signal}.", "context": "lower" if signal == "buy" else "upper" if signal == "sell" else "inside", "middle_band": middle, "lower_band": lower, "upper_band": upper})

    result["signal_key"] = f"{strategy_type}:{interval}:{candle_time}:{result['signal']}"
    return result
