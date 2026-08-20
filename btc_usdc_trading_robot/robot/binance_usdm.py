from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import hmac
import json
import math
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BinanceApiError(RuntimeError):
    """A Binance USDⓈ-M API nem adott biztonságosan használható választ."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | None = None,
        uncertain_execution: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.uncertain_execution = uncertain_execution


@dataclass(frozen=True)
class SymbolRules:
    min_quantity: Decimal
    max_quantity: Decimal
    quantity_step: Decimal
    min_notional: Decimal


class BinanceUsdmClient:
    """Hitelesített Binance USDⓈ-M kliens olvasáshoz és reteszelt végrehajtáshoz."""

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
        self._symbol_rules_cache: dict[str, tuple[SymbolRules, float]] = {}
        self._daily_loss_cache: tuple[str, float, float] | None = None

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

    def symbol_rules(self, symbol: str) -> SymbolRules:
        symbol = symbol.upper()
        cached = self._symbol_rules_cache.get(symbol)
        if cached is not None and time.monotonic() - cached[1] < 3600:
            return cached[0]
        payload = self._public_get("/fapi/v1/exchangeInfo")
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbols, list):
            raise BinanceApiError("A Binance exchangeInfo válaszából hiányzik a szimbólumlista.")
        row = next(
            (item for item in symbols if isinstance(item, dict) and item.get("symbol") == symbol),
            None,
        )
        if row is None or row.get("status") != "TRADING":
            raise BinanceApiError(f"A {symbol} szimbólum nem található vagy nem kereskedhető.")
        filters = row.get("filters")
        if not isinstance(filters, list):
            raise BinanceApiError(f"A {symbol} kereskedési szűrői hiányoznak.")
        by_type = {
            str(item.get("filterType")): item
            for item in filters
            if isinstance(item, dict) and item.get("filterType")
        }
        lot = by_type.get("MARKET_LOT_SIZE") or by_type.get("LOT_SIZE")
        notional = by_type.get("MIN_NOTIONAL")
        if not isinstance(lot, dict) or not isinstance(notional, dict):
            raise BinanceApiError(f"A {symbol} MARKET_LOT_SIZE vagy MIN_NOTIONAL szűrője hiányzik.")
        try:
            rules = SymbolRules(
                min_quantity=Decimal(str(lot["minQty"])),
                max_quantity=Decimal(str(lot["maxQty"])),
                quantity_step=Decimal(str(lot["stepSize"])),
                min_notional=Decimal(str(notional["notional"])),
            )
        except (KeyError, InvalidOperation) as error:
            raise BinanceApiError(f"A {symbol} kereskedési szűrői érvénytelenek.") from error
        if rules.min_quantity <= 0 or rules.quantity_step <= 0 or rules.max_quantity <= 0:
            raise BinanceApiError(f"A {symbol} mennyiségi szűrői nem pozitívak.")
        self._symbol_rules_cache[symbol] = (rules, time.monotonic())
        return rules

    def quantity_for_notional(self, symbol: str, notional: float, price: float) -> str:
        if notional <= 0 or price <= 0:
            raise BinanceApiError("A pozíció névértéke és ára legyen pozitív.")
        rules = self.symbol_rules(symbol)
        raw = Decimal(str(notional)) / Decimal(str(price))
        quantity = self._floor_step(raw, rules.quantity_step)
        self._validate_market_quantity(quantity, Decimal(str(price)), rules)
        return self._decimal_text(quantity)

    def close_quantity(self, symbol: str, current_quantity: float, percent: float) -> str:
        if current_quantity <= 0 or not 0 < percent <= 100:
            raise BinanceApiError("A zárandó mennyiség vagy százalék érvénytelen.")
        rules = self.symbol_rules(symbol)
        current = Decimal(str(current_quantity))
        quantity = self._floor_step(current * Decimal(str(percent)) / Decimal("100"), rules.quantity_step)
        remaining = current - quantity
        if percent >= 100 or (remaining > 0 and remaining < rules.min_quantity):
            quantity = self._floor_step(current, rules.quantity_step)
        if quantity < rules.min_quantity or quantity > rules.max_quantity:
            raise BinanceApiError("A zárandó mennyiség kívül esik a Binance market lot korlátján.")
        return self._decimal_text(quantity)

    def change_leverage(self, symbol: str, leverage: int) -> int:
        if not 1 <= leverage <= 125:
            raise BinanceApiError("A tőkeáttétel 1 és 125 közé essen.")
        payload = self._signed_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        if not isinstance(payload, dict) or int(self._number(payload.get("leverage"))) != leverage:
            raise BinanceApiError("A Binance nem igazolta vissza a kért tőkeáttételt.")
        return leverage

    def query_order(self, symbol: str, original_client_order_id: str) -> dict[str, Any] | None:
        try:
            payload = self._signed_get(
                "/fapi/v1/order",
                {"symbol": symbol, "origClientOrderId": original_client_order_id},
            )
        except BinanceApiError as error:
            if error.code == -2013:
                return None
            raise
        if not isinstance(payload, dict):
            raise BinanceApiError("A Binance order-lekérdezés válasza hibás.")
        return payload

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: str,
        client_order_id: str,
        *,
        reduce_only: bool,
    ) -> dict[str, Any]:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise BinanceApiError("A market megbízás oldala BUY vagy SELL lehet.")
        existing = self.query_order(symbol, client_order_id)
        if existing is not None:
            return existing
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": quantity,
            "newClientOrderId": client_order_id,
            "newOrderRespType": "RESULT",
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            payload = self._signed_post("/fapi/v1/order", params)
        except BinanceApiError as error:
            if not error.uncertain_execution:
                raise
            recovered = self.query_order(symbol, client_order_id)
            if recovered is None:
                raise
            payload = recovered
        if not isinstance(payload, dict):
            raise BinanceApiError("A Binance market order válasza hibás.")
        return payload

    def daily_loss_usdc(self, symbol: str) -> float:
        now = datetime.now(timezone.utc)
        day_key = now.date().isoformat()
        if (
            self._daily_loss_cache is not None
            and self._daily_loss_cache[0] == day_key
            and time.monotonic() - self._daily_loss_cache[2] < 60
        ):
            return self._daily_loss_cache[1]
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        payload = self._signed_get(
            "/fapi/v1/income",
            {
                "symbol": symbol,
                "startTime": int(day_start.timestamp() * 1000),
                "limit": 1000,
            },
        )
        if not isinstance(payload, list):
            raise BinanceApiError("A Binance napi income-válasza nem lista.")
        included = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}
        net_income = 0.0
        for item in payload:
            if not isinstance(item, dict) or item.get("incomeType") not in included:
                continue
            net_income += self._number(item.get("income"))
        loss = max(0.0, -net_income)
        self._daily_loss_cache = (day_key, loss, time.monotonic())
        return loss

    def _signed_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._signed_request("GET", path, params)

    def _signed_post(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._signed_request("POST", path, params)

    def _signed_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        self._ensure_clock_sync()
        signed_params = dict(params or {})
        signed_params["timestamp"] = int(time.time() * 1000) + self._clock_offset_ms
        signed_params["recvWindow"] = self._recv_window_ms
        query = urlencode(signed_params)
        signature = hmac.new(self._api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{self._base_url}{path}?{query}&signature={signature}"
        return self._request_json(url, signed=True, method=method)

    def _public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urlencode(params or {})
        suffix = f"?{query}" if query else ""
        return self._request_json(f"{self._base_url}{path}{suffix}", signed=False, method="GET")

    def _ensure_clock_sync(self) -> None:
        if time.monotonic() - self._clock_synced_monotonic < 300:
            return
        payload = self._request_json(
            f"{self._base_url}/fapi/v1/time", signed=False, method="GET"
        )
        if not isinstance(payload, dict):
            raise BinanceApiError("A Binance időszinkron-válasza hibás.")
        try:
            server_time = int(payload["serverTime"])
        except (KeyError, TypeError, ValueError) as error:
            raise BinanceApiError("A Binance időszinkron-válaszából hiányzik a szerveridő.") from error
        self._clock_offset_ms = server_time - int(time.time() * 1000)
        self._clock_synced_monotonic = time.monotonic()

    def _request_json(self, url: str, *, signed: bool, method: str) -> Any:
        headers = {"Accept": "application/json", "User-Agent": "BTC-USDC-Robot/1.0"}
        if signed:
            headers["X-MBX-APIKEY"] = self._api_key
        request = Request(url, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                status = response.status
        except HTTPError as error:
            raw = error.read()
            status = error.code
        except (URLError, OSError) as error:
            raise BinanceApiError(
                f"A Binance USDⓈ-M API nem érhető el: {error}",
                uncertain_execution=method != "GET",
            ) from error

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BinanceApiError(f"A Binance HTTP {status} választ adott, de az nem érvényes JSON.") from error
        if status != 200:
            raw_code = payload.get("code") if isinstance(payload, dict) else None
            try:
                code = int(raw_code) if raw_code is not None else None
            except (TypeError, ValueError):
                code = None
            message = payload.get("msg") if isinstance(payload, dict) else None
            detail = f" ({code}: {message})" if code is not None or message else ""
            raise BinanceApiError(
                f"A Binance USDⓈ-M API HTTP {status} hibát adott{detail}.",
                status=status,
                code=code,
                uncertain_execution=method != "GET" and status >= 500,
            )
        return payload

    @staticmethod
    def _floor_step(value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    @staticmethod
    def _validate_market_quantity(quantity: Decimal, price: Decimal, rules: SymbolRules) -> None:
        if quantity < rules.min_quantity:
            raise BinanceApiError("A tervezett megbízás kisebb a Binance minimum mennyiségénél.")
        if quantity > rules.max_quantity:
            raise BinanceApiError("A tervezett megbízás nagyobb a Binance maximum mennyiségénél.")
        if quantity * price < rules.min_notional:
            raise BinanceApiError("A tervezett megbízás kisebb a Binance minimum névértékénél.")

    @staticmethod
    def _number(value: Any) -> float:
        try:
            number = float(value or 0)
        except (TypeError, ValueError) as error:
            raise BinanceApiError("A Binance egyik számlamezője nem szám.") from error
        if not math.isfinite(number):
            raise BinanceApiError("A Binance egyik számlamezője nem véges szám.")
        return number
