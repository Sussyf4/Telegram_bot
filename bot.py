#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD AI ANALYSIS BOT v3.0                     ║
║                                                                    ║
║  Credit system · Role-based access · API key rotation              ║
║  Uses: google-genai SDK, Twelve Data, python-telegram-bot, asyncpg ║
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
import functools
from datetime import datetime, timezone, date
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

import asyncpg
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# TwelveData key pool — collect every non-empty key
_td_key_names = [
    "TWELVEDATA_API_KEY",
    "TWELVEDATA_API_KEY2",
    "TWELVEDATA_API_KEY3",
]
TWELVEDATA_API_KEYS: list[str] = [
    os.getenv(name)
    for name in _td_key_names
    if os.getenv(name)
]

_missing: list[str] = []
if not TELEGRAM_BOT_TOKEN:
    _missing.append("TELEGRAM_BOT_TOKEN")
if not TWELVEDATA_API_KEYS:
    _missing.append("TWELVEDATA_API_KEY (at least one)")
if not GEMINI_API_KEY:
    _missing.append("GEMINI_API_KEY")
if not DATABASE_URL:
    _missing.append("DATABASE_URL")
if _missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        f"Please set them in your .env file or Railway dashboard."
    )

# Owner constant
OWNER_USER_ID = 5482019561
OWNER_USERNAME = "EK_HENG"

# Role daily limits
ROLE_LIMITS: dict[str, Optional[int]] = {
    "owner": None,    # unlimited
    "free": 5,
    "premium": 50,
}

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.WARNING)

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

# Color palette
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
# MODULE 1: DATABASE MANAGER (asyncpg + PostgreSQL)
# =============================================================================
class DatabaseManager:
    """Manages the asyncpg connection pool and all user CRUD operations."""

    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        logger.info("Connecting to PostgreSQL...")
        self.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=15,
        )
        # Ensure schema exists (idempotent)
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    BIGINT PRIMARY KEY,
                    username   TEXT DEFAULT '',
                    role       TEXT NOT NULL DEFAULT 'free'
                                   CHECK (role IN ('owner','free','premium')),
                    daily_used INTEGER NOT NULL DEFAULT 0,
                    last_reset DATE NOT NULL DEFAULT CURRENT_DATE
                );
            """)
            # Guarantee owner row
            await conn.execute("""
                INSERT INTO users (user_id, username, role, daily_used, last_reset)
                VALUES ($1, $2, 'owner', 0, CURRENT_DATE)
                ON CONFLICT (user_id) DO UPDATE SET role = 'owner';
            """, OWNER_USER_ID, OWNER_USERNAME)
        logger.info("PostgreSQL connected and schema verified.")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed.")

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------
    async def ensure_user(self, user_id: int, username: str = "") -> asyncpg.Record:
        """Return the user row, creating it as 'free' if it doesn't exist."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1", user_id
            )
            if row is None:
                # Auto-register
                await conn.execute("""
                    INSERT INTO users (user_id, username, role, daily_used, last_reset)
                    VALUES ($1, $2, 'free', 0, CURRENT_DATE)
                    ON CONFLICT (user_id) DO NOTHING;
                """, user_id, username or "")
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id = $1", user_id
                )
                logger.info(
                    f"New user registered: {user_id} ({username}) as free"
                )
            return row

    async def _reset_if_new_day(
        self, conn: asyncpg.Connection, user_id: int
    ) -> None:
        """Reset daily_used to 0 if the stored last_reset is before today (UTC)."""
        today = date.today()
        await conn.execute("""
            UPDATE users
               SET daily_used = 0,
                   last_reset = $2
             WHERE user_id = $1
               AND last_reset < $2;
        """, user_id, today)

    async def check_and_consume_credit(
        self, user_id: int, username: str = ""
    ) -> tuple[bool, str, int, Optional[int]]:
        """
        Returns (allowed, role, used_after, limit_or_none).
        If allowed is True the counter has already been incremented.
        """
        async with self.pool.acquire() as conn:
            # Ensure user exists
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1", user_id
            )
            if row is None:
                await conn.execute("""
                    INSERT INTO users (user_id, username, role, daily_used, last_reset)
                    VALUES ($1, $2, 'free', 0, CURRENT_DATE)
                    ON CONFLICT (user_id) DO NOTHING;
                """, user_id, username or "")
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id = $1", user_id
                )

            # Reset if new day
            await self._reset_if_new_day(conn, user_id)

            # Re-fetch after possible reset
            row = await conn.fetchrow(
                "SELECT role, daily_used FROM users WHERE user_id = $1",
                user_id,
            )
            role = row["role"]
            daily_used = row["daily_used"]
            limit = ROLE_LIMITS.get(role)

            # Owner → unlimited
            if limit is None:
                await conn.execute(
                    "UPDATE users SET daily_used = daily_used + 1 WHERE user_id = $1",
                    user_id,
                )
                return True, role, daily_used + 1, None

            # Check limit
            if daily_used >= limit:
                logger.info(
                    f"User {user_id} ({role}) hit daily limit "
                    f"({daily_used}/{limit})"
                )
                return False, role, daily_used, limit

            # Consume
            await conn.execute(
                "UPDATE users SET daily_used = daily_used + 1 WHERE user_id = $1",
                user_id,
            )
            return True, role, daily_used + 1, limit

    async def get_user_info(
        self, user_id: int, username: str = ""
    ) -> asyncpg.Record:
        """Return full user row with day-reset applied."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1", user_id
            )
            if row is None:
                await conn.execute("""
                    INSERT INTO users (user_id, username, role, daily_used, last_reset)
                    VALUES ($1, $2, 'free', 0, CURRENT_DATE)
                    ON CONFLICT (user_id) DO NOTHING;
                """, user_id, username or "")
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE user_id = $1", user_id
                )
            await self._reset_if_new_day(conn, user_id)
            return await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1", user_id
            )

    async def set_role(self, user_id: int, role: str) -> bool:
        """Set a user's role. Returns True if a row was updated."""
        async with self.pool.acquire() as conn:
            # Ensure target exists
            await conn.execute("""
                INSERT INTO users (user_id, username, role, daily_used, last_reset)
                VALUES ($1, '', $2, 0, CURRENT_DATE)
                ON CONFLICT (user_id) DO UPDATE SET role = $2;
            """, user_id, role)
            return True


