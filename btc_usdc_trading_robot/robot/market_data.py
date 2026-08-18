from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BINANCE_USDM_API = "https://fapi.binance.com/fapi/v1"
INTERVALS = {15: "15m", 60: "1h", 1440: "1d"}


class MarketDataError(RuntimeError):
    """A publikus ár- vagy gyertyaadat nem használható biztonságosan."""


def ticker() -> dict[str, float]:
    payload = _get_json(f"{BINANCE_USDM_API}/ticker/24hr?symbol=BTCUSDC")
    try:
        return {"price": float(payload["lastPrice"]), "change_24h": float(payload["priceChangePercent"])}
    except (KeyError, TypeError, ValueError) as error:
        raise MarketDataError("A ticker válasza hiányos.") from error


def candles(interval_minutes: int, limit: int = 120) -> list[dict[str, float | int]]:
    interval = INTERVALS.get(interval_minutes)
    if not interval:
        raise MarketDataError("Csak 15 perces, 1 órás vagy 1 napos gyertya kérhető.")
    query = urlencode({"symbol": "BTCUSDC", "interval": interval, "limit": limit})
    payload = _get_json(f"{BINANCE_USDM_API}/klines?{query}")
    if not isinstance(payload, list):
        raise MarketDataError("A gyertyaadat válasza hibás.")

    result: list[dict[str, float | int]] = []
    try:
        for row in payload:
            result.append(
                {
                    "time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                }
            )
    except (IndexError, TypeError, ValueError) as error:
        raise MarketDataError("A gyertyaadat egyik sora érvénytelen.") from error
    if len(result) < 52:
        raise MarketDataError("Nincs elegendő gyertya a stratégia számításához.")
    return result


def _get_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "BTC-USDC-Robot/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise MarketDataError(f"A Binance HTTP {response.status} hibát adott.")
            raw = response.read()
    except (HTTPError, URLError, OSError) as error:
        raise MarketDataError(f"A Binance publikus API nem érhető el: {error}") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketDataError("A Binance válasza nem feldolgozható JSON.") from error
