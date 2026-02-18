#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD AI ANALYSIS BOT v2.1                     ║
║                                                                    ║
║  Production-ready Telegram bot for XAU/USD technical analysis      ║
║  Uses: google-genai SDK, Twelve Data, python-telegram-bot          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# =============================================================================
# IMPORTS
# =============================================================================
import os
import io
import re
import logging
import asyncio
import time
import traceback
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import requests
import pandas as pd
import ta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from google import genai
from google.genai import types

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

# =============================================================================
# CONFIGURATION & ENVIRONMENT
# =============================================================================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_missing = []
if not TELEGRAM_BOT_TOKEN:
    _missing.append("TELEGRAM_BOT_TOKEN")
if not TWELVEDATA_API_KEY:
    _missing.append("TWELVEDATA_API_KEY")
if not GEMINI_API_KEY:
    _missing.append("GEMINI_API_KEY")
if _missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        f"Please set them in your .env file."
    )

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt enc="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("XAUUSD_Bot")

# =============================================================================
# CONSTANTS
# =============================================================================
TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
SYMBOL = "XAU/USD"
DEFAULT_OUTPUTSIZE = 100
GEMINI_MODEL = "gemini-2.5-flash"
CHART_STYLE = "dark_background"
CHART_DPI = 150
CHART_FIGSIZE = (14, 10)

# =============================================================================
# COLOR CONSTANTS
# =============================================================================
COLOR_GREEN = "#26a69a"
COLOR_RED = "#ef5350"
COLOR_BLUE = "#2196F3"
COLOR_ORANGE = "#FF9800"
COLOR_PURPLE = "#AB47BC"
COLOR_GREEN_BRIGHT = "#4CAF50"
COLOR_RED_BRIGHT = "#f44336"
COLOR_GOLD = "gold"
COLOR_WHITE = "white"
COLOR_GRAY = "gray"


# =============================================================================
# ENUMS
# =============================================================================
class Timeframe(Enum):
    M5 = "5min"
    M15 = "15min"
    H1 = "1h"
    H4 = "4h"
    D1 = "1day"

    @classmethod
    def from_user_input(cls, text: str) -> Optional["Timeframe"]:
        mapping = {
            "5m": cls.M5, "5min": cls.M5,
            "15m": cls.M15, "15min": cls.M15,
            "1h": cls.H1, "60m": cls.H1, "60min": cls.H1,
            "4h": cls.H4, "240m": cls.H4, "240min": cls.H4,
            "1d": cls.D1, "daily": cls.D1, "d1": cls.D1, "1day": cls.D1,
        }
        return mapping.get(text.lower().strip())

    @property
    def display_name(self) -> str:
        names = {
            "5min": "5 Min",
            "15min": "15 Min",
            "1h": "1 Hour",
            "4h": "4 Hour",
            "1day": "Daily",
        }
        return names.get(self.value, self.value)


# =============================================================================
# DATA CLASSES
# =============================================================================
@dataclass
class TechnicalIndicators:
    rsi: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    atr: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    pivot_point: float = 0.0
    support_2: float = 0.0
    resistance_2: float = 0.0
    rsi_interpretation: str = ""
    ema_trend: str = ""
    macd_interpretation: str = ""
    volatility_condition: str = ""
    trend_direction: str = ""


@dataclass
class AIAnalysis:
    bias: str = "N/A"
    trade_idea: str = "N/A"
    entry: str = "N/A"
    stop_loss: str = "N/A"
    take_profit_1: str = "N/A"
    take_profit_2: str = "N/A"
    risk_note: str = "N/A"
    short_term_outlook: str = "N/A"
    raw_response: str = ""


@dataclass
class UserSession:
    timeframe: Timeframe = Timeframe.M15
    last_request_time: float = 0.0


# =============================================================================
# RATE LIMITER
# =============================================================================
class RateLimiter:
    def __init__(self, max_calls: int = 7, period_seconds: float = 60.0):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                oldest = self.calls[0]
                wait_time = self.period - (now - oldest) + 0.5
                logger.warning(
                    f"Rate limit reached. Waiting {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.calls = [
                    t for t in self.calls if now - t < self.period
                ]
            self.calls.append(time.monotonic())
            return True


twelvedata_limiter = RateLimiter(max_calls=7, period_seconds=60.0)
user_sessions: dict[int, UserSession] = {}


# =============================================================================
# MODULE 1: TWELVE DATA CLIENT
# =============================================================================
class TwelveDataClient:

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "XAUUSD-AI-Bot/2.1"})

    def fetch_time_series(
        self,
        interval: str,
        outputsize: int = DEFAULT_OUTPUTSIZE,
    ) -> Optional[pd.DataFrame]:
        url = f"{TWELVEDATA_BASE_URL}/time_series"
        params = {
            "symbol": SYMBOL,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": self.api_key,
            "format": "JSON",
            "dp": 2,
        }
        try:
            logger.info(
                f"Fetching {SYMBOL} | interval={interval} | size={outputsize}"
            )
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if "code" in data and data["code"] != 200:
                logger.error(
                    f"Twelve Data API error: {data.get('message', 'Unknown')}"
                )
                return None
            if "values" not in data or not data["values"]:
                logger.error("Twelve Data returned empty values")
                return None

            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if "volume" in df.columns:
                df["volume"] = (
                    pd.to_numeric(df["volume"], errors="coerce").fillna(0)
                )
            else:
                df["volume"] = 0

            df = df.sort_values("datetime").reset_index(drop=True)
            df = df.dropna(
                subset=["open", "high", "low", "close"]
            ).reset_index(drop=True)
            logger.info(f"Fetched {len(df)} candles for {SYMBOL}")
            return df

        except requests.exceptions.Timeout:
            logger.error("Twelve Data request timed out")
        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to Twelve Data")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from Twelve Data: {e}")
        except (ValueError, KeyError) as e:
            logger.error(f"Error parsing Twelve Data response: {e}")
        return None

    def fetch_current_price(self) -> Optional[dict]:
        url = f"{TWELVEDATA_BASE_URL}/price"
        params = {
            "symbol": SYMBOL,
            "apikey": self.api_key,
            "dp": 2,
        }
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "price" not in data:
                logger.error(f"No price in response: {data}")
                return None
            return {
                "price": float(data["price"]),
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
            }
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return None


