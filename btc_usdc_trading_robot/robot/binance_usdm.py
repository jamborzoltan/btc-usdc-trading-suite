from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BinanceApiError(RuntimeError):
    """A Binance USDⓈ-M API nem adott biztonságosan használható választ."""


class BinanceUsdmClient:
    """Hitelesített, kizárólag olvasási Binance USDⓈ-M kliens.

    Szándékosan nincs benne megbízást küldő metódus. Az API-kulcs és a secret
    kizárólag a mini PC memóriájában marad; a webapp csak a megtisztított
    számlaképet kapja meg.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        recv_window_ms: int = 5000,
        timeout_seconds: float = 10,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")
        self._base_url = base_url.rstrip("/")
        self._recv_window_ms = recv_window_ms
        self._timeout_seconds = timeout_seconds
        self._clock_offset_ms = 0
        self._clock_synced_monotonic = 0.0
        self._account_config_cache: dict[str, Any] | None = None
        self._account_config_synced_monotonic = 0.0

    def account_snapshot(self, symbol: str = "BTCUSDC") -> dict[str, Any]:
        account_info = self._signed_get("/fapi/v3/account")
        positions = self._signed_get("/fapi/v3/positionRisk", {"symbol": symbol})
        account_config = self._account_configuration()

        if not isinstance(account_info, dict) or not isinstance(account_info.get("assets"), list):
            raise BinanceApiError("A Binance számlaválasza hibás.")
        if not isinstance(positions, list):
            raise BinanceApiError("A Binance pozícióválasza nem lista.")
        if not isinstance(account_config, dict):
            raise BinanceApiError("A Binance fiókbeállítás-válasza hibás.")

        asset_rows = [item for item in account_info["assets"] if isinstance(item, dict)]
        usdc = next((item for item in asset_rows if item.get("asset") == "USDC"), None)
        bnfcr = next((item for item in asset_rows if item.get("asset") == "BNFCR"), None)
        if usdc is None and bnfcr is None:
            raise BinanceApiError("A Binance USDⓈ-M fiókban nem található USDC- vagy BNFCR-egyenleg.")

        def balance_magnitude(item: dict[str, Any] | None) -> float:
            if item is None:
                return 0.0
            return max(
                abs(self._number(item.get("walletBalance"))),
                abs(self._number(item.get("marginBalance"))),
                abs(self._number(item.get("availableBalance"))),
            )

        # Az EEA Futures Credits módban a BTCUSDC kontraktus ára továbbra is
        # USDC-ben értendő, de a tárca, a margin és a P/L BNFCR-ben szerepel.
        # Ilyenkor a külön USDC sor jellemzően nulla, a tényleges fedezet pedig
        # a BNFCR soron érkezik.
        balance = (
            bnfcr
            if bnfcr is not None and (usdc is None or balance_magnitude(bnfcr) > balance_magnitude(usdc))
            else usdc
        )
        if balance is None:  # A fenti ellenőrzés miatt csak a típusellenőrző kedvéért.
            raise BinanceApiError("A Binance USDⓈ-M egyenlegsora hiányzik.")
        balance_asset = str(balance.get("asset") or "USDC").upper()

        open_positions: list[dict[str, Any]] = []
        for item in positions:
            if not isinstance(item, dict):
                continue
            amount = self._number(item.get("positionAmt"))
            if abs(amount) < 1e-12:
                continue
            position_side = str(item.get("positionSide") or "BOTH").upper()
            if position_side == "LONG":
                side = "long"
            elif position_side == "SHORT":
                side = "short"
            else:
                side = "long" if amount > 0 else "short"
            open_positions.append(
                {
                    "symbol": str(item.get("symbol") or symbol),
                    "side": side,
                    "position_side": position_side,
                    "quantity": abs(amount),
                    "signed_quantity": amount,
                    "entry_price": self._number(item.get("entryPrice")),
                    "break_even_price": self._number(item.get("breakEvenPrice")),
                    "mark_price": self._number(item.get("markPrice")),
                    "liquidation_price": self._number(item.get("liquidationPrice")),
                    "unrealized_pnl": self._number(item.get("unRealizedProfit")),
                    "notional": abs(self._number(item.get("notional"))),
                    "initial_margin": self._number(item.get("positionInitialMargin")),
                    "isolated_margin": self._number(item.get("isolatedMargin")),
                    "leverage": int(self._number(item.get("leverage")) or 1),
                    "margin_type": str(item.get("marginType") or ""),
                    "margin_asset": str(item.get("marginAsset") or "USDC"),
                    "pnl_asset": balance_asset,
                    "update_time": int(self._number(item.get("updateTime"))),
                }
            )

        wallet_balance = self._number(balance.get("walletBalance"))
        unrealized_pnl = self._number(balance.get("unrealizedProfit"))
        return {
            "connected": True,
            "source": "binance-usdm",
            "asset": balance_asset,
            "quote_asset": "USDC",
            "credit_mode": balance_asset == "BNFCR",
            "symbol": symbol,
            "wallet_balance": wallet_balance,
            "available_balance": self._number(balance.get("availableBalance")),
            "cross_wallet_balance": self._number(balance.get("crossWalletBalance")),
            "unrealized_pnl": unrealized_pnl,
            "margin_balance": self._number(balance.get("marginBalance")) or wallet_balance + unrealized_pnl,
            "max_withdraw_amount": self._number(balance.get("maxWithdrawAmount")),
            "margin_available": bool(balance.get("marginAvailable", True)),
            "can_trade": bool(account_info.get("canTrade", account_config.get("canTrade", False))),
            "position_mode": "hedge" if bool(account_config.get("dualSidePosition", False)) else "one_way",
            "multi_assets_margin": bool(account_config.get("multiAssetsMargin", False)),
            "positions": open_positions,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _account_configuration(self) -> dict[str, Any]:
        if (
            self._account_config_cache is None
            or time.monotonic() - self._account_config_synced_monotonic >= 300
        ):
            payload = self._signed_get("/fapi/v1/accountConfig")
            if not isinstance(payload, dict):
                raise BinanceApiError("A Binance fiókbeállítás-válasza hibás.")
            self._account_config_cache = payload
            self._account_config_synced_monotonic = time.monotonic()
        return self._account_config_cache

    def _signed_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._ensure_clock_sync()
        signed_params = dict(params or {})
        signed_params["timestamp"] = int(time.time() * 1000) + self._clock_offset_ms
        signed_params["recvWindow"] = self._recv_window_ms
        query = urlencode(signed_params)
        signature = hmac.new(self._api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{self._base_url}{path}?{query}&signature={signature}"
        return self._request_json(url, signed=True)

    def _ensure_clock_sync(self) -> None:
        if time.monotonic() - self._clock_synced_monotonic < 300:
            return
        payload = self._request_json(f"{self._base_url}/fapi/v1/time", signed=False)
        if not isinstance(payload, dict):
            raise BinanceApiError("A Binance időszinkron-válasza hibás.")
        try:
            server_time = int(payload["serverTime"])
        except (KeyError, TypeError, ValueError) as error:
            raise BinanceApiError("A Binance időszinkron-válaszából hiányzik a szerveridő.") from error
        self._clock_offset_ms = server_time - int(time.time() * 1000)
        self._clock_synced_monotonic = time.monotonic()

    def _request_json(self, url: str, *, signed: bool) -> Any:
        headers = {"Accept": "application/json", "User-Agent": "BTC-USDC-Robot/1.0"}
        if signed:
            headers["X-MBX-APIKEY"] = self._api_key
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                status = response.status
        except HTTPError as error:
            raw = error.read()
            status = error.code
        except (URLError, OSError) as error:
            raise BinanceApiError(f"A Binance USDⓈ-M API nem érhető el: {error}") from error

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BinanceApiError(f"A Binance HTTP {status} választ adott, de az nem érvényes JSON.") from error
        if status != 200:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            detail = f" ({code}: {message})" if code is not None or message else ""
            raise BinanceApiError(f"A Binance USDⓈ-M API HTTP {status} hibát adott{detail}.")
        return payload

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError) as error:
            raise BinanceApiError("A Binance egyik számlamezője nem szám.") from error
