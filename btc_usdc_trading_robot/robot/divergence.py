from __future__ import annotations

import math
from typing import Callable

from .market_data import candles


RSI_PERIOD = 14
PIVOT_LEFT = 3
PIVOT_RIGHT = 3
MAX_SIGNAL_AGE_CANDLES = 20
DIVERGENCE_INTERVALS = {60: "1 órás", 1440: "1 napos"}


def wilder_rsi(values: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    """Wilder-féle RSI, az árlistával azonos hosszúságú kimenettel."""

    if period < 2 or len(values) <= period:
        raise ValueError(f"Az RSI({period}) számításához legalább {period + 1} záróár kell.")
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("Az RSI csak pozitív, véges záróárakból számítható.")

    result: list[float | None] = [None] * len(values)
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    average_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    average_loss = sum(max(-change, 0.0) for change in changes[:period]) / period
    result[period] = _rsi_value(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = changes[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        result[index] = _rsi_value(average_gain, average_loss)
    return result


def find_regular_divergence(
    lows: list[float],
    highs: list[float],
    rsi_values: list[float | None],
    times: list[int],
    *,
    left: int = PIVOT_LEFT,
    right: int = PIVOT_RIGHT,
    max_age_candles: int = MAX_SIGNAL_AGE_CANDLES,
) -> dict[str, object]:
    """A legfrissebb megerősített reguláris bullish/bearish divergenciát adja."""

    length = len(lows)
    if length != len(highs) or length != len(rsi_values) or length != len(times):
        raise ValueError("A divergenciasorozatok hossza eltér.")
    if left < 1 or right < 1 or max_age_candles < 1 or length < left + right + 3:
        raise ValueError("Nincs elegendő adat a divergenciakereséshez.")
    if any(not math.isfinite(value) or value <= 0 for value in (*lows, *highs)):
        raise ValueError("A divergenciaárak csak pozitív, véges számok lehetnek.")

    low_pivots = _pivot_indexes(lows, rsi_values, left, right, find_low=True)
    high_pivots = _pivot_indexes(highs, rsi_values, left, right, find_low=False)
    candidates: list[dict[str, object]] = []

    for previous, current in zip(low_pivots, low_pivots[1:]):
        previous_rsi = float(rsi_values[previous])
        current_rsi = float(rsi_values[current])
        if length - 1 - current <= max_age_candles and lows[current] < lows[previous] and current_rsi > previous_rsi:
            candidates.append(
                _candidate(
                    "bullish",
                    previous,
                    current,
                    lows[previous],
                    lows[current],
                    previous_rsi,
                    current_rsi,
                    times,
                )
            )

    for previous, current in zip(high_pivots, high_pivots[1:]):
        previous_rsi = float(rsi_values[previous])
        current_rsi = float(rsi_values[current])
        if length - 1 - current <= max_age_candles and highs[current] > highs[previous] and current_rsi < previous_rsi:
            candidates.append(
                _candidate(
                    "bearish",
                    previous,
                    current,
                    highs[previous],
                    highs[current],
                    previous_rsi,
                    current_rsi,
                    times,
                )
            )

    latest_rsi = next((float(value) for value in reversed(rsi_values) if value is not None), None)
    if not candidates:
        return {
            "signal": "none",
            "current_rsi": latest_rsi,
            "price_from": None,
            "price_to": None,
            "rsi_from": None,
            "rsi_to": None,
            "pivot_from_time": 0,
            "pivot_to_time": 0,
            "age_candles": None,
            "candle_time": times[-1],
            "reason": (
                f"Nincs friss, megerősített reguláris divergencia az utolsó "
                f"{max_age_candles} lezárt gyertyában."
            ),
        }

    latest = max(candidates, key=lambda candidate: int(candidate["pivot_to_index"]))
    latest["current_rsi"] = latest_rsi
    latest["age_candles"] = length - 1 - int(latest["pivot_to_index"])
    latest["candle_time"] = times[-1]
    del latest["pivot_to_index"]
    return latest


def calculate_divergences(
    candle_provider: Callable[[int], list[dict[str, float | int]]] = candles,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for interval, timeframe in DIVERGENCE_INTERVALS.items():
        closed = candle_provider(interval)[:-1]
        if len(closed) < 60:
            raise ValueError(f"A {timeframe} divergenciához legalább 60 lezárt gyertya kell.")
        closes = [float(candle["close"]) for candle in closed]
        result = find_regular_divergence(
            [float(candle["low"]) for candle in closed],
            [float(candle["high"]) for candle in closed],
            wilder_rsi(closes),
            [int(candle["time"]) for candle in closed],
        )
        result.update(
            {
                "interval": interval,
                "timeframe": timeframe,
                "rsi_period": RSI_PERIOD,
                "pivot_left": PIVOT_LEFT,
                "pivot_right": PIVOT_RIGHT,
            }
        )
        results.append(result)
    return results


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    return 100 - 100 / (1 + average_gain / average_loss)


def _pivot_indexes(
    values: list[float],
    rsi_values: list[float | None],
    left: int,
    right: int,
    *,
    find_low: bool,
) -> list[int]:
    indexes: list[int] = []
    for index in range(left, len(values) - right):
        if rsi_values[index] is None:
            continue
        window = values[index - left : index + right + 1]
        extreme = min(window) if find_low else max(window)
        if values[index] == extreme and window.count(extreme) == 1:
            indexes.append(index)
    return indexes


def _candidate(
    signal: str,
    previous: int,
    current: int,
    price_from: float,
    price_to: float,
    rsi_from: float,
    rsi_to: float,
    times: list[int],
) -> dict[str, object]:
    direction = "alacsonyabb mélypontot" if signal == "bullish" else "magasabb csúcsot"
    rsi_direction = "magasabb mélypontot" if signal == "bullish" else "alacsonyabb csúcsot"
    return {
        "signal": signal,
        "price_from": price_from,
        "price_to": price_to,
        "rsi_from": rsi_from,
        "rsi_to": rsi_to,
        "pivot_from_time": times[previous],
        "pivot_to_time": times[current],
        "pivot_to_index": current,
        "reason": (
            f"Az ár {direction} képzett ({price_from:.2f} → {price_to:.2f}), "
            f"miközben az RSI {rsi_direction} ({rsi_from:.2f} → {rsi_to:.2f})."
        ),
    }
