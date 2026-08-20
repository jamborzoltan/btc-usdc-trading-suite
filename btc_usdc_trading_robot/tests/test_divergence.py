from __future__ import annotations

import unittest

from robot.divergence import find_regular_divergence, wilder_rsi


def series_with_pivots(length: int = 18):
    lows = [10.0 + index * 0.01 for index in range(length)]
    highs = [20.0 + index * 0.01 for index in range(length)]
    rsi_values: list[float | None] = [50.0] * length
    times = [index * 3_600_000 for index in range(length)]
    return lows, highs, rsi_values, times


class WilderRsiTests(unittest.TestCase):
    def test_monotonic_and_flat_series_have_expected_limits(self) -> None:
        rising = wilder_rsi([float(value) for value in range(1, 30)])
        falling = wilder_rsi([float(value) for value in range(30, 1, -1)])
        flat = wilder_rsi([10.0] * 30)
        self.assertEqual(rising[-1], 100.0)
        self.assertEqual(falling[-1], 0.0)
        self.assertEqual(flat[-1], 50.0)


class DivergenceDetectionTests(unittest.TestCase):
    def test_bullish_divergence_is_lower_price_low_and_higher_rsi_low(self) -> None:
        lows, highs, rsi_values, times = series_with_pivots()
        lows[5], lows[12] = 8.0, 7.0
        rsi_values[5], rsi_values[12] = 25.0, 35.0
        result = find_regular_divergence(
            lows, highs, rsi_values, times, left=2, right=2, max_age_candles=10
        )
        self.assertEqual(result["signal"], "bullish")
        self.assertEqual(result["price_from"], 8.0)
        self.assertEqual(result["price_to"], 7.0)
        self.assertEqual(result["rsi_from"], 25.0)
        self.assertEqual(result["rsi_to"], 35.0)

    def test_bearish_divergence_is_higher_price_high_and_lower_rsi_high(self) -> None:
        lows, highs, rsi_values, times = series_with_pivots()
        highs[5], highs[12] = 22.0, 23.0
        rsi_values[5], rsi_values[12] = 75.0, 65.0
        result = find_regular_divergence(
            lows, highs, rsi_values, times, left=2, right=2, max_age_candles=10
        )
        self.assertEqual(result["signal"], "bearish")
        self.assertEqual(result["price_from"], 22.0)
        self.assertEqual(result["price_to"], 23.0)
        self.assertEqual(result["rsi_from"], 75.0)
        self.assertEqual(result["rsi_to"], 65.0)

    def test_old_or_unconfirmed_pattern_is_not_reported(self) -> None:
        lows, highs, rsi_values, times = series_with_pivots(length=30)
        lows[5], lows[12] = 8.0, 7.0
        rsi_values[5], rsi_values[12] = 25.0, 35.0
        result = find_regular_divergence(
            lows, highs, rsi_values, times, left=2, right=2, max_age_candles=5
        )
        self.assertEqual(result["signal"], "none")


if __name__ == "__main__":
    unittest.main()
