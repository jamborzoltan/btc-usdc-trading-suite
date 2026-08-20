from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

from .binance_usdm import BinanceApiError, BinanceUsdmClient
from .execution import (
    ExecutionState,
    ExecutionStateStore,
    LiveTradingLocked,
    LiveTradingPolicy,
    client_order_id,
    utc_now_iso,
)


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    message: str
    order_sent: bool = False
    managed_position: bool = False
    daily_loss_usdc: float | None = None


class LiveExecutionEngine:
    """Egyetlen, one-way BTCUSDC pozíció biztonságos stratégiai végrehajtója."""

    def __init__(
        self,
        client: BinanceUsdmClient,
        policy: LiveTradingPolicy,
        state_store: ExecutionStateStore,
        symbol: str = "BTCUSDC",
    ) -> None:
        self.client = client
        self.policy = policy
        self.state_store = state_store
        self.symbol = symbol

    def process(
        self,
        bot: dict[str, Any],
        strategy: dict[str, object],
        account: dict[str, Any],
    ) -> ExecutionOutcome:
        state = self.state_store.load()
        bot_snapshot = self._bot_snapshot(bot)
        if state.bot_snapshot != bot_snapshot:
            state.bot_snapshot = bot_snapshot
            self.state_store.save(state)
        if account.get("position_mode") != "one_way":
            return ExecutionOutcome(
                "blocked",
                "Éles végrehajtás csak Binance one-way pozíciómódban engedélyezett.",
                managed_position=state.managed_position,
            )

        positions = [
            item
            for item in account.get("positions", [])
            if isinstance(item, dict) and item.get("symbol") == self.symbol
        ]
        if len(positions) > 1:
            return ExecutionOutcome(
                "blocked",
                "Egynél több BTCUSDC pozíció látható; a robot nem küld megbízást.",
                managed_position=state.managed_position,
            )
        position = positions[0] if positions else None
        if position is None:
            return self._without_position(bot, strategy, account, state)
        return self._with_position(bot, strategy, account, state, position)

    def _without_position(
        self,
        bot: dict[str, Any],
        strategy: dict[str, object],
        account: dict[str, Any],
        state: ExecutionState,
    ) -> ExecutionOutcome:
        if state.pending_entry_client_id:
            order = self.client.query_order(self.symbol, state.pending_entry_client_id)
            if order is not None and str(order.get("status")) == "FILLED":
                if self._pending_is_recent(state.pending_entry_at):
                    return ExecutionOutcome(
                        "executing",
                        "A belépő market order teljesült; a Binance pozíciófrissítésére vár.",
                        managed_position=True,
                    )
            state.clear_position()
            self.state_store.save(state)
        if state.managed_position or state.pending_close_client_id or state.pending_entry_client_id:
            state.clear_position()
            self.state_store.save(state)

        if not bool(bot.get("enabled")):
            return ExecutionOutcome("paused", "A stratégiafigyelés ki van kapcsolva.")
        signal = str(strategy.get("signal") or "hold")
        signal_key = str(strategy.get("signal_key") or "")
        if signal not in {"buy", "sell"}:
            return ExecutionOutcome("monitoring", "Tartás jel: nincs új belépő megbízás.")
        if not signal_key:
            return ExecutionOutcome("blocked", "A stratégia jelzésazonosítója hiányzik.")
        if state.last_entry_signal_key == signal_key:
            return ExecutionOutcome("monitoring", "Ezt a gyertyajelzést a robot már feldolgozta.")

        leverage = self._integer(bot, "leverage", 1, 125)
        margin_usdc = self._number(bot, "marginUsdc", 0.01, 100_000_000)
        stop_loss_pnl = self._stop_loss_pnl_percent(bot, leverage)
        notional = margin_usdc * leverage
        daily_loss = self.client.daily_loss_usdc(self.symbol)
        self.policy.assert_entry_allowed(
            notional,
            margin_usdc,
            daily_loss,
            account,
            stop_loss_pnl,
        )
        price = float(strategy.get("price") or 0)
        if not math.isfinite(price) or price <= 0:
            raise LiveTradingLocked("A belépéshez nincs érvényes BTCUSDC ár.")

        self.client.change_leverage(self.symbol, leverage)
        quantity = self.client.quantity_for_notional(self.symbol, notional, price)
        side = "BUY" if signal == "buy" else "SELL"
        order_client_id = client_order_id(f"entry:{self.symbol}:{signal_key}")
        state.managed_position = True
        state.position_side = "long" if signal == "buy" else "short"
        state.pending_entry_client_id = order_client_id
        state.pending_entry_at = utc_now_iso()
        state.last_entry_signal_key = signal_key
        self._record_action(state, "entry_pending", "Éles belépő market order küldése folyamatban.")
        self.state_store.save(state)
        order = self.client.place_market_order(
            self.symbol,
            side,
            quantity,
            order_client_id,
            reduce_only=False,
        )
        self._assert_filled(order, "belépő")

        self._record_action(
            state,
            "entry",
            f"Éles {state.position_side} belépés: {quantity} BTC, {leverage}×, {notional:.2f} USDC névérték.",
        )
        self.state_store.save(state)
        return ExecutionOutcome(
            "executing",
            state.last_action_message,
            order_sent=True,
            managed_position=True,
            daily_loss_usdc=daily_loss,
        )

    def _with_position(
        self,
        bot: dict[str, Any],
        strategy: dict[str, object],
        account: dict[str, Any],
        state: ExecutionState,
        position: dict[str, Any],
    ) -> ExecutionOutcome:
        side = str(position.get("side") or "")
        quantity = float(position.get("quantity") or 0)
        entry_price = float(position.get("entry_price") or 0)
        mark_price = float(position.get("mark_price") or strategy.get("price") or 0)
        if (
            side not in {"long", "short"}
            or not all(math.isfinite(value) for value in (quantity, entry_price, mark_price))
            or quantity <= 0
            or entry_price <= 0
            or mark_price <= 0
        ):
            return ExecutionOutcome("blocked", "A Binance pozíció adatai hiányosak; nincs végrehajtás.")

        if state.pending_entry_client_id:
            if state.position_side != side:
                state.clear_position()
                self.state_store.save(state)
                return ExecutionOutcome(
                    "blocked",
                    "A megjelent pozíció iránya eltér a robot belépő megbízásától; kezelés letiltva.",
                )
            state.pending_entry_client_id = ""
            state.pending_entry_at = ""
            state.entry_price = entry_price
            state.initial_quantity = quantity
            state.peak_return_percent = max(0.0, self._position_return(side, entry_price, mark_price))
            self.state_store.save(state)

        if not state.managed_position:
            return ExecutionOutcome(
                "monitoring",
                "A nyitott BTCUSDC pozíciót nem ez a robot nyitotta; automatikusan nem módosítja.",
            )
        if (
            state.position_side != side
            or state.entry_price <= 0
            or abs(state.entry_price - entry_price) > max(0.01, entry_price * 0.000001)
            or (state.initial_quantity > 0 and quantity > state.initial_quantity * 1.000001)
        ):
            state.clear_position()
            self._record_action(
                state,
                "ownership_lost",
                "A pozíció iránya, belépőára vagy mennyisége külsőleg megváltozott; automatikus kezelés letiltva.",
            )
            self.state_store.save(state)
            return ExecutionOutcome("blocked", state.last_action_message)

        if state.pending_close_client_id:
            order = self.client.query_order(self.symbol, state.pending_close_client_id)
            order_status = str(order.get("status")) if order is not None else ""
            if order_status == "FILLED":
                if state.pending_close_percent >= 100:
                    return ExecutionOutcome(
                        "executing",
                        "A záró market order teljesült; a Binance pozíciófrissítésére vár.",
                        managed_position=True,
                    )
                if state.pending_close_action == "partial_take_profit":
                    state.partial_taken = True
                elif state.pending_close_action == "profit_fade":
                    state.profit_fade_done = True
                state.close_retry_sequence = 0
            elif order_status in {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}:
                return ExecutionOutcome(
                    "executing",
                    "A záró market order még feldolgozás alatt áll a Binance-on.",
                    managed_position=True,
                )
            else:
                state.close_retry_sequence += 1
            state.pending_close_client_id = ""
            state.pending_close_percent = 0.0
            state.pending_close_action = ""
            self.state_store.save(state)

        current_return = self._position_return(side, entry_price, mark_price)
        if current_return > state.peak_return_percent:
            state.peak_return_percent = current_return
            self.state_store.save(state)

        position_leverage = self._position_leverage(position, bot)
        stop_loss_pnl = self._stop_loss_pnl_percent(bot, position_leverage)
        trailing = self._number(bot, "trailingStopPercent", 0.25, 20)
        stop_price = mark_price
        if bool(bot.get("stopOnCandleClose")):
            stop_price = float(strategy.get("closed_candle_price") or 0)
        stop_return = self._position_return(side, entry_price, stop_price) if stop_price > 0 else current_return
        stop_pnl_return = stop_return * position_leverage
        if stop_pnl_return <= -stop_loss_pnl:
            return self._close(
                account,
                state,
                position,
                100,
                "stop_loss",
                f"Stop-loss ({stop_pnl_return:.2f}% becsült PnL; {stop_return:.4f}% ármozgás)",
            )
        drawdown = state.peak_return_percent - current_return
        if drawdown >= trailing:
            return self._close(
                account,
                state,
                position,
                100,
                "trailing_stop",
                f"Trailing stop ({drawdown:.2f}% visszaesés a csúcstól)",
            )

        signal = str(strategy.get("signal") or "hold")
        if bool(bot.get("enabled")) and (
            (side == "long" and signal == "sell") or (side == "short" and signal == "buy")
        ):
            signal_key = str(strategy.get("signal_key") or "unknown")
            return self._close(
                account,
                state,
                position,
                100,
                f"opposite:{signal_key}",
                "Ellentétes stratégiajel",
            )

        partial_trigger = self._number(bot, "partialTakeProfitPercent", 0, 20)
        if bool(bot.get("enabled")) and partial_trigger > 0 and not state.partial_taken:
            if current_return >= partial_trigger:
                partial_percent = self._number(bot, "partialClosePercent", 10, 90)
                outcome = self._close(
                    account,
                    state,
                    position,
                    partial_percent,
                    "partial_take_profit",
                    f"Részleges profitrealizálás (+{current_return:.2f}% ármozgás)",
                )
                state.partial_taken = True
                self.state_store.save(state)
                return outcome

        fade_trigger = self._number(bot, "profitFadePercent", 0, 10)
        if (
            bool(bot.get("enabled"))
            and signal == "hold"
            and state.partial_taken
            and not state.profit_fade_done
            and fade_trigger > 0
            and drawdown >= fade_trigger
        ):
            close_percent = self._number(bot, "profitFadeClosePercent", 10, 100)
            outcome = self._close(
                account,
                state,
                position,
                close_percent,
                "profit_fade",
                f"Profitvédelem ({drawdown:.2f}% visszaesés a csúcstól)",
            )
            state.profit_fade_done = True
            self.state_store.save(state)
            return outcome

        mode = "aktív" if bool(bot.get("enabled")) else "új belépés szünetel"
        return ExecutionOutcome(
            "monitoring",
            f"Saját {side} pozíció kezelése {mode}; ármozgás: {current_return:+.2f}%.",
            managed_position=True,
        )

    def _close(
        self,
        account: dict[str, Any],
        state: ExecutionState,
        position: dict[str, Any],
        percent: float,
        reason_key: str,
        reason_label: str,
    ) -> ExecutionOutcome:
        self.policy.assert_close_allowed(account)
        quantity = self.client.close_quantity(self.symbol, float(position["quantity"]), percent)
        side = "SELL" if position["side"] == "long" else "BUY"
        position_key = f"{state.position_side}:{state.entry_price:.8f}:{state.last_entry_signal_key}"
        order_client_id = client_order_id(
            f"close:{position_key}:{reason_key}:{percent:.2f}:retry:{state.close_retry_sequence}"
        )
        state.pending_close_client_id = order_client_id
        state.pending_close_percent = percent
        state.pending_close_action = reason_key
        self._record_action(state, "close_pending", f"{reason_label}: záró market order küldése folyamatban.")
        self.state_store.save(state)
        order = self.client.place_market_order(
            self.symbol,
            side,
            quantity,
            order_client_id,
            reduce_only=True,
        )
        self._assert_filled(order, "záró")
        if percent < 100:
            state.pending_close_client_id = ""
            state.pending_close_percent = 0.0
            state.pending_close_action = ""
            state.close_retry_sequence = 0
        self._record_action(
            state,
            "close" if percent >= 100 else "partial_close",
            f"{reason_label}: {quantity} BTC zárva ({percent:.0f}%).",
        )
        self.state_store.save(state)
        return ExecutionOutcome(
            "executing",
            state.last_action_message,
            order_sent=True,
            managed_position=True,
        )

    @staticmethod
    def _position_return(side: str, entry_price: float, price: float) -> float:
        if side == "long":
            return (price / entry_price - 1) * 100
        return (entry_price - price) / entry_price * 100

    @staticmethod
    def _pending_is_recent(value: str) -> bool:
        if not value:
            return False
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp).total_seconds() < 30

    @staticmethod
    def _record_action(state: ExecutionState, action: str, message: str) -> None:
        state.last_action = action
        state.last_action_message = message
        state.last_action_at = utc_now_iso()

    @staticmethod
    def _assert_filled(order: dict[str, Any], label: str) -> None:
        status = str(order.get("status") or "")
        if status != "FILLED":
            raise BinanceApiError(f"A {label} market order nem FILLED állapotú ({status or 'ismeretlen'}).")

    @staticmethod
    def _number(source: dict[str, Any], key: str, minimum: float, maximum: float) -> float:
        try:
            value = float(source[key])
        except (KeyError, TypeError, ValueError) as error:
            raise LiveTradingLocked(f"A {key} robotbeállítás érvénytelen.") from error
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise LiveTradingLocked(f"A {key} robotbeállítás kívül esik az engedélyezett tartományon.")
        return value

    @staticmethod
    def _integer(source: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
        try:
            raw = float(source[key])
        except (KeyError, TypeError, ValueError) as error:
            raise LiveTradingLocked(f"A {key} robotbeállítás érvénytelen.") from error
        if not math.isfinite(raw) or not raw.is_integer():
            raise LiveTradingLocked(f"A {key} robotbeállítás egész szám legyen.")
        value = int(raw)
        if not minimum <= value <= maximum:
            raise LiveTradingLocked(f"A {key} robotbeállítás kívül esik az engedélyezett tartományon.")
        return value

    @classmethod
    def _position_leverage(cls, position: dict[str, Any], bot: dict[str, Any]) -> int:
        source = position if position.get("leverage") is not None else bot
        return cls._integer(source, "leverage", 1, 125)

    @classmethod
    def _stop_loss_pnl_percent(cls, bot: dict[str, Any], leverage: int) -> float:
        """A 9-es botverziótól közvetlen PnL%; régebbinél ár% × leverage."""

        try:
            version = int(bot.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        if version >= 9:
            return cls._number(bot, "stopLossPercent", 1, 100)
        legacy_price_percent = cls._number(bot, "stopLossPercent", 0.25, 20)
        return min(100.0, max(1.0, legacy_price_percent * leverage))

    @staticmethod
    def _bot_snapshot(bot: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "version",
            "enabled",
            "strategyType",
            "strategyInterval",
            "leverage",
            "marginUsdc",
            "stopLossPercent",
            "trailingStopPercent",
            "partialTakeProfitPercent",
            "partialClosePercent",
            "profitFadePercent",
            "profitFadeClosePercent",
            "stopOnCandleClose",
        )
        return {key: bot[key] for key in keys if key in bot}