db = DatabaseManager()


# =============================================================================
# MODULE 2: TWELVE DATA CLIENT WITH KEY ROTATION
# =============================================================================
class TwelveDataClient:
    """HTTP client for Twelve Data with automatic API key rotation."""

    # HTTP codes / JSON messages that signal quota exhaustion
    _QUOTA_CODES = {429}
    _QUOTA_MESSAGES = {
        "You have run out of API credits",
        "Too many requests",
        "api credits",
    }

    def __init__(self, api_keys: list[str]) -> None:
        if not api_keys:
            raise ValueError("At least one TwelveData API key is required")
        self.api_keys = list(api_keys)
        self._current_index = 0
        self._lock = asyncio.Lock()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "XAUUSD-AI-Bot/3.0"})
        logger.info(
            f"TwelveData client initialised with {len(self.api_keys)} key(s). "
            f"Active key index: 0"
        )

    @property
    def active_key(self) -> str:
        return self.api_keys[self._current_index]

    def _rotate_key(self) -> Optional[str]:
        """Move to the next key. Returns the new key, or None if exhausted."""
        next_index = self._current_index + 1
        if next_index >= len(self.api_keys):
            return None
        self._current_index = next_index
        logger.warning(
            f"Rotated to TwelveData key index {self._current_index} "
            f"(of {len(self.api_keys)})"
        )
        return self.api_keys[self._current_index]

    def _reset_rotation(self) -> None:
        """Reset back to first key (called at start of a new request cycle)."""
        self._current_index = 0

    def _is_quota_error(self, response: requests.Response) -> bool:
        if response.status_code in self._QUOTA_CODES:
            return True
        try:
            body = response.json()
            msg = str(body.get("message", "")).lower()
            code = body.get("code", 0)
            if code == 429:
                return True
            for phrase in self._QUOTA_MESSAGES:
                if phrase.lower() in msg:
                    return True
        except (ValueError, AttributeError):
            pass
        return False

    # ------------------------------------------------------------------
    # Public fetch methods
    # ------------------------------------------------------------------
    def fetch_time_series(
        self,
        interval: str,
        outputsize: int = DEFAULT_OUTPUTSIZE,
    ) -> Optional[pd.DataFrame]:
        self._reset_rotation()

        while True:
            key = self.active_key
            url = f"{TWELVEDATA_BASE_URL}/time_series"
            params = {
                "symbol": SYMBOL,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": key,
                "format": "JSON",
                "dp": 2,
            }
            try:
                key_label = f"key[{self._current_index}]"
                logger.info(
                    f"Fetching {SYMBOL} | interval={interval} | "
                    f"size={outputsize} | {key_label}"
                )
                response = self.session.get(url, params=params, timeout=15)

                # Check for quota error before anything else
                if self._is_quota_error(response):
                    logger.warning(
                        f"Quota exhausted on {key_label}. Rotating..."
                    )
                    next_key = self._rotate_key()
                    if next_key is None:
                        logger.error("All TwelveData API keys exhausted.")
                        return None
                    continue

                response.raise_for_status()
                data = response.json()

                if "code" in data and data["code"] != 200:
                    logger.error(
                        f"TwelveData API error: {data.get('message', 'Unknown')}"
                    )
                    return None
                if "values" not in data or not data["values"]:
                    logger.error("TwelveData returned empty values")
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
                logger.error(f"TwelveData request timed out on key[{self._current_index}]")
                next_key = self._rotate_key()
                if next_key is None:
                    return None
            except requests.exceptions.ConnectionError:
                logger.error("Failed to connect to TwelveData")
                return None
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error from TwelveData: {e}")
                return None
            except (ValueError, KeyError) as e:
                logger.error(f"Error parsing TwelveData response: {e}")
                return None

    def fetch_current_price(self) -> Optional[dict]:
        self._reset_rotation()

        while True:
            key = self.active_key
            url = f"{TWELVEDATA_BASE_URL}/price"
            params = {
                "symbol": SYMBOL,
                "apikey": key,
                "dp": 2,
            }
            try:
                response = self.session.get(url, params=params, timeout=10)

                if self._is_quota_error(response):
                    logger.warning(
                        f"Quota exhausted on key[{self._current_index}] "
                        f"(price). Rotating..."
                    )
                    next_key = self._rotate_key()
                    if next_key is None:
                        logger.error("All TwelveData API keys exhausted.")
                        return None
                    continue

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
            except requests.exceptions.Timeout:
                logger.error(
                    f"Price request timed out on key[{self._current_index}]"
                )
                next_key = self._rotate_key()
                if next_key is None:
                    return None
            except Exception as e:
                logger.error(f"Error fetching price: {e}")
                return None


