#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                      SYMBOL REGISTRY                               ║
║                                                                    ║
║  Central config for all tradable symbols.                          ║
║  Add new symbols here — everything else adapts automatically.      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SymbolConfig:
    """Immutable config for a tradable instrument."""
    key: str                    # Internal key: "XAUUSD", "BTCUSD"
    twelvedata_symbol: str      # TwelveData API symbol
    display_name: str           # "XAU/USD", "BTC/USD"
    emoji: str                  # 🥇, ₿
    asset_type: str             # "commodity", "crypto"
    base_currency: str          # "XAU", "BTC"
    quote_currency: str         # "USD"
    decimal_places: int         # Price display precision
    typical_atr_pct: float      # Rough ATR% for volatility context
    description: str            # Short description

    # Fundamental data sources
    fundamental_apis: list = field(default_factory=list)


# ==========================================================================
# Symbol Registry
# ==========================================================================
SYMBOLS: dict[str, SymbolConfig] = {
    "XAUUSD": SymbolConfig(
        key="XAUUSD",
        twelvedata_symbol="XAU/USD",
        display_name="XAU/USD",
        emoji="🥇",
        asset_type="commodity",
        base_currency="XAU",
        quote_currency="USD",
        decimal_places=2,
        typical_atr_pct=0.8,
        description="Gold vs US Dollar",
        fundamental_apis=[
            "fed_rate",
            "dxy_index",
            "us_inflation",
            "gold_etf_flows",
        ],
    ),
    "BTCUSD": SymbolConfig(
        key="BTCUSD",
        twelvedata_symbol="BTC/USD",
        display_name="BTC/USD",
        emoji="₿",
        asset_type="crypto",
        base_currency="BTC",
        quote_currency="USD",
        decimal_places=2,
        typical_atr_pct=3.0,
        description="Bitcoin vs US Dollar",
        fundamental_apis=[
            "btc_network",
            "btc_dominance",
            "crypto_fear_greed",
            "btc_etf_flows",
        ],
    ),
}

DEFAULT_SYMBOL_KEY = "XAUUSD"


def get_symbol(key: str) -> Optional[SymbolConfig]:
    """Get symbol config by key (case-insensitive)."""
    return SYMBOLS.get(key.upper().replace("/", ""))


def get_symbol_by_display(display: str) -> Optional[SymbolConfig]:
    """Get symbol config by display name like 'XAU/USD'."""
    normalized = display.upper().replace(" ", "")
    for sym in SYMBOLS.values():
        if sym.display_name.replace(" ", "") == normalized:
            return sym
    return get_symbol(normalized)


def get_all_symbol_keys() -> list[str]:
    """Return all registered symbol keys."""
    return list(SYMBOLS.keys())


def get_symbol_choices_text() -> str:
    """Return formatted HTML text showing available symbols."""
    lines = []
    for sym in SYMBOLS.values():
        lines.append(
            f"  {sym.emoji} <code>{sym.display_name}</code>"
            f" — {sym.description}"
        )
    return "\n".join(lines)