td_client = TwelveDataClient(TWELVEDATA_API_KEY)


# =============================================================================
# MODULE 2: TECHNICAL ANALYSIS ENGINE (IMPROVED SUPPORT/RESISTANCE)
# =============================================================================
class TechnicalAnalysisEngine:

    @staticmethod
    def compute_indicators(
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, TechnicalIndicators]:
        indicators = TechnicalIndicators()

        if df is None or len(df) < 50:
            logger.warning(
                f"Insufficient data: {len(df) if df is not None else 0}"
            )
            return df, indicators

        # RSI (14)
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=14
        ).rsi()

        # EMA 20 & 50
        df["ema_20"] = ta.trend.EMAIndicator(
            close=df["close"], window=20
        ).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(
            close=df["close"], window=50
        ).ema_indicator()

        # MACD (12, 26, 9)
        macd_calc = ta.trend.MACD(
            close=df["close"],
            window_slow=26,
            window_fast=12,
            window_sign=9,
        )
        df["macd_line"] = macd_calc.macd()
        df["macd_signal"] = macd_calc.macd_signal()
        df["macd_histogram"] = macd_calc.macd_diff()

        # ATR (14)
        df["atr"] = ta.volatility.AverageTrueRange(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=14,
        ).average_true_range()

        # IMPROVED Support & Resistance (multi-method)
        support, resistance, pivot, s2, r2 = (
            TechnicalAnalysisEngine._compute_support_resistance(df)
        )

        # Populate summary from latest candle
        latest = df.iloc[-1]

        indicators.rsi = (
            round(latest["rsi"], 2)
            if pd.notna(latest["rsi"])
            else 0.0
        )
        indicators.ema_20 = (
            round(latest["ema_20"], 2)
            if pd.notna(latest["ema_20"])
            else 0.0
        )
        indicators.ema_50 = (
            round(latest["ema_50"], 2)
            if pd.notna(latest["ema_50"])
            else 0.0
        )
        indicators.macd_line = (
            round(latest["macd_line"], 4)
            if pd.notna(latest["macd_line"])
            else 0.0
        )
        indicators.macd_signal = (
            round(latest["macd_signal"], 4)
            if pd.notna(latest["macd_signal"])
            else 0.0
        )
        indicators.macd_histogram = (
            round(latest["macd_histogram"], 4)
            if pd.notna(latest["macd_histogram"])
            else 0.0
        )
        indicators.atr = (
            round(latest["atr"], 2)
            if pd.notna(latest["atr"])
            else 0.0
        )
        indicators.support = round(support, 2)
        indicators.resistance = round(resistance, 2)
        indicators.pivot_point = round(pivot, 2)
        indicators.support_2 = round(s2, 2)
        indicators.resistance_2 = round(r2, 2)

        # --- RSI Interpretation ---
        if indicators.rsi >= 70:
            indicators.rsi_interpretation = "Overbought"
        elif indicators.rsi >= 60:
            indicators.rsi_interpretation = "Bullish Momentum"
        elif indicators.rsi >= 40:
            indicators.rsi_interpretation = "Neutral"
        elif indicators.rsi >= 30:
            indicators.rsi_interpretation = "Bearish Momentum"
        else:
            indicators.rsi_interpretation = "Oversold"

        # --- EMA Trend ---
        if indicators.ema_20 > indicators.ema_50:
            if latest["close"] > indicators.ema_20:
                indicators.ema_trend = "Strong Bullish"
            else:
                indicators.ema_trend = "Bullish Crossover"
        elif indicators.ema_20 < indicators.ema_50:
            if latest["close"] < indicators.ema_20:
                indicators.ema_trend = "Strong Bearish"
            else:
                indicators.ema_trend = "Bearish Crossover"
        else:
            indicators.ema_trend = "Neutral"

        # --- MACD ---
        if indicators.macd_histogram > 0:
            indicators.macd_interpretation = "Positive"
        elif indicators.macd_histogram < 0:
            indicators.macd_interpretation = "Negative"
        else:
            indicators.macd_interpretation = "Neutral"

        # --- Volatility ---
        atr_pct = (
            (indicators.atr / latest["close"]) * 100
            if latest["close"] > 0
            else 0
        )
        if atr_pct > 1.0:
            indicators.volatility_condition = "High Volatility"
        elif atr_pct > 0.5:
            indicators.volatility_condition = "Moderate Volatility"
        else:
            indicators.volatility_condition = "Low Volatility"

        # --- Overall Trend ---
        bullish = sum([
            indicators.rsi > 50,
            indicators.ema_20 > indicators.ema_50,
            indicators.macd_histogram > 0,
        ])
        if bullish >= 2:
            indicators.trend_direction = "Bullish"
        elif bullish <= 0:
            indicators.trend_direction = "Bearish"
        else:
            indicators.trend_direction = "Mixed/Neutral"

        return df, indicators

    @staticmethod
    def _compute_support_resistance(
        df: pd.DataFrame,
    ) -> tuple[float, float, float, float, float]:
        """
        Multi-method support/resistance that stays CLOSE to current price.

        Combines:
        1. Pivot Points (from recent session high/low/close)
        2. Swing high/low detection on recent candles
        3. ATR-based fallback to guarantee nearby levels

        Returns: (support_1, resistance_1, pivot, support_2, resistance_2)
        """
        latest_close = df.iloc[-1]["close"]
        recent = df.tail(30).copy()

        session_high = recent["high"].max()
        session_low = recent["low"].min()
        session_close = latest_close

        # --- Method 1: Classic Pivot Points ---
        pivot = (session_high + session_low + session_close) / 3.0
        pivot_r1 = (2 * pivot) - session_low
        pivot_s1 = (2 * pivot) - session_high
        pivot_r2 = pivot + (session_high - session_low)
        pivot_s2 = pivot - (session_high - session_low)

        # --- Method 2: Swing Detection on recent candles ---
        swing_support, swing_resistance = (
            TechnicalAnalysisEngine._detect_swings(df, lookback=40, window=5)
        )

        # --- Method 3: ATR-based nearby levels ---
        atr_series = df["atr"] if "atr" in df.columns else None
        if atr_series is not None and pd.notna(atr_series.iloc[-1]):
            current_atr = atr_series.iloc[-1]
        else:
            current_atr = (session_high - session_low) / 3.0

        atr_support = latest_close - current_atr * 1.5
        atr_resistance = latest_close + current_atr * 1.5

        # --- Combine: pick the CLOSEST valid levels to price ---
        support_candidates = [
            pivot_s1,
            swing_support,
            atr_support,
        ]
        resistance_candidates = [
            pivot_r1,
            swing_resistance,
            atr_resistance,
        ]

        # Filter: support must be BELOW price, resistance ABOVE price
        valid_supports = [
            s for s in support_candidates
            if s < latest_close and s > 0
        ]
        valid_resistances = [
            r for r in resistance_candidates
            if r > latest_close
        ]

        # Pick closest to current price
        if valid_supports:
            support = max(valid_supports)  # highest support below price
        else:
            support = latest_close - current_atr * 1.5

        if valid_resistances:
            resistance = min(valid_resistances)  # lowest resistance above
        else:
            resistance = latest_close + current_atr * 1.5

        # S2/R2: wider levels
        s2_candidates = [
            pivot_s2,
            support - current_atr,
        ]
        r2_candidates = [
            pivot_r2,
            resistance + current_atr,
        ]
        support_2 = min([s for s in s2_candidates if s > 0] or [support - current_atr * 2])
        resistance_2 = max(r2_candidates)

        # Safety: ensure S < price < R
        if support >= latest_close:
            support = latest_close - current_atr
        if resistance <= latest_close:
            resistance = latest_close + current_atr
        if support_2 >= support:
            support_2 = support - current_atr
        if resistance_2 <= resistance:
            resistance_2 = resistance + current_atr

        logger.info(
            f"S/R levels: S2={support_2:.2f} S1={support:.2f} "
            f"Pivot={pivot:.2f} R1={resistance:.2f} R2={resistance_2:.2f} "
            f"(price={latest_close:.2f})"
        )

        return support, resistance, pivot, support_2, resistance_2

    @staticmethod
    def _detect_swings(
        df: pd.DataFrame, lookback: int = 40, window: int = 5
    ) -> tuple[float, float]:
        """Detect nearest swing low (support) and swing high (resistance)."""
        recent = df.tail(lookback).copy()
        latest_close = df.iloc[-1]["close"]

        swing_lows = []
        swing_highs = []

        for i in range(window, len(recent) - window):
            segment_low = recent.iloc[i - window: i + window + 1]["low"]
            segment_high = recent.iloc[i - window: i + window + 1]["high"]

            if recent.iloc[i]["low"] == segment_low.min():
                swing_lows.append(recent.iloc[i]["low"])
            if recent.iloc[i]["high"] == segment_high.max():
                swing_highs.append(recent.iloc[i]["high"])

        # Pick closest swing low below price
        valid_lows = [s for s in swing_lows if s < latest_close]
        if valid_lows:
            support = max(valid_lows)
        else:
            support = recent["low"].min()

        # Pick closest swing high above price
        valid_highs = [r for r in swing_highs if r > latest_close]
        if valid_highs:
            resistance = min(valid_highs)
        else:
            resistance = recent["high"].max()

        return support, resistance