td_client = TwelveDataClient(TWELVEDATA_API_KEYS)


# =============================================================================
# MODULE 3: RATE LIMITER (per-client throttle for Twelve Data)
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
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())
            return True


twelvedata_limiter = RateLimiter(max_calls=7, period_seconds=60.0)
user_sessions: dict[int, UserSession] = {}


# =============================================================================
# MODULE 4: TECHNICAL ANALYSIS ENGINE
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

        # Support & Resistance
        support, resistance = (
            TechnicalAnalysisEngine._detect_support_resistance(df)
        )

        latest = df.iloc[-1]

        indicators.rsi = (
            round(latest["rsi"], 2) if pd.notna(latest["rsi"]) else 0.0
        )
        indicators.ema_20 = (
            round(latest["ema_20"], 2) if pd.notna(latest["ema_20"]) else 0.0
        )
        indicators.ema_50 = (
            round(latest["ema_50"], 2) if pd.notna(latest["ema_50"]) else 0.0
        )
        indicators.macd_line = (
            round(latest["macd_line"], 4) if pd.notna(latest["macd_line"]) else 0.0
        )
        indicators.macd_signal = (
            round(latest["macd_signal"], 4) if pd.notna(latest["macd_signal"]) else 0.0
        )
        indicators.macd_histogram = (
            round(latest["macd_histogram"], 4)
            if pd.notna(latest["macd_histogram"]) else 0.0
        )
        indicators.atr = (
            round(latest["atr"], 2) if pd.notna(latest["atr"]) else 0.0
        )
        indicators.support = round(support, 2)
        indicators.resistance = round(resistance, 2)

        # RSI Interpretation
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

        # EMA Trend
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

        # MACD
        if indicators.macd_histogram > 0:
            indicators.macd_interpretation = "Positive"
        elif indicators.macd_histogram < 0:
            indicators.macd_interpretation = "Negative"
        else:
            indicators.macd_interpretation = "Neutral"

        # Volatility
        atr_pct = (
            (indicators.atr / latest["close"]) * 100
            if latest["close"] > 0 else 0
        )
        if atr_pct > 1.0:
            indicators.volatility_condition = "High Volatility"
        elif atr_pct > 0.5:
            indicators.volatility_condition = "Moderate Volatility"
        else:
            indicators.volatility_condition = "Low Volatility"

        # Overall Trend
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
    def _detect_support_resistance(
        df: pd.DataFrame, window: int = 10
    ) -> tuple[float, float]:
        if len(df) < window * 2:
            return df["low"].min(), df["high"].max()

        recent = df.tail(60).copy()
        swing_lows: list[float] = []
        swing_highs: list[float] = []

        for i in range(window, len(recent) - window):
            segment = recent.iloc[i - window: i + window + 1]
            if recent.iloc[i]["low"] == segment["low"].min():
                swing_lows.append(recent.iloc[i]["low"])
            if recent.iloc[i]["high"] == segment["high"].max():
                swing_highs.append(recent.iloc[i]["high"])

        support = max(swing_lows[-3:]) if swing_lows else recent["low"].min()
        resistance = (
            min(swing_highs[-3:]) if swing_highs else recent["high"].max()
        )

        if support >= resistance:
            support = recent["low"].tail(20).min()
            resistance = recent["high"].tail(20).max()

        return support, resistance


ta_engine = TechnicalAnalysisEngine()


