from __future__ import annotations

import unittest

from robot.binance_usdm import BinanceApiError, BinanceUsdmClient


class StubBinanceClient(BinanceUsdmClient):
    def __init__(self) -> None:
        super().__init__("test-key", "test-secret")

    def _signed_get(self, path, params=None):  # type: ignore[override]
        if path == "/fapi/v3/account":
            return {
                "canTrade": True,
                "assets": [
                    {
                        "asset": "USDC",
                        "walletBalance": "1541.00",
                        "unrealizedProfit": "6.25",
                        "marginBalance": "1547.25",
                        "availableBalance": "1200.50",
                        "crossWalletBalance": "1500.00",
                        "maxWithdrawAmount": "1190.50",
                        "marginAvailable": True,
                    }
                ],
            }
        if path == "/fapi/v3/positionRisk":
            self.assert_symbol(params)
            return [
                {
                    "symbol": "BTCUSDC",
                    "positionSide": "BOTH",
                    "positionAmt": "-0.1258",
                    "entryPrice": "64000",
                    "breakEvenPrice": "63980",
                    "markPrice": "63500",
                    "liquidationPrice": "68250",
                    "unRealizedProfit": "62.90",
                    "notional": "-7988.30",
                    "positionInitialMargin": "399.42",
                    "isolatedMargin": "400.00",
                    "leverage": "20",
                    "marginType": "isolated",
                    "marginAsset": "USDC",
                    "updateTime": 1_700_000_000_000,
                }
            ]
        if path == "/fapi/v1/accountConfig":
            return {"dualSidePosition": False, "multiAssetsMargin": False, "canTrade": True}
        raise AssertionError(path)

    @staticmethod
    def assert_symbol(params):
        if params != {"symbol": "BTCUSDC"}:
            raise AssertionError(params)


class BinanceAccountSnapshotTests(unittest.TestCase):
    def test_usdc_balance_and_short_position_are_sanitized(self) -> None:
        snapshot = StubBinanceClient().account_snapshot("BTCUSDC")

        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["asset"], "USDC")
        self.assertEqual(snapshot["wallet_balance"], 1541.0)
        self.assertEqual(snapshot["margin_balance"], 1547.25)
        self.assertEqual(snapshot["position_mode"], "one_way")
        self.assertEqual(len(snapshot["positions"]), 1)
        position = snapshot["positions"][0]
        self.assertEqual(position["side"], "short")
        self.assertEqual(position["quantity"], 0.1258)
        self.assertEqual(position["leverage"], 20)
        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("api_secret", snapshot)

    def test_bnfcr_credit_balance_is_used_when_usdc_row_is_zero(self) -> None:
        client = StubBinanceClient()
        original_signed_get = client._signed_get

        def credit_response(path, params=None):
            if path == "/fapi/v3/account":
                return {
                    "assets": [
                        {
                            "asset": "USDC",
                            "walletBalance": "0",
                            "unrealizedProfit": "0",
                            "marginBalance": "0",
                            "availableBalance": "0",
                        },
                        {
                            "asset": "BNFCR",
                            "walletBalance": "30.68581051",
                            "unrealizedProfit": "0",
                            "marginBalance": "30.68581051",
                            "availableBalance": "30.68581051",
                        },
                    ],
                }
            return original_signed_get(path, params)

        client._signed_get = credit_response  # type: ignore[method-assign]
        snapshot = client.account_snapshot("BTCUSDC")

        self.assertEqual(snapshot["asset"], "BNFCR")
        self.assertEqual(snapshot["quote_asset"], "USDC")
        self.assertTrue(snapshot["credit_mode"])
        self.assertEqual(snapshot["wallet_balance"], 30.68581051)
        self.assertEqual(snapshot["available_balance"], 30.68581051)
        self.assertEqual(snapshot["positions"][0]["pnl_asset"], "BNFCR")


class StubTradingClient(BinanceUsdmClient):
    def __init__(self) -> None:
        super().__init__("test-key", "test-secret")
        self.posts = []
        self.existing_order = None

    def _public_get(self, path, params=None):  # type: ignore[override]
        if path != "/fapi/v1/exchangeInfo":
            raise AssertionError(path)
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDC",
                    "status": "TRADING",
                    "filters": [
                        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                }
            ]
        }

    def _signed_get(self, path, params=None):  # type: ignore[override]
        if path == "/fapi/v1/order":
            if self.existing_order is not None:
                return self.existing_order
            raise BinanceApiError("Order does not exist", code=-2013)
        if path == "/fapi/v1/income":
            return [
                {"incomeType": "REALIZED_PNL", "income": "-3.5"},
                {"incomeType": "COMMISSION", "income": "-0.5"},
                {"incomeType": "TRANSFER", "income": "-100"},
            ]
        raise AssertionError(path)

    def _signed_post(self, path, params=None):  # type: ignore[override]
        self.posts.append((path, params))
        if path == "/fapi/v1/leverage":
            return {"symbol": "BTCUSDC", "leverage": params["leverage"]}
        if path == "/fapi/v1/order":
            return {"status": "FILLED", "clientOrderId": params["newClientOrderId"]}
        raise AssertionError(path)


class BinanceTradingTests(unittest.TestCase):
    def test_market_quantity_is_rounded_down_to_exchange_step(self) -> None:
        client = StubTradingClient()
        self.assertEqual(client.quantity_for_notional("BTCUSDC", 100, 64_000), "0.001")
        self.assertEqual(client.close_quantity("BTCUSDC", 0.003, 50), "0.001")

    def test_idempotent_market_order_uses_client_id_and_reduce_only(self) -> None:
        client = StubTradingClient()
        order = client.place_market_order(
            "BTCUSDC", "SELL", "0.001", "btcusdc-test", reduce_only=True
        )
        self.assertEqual(order["status"], "FILLED")
        _, params = client.posts[-1]
        self.assertEqual(params["newClientOrderId"], "btcusdc-test")
        self.assertEqual(params["reduceOnly"], "true")

    def test_daily_loss_includes_realized_pnl_commission_but_not_transfer(self) -> None:
        self.assertEqual(StubTradingClient().daily_loss_usdc("BTCUSDC"), 4.0)

    def test_existing_client_order_is_not_posted_again(self) -> None:
        client = StubTradingClient()
        client.existing_order = {"status": "FILLED", "clientOrderId": "btcusdc-existing"}
        order = client.place_market_order(
            "BTCUSDC", "BUY", "0.001", "btcusdc-existing", reduce_only=False
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(client.posts, [])


if __name__ == "__main__":
    unittest.main()