ta_engine = TechnicalAnalysisEngine()


# =============================================================================
# MODULE 3: GEMINI AI ANALYSIS (IMPROVED PARSING)
# =============================================================================
class GeminiAnalyzer:

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = GEMINI_MODEL
        self._max_retries = 3
        self._retry_delay = 2.0
        logger.info(
            f"Gemini AI initialized | model: {self.model_name} | "
            f"SDK: google-genai (new)"
        )

    def generate_analysis(
        self,
        df: pd.DataFrame,
        indicators: TechnicalIndicators,
        timeframe: str,
    ) -> AIAnalysis:
        analysis = AIAnalysis()

        if df is None or len(df) < 10:
            analysis.raw_response = "Insufficient data for analysis."
            return analysis

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        prompt = self._build_prompt(latest, prev, indicators, timeframe, df)

        last_error = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(
                    f"Gemini request attempt {attempt}/{self._max_retries}..."
                )

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=1024,
                    ),
                )

                raw_text = response.text

                if not raw_text or len(raw_text.strip()) < 20:
                    logger.warning(
                        f"Attempt {attempt}: Empty/short response"
                    )
                    last_error = "Empty response from AI"
                    if attempt < self._max_retries:
                        time.sleep(self._retry_delay * attempt)
                    continue

                analysis.raw_response = raw_text
                logger.info(
                    f"Gemini response received ({len(raw_text)} chars)"
                )
                logger.debug(f"Raw Gemini response:\n{raw_text}")

                # Try primary parse
                analysis = self._parse_response(raw_text, analysis)

                # Count how many fields are still N/A
                na_count = sum([
                    analysis.bias == "N/A",
                    analysis.trade_idea == "N/A",
                    analysis.entry == "N/A",
                    analysis.stop_loss == "N/A",
                    analysis.take_profit_1 == "N/A",
                    analysis.take_profit_2 == "N/A",
                    analysis.risk_note == "N/A",
                    analysis.short_term_outlook == "N/A",
                ])

                logger.info(
                    f"After primary parse: {8 - na_count}/8 fields filled"
                )

                # If some fields missing, try fallback regex
                if na_count > 0:
                    analysis = self._fallback_parse(raw_text, analysis)
                    na_count_after = sum([
                        analysis.bias == "N/A",
                        analysis.trade_idea == "N/A",
                        analysis.entry == "N/A",
                        analysis.stop_loss == "N/A",
                        analysis.take_profit_1 == "N/A",
                        analysis.take_profit_2 == "N/A",
                        analysis.risk_note == "N/A",
                        analysis.short_term_outlook == "N/A",
                    ])
                    logger.info(
                        f"After fallback parse: "
                        f"{8 - na_count_after}/8 fields filled"
                    )

                # Fill any remaining N/A with indicator-based values
                analysis = self._fill_missing_fields(
                    analysis, indicators, df
                )

                if analysis.bias not in ("N/A", "Error", ""):
                    logger.info(
                        f"AI analysis complete: bias={analysis.bias}"
                    )
                    return analysis

                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)
                continue

            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Attempt {attempt}/{self._max_retries} failed: {e}"
                )
                logger.debug(traceback.format_exc())
                if attempt < self._max_retries:
                    sleep_time = self._retry_delay * attempt
                    logger.info(f"Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)

        logger.error(
            f"All {self._max_retries} attempts failed. "
            f"Last error: {last_error}"
        )
        analysis = self._generate_fallback_analysis(indicators, df)
        return analysis

    def _build_prompt(
        self,
        latest: pd.Series,
        prev: pd.Series,
        ind: TechnicalIndicators,
        timeframe: str,
        df: pd.DataFrame,
    ) -> str:
        price_change = latest["close"] - prev["close"]
        price_change_pct = (
            (price_change / prev["close"]) * 100
            if prev["close"] > 0
            else 0
        )
        last_5_closes = df["close"].tail(5).tolist()
        last_5_str = ", ".join([f"{c:.2f}" for c in last_5_closes])

        session_high = df["high"].tail(20).max()
        session_low = df["low"].tail(20).min()

        prompt = (
            "You are a senior XAUUSD (Gold) technical analyst. "
            "Analyze the data below and provide a trading recommendation.\n"
            "\n"
            "IMPORTANT RULES:\n"
            "1. You MUST respond with ALL 8 fields below, no exceptions\n"
            "2. Each field MUST be on its own line starting with the label\n"
            "3. Use exact price numbers with 2 decimal places\n"
            "4. Do NOT add any text before BIAS or after OUTLOOK\n"
            "5. Do NOT use markdown, asterisks, or bullet points\n"
            "6. TP1 should be conservative, TP2 aggressive\n"
            "7. Stop loss must account for ATR volatility\n"
            "8. If market is unclear, use BIAS: Neutral and TRADE: Wait\n"
            "\n"
            f"=== MARKET DATA - XAU/USD ({timeframe}) ===\n"
            "\n"
            f"Current Price: {latest['close']:.2f}\n"
            f"Open: {latest['open']:.2f}\n"
            f"High: {latest['high']:.2f}\n"
            f"Low: {latest['low']:.2f}\n"
            f"Change: {price_change:+.2f} ({price_change_pct:+.3f}%)\n"
            f"Last 5 Closes: {last_5_str}\n"
            f"Session High: {session_high:.2f}\n"
            f"Session Low: {session_low:.2f}\n"
            "\n"
            "=== TECHNICAL INDICATORS ===\n"
            f"RSI(14): {ind.rsi:.2f} ({ind.rsi_interpretation})\n"
            f"EMA20: {ind.ema_20:.2f}\n"
            f"EMA50: {ind.ema_50:.2f}\n"
            f"EMA Trend: {ind.ema_trend}\n"
            f"MACD Line: {ind.macd_line:.4f}\n"
            f"MACD Signal: {ind.macd_signal:.4f}\n"
            f"MACD Histogram: {ind.macd_histogram:.4f} "
            f"({ind.macd_interpretation})\n"
            f"ATR(14): {ind.atr:.2f} ({ind.volatility_condition})\n"
            f"Support S1: {ind.support:.2f}\n"
            f"Support S2: {ind.support_2:.2f}\n"
            f"Resistance R1: {ind.resistance:.2f}\n"
            f"Resistance R2: {ind.resistance_2:.2f}\n"
            f"Pivot: {ind.pivot_point:.2f}\n"
            f"Overall Trend: {ind.trend_direction}\n"
            "\n"
            "=== RESPOND EXACTLY IN THIS FORMAT ===\n"
            "\n"
            "BIAS: Bullish\n"
            "TRADE: Buy\n"
            "ENTRY: 2350.00-2352.00\n"
            "STOP_LOSS: 2340.00\n"
            "TP1: 2360.00\n"
            "TP2: 2370.00\n"
            "RISK: Brief risk assessment in one sentence.\n"
            "OUTLOOK: One to two sentence market outlook.\n"
        )
        return prompt

    def _parse_response(
        self, text: str, analysis: AIAnalysis
    ) -> AIAnalysis:
        if not text:
            return analysis

        # Clean up markdown/formatting artifacts
        text = text.replace("**", "").replace("*", "").replace("```", "")
        text = text.replace("##", "").replace("###", "")
        lines = text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try splitting on first colon
            colon_idx = line.find(":")
            if colon_idx == -1:
                continue

            key = line[:colon_idx].strip().upper()
            value = line[colon_idx + 1:].strip()

            if not value:
                continue

            # Remove leading/trailing quotes or dashes
            value = value.strip("\"'- ")

            if key in ("BIAS", "MARKET BIAS", "DIRECTION"):
                analysis.bias = value
            elif key in (
                "TRADE", "TRADE IDEA", "ACTION", "SIGNAL",
                "RECOMMENDATION"
            ):
                analysis.trade_idea = value
            elif key in ("ENTRY", "ENTRY ZONE", "ENTRY PRICE", "ENTRY RANGE"):
                analysis.entry = value
            elif key in (
                "STOP_LOSS", "STOP LOSS", "SL", "STOPLOSS",
                "STOP", "STOP LOSS LEVEL"
            ):
                analysis.stop_loss = value
            elif key in (
                "TP1", "TAKE PROFIT 1", "TARGET 1",
                "TAKE_PROFIT_1", "TAKEPROFIT1", "TARGET1",
                "TP 1", "FIRST TARGET"
            ):
                analysis.take_profit_1 = value
            elif key in (
                "TP2", "TAKE PROFIT 2", "TARGET 2",
                "TAKE_PROFIT_2", "TAKEPROFIT2", "TARGET2",
                "TP 2", "SECOND TARGET"
            ):
                analysis.take_profit_2 = value
            elif key in (
                "RISK", "RISK NOTE", "RISK ASSESSMENT",
                "RISK LEVEL", "RISK WARNING", "RISK MANAGEMENT"
            ):
                analysis.risk_note = value
            elif key in (
                "OUTLOOK", "SHORT TERM OUTLOOK",
                "SHORT-TERM OUTLOOK", "MARKET OUTLOOK",
                "SHORT TERM", "SUMMARY"
            ):
                analysis.short_term_outlook = value

        return analysis

    def _fallback_parse(
        self, text: str, analysis: AIAnalysis
    ) -> AIAnalysis:
        """Aggressive regex-based parsing for non-standard formats."""
        if not text:
            return analysis

        text_clean = (
            text.replace("**", "").replace("*", "").replace("`", "")
                .replace("#", "")
        )

        # Only overwrite fields that are still N/A
        patterns = {
            "bias": [
                r"(?:BIAS|MARKET\s*BIAS|DIRECTION)\s*[:=]\s*(.+?)(?:\n|$)",
                r"(?:bullish|bearish|neutral)",  # bare word
            ],
            "trade_idea": [
                r"(?:TRADE|ACTION|SIGNAL|RECOMMENDATION)\s*[:=]\s*(.+?)(?:\n|$)",
            ],
            "entry": [
                r"(?:ENTRY|ENTRY\s*(?:ZONE|PRICE|RANGE)?)\s*[:=]\s*(.+?)(?:\n|$)",
            ],
            "stop_loss": [
                r"(?:STOP[\s_]*LOSS|SL|STOP)\s*[:=]\s*(.+?)(?:\n|$)",
            ],
            "take_profit_1": [
                r"(?:TP[\s_]*1|TAKE[\s_]*PROFIT[\s_]*1|TARGET[\s_]*1|FIRST[\s_]*TARGET)\s*[:=]\s*(.+?)(?:\n|$)",
                r"TP1\s*[:=]?\s*\$?([\d,]+\.?\d*)",
            ],
            "take_profit_2": [
                r"(?:TP[\s_]*2|TAKE[\s_]*PROFIT[\s_]*2|TARGET[\s_]*2|SECOND[\s_]*TARGET)\s*[:=]\s*(.+?)(?:\n|$)",
                r"TP2\s*[:=]?\s*\$?([\d,]+\.?\d*)",
            ],
            "risk_note": [
                r"(?:RISK|RISK[\s_]*(?:NOTE|ASSESSMENT|LEVEL|WARNING|MANAGEMENT))\s*[:=]\s*(.+?)(?:\n|$)",
            ],
            "short_term_outlook": [
                r"(?:OUTLOOK|SHORT[\s\-_]*TERM[\s_]*(?:OUTLOOK)?|MARKET[\s_]*OUTLOOK|SUMMARY)\s*[:=]\s*(.+?)(?:\n|$)",
            ],
        }

        for field_name, pattern_list in patterns.items():
            current_value = getattr(analysis, field_name, "N/A")
            if current_value != "N/A":
                continue  # already filled

            for pattern in pattern_list:
                match = re.search(pattern, text_clean, re.IGNORECASE)
                if match:
                    value = match.group(1).strip() if match.lastindex else match.group(0).strip()
                    value = value.strip("\"'- ")
                    if value and value.upper() != "N/A":
                        setattr(analysis, field_name, value)
                        logger.debug(
                            f"Fallback matched {field_name}: {value}"
                        )
                        break

        return analysis

    def _fill_missing_fields(
        self,
        analysis: AIAnalysis,
        indicators: TechnicalIndicators,
        df: pd.DataFrame,
    ) -> AIAnalysis:
        """Fill any remaining N/A fields with indicator-based calculations."""
        latest_close = df.iloc[-1]["close"]
        atr = indicators.atr if indicators.atr > 0 else 5.0

        # Fill bias from indicators if missing
        if analysis.bias == "N/A":
            analysis.bias = indicators.trend_direction

        # Fill trade from bias
        if analysis.trade_idea == "N/A":
            if "bullish" in analysis.bias.lower():
                analysis.trade_idea = "Buy"
            elif "bearish" in analysis.bias.lower():
                analysis.trade_idea = "Sell"
            else:
                analysis.trade_idea = "Wait"

        is_buy = "buy" in analysis.trade_idea.lower()
        is_sell = "sell" in analysis.trade_idea.lower()

        # Fill entry
        if analysis.entry == "N/A":
            if is_buy:
                analysis.entry = (
                    f"{latest_close - atr * 0.3:.2f}-{latest_close:.2f}"
                )
            elif is_sell:
                analysis.entry = (
                    f"{latest_close:.2f}-{latest_close + atr * 0.3:.2f}"
                )
            else:
                analysis.entry = f"Wait for clearer signal near {latest_close:.2f}"

        # Fill stop loss
        if analysis.stop_loss == "N/A":
            if is_buy:
                analysis.stop_loss = f"{indicators.support - atr * 0.5:.2f}"
            elif is_sell:
                analysis.stop_loss = f"{indicators.resistance + atr * 0.5:.2f}"
            else:
                analysis.stop_loss = f"{indicators.support:.2f}"

        # Fill TP1
        if analysis.take_profit_1 == "N/A":
            if is_buy:
                analysis.take_profit_1 = f"{latest_close + atr * 1.5:.2f}"
            elif is_sell:
                analysis.take_profit_1 = f"{latest_close - atr * 1.5:.2f}"
            else:
                analysis.take_profit_1 = f"{indicators.resistance:.2f}"

        # Fill TP2
        if analysis.take_profit_2 == "N/A":
            if is_buy:
                analysis.take_profit_2 = f"{latest_close + atr * 2.5:.2f}"
            elif is_sell:
                analysis.take_profit_2 = f"{latest_close - atr * 2.5:.2f}"
            else:
                analysis.take_profit_2 = f"{indicators.resistance_2:.2f}"

        # Fill risk note
        if analysis.risk_note == "N/A":
            analysis.risk_note = (
                f"{indicators.volatility_condition}. "
                f"ATR: {atr:.2f}. "
                f"RSI at {indicators.rsi:.1f} ({indicators.rsi_interpretation}). "
                f"Use proper position sizing."
            )

        # Fill outlook
        if analysis.short_term_outlook == "N/A":
            analysis.short_term_outlook = (
                f"EMA trend is {indicators.ema_trend}. "
                f"Price near {'resistance' if latest_close > indicators.pivot_point else 'support'} zone. "
                f"MACD histogram {indicators.macd_interpretation.lower()}."
            )

        return analysis

    def _generate_fallback_analysis(
        self,
        indicators: TechnicalIndicators,
        df: pd.DataFrame,
    ) -> AIAnalysis:
        logger.warning(
            "Using full indicator-based fallback (Gemini unavailable)"
        )
        analysis = AIAnalysis()
        analysis.raw_response = (
            "[Fallback: Generated from technical indicators]"
        )
        # Fill everything from indicators
        return self._fill_missing_fields(analysis, indicators, df)


gemini_analyzer = GeminiAnalyzer(GEMINI_API_KEY)


# =============================================================================
# MODULE 4: CHART GENERATOR
# =============================================================================
class ChartGenerator:

    @staticmethod
    def generate_chart(
        df: pd.DataFrame,
        indicators: TechnicalIndicators,
        timeframe: str,
    ) -> Optional[io.BytesIO]:
        if df is None or len(df) < 20:
            return None

        try:
            plt.style.use(CHART_STYLE)
            plot_df = df.tail(60).copy()

            fig, axes = plt.subplots(
                3,
                1,
                figsize=CHART_FIGSIZE,
                gridspec_kw={"height_ratios": [3, 1, 1]},
                sharex=True,
            )
            fig.suptitle(
                f"XAU/USD - {timeframe} Analysis",
                fontsize=16,
                fontweight="bold",
                color=COLOR_GOLD,
                y=0.98,
            )

            # =============================================================
            # Panel 1: Price Action + EMAs + Support/Resistance
            # =============================================================
            ax1 = axes[0]

            ax1.plot(
                plot_df["datetime"],
                plot_df["close"],
                color=COLOR_WHITE,
                linewidth=1.5,
                label="Close",
                zorder=5,
            )
            ax1.fill_between(
                plot_df["datetime"],
                plot_df["low"],
                plot_df["high"],
                alpha=0.1,
                color=COLOR_GOLD,
            )

            # Candlestick-style bars
            for idx_val, row in plot_df.iterrows():
                if row["close"] >= row["open"]:
                    bar_color = COLOR_GREEN
                else:
                    bar_color = COLOR_RED

                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [row["low"], row["high"]],
                    color=bar_color,
                    linewidth=0.8,
                    alpha=0.6,
                )
                body_low = min(row["open"], row["close"])
                body_high = max(row["open"], row["close"])
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [body_low, body_high],
                    color=bar_color,
                    linewidth=2.5,
                )

            # EMA lines
            if "ema_20" in plot_df.columns:
                ema20_label = f"EMA 20 ({indicators.ema_20:.2f})"
                ax1.plot(
                    plot_df["datetime"],
                    plot_df["ema_20"],
                    color=COLOR_BLUE,
                    linewidth=1.2,
                    linestyle="--",
                    label=ema20_label,
                    alpha=0.9,
                )
            if "ema_50" in plot_df.columns:
                ema50_label = f"EMA 50 ({indicators.ema_50:.2f})"
                ax1.plot(
                    plot_df["datetime"],
                    plot_df["ema_50"],
                    color=COLOR_ORANGE,
                    linewidth=1.2,
                    linestyle="--",
                    label=ema50_label,
                    alpha=0.9,
                )

            # Support & Resistance with zones
            support_label = f"S1 ({indicators.support:.2f})"
            ax1.axhline(
                y=indicators.support,
                color=COLOR_GREEN_BRIGHT,
                linestyle=":",
                linewidth=1.0,
                alpha=0.8,
                label=support_label,
            )

            resistance_label = f"R1 ({indicators.resistance:.2f})"
            ax1.axhline(
                y=indicators.resistance,
                color=COLOR_RED_BRIGHT,
                linestyle=":",
                linewidth=1.0,
                alpha=0.8,
                label=resistance_label,
            )

            # S2/R2 as lighter lines
            ax1.axhline(
                y=indicators.support_2,
                color=COLOR_GREEN_BRIGHT,
                linestyle=":",
                linewidth=0.6,
                alpha=0.4,
            )
            ax1.axhline(
                y=indicators.resistance_2,
                color=COLOR_RED_BRIGHT,
                linestyle=":",
                linewidth=0.6,
                alpha=0.4,
            )

            # Pivot line
            ax1.axhline(
                y=indicators.pivot_point,
                color=COLOR_GOLD,
                linestyle="-.",
                linewidth=0.7,
                alpha=0.5,
                label=f"Pivot ({indicators.pivot_point:.2f})",
            )

            ax1.set_ylabel("Price (USD)", fontsize=10, color=COLOR_WHITE)
            ax1.legend(loc="upper left", fontsize=7, framealpha=0.3)
            ax1.grid(True, alpha=0.15)

            # =============================================================
            # Panel 2: RSI
            # =============================================================
            ax2 = axes[1]

            if "rsi" in plot_df.columns:
                rsi_label = f"RSI ({indicators.rsi:.1f})"
                ax2.plot(
                    plot_df["datetime"],
                    plot_df["rsi"],
                    color=COLOR_PURPLE,
                    linewidth=1.5,
                    label=rsi_label,
                )
                ax2.fill_between(
                    plot_df["datetime"],
                    plot_df["rsi"],
                    50,
                    where=(plot_df["rsi"] >= 50),
                    alpha=0.2,
                    color=COLOR_GREEN,
                )
                ax2.fill_between(
                    plot_df["datetime"],
                    plot_df["rsi"],
                    50,
                    where=(plot_df["rsi"] < 50),
                    alpha=0.2,
                    color=COLOR_RED,
                )
                ax2.axhline(
                    y=70,
                    color=COLOR_RED_BRIGHT,
                    linestyle="--",
                    linewidth=0.8,
                    alpha=0.6,
                )
                ax2.axhline(
                    y=30,
                    color=COLOR_GREEN_BRIGHT,
                    linestyle="--",
                    linewidth=0.8,
                    alpha=0.6,
                )
                ax2.axhline(
                    y=50,
                    color=COLOR_GRAY,
                    linestyle="-",
                    linewidth=0.5,
                    alpha=0.4,
                )

            ax2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE)
            ax2.set_ylim(10, 90)
            ax2.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax2.grid(True, alpha=0.15)

            # =============================================================
            # Panel 3: MACD
            # =============================================================
            ax3 = axes[2]

            if "macd_line" in plot_df.columns:
                ax3.plot(
                    plot_df["datetime"],
                    plot_df["macd_line"],
                    color=COLOR_BLUE,
                    linewidth=1.2,
                    label="MACD",
                )
                ax3.plot(
                    plot_df["datetime"],
                    plot_df["macd_signal"],
                    color=COLOR_ORANGE,
                    linewidth=1.2,
                    label="Signal",
                )

                hist_colors = []
                for v in plot_df["macd_histogram"]:
                    if v >= 0:
                        hist_colors.append(COLOR_GREEN)
                    else:
                        hist_colors.append(COLOR_RED)

                ax3.bar(
                    plot_df["datetime"],
                    plot_df["macd_histogram"],
                    color=hist_colors,
                    alpha=0.5,
                    width=0.6,
                )
                ax3.axhline(
                    y=0,
                    color=COLOR_GRAY,
                    linestyle="-",
                    linewidth=0.5,
                    alpha=0.4,
                )

            ax3.set_ylabel("MACD", fontsize=10, color=COLOR_WHITE)
            ax3.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax3.grid(True, alpha=0.15)

            ax3.xaxis.set_major_formatter(
                mdates.DateFormatter("%m/%d %H:%M")
            )
            plt.xticks(rotation=45, fontsize=8)

            now_str = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            fig.text(
                0.99,
                0.01,
                f"Generated: {now_str}",
                ha="right",
                va="bottom",
                fontsize=7,
                color=COLOR_GRAY,
                alpha=0.6,
            )

            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(
                buf,
                format="png",
                dpi=CHART_DPI,
                bbox_inches="tight",
                facecolor=fig.get_facecolor(),
                edgecolor="none",
            )
            buf.seek(0)
            plt.close(fig)

            logger.info("Chart generated successfully")
            return buf

        except Exception as e:
            logger.error(f"Chart generation error: {e}")
            plt.close("all")
            return None


