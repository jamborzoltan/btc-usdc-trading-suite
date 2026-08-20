from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from robot.execution import (
    ExecutionState,
    ExecutionStateStore,
    LIVE_CONFIRMATION_PHRASE,
    LiveTradingPolicy,
)
from robot.live_execution import LiveExecutionEngine


class FakeTradingClient:
    def __init__(self) -> None:
        self.orders = []
        self.leverage = None
        self.query_results = {}

    def daily_loss_usdc(self, symbol):
        return 0.0

    def change_leverage(self, symbol, leverage):
        self.leverage = leverage
        return leverage

    def quantity_for_notional(self, symbol, notional, price):
        return "0.001"

    def close_quantity(self, symbol, current_quantity, percent):
        return "0.001"

    def query_order(self, symbol, client_order_id):
        return self.query_results.get(
            client_order_id,
            {"status": "FILLED", "clientOrderId": client_order_id},
        )

    def place_market_order(self, symbol, side, quantity, client_order_id, *, reduce_only):
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "client_order_id": client_order_id,
                "reduce_only": reduce_only,
            }
        )
        return {"status": "FILLED", "clientOrderId": client_order_id}


def bot(**changes):
    value = {
        "version": 9,
        "enabled": True,
        "leverage": 5,
        "marginUsdc": 20,
        "stopLossPercent": 10,
        "trailingStopPercent": 3,
        "partialTakeProfitPercent": 0,
        "partialClosePercent": 50,
        "profitFadePercent": 1,
        "profitFadeClosePercent": 100,
        "stopOnCandleClose": False,
    }
    value.update(changes)
    return value


def strategy(signal="buy", price=100.0):
    return {
        "signal": signal,
        "signal_key": f"trend:60:123:{signal}",
        "price": price,
        "closed_candle_price": price,
    }


def account(positions=None):
    return {
        "connected": True,
        "can_trade": True,
        "available_balance": 100,
        "position_mode": "one_way",
        "positions": positions or [],
    }


class LiveExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ExecutionStateStore(Path(self.temporary.name) / "execution_state.json")
        self.client = FakeTradingClient()
        policy = LiveTradingPolicy(True, LIVE_CONFIRMATION_PHRASE, 200, 20, 50)
        self.engine = LiveExecutionEngine(self.client, policy, self.store)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_buy_signal_opens_one_market_position(self) -> None:
        outcome = self.engine.process(bot(), strategy("buy"), account())
        self.assertTrue(outcome.order_sent)
        self.assertEqual(self.client.leverage, 5)
        self.assertEqual(len(self.client.orders), 1)
        self.assertEqual(self.client.orders[0]["side"], "BUY")
        self.assertFalse(self.client.orders[0]["reduce_only"])
        self.assertEqual(self.store.load().bot_snapshot["stopLossPercent"], 10)

        repeated = self.engine.process(bot(), strategy("buy"), account())
        self.assertFalse(repeated.order_sent)
        self.assertEqual(len(self.client.orders), 1)

    def test_manual_position_is_never_closed(self) -> None:
        position = {"symbol": "BTCUSDC", "side": "long", "quantity": 0.001, "entry_price": 100, "mark_price": 90}
        outcome = self.engine.process(bot(), strategy("sell", 90), account([position]))
        self.assertFalse(outcome.order_sent)
        self.assertEqual(self.client.orders, [])
        self.assertIn("nem ez a robot", outcome.message)

    def test_managed_position_stop_is_reduce_only(self) -> None:
        self.store.save(
            ExecutionState(
                managed_position=True,
                position_side="long",
                entry_price=100,
                initial_quantity=0.001,
                last_entry_signal_key="trend:60:100:buy",
            )
        )
        position = {"symbol": "BTCUSDC", "side": "long", "quantity": 0.001, "entry_price": 100, "mark_price": 97}
        outcome = self.engine.process(bot(), strategy("hold", 97), account([position]))
        self.assertTrue(outcome.order_sent)
        self.assertEqual(self.client.orders[0]["side"], "SELL")
        self.assertTrue(self.client.orders[0]["reduce_only"])

    def test_125x_entry_uses_stop_as_direct_pnl_percent(self) -> None:
        policy = LiveTradingPolicy(True, LIVE_CONFIRMATION_PHRASE, 300, 20, 50)
        engine = LiveExecutionEngine(self.client, policy, self.store)  # type: ignore[arg-type]
        outcome = engine.process(
            bot(leverage=125, marginUsdc=2, stopLossPercent=50),
            strategy("buy"),
            account(),
        )
        self.assertTrue(outcome.order_sent)
        self.assertEqual(self.client.leverage, 125)

    def test_125x_pnl_stop_converts_to_price_distance(self) -> None:
        self.store.save(
            ExecutionState(
                managed_position=True,
                position_side="long",
                entry_price=100,
                initial_quantity=0.001,
                last_entry_signal_key="trend:60:100:buy",
            )
        )
        position = {
            "symbol": "BTCUSDC",
            "side": "long",
            "quantity": 0.001,
            "entry_price": 100,
            "mark_price": 99.59,
            "leverage": 125,
        }
        outcome = self.engine.process(
            bot(leverage=125, stopLossPercent=50),
            strategy("hold", 99.59),
            account([position]),
        )
        self.assertTrue(outcome.order_sent)
        self.assertIn("becsült PnL", outcome.message)

    def test_125x_pnl_stop_does_not_close_before_threshold(self) -> None:
        self.store.save(
            ExecutionState(
                managed_position=True,
                position_side="long",
                entry_price=100,
                initial_quantity=0.001,
                last_entry_signal_key="trend:60:100:buy",
            )
        )
        position = {
            "symbol": "BTCUSDC",
            "side": "long",
            "quantity": 0.001,
            "entry_price": 100,
            "mark_price": 99.61,
            "leverage": 125,
        }
        outcome = self.engine.process(
            bot(leverage=125, stopLossPercent=50),
            strategy("hold", 99.61),
            account([position]),
        )
        self.assertFalse(outcome.order_sent)

    def test_disabled_strategy_still_protects_managed_position(self) -> None:
        self.store.save(
            ExecutionState(
                managed_position=True,
                position_side="long",
                entry_price=100,
                initial_quantity=0.001,
                last_entry_signal_key="trend:60:100:buy",
            )
        )
        position = {"symbol": "BTCUSDC", "side": "long", "quantity": 0.001, "entry_price": 100, "mark_price": 97}
        outcome = self.engine.process(
            bot(enabled=False, stopOnCandleClose=True),
            {"signal": "hold", "signal_key": "offline", "price": 97, "closed_candle_price": 0},
            account([position]),
        )
        self.assertTrue(outcome.order_sent)
        self.assertTrue(self.client.orders[0]["reduce_only"])

    def test_hedge_mode_blocks_execution(self) -> None:
        value = account()
        value["position_mode"] = "hedge"
        outcome = self.engine.process(bot(), strategy("buy"), value)
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(self.client.orders, [])

    def test_rejected_close_is_retried_with_a_new_client_id(self) -> None:
        self.client.query_results["old-close-id"] = {"status": "CANCELED"}
        self.store.save(
            ExecutionState(
                managed_position=True,
                position_side="long",
                entry_price=100,
                initial_quantity=0.001,
                pending_close_client_id="old-close-id",
                pending_close_percent=100,
                pending_close_action="stop_loss",
                last_entry_signal_key="trend:60:100:buy",
            )
        )
        position = {"symbol": "BTCUSDC", "side": "long", "quantity": 0.001, "entry_price": 100, "mark_price": 97}
        outcome = self.engine.process(bot(), strategy("hold", 97), account([position]))
        self.assertTrue(outcome.order_sent)
        self.assertNotEqual(self.client.orders[0]["client_order_id"], "old-close-id")


if __name__ == "__main__":
    unittest.main()