# =============================================================================
# MODULE 5: GEMINI AI ANALYSIS
# =============================================================================
class GeminiAnalyzer:

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model_name = GEMINI_MODEL
        self._max_retries = 3
        self._retry_delay = 2.0
        logger.info(
            f"Gemini AI initialised | model: {self.model_name}"
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
                    logger.warning(f"Attempt {attempt}: Empty/short response")
                    last_error = "Empty response from AI"
                    if attempt < self._max_retries:
                        time.sleep(self._retry_delay * attempt)
                    continue

                analysis.raw_response = raw_text
                logger.info(f"Gemini response received ({len(raw_text)} chars)")

                analysis = self._parse_response(raw_text, analysis)

                if analysis.bias not in ("N/A", "Error", ""):
                    logger.info(f"AI analysis parsed: bias={analysis.bias}")
                    return analysis

                logger.warning(
                    f"Attempt {attempt}: Parsing incomplete, "
                    f"trying fallback regex..."
                )
                analysis = self._fallback_parse(raw_text, analysis)
                if analysis.bias not in ("N/A", "Error", ""):
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
            f"All {self._max_retries} attempts failed. Last error: {last_error}"
        )
        analysis = self._generate_fallback_analysis(indicators, df)
        return analysis

    # -- prompt builder (unchanged logic) ----------------------------------
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
            if prev["close"] > 0 else 0
        )
        last_5_closes = df["close"].tail(5).tolist()
        last_5_str = ", ".join([f"{c:.2f}" for c in last_5_closes])

        session_high = df["high"].tail(20).max()
        session_low = df["low"].tail(20).min()

        prompt = (
            "You are a senior XAUUSD (Gold) technical analyst. "
            "Analyze this data and respond in the EXACT format below.\n"
            "\n"
            f"MARKET DATA - XAU/USD ({timeframe})\n"
            "\n"
            "LATEST CANDLE:\n"
            f"Open: {latest['open']:.2f}\n"
            f"High: {latest['high']:.2f}\n"
            f"Low: {latest['low']:.2f}\n"
            f"Close: {latest['close']:.2f}\n"
            f"Change: {price_change:+.2f} ({price_change_pct:+.3f}%)\n"
            "\n"
            f"LAST 5 CLOSES: {last_5_str}\n"
            "\n"
            "SESSION RANGE:\n"
            f"High: {session_high:.2f}\n"
            f"Low: {session_low:.2f}\n"
            "\n"
            "TECHNICAL INDICATORS:\n"
            f"RSI(14): {ind.rsi:.2f} ({ind.rsi_interpretation})\n"
            f"EMA20: {ind.ema_20:.2f}\n"
            f"EMA50: {ind.ema_50:.2f}\n"
            f"EMA Trend: {ind.ema_trend}\n"
            f"MACD Line: {ind.macd_line:.4f}\n"
            f"MACD Signal: {ind.macd_signal:.4f}\n"
            f"MACD Histogram: {ind.macd_histogram:.4f} "
            f"({ind.macd_interpretation})\n"
            f"ATR(14): {ind.atr:.2f} ({ind.volatility_condition})\n"
            f"Support: {ind.support:.2f}\n"
            f"Resistance: {ind.resistance:.2f}\n"
            f"Overall Trend: {ind.trend_direction}\n"
            "\n"
            "RESPOND IN EXACTLY THIS FORMAT "
            "(each field on its own line):\n"
            "\n"
            "BIAS: Bullish\n"
            "TRADE: Buy\n"
            "ENTRY: 2350.00-2352.00\n"
            "STOP_LOSS: 2340.00\n"
            "TP1: 2360.00\n"
            "TP2: 2370.00\n"
            "RISK: One sentence risk assessment.\n"
            "OUTLOOK: One to two sentence outlook.\n"
            "\n"
            "RULES:\n"
            "- BIAS must be: Bullish, Bearish, or Neutral\n"
            "- TRADE must be: Buy, Sell, or Wait\n"
            "- Use specific prices with 2 decimal places\n"
            "- Stop loss should account for ATR volatility\n"
            "- TP1 conservative, TP2 aggressive\n"
            "- If unclear, recommend Wait\n"
            "- NO markdown, NO asterisks, NO bullet points\n"
            "- NO text before BIAS or after OUTLOOK\n"
            "- Each field MUST start at beginning of a new line"
        )
        return prompt

    def _parse_response(self, text: str, analysis: AIAnalysis) -> AIAnalysis:
        if not text:
            return analysis

        text = text.replace("**", "").replace("*", "").replace("```", "")
        lines = text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line or ":" not in line:
                continue

            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            key = parts[0].strip().upper()
            value = parts[1].strip()

            if not value:
                continue

            if key in ("BIAS", "MARKET BIAS"):
                analysis.bias = value
            elif key in ("TRADE", "TRADE IDEA", "ACTION", "SIGNAL"):
                analysis.trade_idea = value
            elif key in ("ENTRY", "ENTRY ZONE", "ENTRY PRICE"):
                analysis.entry = value
            elif key in ("STOP_LOSS", "STOP LOSS", "SL", "STOPLOSS"):
                analysis.stop_loss = value
            elif key in ("TP1", "TAKE PROFIT 1", "TARGET 1"):
                analysis.take_profit_1 = value
            elif key in ("TP2", "TAKE PROFIT 2", "TARGET 2"):
                analysis.take_profit_2 = value
            elif key in ("RISK", "RISK NOTE", "RISK ASSESSMENT"):
                analysis.risk_note = value
            elif key in ("OUTLOOK", "SHORT TERM OUTLOOK", "SHORT-TERM OUTLOOK"):
                analysis.short_term_outlook = value

        return analysis

    def _fallback_parse(self, text: str, analysis: AIAnalysis) -> AIAnalysis:
        if not text:
            return analysis

        text_clean = text.replace("**", "").replace("*", "").replace("`", "")

        patterns = {
            "bias": r"(?:BIAS|MARKET\s*BIAS)\s*[:=]\s*(.+?)(?:\n|$)",
            "trade_idea": (
                r"(?:TRADE|TRADE\s*IDEA|ACTION|SIGNAL)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "entry": (
                r"(?:ENTRY|ENTRY\s*(?:ZONE|PRICE)?)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "stop_loss": r"(?:STOP[\s_]*LOSS|SL)\s*[:=]\s*(.+?)(?:\n|$)",
            "take_profit_1": (
                r"(?:TP1|TAKE[\s_]*PROFIT[\s_]*1|TARGET[\s_]*1)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "take_profit_2": (
                r"(?:TP2|TAKE[\s_]*PROFIT[\s_]*2|TARGET[\s_]*2)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "risk_note": (
                r"(?:RISK|RISK[\s_]*(?:NOTE|ASSESSMENT)?)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "short_term_outlook": (
                r"(?:OUTLOOK|SHORT[\s\-_]*TERM[\s_]*OUTLOOK)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
        }

        for field_name, pattern in patterns.items():
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value and value != "N/A":
                    setattr(analysis, field_name, value)

        logger.info(
            f"Fallback parse: bias={analysis.bias}, trade={analysis.trade_idea}"
        )
        return analysis

    def _generate_fallback_analysis(
        self,
        indicators: TechnicalIndicators,
        df: pd.DataFrame,
    ) -> AIAnalysis:
        logger.warning("Using indicator-based fallback (Gemini unavailable)")
        analysis = AIAnalysis()
        latest_close = df.iloc[-1]["close"]
        atr = indicators.atr

        bullish_count = sum([
            indicators.rsi > 50,
            indicators.ema_20 > indicators.ema_50,
            indicators.macd_histogram > 0,
        ])

        if bullish_count >= 2:
            analysis.bias = "Bullish (Indicator-Based)"
            analysis.trade_idea = "Buy"
            entry_low = latest_close - atr * 0.3
            analysis.entry = f"{entry_low:.2f}-{latest_close:.2f}"
            analysis.stop_loss = f"{indicators.support - atr * 0.5:.2f}"
            analysis.take_profit_1 = f"{latest_close + atr * 1.5:.2f}"
            analysis.take_profit_2 = f"{latest_close + atr * 2.5:.2f}"
        elif bullish_count == 0:
            analysis.bias = "Bearish (Indicator-Based)"
            analysis.trade_idea = "Sell"
            entry_high = latest_close + atr * 0.3
            analysis.entry = f"{latest_close:.2f}-{entry_high:.2f}"
            analysis.stop_loss = f"{indicators.resistance + atr * 0.5:.2f}"
            analysis.take_profit_1 = f"{latest_close - atr * 1.5:.2f}"
            analysis.take_profit_2 = f"{latest_close - atr * 2.5:.2f}"
        else:
            analysis.bias = "Neutral (Indicator-Based)"
            analysis.trade_idea = "Wait"
            analysis.entry = "Wait for clearer signal"
            analysis.stop_loss = f"{indicators.support:.2f}"
            analysis.take_profit_1 = f"{indicators.resistance:.2f}"
            analysis.take_profit_2 = f"{indicators.resistance + atr:.2f}"

        analysis.risk_note = (
            f"ATR-based volatility: {indicators.volatility_condition}. "
            f"AI service unavailable - using indicator fallback."
        )
        analysis.short_term_outlook = (
            f"RSI at {indicators.rsi:.1f} ({indicators.rsi_interpretation}). "
            f"EMA trend: {indicators.ema_trend}. "
            f"Support at {indicators.support:.2f}, "
            f"resistance at {indicators.resistance:.2f}."
        )
        analysis.raw_response = "[Fallback: Generated from technical indicators]"
        return analysis


gemini_analyzer = GeminiAnalyzer(GEMINI_API_KEY)


# =============================================================================
# MODULE 6: CHART GENERATOR
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
                3, 1,
                figsize=CHART_FIGSIZE,
                gridspec_kw={"height_ratios": [3, 1, 1]},
                sharex=True,
            )
            fig.suptitle(
                f"XAU/USD - {timeframe} Analysis",
                fontsize=16, fontweight="bold",
                color=COLOR_GOLD, y=0.98,
            )

            # --- Panel 1: Price + EMAs + S/R ---
            ax1 = axes[0]
            ax1.plot(
                plot_df["datetime"], plot_df["close"],
                color=COLOR_WHITE, linewidth=1.5, label="Close", zorder=5,
            )
            ax1.fill_between(
                plot_df["datetime"], plot_df["low"], plot_df["high"],
                alpha=0.1, color=COLOR_GOLD,
            )

            for _, row in plot_df.iterrows():
                bar_color = COLOR_GREEN if row["close"] >= row["open"] else COLOR_RED
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [row["low"], row["high"]],
                    color=bar_color, linewidth=0.8, alpha=0.6,
                )
                body_low = min(row["open"], row["close"])
                body_high = max(row["open"], row["close"])
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [body_low, body_high],
                    color=bar_color, linewidth=2.5,
                )

            if "ema_20" in plot_df.columns:
                ax1.plot(
                    plot_df["datetime"], plot_df["ema_20"],
                    color=COLOR_BLUE, linewidth=1.2, linestyle="--",
                    label=f"EMA 20 ({indicators.ema_20:.2f})", alpha=0.9,
                )
            if "ema_50" in plot_df.columns:
                ax1.plot(
                    plot_df["datetime"], plot_df["ema_50"],
                    color=COLOR_ORANGE, linewidth=1.2, linestyle="--",
                    label=f"EMA 50 ({indicators.ema_50:.2f})", alpha=0.9,
                )

            ax1.axhline(
                y=indicators.support, color=COLOR_GREEN_BRIGHT,
                linestyle=":", linewidth=1.0, alpha=0.8,
                label=f"Support ({indicators.support:.2f})",
            )
            ax1.axhline(
                y=indicators.resistance, color=COLOR_RED_BRIGHT,
                linestyle=":", linewidth=1.0, alpha=0.8,
                label=f"Resistance ({indicators.resistance:.2f})",
            )
            ax1.set_ylabel("Price (USD)", fontsize=10, color=COLOR_WHITE)
            ax1.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax1.grid(True, alpha=0.15)

            # --- Panel 2: RSI ---
            ax2 = axes[1]
            if "rsi" in plot_df.columns:
                ax2.plot(
                    plot_df["datetime"], plot_df["rsi"],
                    color=COLOR_PURPLE, linewidth=1.5,
                    label=f"RSI ({indicators.rsi:.1f})",
                )
                ax2.fill_between(
                    plot_df["datetime"], plot_df["rsi"], 50,
                    where=(plot_df["rsi"] >= 50), alpha=0.2, color=COLOR_GREEN,
                )
                ax2.fill_between(
                    plot_df["datetime"], plot_df["rsi"], 50,
                    where=(plot_df["rsi"] < 50), alpha=0.2, color=COLOR_RED,
                )
                ax2.axhline(y=70, color=COLOR_RED_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=30, color=COLOR_GREEN_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=50, color=COLOR_GRAY, linestyle="-", linewidth=0.5, alpha=0.4)
            ax2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE)
            ax2.set_ylim(10, 90)
            ax2.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax2.grid(True, alpha=0.15)

            # --- Panel 3: MACD ---
            ax3 = axes[2]
            if "macd_line" in plot_df.columns:
                ax3.plot(
                    plot_df["datetime"], plot_df["macd_line"],
                    color=COLOR_BLUE, linewidth=1.2, label="MACD",
                )
                ax3.plot(
                    plot_df["datetime"], plot_df["macd_signal"],
                    color=COLOR_ORANGE, linewidth=1.2, label="Signal",
                )
                hist_colors = [
                    COLOR_GREEN if v >= 0 else COLOR_RED
                    for v in plot_df["macd_histogram"]
                ]
                ax3.bar(
                    plot_df["datetime"], plot_df["macd_histogram"],
                    color=hist_colors, alpha=0.5, width=0.6,
                )
                ax3.axhline(y=0, color=COLOR_GRAY, linestyle="-", linewidth=0.5, alpha=0.4)
            ax3.set_ylabel("MACD", fontsize=10, color=COLOR_WHITE)
            ax3.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax3.grid(True, alpha=0.15)

            ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            plt.xticks(rotation=45, fontsize=8)

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            fig.text(
                0.99, 0.01, f"Generated: {now_str}",
                ha="right", va="bottom", fontsize=7,
                color=COLOR_GRAY, alpha=0.6,
            )

            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(
                buf, format="png", dpi=CHART_DPI,
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
# MODULE 7: CREDIT-CHECK MIDDLEWARE (decorator)
# =============================================================================
def check_credit(func: Callable) -> Callable:
    """
    Decorator that wraps any command handler.
    Before the handler runs it:
      1. Ensures the user exists in the DB (auto-registers as 'free').
      2. Resets daily_used if a new UTC day has started.
      3. Validates remaining credits for the user's role.
      4. Increments the counter if allowed.
      5. Blocks with a friendly message if the limit is reached.
    """

    @functools.wraps(func)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        user = update.effective_user
        if user is None:
            return

        user_id = user.id
        username = user.username or user.first_name or ""

        allowed, role, used, limit = await db.check_and_consume_credit(
            user_id, username
        )

        if not allowed:
            # Build a nice "limit reached" message
            remaining = 0
            limit_str = str(limit) if limit is not None else "∞"
            if role == "free":
                upgrade_hint = (
                    "\n\n💎 *Upgrade to Premium* for 50 signals per day\\!\n"
                    "Contact the bot owner to upgrade\\."
                )
            else:
                upgrade_hint = ""

            msg = (
                "⛔ *Daily Limit Reached*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "\n"
                f"Role: `{_escape_md(role)}`\n"
                f"Used today: `{used}/{limit_str}`\n"
                f"Remaining: `0`\n"
                "\n"
                "Your daily credits reset at *00:00 UTC*\\.\n"
                f"{upgrade_hint}"
            )
            await update.message.reply_text(
                msg, parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(
                f"Blocked user {user_id} ({role}): "
                f"{used}/{limit_str} credits used"
            )
            return  # Do NOT run the handler

        # Allowed — log and proceed
        limit_str = str(limit) if limit is not None else "∞"
        logger.info(
            f"Credit consumed: user={user_id} role={role} "
            f"used={used}/{limit_str}"
        )
        return await func(update, context, *args, **kwargs)

    return wrapper


# =============================================================================
# MODULE 8: TELEGRAM BOT HANDLERS
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


def _owner_only(func: Callable) -> Callable:
    """Decorator restricting a command to the owner only."""

    @functools.wraps(func)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if update.effective_user.id != OWNER_USER_ID:
            await update.message.reply_text(
                "⛔ This command is restricted to the bot owner."
            )
            logger.warning(
                f"Unauthorised admin attempt by user "
                f"{update.effective_user.id}"
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


# --------------- /start ---------------
async def cmd_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    # Ensure user in DB
    await db.ensure_user(user.id, user.username or user.first_name or "")

    welcome = (
        "🥇 *XAUUSD AI Analysis Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Welcome\\! I provide real\\-time AI\\-powered "
        "technical analysis for *Gold \\(XAU/USD\\)*\\.\n"
        "\n"
        "🔹 Real\\-time price data from Twelve Data\n"
        "🔹 Technical indicators \\(RSI, EMA, MACD, ATR\\)\n"
        "🔹 AI analysis powered by Google Gemini\n"
        "🔹 Professional chart generation\n"
        "🔹 Daily credit system with role\\-based access\n"
        "\n"
        "*Available Commands:*\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI technical breakdown\n"
        "/chart \\- Technical analysis chart\n"
        "/timeframe \\- Change timeframe "
        "\\(e\\.g\\. `/timeframe 1h`\\)\n"
        "/credits \\- Check remaining daily credits\n"
        "/role \\- Show your current role\n"
        "/help \\- Show all commands\n"
        "\n"
        "Default timeframe: *15 Min*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_Disclaimer: Not financial advice\\. Trade responsibly\\._"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"User {user.id} started the bot")


# --------------- /help ---------------
async def cmd_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    help_text = (
        "🔹 *Bot Commands*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "/start \\- Welcome message\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI technical analysis\n"
        "/chart \\- Send technical chart\n"
        "/timeframe <tf> \\- Change timeframe\n"
        "/credits \\- Remaining daily credits\n"
        "/role \\- Your current role\n"
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
        "*Admin Commands \\(Owner only\\):*\n"
        "/addprem <user\\_id> \\- Promote to Premium\n"
        "/addpremium <user\\_id> \\- Promote to Premium\n"
        "/delprem <user\\_id> \\- Demote to Free\n"
        "/removepremium <user\\_id> \\- Demote to Free\n"
        "\n"
        "/help \\- This message\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(
        help_text, parse_mode=ParseMode.MARKDOWN_V2
    )


# --------------- /credits ---------------
async def cmd_credits(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    row = await db.get_user_info(user.id, user.username or "")
    role = row["role"]
    daily_used = row["daily_used"]
    limit = ROLE_LIMITS.get(role)

    if limit is None:
        remaining_str = "∞"
        limit_str = "∞"
    else:
        remaining = max(0, limit - daily_used)
        remaining_str = str(remaining)
        limit_str = str(limit)

    role_emoji = {"owner": "👑", "premium": "💎", "free": "🆓"}.get(role, "❓")

    msg = (
        "📊 *Your Daily Credits*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        f"{role_emoji} Role: `{_escape_md(role)}`\n"
        f"📈 Used today: `{daily_used}`\n"
        f"📉 Remaining: `{_escape_md(remaining_str)}`\n"
        f"🔄 Daily limit: `{_escape_md(limit_str)}`\n"
        "\n"
        "Credits reset at *00:00 UTC* daily\\.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


# --------------- /role ---------------
async def cmd_role(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    row = await db.get_user_info(user.id, user.username or "")
    role = row["role"]
    limit = ROLE_LIMITS.get(role)

    role_emoji = {"owner": "👑", "premium": "💎", "free": "🆓"}.get(role, "❓")
    limit_str = str(limit) if limit is not None else "Unlimited"

    msg = (
        f"{role_emoji} *Your Role: {_escape_md(role.capitalize())}*\n"
        f"Daily limit: `{_escape_md(limit_str)}`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


# --------------- /price ---------------
@check_credit
async def cmd_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text("Fetching latest XAU/USD price...")

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        price_data = await loop.run_in_executor(
            None, td_client.fetch_current_price
        )

        if price_data is None:
            await update.message.reply_text(
                "⚠️ All data providers are currently busy. "
                "Please try again later."
            )
            return

        price = price_data["price"]
        timestamp = price_data["timestamp"]

        msg = (
            "🥇 *XAU/USD \\- Live Price*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            f"💰 *Price:* `${price:,.2f}`\n"
            f"🕐 *Time:*  `{timestamp}`\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(
            f"Price sent to user {update.effective_user.id}: ${price:.2f}"
        )

    except Exception as e:
        logger.error(f"Price command error: {e}")
        await update.message.reply_text(
            "An error occurred while fetching the price."
        )


# --------------- /analysis ---------------
@check_credit
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
                "⚠️ All data providers are currently busy or returned "
                "insufficient data. Please try again later."
            )
            return

        df, indicators = ta_engine.compute_indicators(df)
        latest = df.iloc[-1]

        ai_result = await loop.run_in_executor(
            None,
            gemini_analyzer.generate_analysis,
            df,
            indicators,
            tf.display_name,
        )

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
            f"🥇 *XAU/USD Analysis \\({tf_escaped}\\)*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            "📊 *PRICE ACTION*\n"
            f"Price: `${latest['close']:,.2f}`\n"
            f"Open: `${latest['open']:,.2f}`\n"
            f"High: `${latest['high']:,.2f}`\n"
            f"Low:  `${latest['low']:,.2f}`\n"
            "\n"
            "📈 *TECHNICAL INDICATORS*\n"
            f"RSI \\(14\\):  `{indicators.rsi}` \\- {rsi_interp}\n"
            f"EMA 20:    `{indicators.ema_20}`\n"
            f"EMA 50:    `{indicators.ema_50}`\n"
            f"EMA Trend: {ema_trend}\n"
            f"MACD:      {macd_interp}\n"
            f"ATR \\(14\\):  `{indicators.atr}`\n"
            f"Volatility: {vol_cond}\n"
            "\n"
            "🛡 *KEY LEVELS*\n"
            f"Support:    `${indicators.support:,.2f}`\n"
            f"Resistance: `${indicators.resistance:,.2f}`\n"
            "\n"
            "🤖 *AI ANALYSIS*\n"
            f"Bias:     {ai_bias}\n"
            f"Trade:    {ai_trade}\n"
            f"Entry:    `{ai_entry}`\n"
            f"SL:       `{ai_sl}`\n"
            f"TP1:      `{ai_tp1}`\n"
            f"TP2:      `{ai_tp2}`\n"
            "\n"
            f"⚠️ *Risk:* {ai_risk}\n"
            f"🔮 *Outlook:* {ai_outlook}\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_{now_str}_\n"
            "_Not financial advice\\. Trade at your own risk\\._"
        )
        await loading_msg.edit_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"Analysis delivered to user {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Analysis command error: {e}", exc_info=True)
        await loading_msg.edit_text(
            "An error occurred during analysis. Please try again."
        )


# --------------- /chart ---------------
@check_credit
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
                "⚠️ All data providers are currently busy or returned "
                "insufficient data. Please try again later."
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

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        caption = (
            f"XAU/USD - {tf.display_name} Chart\n"
            f"Price: ${df.iloc[-1]['close']:,.2f}\n"
            f"RSI: {indicators.rsi} | ATR: {indicators.atr}\n"
            f"{now_str}"
        )

        await loading_msg.delete()
        await update.message.reply_photo(photo=chart_buf, caption=caption)
        logger.info(f"Chart sent to user {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Chart command error: {e}", exc_info=True)
        await loading_msg.edit_text(
            "An error occurred while generating the chart."
        )


# --------------- /timeframe ---------------
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
        f"User {update.effective_user.id} changed timeframe to {new_tf.value}"
    )


# =============================================================================
# MODULE 9: ADMIN COMMANDS (Owner only)
# =============================================================================

@_owner_only
async def cmd_addprem(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Promote a user to premium. Usage: /addprem <user_id>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /addprem <user_id>\nExample: /addprem 123456789"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return

    if target_id == OWNER_USER_ID:
        await update.message.reply_text("Cannot modify the owner role.")
        return

    await db.set_role(target_id, "premium")
    logger.info(
        f"Owner promoted user {target_id} to premium"
    )
    await update.message.reply_text(
        f"✅ User `{target_id}` is now *Premium* \\(50/day\\)\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@_owner_only
async def cmd_delprem(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Demote a user to free. Usage: /delprem <user_id>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /delprem <user_id>\nExample: /delprem 123456789"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return

    if target_id == OWNER_USER_ID:
        await update.message.reply_text("Cannot modify the owner role.")
        return

    await db.set_role(target_id, "free")
    logger.info(
        f"Owner demoted user {target_id} to free"
    )
    await update.message.reply_text(
        f"✅ User `{target_id}` is now *Free* \\(5/day\\)\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# =============================================================================
# MODULE 10: ERROR HANDLER
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
# MODULE 11: APPLICATION LIFECYCLE
# =============================================================================
async def post_init(application: Application) -> None:
    # Connect to PostgreSQL
    await db.connect()

    # Register bot commands with Telegram
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("price", "Latest XAU/USD price"),
        BotCommand("analysis", "Full AI technical analysis"),
        BotCommand("chart", "Technical analysis chart"),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check remaining daily credits"),
        BotCommand("role", "Show your current role"),
        BotCommand("help", "Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram")


async def post_shutdown(application: Application) -> None:
    await db.close()
    logger.info("Application shutdown complete.")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  XAUUSD AI ANALYSIS BOT v3.0 - Starting...")
    logger.info(f"  TwelveData keys loaded: {len(TWELVEDATA_API_KEYS)}")
    logger.info(f"  Owner: {OWNER_USER_ID} (@{OWNER_USERNAME})")
    logger.info("=" * 60)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    # Public commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("role", cmd_role))
    app.add_handler(CommandHandler("timeframe", cmd_timeframe))

    # Credit-gated commands
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("chart", cmd_chart))

    # Admin commands (owner only)
    app.add_handler(CommandHandler("addprem", cmd_addprem))
    app.add_handler(CommandHandler("addpremium", cmd_addprem))
    app.add_handler(CommandHandler("delprem", cmd_delprem))
    app.add_handler(CommandHandler("removepremium", cmd_delprem))

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot polling for updates... Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
