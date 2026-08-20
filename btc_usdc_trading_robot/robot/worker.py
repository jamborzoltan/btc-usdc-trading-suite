from __future__ import annotations

from datetime import datetime, timezone
import copy
import logging
import time
from typing import Any

from .binance_usdm import BinanceApiError, BinanceUsdmClient
from .config import RobotSettings
from .divergence import calculate_divergences
from .execution import ExecutionStateStore, LiveTradingLocked, LiveTradingPolicy
from .live_execution import ExecutionOutcome, LiveExecutionEngine
from .market_data import candles, ticker
from .state_store import RemoteRuntimeStore, RemoteStateError, RemoteStateStore
from .strategies import calculate


class ContinuousRobot:
    """Böngészőtől független, folyamatos jelzésfigyelő.

    Read-only módban csak számlát olvas. A külön, többszörösen reteszelt live
    módban a webes stratégiajelzéseket market megbízásokkal hajtja végre.
    """

    def __init__(self, settings: RobotSettings) -> None:
        self.settings = settings
        self.store = RemoteStateStore(
            settings.state_url,
            settings.runtime_token,
            settings.username,
            settings.password,
        )
        self.runtime_store = RemoteRuntimeStore(
            settings.runtime_url,
            settings.runtime_token,
            settings.username,
            settings.password,
        )
        self.binance = BinanceUsdmClient(
            settings.binance_api_key,
            settings.binance_api_secret,
            settings.binance_base_url,
            settings.recv_window_ms,
        )
        self.live_engine: LiveExecutionEngine | None = None
        self.execution_state_store: ExecutionStateStore | None = None
        if settings.live_trading_enabled:
            policy = LiveTradingPolicy(
                settings.live_trading_enabled,
                settings.live_acknowledgement,
                settings.max_order_notional_usdc,
                settings.max_daily_loss_usdc,
                settings.max_position_loss_percent,
            )
            self.execution_state_store = ExecutionStateStore(settings.execution_state_path)
            self.live_engine = LiveExecutionEngine(
                self.binance,
                policy,
                self.execution_state_store,
                settings.binance_symbol,
            )

    def tick(self) -> None:
        state_warning = ""
        try:
            snapshot = self.store.load()
            if snapshot is None:
                raise RemoteStateError("A webapp még nem hozta létre a közös robotállapotot.")
            bot = snapshot.portfolio.get("bot")
            if not isinstance(bot, dict):
                raise RemoteStateError("A közös állapotban nincs érvényes robotbeállítás.")
        except RemoteStateError as error:
            bot = self._fallback_bot()
            if bot is None:
                raise
            state_warning = f"A webes állapot nem érhető el ({error}); új belépés tiltva, helyi pozícióvédelem aktív."

        account: dict[str, Any] | None = None
        market: dict[str, float] | None = None
        strategy: dict[str, object] | None = None
        divergences: list[dict[str, object]] = []
        execution_outcome: ExecutionOutcome | None = None
        errors: list[str] = []
        warnings: list[str] = []
        candle_cache: dict[int, list[dict[str, float | int]]] = {}

        def candle_provider(interval: int) -> list[dict[str, float | int]]:
            if interval not in candle_cache:
                candle_cache[interval] = candles(interval, limit=250)
            return candle_cache[interval]

        try:
            account = self.binance.account_snapshot(self.settings.binance_symbol)
        except BinanceApiError as error:
            errors.append(f"Binance számlahiba: {error}")
        try:
            market = ticker()
            strategy_type = str(bot.get("strategyType", "trend"))
            interval = int(bot.get("strategyInterval", 60))
            strategy = calculate(strategy_type, interval, market["price"], candle_provider)
        except Exception as error:
            errors.append(f"Piaci adat vagy stratégiahiba: {error}")
        try:
            divergences = calculate_divergences(candle_provider)
        except Exception as error:
            warnings.append(f"Divergenciaindikátor-hiba: {error}")

        if self.live_engine is not None and account is not None:
            execution_bot = bot
            execution_strategy = strategy
            if execution_strategy is None:
                execution_bot = copy.deepcopy(bot)
                execution_bot["enabled"] = False
                positions = account.get("positions") if isinstance(account.get("positions"), list) else []
                mark_price = next(
                    (
                        float(item.get("mark_price") or 0)
                        for item in positions
                        if isinstance(item, dict) and item.get("symbol") == self.settings.binance_symbol
                    ),
                    0.0,
                )
                execution_strategy = {
                    "signal": "hold",
                    "signal_key": "market-data-unavailable",
                    "price": mark_price,
                    "closed_candle_price": 0.0,
                }
            try:
                execution_outcome = self.live_engine.process(execution_bot, execution_strategy, account)
                if execution_outcome.order_sent:
                    account = self.binance.account_snapshot(self.settings.binance_symbol)
            except (BinanceApiError, LiveTradingLocked) as error:
                errors.append(f"Éles végrehajtás letiltva: {error}")
            except Exception as error:
                errors.append(f"Éles végrehajtási hiba: {error}")

        if errors:
            runtime = self._runtime_payload("degraded", market, strategy, divergences, account)
            runtime["message"] = " · ".join(
                [*errors, *warnings, *([execution_outcome.message] if execution_outcome is not None else [])]
            )
            logging.warning(runtime["message"])
        elif execution_outcome is not None:
            runtime = self._runtime_payload(execution_outcome.status, market, strategy, divergences, account)
            runtime["message"] = " · ".join(
                value for value in (state_warning, execution_outcome.message, *warnings) if value
            )
        elif bot.get("enabled"):
            runtime = self._runtime_payload("monitoring", market, strategy, divergences, account)
            runtime["message"] = " · ".join(
                (
                    "A robot valódi Binance-számlát figyel; az éles megbízásküldés biztonsági retesze zárva van.",
                    *warnings,
                )
            )
        else:
            runtime = self._runtime_payload("paused", market, strategy, divergences, account)
            runtime["message"] = " · ".join(
                (
                    "A stratégia ki van kapcsolva. A Binance-egyenleg tovább frissül; megbízásküldés nincs.",
                    *warnings,
                )
            )

        self.runtime_store.save(runtime)
        logging.info("Robot szívverés mentve: %s", runtime["status"])

    def _fallback_bot(self) -> dict[str, Any] | None:
        if self.execution_state_store is None:
            return None
        state = self.execution_state_store.load()
        if not state.bot_snapshot:
            return None
        bot = copy.deepcopy(state.bot_snapshot)
        bot["enabled"] = False
        return bot

    def run_forever(self) -> None:
        logging.info("Külön robot elindult: %s mp-es ciklus, %s mód.", self.settings.poll_seconds, self.settings.mode)
        while True:
            started = time.monotonic()
            try:
                self.tick()
            except Exception as error:
                logging.warning("Robotciklus hiba: %s", error)
            elapsed = time.monotonic() - started
            time.sleep(max(0.1, self.settings.poll_seconds - elapsed))

    def _runtime_payload(
        self,
        status: str,
        market: dict[str, float] | None,
        strategy: dict[str, object] | None,
        divergences: list[dict[str, object]],
        account: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "version": 4,
            "mode": self.settings.mode,
            "execution": "live" if self.settings.live_trading_enabled else "locked",
            "status": status,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "poll_seconds": self.settings.poll_seconds,
            "price": market["price"] if market else None,
            "change_24h": market["change_24h"] if market else None,
            "strategy": strategy,
            "divergences": divergences,
            "account": account,
        }
