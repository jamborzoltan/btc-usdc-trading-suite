from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from robot.config import ConfigurationError, load_settings
from robot.execution import LiveTradingLocked, LiveTradingPolicy
from robot.state_store import RemoteStateStore


VALID_CONFIG = """
[robot]
mode = live_read_only
poll_seconds = 1
[web_state]
url = https://example.com/api/state.php
runtime_url = https://example.com/api/robot-runtime.php
runtime_token = 123456789012345678901234
[binance_usdm]
api_key = read-only-key
api_secret = read-only-secret
base_url = https://fapi.binance.com
symbol = BTCUSDC
recv_window_ms = 5000
[live_trading]
enabled = false
max_order_notional_usdc = 0
max_daily_loss_usdc = 0
"""


class ConfigurationTests(unittest.TestCase):
    def load(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "robot.cfg"
            path.write_text(content, encoding="utf-8")
            return load_settings(path)

    def test_read_only_configuration_loads(self) -> None:
        settings = self.load(VALID_CONFIG)
        self.assertEqual(settings.mode, "live_read_only")
        self.assertEqual(settings.binance_symbol, "BTCUSDC")
        self.assertFalse(settings.live_trading_enabled)

    def test_live_switch_is_rejected_by_current_build(self) -> None:
        content = VALID_CONFIG.replace("enabled = false", "enabled = true")
        with self.assertRaises(ConfigurationError):
            self.load(content)


class ExecutionGateTests(unittest.TestCase):
    def test_disabled_policy_always_rejects_orders(self) -> None:
        policy = LiveTradingPolicy(False, "", 100, 20)
        with self.assertRaises(LiveTradingLocked):
            policy.assert_order_allowed(10, 0, {"connected": True, "can_trade": True})


class RemoteStateAuthenticationTests(unittest.TestCase):
    def test_state_reads_use_the_machine_token(self) -> None:
        token = "123456789012345678901234"
        store = RemoteStateStore("https://example.com/api/state.php", token)
        self.assertEqual(store.headers["X-Robot-Token"], token)


if __name__ == "__main__":
    unittest.main()
