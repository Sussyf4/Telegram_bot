#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   FUNDAMENTAL DATA ENGINE                          ║
║                                                                    ║
║  Fetches macro & on-chain data for Gold and Bitcoin.               ║
║  Purely synchronous — runs inside run_in_executor().               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from symbols import SymbolConfig

logger = logging.getLogger("XAUUSD_Bot.fundamental")

TIMEOUT = 10


@dataclass
class FundamentalData:
    """Fundamental analysis data for any asset."""
    symbol_key: str = ""
    symbol_name: str = ""

    # ── Macro ─────────────────────────────────────────
    fed_rate: str = "N/A"
    dxy_index: str = "N/A"
    us_cpi_yoy: str = "N/A"
    us_10y_yield: str = "N/A"

    # ── Gold specific ─────────────────────────────────
    gold_etf_flows: str = "N/A"
    central_bank_buying: str = "N/A"
    gold_supply_note: str = "N/A"

    # ── Crypto specific ───────────────────────────────
    fear_greed_index: str = "N/A"
    fear_greed_label: str = "N/A"
    btc_dominance: str = "N/A"
    btc_market_cap: str = "N/A"
    btc_24h_volume: str = "N/A"
    btc_circulating: str = "N/A"
    btc_hashrate: str = "N/A"
    btc_active_addresses: str = "N/A"
    btc_etf_note: str = "N/A"

    # ── Interpretation ────────────────────────────────
    macro_outlook: str = "N/A"
    fundamental_bias: str = "N/A"
    key_drivers: list = field(default_factory=list)
    risk_factors: list = field(default_factory=list)
    combined_score: str = "N/A"


