#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    UNIFIED MARKET DATA CLIENT                      ║
║                                                                    ║
║  Purely synchronous — runs inside run_in_executor().               ║
║  NO asyncio calls. API tracking done by the caller.                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
import pandas as pd

from symbols import SymbolConfig

logger = logging.getLogger("XAUUSD_Bot.market_data")

TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
DEFAULT_OUTPUTSIZE = 100


class MarketDataClient:
    """
    Synchronous HTTP client for Twelve Data.
    Supports any symbol from the registry.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "XAUUSD-BTC-Bot/4.0"}
        )

    def fetch_time_series(
        self,
        symbol: SymbolConfig,
        interval: str,
        outputsize: int = DEFAULT_OUTPUTSIZE,
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV candles for any symbol."""
        url = f"{TWELVEDATA_BASE_URL}/time_series"
        params = {
            "symbol": symbol.twelvedata_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": self.api_key,
            "format": "JSON",
            "dp": symbol.decimal_places,
        }
        try:
            logger.info(
                f"Fetching {symbol.display_name} | "
                f"interval={interval} | size={outputsize}"
            )
            response = self.session.get(
                url, params=params, timeout=15
            )
            response.raise_for_status()
            data = response.json()

            if "code" in data and data["code"] != 200:
                logger.error(
                    f"TwelveData error for "
                    f"{symbol.display_name}: "
                    f"{data.get('message', 'Unknown')}"
                )
                return None
            if "values" not in data or not data["values"]:
                logger.error(
                    f"TwelveData empty values for "
                    f"{symbol.display_name}"
                )
                return None

            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(
                    df[col], errors="coerce"
                )
            if "volume" in df.columns:
                df["volume"] = (
                    pd.to_numeric(
                        df["volume"], errors="coerce"
                    ).fillna(0)
                )
            else:
                df["volume"] = 0

            df = df.sort_values("datetime").reset_index(
                drop=True
            )
            df = df.dropna(
                subset=["open", "high", "low", "close"]
            ).reset_index(drop=True)

            logger.info(
                f"Fetched {len(df)} candles for "
                f"{symbol.display_name}"
            )
            return df

        except requests.exceptions.Timeout:
            logger.error(
                f"Timeout fetching {symbol.display_name}"
            )
        except requests.exceptions.ConnectionError:
            logger.error(
                f"Connection error for "
                f"{symbol.display_name}"
            )
        except requests.exceptions.HTTPError as exc:
            logger.error(f"HTTP error: {exc}")
        except (ValueError, KeyError) as exc:
            logger.error(f"Parse error: {exc}")
        return None

    def fetch_current_price(
        self, symbol: SymbolConfig
    ) -> Optional[dict]:
        """Fetch real-time price for any symbol."""
        url = f"{TWELVEDATA_BASE_URL}/price"
        params = {
            "symbol": symbol.twelvedata_symbol,
            "apikey": self.api_key,
            "dp": symbol.decimal_places,
        }
        try:
            response = self.session.get(
                url, params=params, timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if "price" not in data:
                logger.error(
                    f"No price for "
                    f"{symbol.display_name}: {data}"
                )
                return None

            return {
                "price": float(data["price"]),
                "symbol": symbol.display_name,
                "emoji": symbol.emoji,
                "timestamp": datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        except Exception as exc:
            logger.error(
                f"Price fetch error "
                f"{symbol.display_name}: {exc}"
            )
            return None

    def fetch_multiple_timeframes(
        self,
        symbol: SymbolConfig,
        intervals: list[str],
        outputsize: int = 60,
    ) -> dict[str, Optional[pd.DataFrame]]:
        """Fetch data for multiple timeframes at once."""
        results = {}
        for interval in intervals:
            results[interval] = self.fetch_time_series(
                symbol, interval, outputsize
            )
        return results
