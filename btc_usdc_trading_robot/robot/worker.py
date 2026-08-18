from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any

from .binance_usdm import BinanceApiError, BinanceUsdmClient
from .config import RobotSettings
from .market_data import ticker
from .state_store import RemoteRuntimeStore, RemoteStateError, RemoteStateStore
from .strategies import calculate


class ContinuousRobot:
    """Böngészőtől független, folyamatos jelzésfigyelő.

    Ez a fázis valódi Binance USDⓈ-M egyenleget és pozíciót olvas, de még nem
    küld tőzsdei megbízást. A webapp csak a megtisztított számlaképet kapja meg.
    """

    def __init__(self, settings: RobotSettings) -> None:
        self.settings = settings
        self.store = RemoteStateStore(
            settings.state_url,
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

    def tick(self) -> None:
        snapshot = self.store.load()
        if snapshot is None:
            raise RemoteStateError("A webapp még nem hozta létre a közös robotállapotot.")

        bot = snapshot.portfolio.get("bot")
        if not isinstance(bot, dict):
            raise RemoteStateError("A közös állapotban nincs érvényes robotbeállítás.")

        account: dict[str, Any] | None = None
        market: dict[str, float] | None = None
        strategy: dict[str, object] | None = None
        errors: list[str] = []
        try:
            account = self.binance.account_snapshot(self.settings.binance_symbol)
        except BinanceApiError as error:
            errors.append(f"Binance számlahiba: {error}")
        try:
            market = ticker()
            strategy_type = str(bot.get("strategyType", "trend"))
            interval = int(bot.get("strategyInterval", 60))
            strategy = calculate(strategy_type, interval, market["price"])
        except Exception as error:
            errors.append(f"Piaci adat vagy stratégiahiba: {error}")

        if errors:
            runtime = self._runtime_payload("degraded", market, strategy, account)
            runtime["message"] = " · ".join(errors)
            logging.warning(runtime["message"])
        elif bot.get("enabled"):
            runtime = self._runtime_payload("monitoring", market, strategy, account)
            runtime["message"] = (
                "A robot valódi Binance-számlát figyel; az éles megbízásküldés biztonsági retesze zárva van."
            )
        else:
            runtime = self._runtime_payload("paused", market, strategy, account)
            runtime["message"] = (
                "A stratégia ki van kapcsolva. A Binance-egyenleg tovább frissül; megbízásküldés nincs."
            )

        self.runtime_store.save(runtime)
        logging.info("Robot szívverés mentve: %s", runtime["status"])

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
        account: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "version": 2,
            "mode": "live_read_only",
            "execution": "locked",
            "status": status,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "poll_seconds": self.settings.poll_seconds,
            "price": market["price"] if market else None,
            "change_24h": market["change_24h"] if market else None,
            "strategy": strategy,
            "account": account,
        }