class FundamentalEngine:
    """Fetch fundamental data from public APIs."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "XAUUSD-BTC-Bot/4.0"}
        )

    def fetch_fundamentals(
        self, symbol: SymbolConfig
    ) -> FundamentalData:
        """Dispatch to the right fetcher based on asset type."""
        data = FundamentalData(
            symbol_key=symbol.key,
            symbol_name=symbol.display_name,
        )

        if symbol.asset_type == "crypto":
            data = self._fetch_crypto_fundamentals(
                data, symbol
            )
        elif symbol.asset_type == "commodity":
            data = self._fetch_gold_fundamentals(
                data, symbol
            )

        # Common macro
        data = self._fetch_macro_data(data)

        # Interpret
        data = self._interpret(data, symbol)

        return data

    # ──────────────────────────────────────────────────
    # Crypto: CoinGecko + Alternative.me
    # ──────────────────────────────────────────────────
    def _fetch_crypto_fundamentals(
        self,
        data: FundamentalData,
        symbol: SymbolConfig,
    ) -> FundamentalData:
        # Fear & Greed Index
        try:
            resp = self.session.get(
                "https://api.alternative.me/fng/"
                "?limit=1",
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            fng = resp.json()["data"][0]
            data.fear_greed_index = fng["value"]
            data.fear_greed_label = fng[
                "value_classification"
            ]
            logger.info(
                f"Fear & Greed: {fng['value']} "
                f"({fng['value_classification']})"
            )
        except Exception as exc:
            logger.warning(
                f"Fear & Greed fetch failed: {exc}"
            )

        # CoinGecko market data
        try:
            resp = self.session.get(
                "https://api.coingecko.com/api/v3/"
                "coins/bitcoin"
                "?localization=false"
                "&tickers=false"
                "&community_data=false"
                "&developer_data=false",
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            cg = resp.json()

            md = cg.get("market_data", {})
            data.btc_market_cap = self._format_large(
                md.get("market_cap", {}).get("usd", 0)
            )
            data.btc_24h_volume = self._format_large(
                md.get("total_volume", {}).get("usd", 0)
            )
            data.btc_circulating = self._format_large(
                md.get("circulating_supply", 0)
            )

            dom = md.get(
                "market_cap_change_percentage_24h", 0
            )
            data.btc_dominance = f"{dom:+.2f}% (24h)"

            logger.info(
                f"CoinGecko BTC data fetched: "
                f"MCap={data.btc_market_cap}"
            )
        except Exception as exc:
            logger.warning(
                f"CoinGecko fetch failed: {exc}"
            )

        # Blockchain.info for hashrate
        try:
            resp = self.session.get(
                "https://blockchain.info/q/hashrate",
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            hashrate_gh = float(resp.text)
            data.btc_hashrate = (
                f"{hashrate_gh / 1e9:.1f} EH/s"
            )
            logger.info(
                f"BTC Hashrate: {data.btc_hashrate}"
            )
        except Exception as exc:
            logger.warning(
                f"Hashrate fetch failed: {exc}"
            )

        data.btc_etf_note = (
            "Spot BTC ETFs approved — "
            "institutional inflows active"
        )

        return data

    # ──────────────────────────────────────────────────
    # Gold: Macro proxies
    # ──────────────────────────────────────────────────
    def _fetch_gold_fundamentals(
        self,
        data: FundamentalData,
        symbol: SymbolConfig,
    ) -> FundamentalData:
        # Gold fundamentals mostly come from macro data
        # which is fetched separately.
        # Add gold-specific context notes.
        data.gold_etf_flows = (
            "Monitor GLD/IAU ETF flow reports "
            "for institutional sentiment"
        )
        data.central_bank_buying = (
            "Central banks remain net buyers of gold "
            "(2024 trend continuing)"
        )
        data.gold_supply_note = (
            "Mine production stable; "
            "recycling supply elevated"
        )

        return data

    # ──────────────────────────────────────────────────
    # Macro indicators
    # ──────────────────────────────────────────────────
    def _fetch_macro_data(
        self, data: FundamentalData
    ) -> FundamentalData:
        # DXY from TwelveData-style public endpoint
        try:
            resp = self.session.get(
                "https://api.twelvedata.com/price"
                "?symbol=DXY&apikey=demo&dp=2",
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()
            if "price" in result:
                dxy = float(result["price"])
                data.dxy_index = f"{dxy:.2f}"
                logger.info(f"DXY: {dxy:.2f}")
        except Exception as exc:
            logger.warning(f"DXY fetch failed: {exc}")

        # Federal Reserve rate — static from last
        # known meeting (updated periodically)
        data.fed_rate = "5.25-5.50%"
        data.us_cpi_yoy = "~3.0% (latest)"
        data.us_10y_yield = "Monitor live"

        return data

    # ──────────────────────────────────────────────────
    # Interpretation
    # ──────────────────────────────────────────────────
    def _interpret(
        self,
        data: FundamentalData,
        symbol: SymbolConfig,
    ) -> FundamentalData:
        drivers = []
        risks = []
        bull_count = 0
        bear_count = 0

        if symbol.asset_type == "crypto":
            # Fear & Greed
            try:
                fng_val = int(data.fear_greed_index)
                if fng_val >= 75:
                    bear_count += 1
                    risks.append(
                        "Extreme greed — correction risk"
                    )
                elif fng_val >= 55:
                    bull_count += 1
                    drivers.append(
                        "Greed sentiment supports upside"
                    )
                elif fng_val >= 25:
                    drivers.append(
                        "Neutral sentiment — "
                        "watch for catalyst"
                    )
                else:
                    bull_count += 1
                    drivers.append(
                        "Fear sentiment — "
                        "contrarian buy signal"
                    )
            except (ValueError, TypeError):
                pass

            drivers.append(
                "Spot BTC ETF inflows "
                "driving institutional demand"
            )
            risks.append(
                "Regulatory uncertainty "
                "remains in key markets"
            )

        elif symbol.asset_type == "commodity":
            # Gold fundamentals interpretation
            drivers.append(
                "Central bank buying "
                "continues to support floor"
            )
            drivers.append(
                "Geopolitical tensions "
                "boost safe-haven demand"
            )
            risks.append(
                "Strong USD (high DXY) "
                "pressures gold prices"
            )
            risks.append(
                "Higher real yields "
                "reduce gold attractiveness"
            )

            # DXY interpretation
            try:
                dxy = float(data.dxy_index)
                if dxy > 105:
                    bear_count += 1
                    risks.append(
                        f"Strong dollar "
                        f"(DXY {dxy:.1f}) — "
                        f"headwind for gold"
                    )
                elif dxy < 100:
                    bull_count += 1
                    drivers.append(
                        f"Weak dollar "
                        f"(DXY {dxy:.1f}) — "
                        f"tailwind for gold"
                    )
            except (ValueError, TypeError):
                pass

        data.key_drivers = drivers
        data.risk_factors = risks

        if bull_count > bear_count:
            data.fundamental_bias = "Bullish"
            data.macro_outlook = "Supportive"
        elif bear_count > bull_count:
            data.fundamental_bias = "Bearish"
            data.macro_outlook = "Headwind"
        else:
            data.fundamental_bias = "Neutral"
            data.macro_outlook = "Mixed"

        data.combined_score = (
            f"Fundamental: {data.fundamental_bias} "
            f"({bull_count} bull / "
            f"{bear_count} bear factors)"
        )

        return data

    @staticmethod
    def _format_large(value) -> str:
        """Format large numbers for display."""
        try:
            val = float(value)
            if val >= 1e12:
                return f"${val / 1e12:.2f}T"
            elif val >= 1e9:
                return f"${val / 1e9:.2f}B"
            elif val >= 1e6:
                return f"${val / 1e6:.2f}M"
            elif val >= 1e3:
                return f"{val / 1e3:.1f}K"
            else:
                return f"{val:.0f}"
        except (ValueError, TypeError):
            return "N/A"
