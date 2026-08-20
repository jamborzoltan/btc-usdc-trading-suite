from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LIVE_CONFIRMATION_PHRASE = "ENGEDÉLYEZEM_A_BTCUSDC_ÉLES_KERESKEDÉST"


class LiveTradingLocked(RuntimeError):
    """Az éles megbízási retesz nem engedélyezi a végrehajtást."""


@dataclass(frozen=True)
class LiveTradingPolicy:
    enabled: bool
    acknowledgement: str
    max_order_notional_usdc: float
    max_daily_loss_usdc: float

    max_position_loss_percent: float = 50

    def _assert_live_account(self, account: dict[str, Any]) -> None:
        if not self.enabled or self.acknowledgement != LIVE_CONFIRMATION_PHRASE:
            raise LiveTradingLocked("Az éles kereskedés konfigurációs retesze zárva van.")
        if not account.get("connected") or not account.get("can_trade"):
            raise LiveTradingLocked("A Binance számla nem kapcsolódik vagy nem kereskedhet.")

    def assert_entry_allowed(
        self,
        notional_usdc: float,
        margin_usdc: float,
        daily_realized_loss_usdc: float,
        account: dict[str, Any],
        estimated_margin_loss_percent: float,
    ) -> None:
        """Új kockázat nyitása előtt ellenőrzi a helyi, kötelező limiteket."""

        self._assert_live_account(account)
        if notional_usdc <= 0 or notional_usdc > self.max_order_notional_usdc:
            raise LiveTradingLocked("A megbízás névértéke kívül esik az engedélyezett korláton.")
        if daily_realized_loss_usdc >= self.max_daily_loss_usdc:
            raise LiveTradingLocked("A napi veszteséglimit elérte a beállított határt.")
        available = float(account.get("available_balance") or 0)
        if margin_usdc <= 0 or margin_usdc > available:
            raise LiveTradingLocked("A tervezett margin nagyobb a Binance elérhető egyenlegénél.")
        if estimated_margin_loss_percent > self.max_position_loss_percent:
            raise LiveTradingLocked(
                "A stop PnL%-a meghaladja a helyi pozícióveszteség-korlátot."
            )

    def assert_close_allowed(self, account: dict[str, Any]) -> None:
        """A kockázatcsökkentő zárást a belépési limitek nem akadályozhatják."""

        self._assert_live_account(account)


@dataclass
class ExecutionState:
    version: int = 1
    managed_position: bool = False
    position_side: str = ""
    entry_price: float = 0.0
    initial_quantity: float = 0.0
    peak_return_percent: float = 0.0
    partial_taken: bool = False
    profit_fade_done: bool = False
    pending_entry_client_id: str = ""
    pending_entry_at: str = ""
    pending_close_client_id: str = ""
    pending_close_percent: float = 0.0
    pending_close_action: str = ""
    close_retry_sequence: int = 0
    last_entry_signal_key: str = ""
    last_action: str = ""
    last_action_message: str = ""
    last_action_at: str = ""
    bot_snapshot: dict[str, Any] = field(default_factory=dict)

    def clear_position(self) -> None:
        self.managed_position = False
        self.position_side = ""
        self.entry_price = 0.0
        self.initial_quantity = 0.0
        self.peak_return_percent = 0.0
        self.partial_taken = False
        self.profit_fade_done = False
        self.pending_entry_client_id = ""
        self.pending_entry_at = ""
        self.pending_close_client_id = ""
        self.pending_close_percent = 0.0
        self.pending_close_action = ""
        self.close_retry_sequence = 0


class ExecutionStateStore:
    """A trailing és részleges zárási állapotot atomikusan tartja a mini PC-n."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ExecutionState:
        if not self.path.is_file():
            return ExecutionState()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LiveTradingLocked(f"A helyi végrehajtási állapot nem olvasható: {error}") from error
        if not isinstance(value, dict) or value.get("version") != 1:
            raise LiveTradingLocked("A helyi végrehajtási állapot verziója vagy formátuma hibás.")
        allowed = ExecutionState.__dataclass_fields__.keys()
        try:
            state = ExecutionState(**{key: value[key] for key in allowed if key in value})
        except TypeError as error:
            raise LiveTradingLocked("A helyi végrehajtási állapot mezői hibásak.") from error
        if not isinstance(state.bot_snapshot, dict):
            raise LiveTradingLocked("A helyi végrehajtási állapot bot_snapshot mezője hibás.")
        return state

    def save(self, state: ExecutionState) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            temporary.write_text(
                json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            raise LiveTradingLocked(f"A helyi végrehajtási állapot nem menthető: {error}") from error


def client_order_id(action_key: str) -> str:
    digest = hashlib.sha256(action_key.encode("utf-8")).hexdigest()[:28]
    return f"btcusdc-{digest}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
