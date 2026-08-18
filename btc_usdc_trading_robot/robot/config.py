from __future__ import annotations

from dataclasses import dataclass
import configparser
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """A robot lokális konfigurációja nem indítható el biztonságosan."""


@dataclass(frozen=True)
class RobotSettings:
    mode: str
    poll_seconds: float
    state_url: str
    runtime_url: str
    runtime_token: str
    username: str | None
    password: str | None
    binance_api_key: str
    binance_api_secret: str
    binance_base_url: str
    binance_symbol: str
    recv_window_ms: int
    live_trading_enabled: bool
    live_acknowledgement: str
    max_order_notional_usdc: float
    max_daily_loss_usdc: float


def load_settings(path: Path) -> RobotSettings:
    if not path.is_file():
        raise ConfigurationError(
            f"Hiányzik a konfiguráció: {path}. Másold a robot.cfg.example fájlt robot.cfg néven."
        )

    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as error:
        raise ConfigurationError(f"A konfiguráció nem olvasható: {error}") from error

    mode = parser.get("robot", "mode", fallback="").strip().lower()
    if mode != "live_read_only":
        raise ConfigurationError("Ebben a fázisban kizárólag a mode = live_read_only engedélyezett.")

    try:
        poll_seconds = parser.getfloat("robot", "poll_seconds", fallback=5)
    except ValueError as error:
        raise ConfigurationError("A poll_seconds szám legyen.") from error
    if not 1 <= poll_seconds <= 60:
        raise ConfigurationError("A poll_seconds értéke 1 és 60 másodperc közé essen.")

    state_url = parser.get("web_state", "url", fallback="").strip()
    parsed_url = urlparse(state_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ConfigurationError("A web_state.url teljes, HTTPS-es cím legyen.")

    runtime_url = parser.get("web_state", "runtime_url", fallback="").strip()
    parsed_runtime_url = urlparse(runtime_url)
    if parsed_runtime_url.scheme != "https" or not parsed_runtime_url.netloc:
        raise ConfigurationError("A web_state.runtime_url teljes, HTTPS-es cím legyen.")
    runtime_token = parser.get("web_state", "runtime_token", fallback="").strip()
    if len(runtime_token) < 24:
        raise ConfigurationError("A web_state.runtime_token legalább 24 karakteres, titkos érték legyen.")

    username = parser.get("web_state", "username", fallback="").strip() or None
    password = parser.get("web_state", "password", fallback="").strip() or None
    if bool(username) != bool(password):
        raise ConfigurationError("Basic Auth használatakor a username és password is kötelező.")

    binance_api_key = parser.get("binance_usdm", "api_key", fallback="").strip()
    binance_api_secret = parser.get("binance_usdm", "api_secret", fallback="").strip()
    if not binance_api_key or not binance_api_secret:
        raise ConfigurationError("A [binance_usdm] api_key és api_secret kitöltése kötelező.")
    binance_base_url = parser.get(
        "binance_usdm", "base_url", fallback="https://fapi.binance.com"
    ).strip().rstrip("/")
    parsed_binance_url = urlparse(binance_base_url)
    if parsed_binance_url.scheme != "https" or parsed_binance_url.hostname != "fapi.binance.com":
        raise ConfigurationError("A binance_usdm.base_url ebben a verzióban https://fapi.binance.com legyen.")
    binance_symbol = parser.get("binance_usdm", "symbol", fallback="BTCUSDC").strip().upper()
    if binance_symbol != "BTCUSDC":
        raise ConfigurationError("Ez a robot kizárólag a BTCUSDC USDⓈ-M párra van előkészítve.")
    try:
        recv_window_ms = parser.getint("binance_usdm", "recv_window_ms", fallback=5000)
    except ValueError as error:
        raise ConfigurationError("A recv_window_ms egész szám legyen.") from error
    if not 1000 <= recv_window_ms <= 5000:
        raise ConfigurationError("A recv_window_ms értéke 1000 és 5000 ms közé essen.")

    live_trading_enabled = parser.getboolean("live_trading", "enabled", fallback=False)
    live_acknowledgement = parser.get("live_trading", "acknowledgement", fallback="").strip()
    try:
        max_order_notional_usdc = parser.getfloat("live_trading", "max_order_notional_usdc", fallback=0)
        max_daily_loss_usdc = parser.getfloat("live_trading", "max_daily_loss_usdc", fallback=0)
    except ValueError as error:
        raise ConfigurationError("Az éles kereskedési limitek számok legyenek.") from error
    if live_trading_enabled:
        raise ConfigurationError(
            "Az order-küldés ebben a verzióban még kód szinten zárolt; hagyd a live_trading.enabled értékét false-on."
        )

    return RobotSettings(
        mode=mode,
        poll_seconds=poll_seconds,
        state_url=state_url,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
        username=username,
        password=password,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        binance_base_url=binance_base_url,
        binance_symbol=binance_symbol,
        recv_window_ms=recv_window_ms,
        live_trading_enabled=live_trading_enabled,
        live_acknowledgement=live_acknowledgement,
        max_order_notional_usdc=max(0, max_order_notional_usdc),
        max_daily_loss_usdc=max(0, max_daily_loss_usdc),
    )
