from __future__ import annotations

from dataclasses import dataclass
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

    def assert_order_allowed(
        self,
        notional_usdc: float,
        daily_realized_loss_usdc: float,
        account: dict[str, Any],
    ) -> None:
        """Későbbi order-küldés előtt kötelezően meghívandó biztonsági kapu.

        A jelenlegi verzióban nincs order-küldő API-metódus, ezért ez a kapu
        kizárólag a következő fázis szerződését és korlátait rögzíti.
        """

        if not self.enabled or self.acknowledgement != LIVE_CONFIRMATION_PHRASE:
            raise LiveTradingLocked("Az éles kereskedés konfigurációs retesze zárva van.")
        if not account.get("connected") or not account.get("can_trade"):
            raise LiveTradingLocked("A Binance számla nem kapcsolódik vagy nem kereskedhet.")
        if notional_usdc <= 0 or notional_usdc > self.max_order_notional_usdc:
            raise LiveTradingLocked("A megbízás névértéke kívül esik az engedélyezett korláton.")
        if daily_realized_loss_usdc >= self.max_daily_loss_usdc:
            raise LiveTradingLocked("A napi veszteséglimit elérte a beállított határt.")