chart_gen = ChartGenerator()


# =============================================================================
# MODULE 5: TELEGRAM BOT HANDLERS
# =============================================================================

def get_session(user_id: int) -> UserSession:
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession()
    return user_sessions[user_id]


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not isinstance(text, str):
        text = str(text)
    special_chars = [
        "_", "*", "[", "]", "(", ")", "~", "`", ">",
        "#", "+", "-", "=", "|", "{", "}", ".", "!",
    ]
    for char in special_chars:
        text = text.replace(char, "\\" + char)
    return text


async def cmd_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    welcome = (
        "\U0001f947 *XAUUSD AI Analysis Bot*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\n"
        "Welcome\\! I provide real\\-time AI\\-powered "
        "technical analysis for *Gold \\(XAU/USD\\)*\\.\n"
        "\n"
        "\U0001f539 Real\\-time price data from Twelve Data\n"
        "\U0001f539 Technical indicators \\(RSI, EMA, MACD, ATR\\)\n"
        "\U0001f539 AI analysis powered by Google Gemini\n"
        "\U0001f539 Professional chart generation\n"
        "\n"
        "*Available Commands:*\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI technical breakdown\n"
        "/chart \\- Technical analysis chart\n"
        "/timeframe \\- Change timeframe "
        "\\(e\\.g\\. `/timeframe 1h`\\)\n"
        "/help \\- Show all commands\n"
        "\n"
        "Default timeframe: *15 Min*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "_Disclaimer: Not financial advice\\. Trade responsibly\\._"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"User {update.effective_user.id} started the bot")


async def cmd_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    help_text = (
        "\U0001f539 *Bot Commands*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\n"
        "/start \\- Welcome message\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI technical analysis\n"
        "/chart \\- Send technical chart\n"
        "/timeframe <tf> \\- Change timeframe\n"
        "\n"
        "*Timeframe Options:*\n"
        "  `5m`  \\- 5 Minutes\n"
        "  `15m` \\- 15 Minutes\n"
        "  `1h`  \\- 1 Hour\n"
        "  `4h`  \\- 4 Hours\n"
        "  `1d`  \\- Daily\n"
        "\n"
        "*Example:* `/timeframe 4h`\n"
        "\n"
        "/help \\- This message\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    )
    await update.message.reply_text(
        help_text, parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text(
        "Fetching latest XAU/USD price..."
    )

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        price_data = await loop.run_in_executor(
            None, td_client.fetch_current_price
        )

        if price_data is None:
            await update.message.reply_text(
                "Failed to fetch price data. Please try again later."
            )
            return

        price = price_data["price"]
        timestamp = price_data["timestamp"]

        msg = (
            "\U0001f947 *XAU/USD \\- Live Price*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            f"\U0001f4b0 *Price:* `${price:,.2f}`\n"
            f"\U0001f550 *Time:*  `{timestamp}`\n"
            "\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        )
        await update.message.reply_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(
            f"Price sent to user {update.effective_user.id}: "
            f"${price:.2f}"
        )

    except Exception as e:
        logger.error(f"Price command error: {e}")
        await update.message.reply_text(
            "An error occurred while fetching the price."
        )


async def cmd_analysis(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    session = get_session(update.effective_user.id)
    tf = session.timeframe

    loading_msg = await update.message.reply_text(
        f"Generating AI analysis for XAU/USD "
        f"({tf.display_name})...\n"
        f"This may take a few seconds."
    )

    try:
        # Step 1: Fetch market data
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            td_client.fetch_time_series,
            tf.value,
            DEFAULT_OUTPUTSIZE,
        )

        if df is None or len(df) < 50:
            await loading_msg.edit_text(
                "Failed to fetch sufficient market data. "
                "Please try again."
            )
            return

        # Step 2: Calculate indicators
        df, indicators = ta_engine.compute_indicators(df)
        latest = df.iloc[-1]

        # Step 3: AI analysis
        ai_result = await loop.run_in_executor(
            None,
            gemini_analyzer.generate_analysis,
            df,
            indicators,
            tf.display_name,
        )

        # Step 4: Format and send
        tf_escaped = _escape_md(tf.display_name)
        rsi_interp = _escape_md(indicators.rsi_interpretation)
        ema_trend = _escape_md(indicators.ema_trend)
        macd_interp = _escape_md(indicators.macd_interpretation)
        vol_cond = _escape_md(indicators.volatility_condition)
        ai_bias = _escape_md(ai_result.bias)
        ai_trade = _escape_md(ai_result.trade_idea)
        ai_entry = _escape_md(ai_result.entry)
        ai_sl = _escape_md(ai_result.stop_loss)
        ai_tp1 = _escape_md(ai_result.take_profit_1)
        ai_tp2 = _escape_md(ai_result.take_profit_2)
        ai_risk = _escape_md(ai_result.risk_note)
        ai_outlook = _escape_md(ai_result.short_term_outlook)
        now_str = _escape_md(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )

        msg = (
            f"\U0001f947 *XAU/USD Analysis \\({tf_escaped}\\)*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\n"
            "\U0001f4ca *PRICE ACTION*\n"
            f"Price: `${latest['close']:,.2f}`\n"
            f"Open: `${latest['open']:,.2f}`\n"
            f"High: `${latest['high']:,.2f}`\n"
            f"Low:  `${latest['low']:,.2f}`\n"
            "\n"
            "\U0001f4c8 *TECHNICAL INDICATORS*\n"
            f"RSI \\(14\\):  `{indicators.rsi}` \\- {rsi_interp}\n"
            f"EMA 20:    `{indicators.ema_20}`\n"
            f"EMA 50:    `{indicators.ema_50}`\n"
            f"EMA Trend: {ema_trend}\n"
            f"MACD:      {macd_interp}\n"
            f"ATR \\(14\\):  `{indicators.atr}`\n"
            f"Volatility: {vol_cond}\n"
            "\n"
            "\U0001f6e1 *KEY LEVELS*\n"
            f"Resistance R2: `${indicators.resistance_2:,.2f}`\n"
            f"Resistance R1: `${indicators.resistance:,.2f}`\n"
            f"Pivot:         `${indicators.pivot_point:,.2f}`\n"
            f"Support S1:    `${indicators.support:,.2f}`\n"
            f"Support S2:    `${indicators.support_2:,.2f}`\n"
            "\n"
            "\U0001f916 *AI ANALYSIS*\n"
            f"Bias:     {ai_bias}\n"
            f"Trade:    {ai_trade}\n"
            f"Entry:    `{ai_entry}`\n"
            f"SL:       `{ai_sl}`\n"
            f"TP1:      `{ai_tp1}`\n"
            f"TP2:      `{ai_tp2}`\n"
            "\n"
            f"\u26a0\ufe0f *Risk:* {ai_risk}\n"
            f"\U0001f52e *Outlook:* {ai_outlook}\n"
            "\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"_{now_str}_\n"
            "_Not financial advice\\. Trade at your own risk\\._"
        )
        await loading_msg.edit_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(
            f"Analysis delivered to user {update.effective_user.id}"
        )

    except Exception as e:
        logger.error(f"Analysis command error: {e}", exc_info=True)
        await loading_msg.edit_text(
            "An error occurred during analysis. Please try again."
        )


async def cmd_chart(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    session = get_session(update.effective_user.id)
    tf = session.timeframe

    loading_msg = await update.message.reply_text(
        f"Generating chart for XAU/USD ({tf.display_name})..."
    )

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            td_client.fetch_time_series,
            tf.value,
            DEFAULT_OUTPUTSIZE,
        )

        if df is None or len(df) < 20:
            await loading_msg.edit_text(
                "Insufficient data for chart generation."
            )
            return

        df, indicators = ta_engine.compute_indicators(df)

        chart_buf = await loop.run_in_executor(
            None,
            chart_gen.generate_chart,
            df,
            indicators,
            tf.display_name,
        )

        if chart_buf is None:
            await loading_msg.edit_text("Chart generation failed.")
            return

        now_str = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        caption = (
            f"XAU/USD - {tf.display_name} Chart\n"
            f"Price: ${df.iloc[-1]['close']:,.2f}\n"
            f"RSI: {indicators.rsi} | ATR: {indicators.atr}\n"
            f"S1: ${indicators.support:,.2f} | "
            f"R1: ${indicators.resistance:,.2f}\n"
            f"{now_str}"
        )

        await loading_msg.delete()
        await update.message.reply_photo(
            photo=chart_buf, caption=caption
        )
        logger.info(f"Chart sent to user {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Chart command error: {e}", exc_info=True)
        await loading_msg.edit_text(
            "An error occurred while generating the chart."
        )


async def cmd_timeframe(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    session = get_session(update.effective_user.id)

    if not context.args:
        current_tf = session.timeframe.display_name
        msg = (
            f"Current Timeframe: *{_escape_md(current_tf)}*\n"
            "\n"
            "*Usage:* `/timeframe <option>`\n"
            "\n"
            "*Options:*\n"
            "  `5m`  \\- 5 Minutes\n"
            "  `15m` \\- 15 Minutes\n"
            "  `1h`  \\- 1 Hour\n"
            "  `4h`  \\- 4 Hours\n"
            "  `1d`  \\- Daily\n"
            "\n"
            "*Example:* `/timeframe 4h`"
        )
        await update.message.reply_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    user_input = context.args[0]
    new_tf = Timeframe.from_user_input(user_input)

    if new_tf is None:
        escaped_input = _escape_md(user_input)
        await update.message.reply_text(
            f"Invalid timeframe: `{escaped_input}`\n\n"
            f"Valid options: `5m`, `15m`, `1h`, `4h`, `1d`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    session.timeframe = new_tf
    escaped_name = _escape_md(new_tf.display_name)
    await update.message.reply_text(
        f"Timeframe changed to *{escaped_name}*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    logger.info(
        f"User {update.effective_user.id} changed timeframe "
        f"to {new_tf.value}"
    )


# =============================================================================
# MODULE 6: ERROR HANDLER
# =============================================================================
async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.error(
        f"Unhandled exception: {context.error}",
        exc_info=context.error,
    )
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                "An unexpected error occurred. Please try again later."
            )
        except Exception:
            pass


# =============================================================================
# MODULE 7: MAIN ENTRY POINT
# =============================================================================
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("price", "Latest XAU/USD price"),
        BotCommand("analysis", "Full AI technical analysis"),
        BotCommand("chart", "Technical analysis chart"),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("help", "Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  XAUUSD AI ANALYSIS BOT v2.1 - Starting...")
    logger.info("  SDK: google-genai (new)")
    logger.info("=" * 60)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("timeframe", cmd_timeframe))
    app.add_error_handler(error_handler)

    logger.info("Bot polling for updates... Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
