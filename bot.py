#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD AI ANALYSIS BOT v3.0                     ║
║                                                                    ║
║  Production-ready Telegram bot for XAU/USD technical analysis      ║
║  Features: Credits, Premium, Owner Controls, API Fallback          ║
║  Uses: google-genai SDK, Twelve Data, python-telegram-bot, SQLite  ║
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
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TWELVEDATA_API_KEY2 = os.getenv("TWELVEDATA_API_KEY2", "")
TWELVEDATA_API_KEY3 = os.getenv("TWELVEDATA_API_KEY3", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Owner configuration
OWNER_ID = 5482019561
OWNER_USERNAME = "@EK-HENG"

# Credit limits
NORMAL_DAILY_LIMIT = 5
PREMIUM_DAILY_LIMIT = 25

# Collect all available API keys
TWELVEDATA_KEYS = [
    k for k in [TWELVEDATA_API_KEY, TWELVEDATA_API_KEY2, TWELVEDATA_API_KEY3]
    if k and k.strip()
]

_missing = []
if not TELEGRAM_BOT_TOKEN:
    _missing.append("TELEGRAM_BOT_TOKEN")
if not TWELVEDATA_KEYS:
    _missing.append("TWELVEDATA_API_KEY (at least one)")
if not GEMINI_API_KEY:
    _missing.append("GEMINI_API_KEY")
if _missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        f"Please set them in your .env file."
    )

# Database path - uses Railway volume if available, else local
DB_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
if not os.path.exists(DB_DIR):
    try:
        os.makedirs(DB_DIR, exist_ok=True)
    except OSError:
        DB_DIR = "."  # fallback to current directory
DB_PATH = os.path.join(DB_DIR, "bot_data.db")

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
# MODULE 0: DATABASE MANAGER (SQLite Persistent Storage)
# =============================================================================
class DatabaseManager:
    """Thread-safe SQLite database for premium users and credit tracking."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        logger.info(f"Database initialized at: {db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TEXT DEFAULT (datetime('now')),
                username TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS user_credits (
                user_id INTEGER PRIMARY KEY,
                usage_count INTEGER DEFAULT 0,
                last_reset_date TEXT,
                total_lifetime_usage INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_info (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                last_seen TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        logger.info("Database tables verified")

    # ---- Premium User Methods ----

    def is_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM premium_users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row is not None

    def add_premium(self, user_id: int, added_by: int, username: str = "") -> bool:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO premium_users "
                "(user_id, added_by, added_at, username) VALUES (?, ?, ?, ?)",
                (user_id, added_by, datetime.now(timezone.utc).isoformat(), username)
            )
            conn.commit()
            logger.info(f"Premium added: user {user_id} by {added_by}")
            return True
        except Exception as e:
            logger.error(f"Error adding premium: {e}")
            return False

    def remove_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM premium_users WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
            removed = cursor.rowcount > 0
            if removed:
                logger.info(f"Premium removed: user {user_id}")
            return removed
        except Exception as e:
            logger.error(f"Error removing premium: {e}")
            return False

    def get_all_premium_users(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT user_id, username, added_at FROM premium_users"
        ).fetchall()
        return [
            {"user_id": r[0], "username": r[1], "added_at": r[2]}
            for r in rows
        ]

    # ---- Credit / Usage Methods ----

    def get_usage(self, user_id: int) -> dict:
        conn = self._get_conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        row = conn.execute(
            "SELECT usage_count, last_reset_date, total_lifetime_usage "
            "FROM user_credits WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if row is None:
            # New user
            conn.execute(
                "INSERT INTO user_credits "
                "(user_id, usage_count, last_reset_date, total_lifetime_usage) "
                "VALUES (?, 0, ?, 0)",
                (user_id, today)
            )
            conn.commit()
            return {"usage_count": 0, "last_reset_date": today, "total_lifetime": 0}

        usage_count, last_reset, total_lifetime = row

        # Auto-reset if new day
        if last_reset != today:
            conn.execute(
                "UPDATE user_credits "
                "SET usage_count = 0, last_reset_date = ? "
                "WHERE user_id = ?",
                (today, user_id)
            )
            conn.commit()
            usage_count = 0

        return {
            "usage_count": usage_count,
            "last_reset_date": today,
            "total_lifetime": total_lifetime or 0,
        }

    def use_credit(self, user_id: int) -> bool:
        """Increment usage count. Returns True if successful."""
        conn = self._get_conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Ensure record exists and is reset for today
        self.get_usage(user_id)

        conn.execute(
            "UPDATE user_credits "
            "SET usage_count = usage_count + 1, "
            "    total_lifetime_usage = total_lifetime_usage + 1 "
            "WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        return True

    def check_and_use_credit(self, user_id: int) -> tuple[bool, int, int]:
        """
        Check if user has credits remaining and consume one if yes.
        Returns: (allowed, remaining, limit)
        """
        # Owner bypass
        if user_id == OWNER_ID:
            return True, 999, 999

        is_prem = self.is_premium(user_id)
        limit = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        usage = self.get_usage(user_id)
        current_count = usage["usage_count"]

        if current_count >= limit:
            remaining = 0
            return False, remaining, limit

        # Consume credit
        self.use_credit(user_id)
        remaining = limit - current_count - 1
        return True, remaining, limit

    # ---- User Info Methods ----

    def update_user_info(
        self, user_id: int, username: str = "", first_name: str = ""
    ):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO user_info "
            "(user_id, username, first_name, last_seen) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name,
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

    def get_user_info(self, user_id: int) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT username, first_name, last_seen FROM user_info "
            "WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            return {
                "username": row[0],
                "first_name": row[1],
                "last_seen": row[2],
            }
        return None

    def get_stats(self) -> dict:
        """Get bot-wide statistics for owner."""
        conn = self._get_conn()
        total_users = conn.execute(
            "SELECT COUNT(*) FROM user_credits"
        ).fetchone()[0]
        premium_count = conn.execute(
            "SELECT COUNT(*) FROM premium_users"
        ).fetchone()[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        active_today = conn.execute(
            "SELECT COUNT(*) FROM user_credits WHERE last_reset_date = ? AND usage_count > 0",
            (today,)
        ).fetchone()[0]
        total_usage = conn.execute(
            "SELECT COALESCE(SUM(total_lifetime_usage), 0) FROM user_credits"
        ).fetchone()[0]
        return {
            "total_users": total_users,
            "premium_users": premium_count,
            "active_today": active_today,
            "total_lifetime_usage": total_usage,
        }


# Initialize database
db = DatabaseManager(DB_PATH)


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
# MODULE 1: TWELVE DATA CLIENT WITH API FALLBACK
# =============================================================================
class TwelveDataClient:
    """Twelve Data client with automatic API key fallback."""

    def __init__(self, api_keys: list[str]):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "XAUUSD-AI-Bot/3.0"})
        self._key_failures: dict[int, float] = {}  # index -> failure timestamp
        logger.info(
            f"TwelveData initialized with {len(api_keys)} API key(s)"
        )

    @property
    def current_key(self) -> str:
        return self.api_keys[self.current_key_index]

    def _get_next_working_key(self) -> Optional[str]:
        """Find next available API key, skipping recently failed ones."""
        now = time.time()
        for i in range(len(self.api_keys)):
            # Skip keys that failed less than 60s ago
            if i in self._key_failures:
                if now - self._key_failures[i] < 60:
                    continue
                else:
                    del self._key_failures[i]
            self.current_key_index = i
            return self.api_keys[i]
        # All keys failed recently, try first one anyway
        self.current_key_index = 0
        return self.api_keys[0] if self.api_keys else None

    def _mark_key_failed(self, index: int):
        self._key_failures[index] = time.time()
        logger.warning(
            f"API key #{index + 1} marked as failed, "
            f"will retry after 60s"
        )

    def _is_quota_error(self, data: dict) -> bool:
        """Check if response indicates quota/rate limit exceeded."""
        code = data.get("code", 0)
        message = str(data.get("message", "")).lower()
        # Twelve Data error codes for quota
        if code in (429, 401, 403):
            return True
        if any(word in message for word in [
            "quota", "limit", "exceeded", "too many", "rate limit",
            "api key", "unauthorized", "forbidden"
        ]):
            return True
        return False

    def fetch_time_series(
        self,
        interval: str,
        outputsize: int = DEFAULT_OUTPUTSIZE,
    ) -> Optional[pd.DataFrame]:
        """Fetch time series with automatic API key fallback."""
        last_error = None

        for attempt_idx in range(len(self.api_keys)):
            api_key = self._get_next_working_key()
            if not api_key:
                logger.error("No working API keys available")
                return None

            key_num = self.current_key_index + 1
            url = f"{TWELVEDATA_BASE_URL}/time_series"
            params = {
                "symbol": SYMBOL,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": api_key,
                "format": "JSON",
                "dp": 2,
            }

            try:
                logger.info(
                    f"Fetching {SYMBOL} | interval={interval} | "
                    f"key #{key_num}/{len(self.api_keys)}"
                )
                response = self.session.get(url, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()

                # Check for API-level errors
                if "code" in data:
                    if self._is_quota_error(data):
                        logger.warning(
                            f"Key #{key_num} quota exceeded: "
                            f"{data.get('message', 'Unknown')}"
                        )
                        self._mark_key_failed(self.current_key_index)
                        last_error = f"Key #{key_num}: {data.get('message')}"
                        continue  # try next key
                    elif data["code"] != 200:
                        logger.error(
                            f"API error: {data.get('message', 'Unknown')}"
                        )
                        last_error = data.get("message", "Unknown error")
                        continue

                if "values" not in data or not data["values"]:
                    logger.error("Twelve Data returned empty values")
                    return None

                df = pd.DataFrame(data["values"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                if "volume" in df.columns:
                    df["volume"] = (
                        pd.to_numeric(df["volume"], errors="coerce")
                        .fillna(0)
                    )
                else:
                    df["volume"] = 0

                df = df.sort_values("datetime").reset_index(drop=True)
                df = df.dropna(
                    subset=["open", "high", "low", "close"]
                ).reset_index(drop=True)

                logger.info(
                    f"Fetched {len(df)} candles using key #{key_num}"
                )
                return df

            except requests.exceptions.Timeout:
                logger.error(f"Key #{key_num}: Request timed out")
                self._mark_key_failed(self.current_key_index)
                last_error = "Timeout"
            except requests.exceptions.ConnectionError:
                logger.error(f"Key #{key_num}: Connection failed")
                last_error = "Connection error"
                break  # connection issue, no point trying other keys
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (429, 401, 403):
                    logger.warning(f"Key #{key_num}: HTTP {status}")
                    self._mark_key_failed(self.current_key_index)
                    last_error = f"HTTP {status}"
                    continue
                logger.error(f"HTTP error: {e}")
                last_error = str(e)
                break
            except (ValueError, KeyError) as e:
                logger.error(f"Parse error: {e}")
                last_error = str(e)
                break

        logger.error(
            f"All {len(self.api_keys)} API keys exhausted. "
            f"Last error: {last_error}"
        )
        return None

    def fetch_current_price(self) -> Optional[dict]:
        """Fetch current price with API key fallback."""
        for attempt_idx in range(len(self.api_keys)):
            api_key = self._get_next_working_key()
            if not api_key:
                return None

            key_num = self.current_key_index + 1
            url = f"{TWELVEDATA_BASE_URL}/price"
            params = {
                "symbol": SYMBOL,
                "apikey": api_key,
                "dp": 2,
            }
            try:
                response = self.session.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                if "code" in data and self._is_quota_error(data):
                    logger.warning(f"Price key #{key_num} quota exceeded")
                    self._mark_key_failed(self.current_key_index)
                    continue

                if "price" not in data:
                    logger.error(f"No price in response: {data}")
                    continue

                return {
                    "price": float(data["price"]),
                    "timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    ),
                }
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (429, 401, 403):
                    self._mark_key_failed(self.current_key_index)
                    continue
                logger.error(f"Price HTTP error: {e}")
                break
            except Exception as e:
                logger.error(f"Error fetching price: {e}")
                break

        return None


td_client = TwelveDataClient(TWELVEDATA_KEYS)


# =============================================================================
# MODULE 2: TECHNICAL ANALYSIS ENGINE
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

        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"], window=14
        ).rsi()
        df["ema_20"] = ta.trend.EMAIndicator(
            close=df["close"], window=20
        ).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(
            close=df["close"], window=50
        ).ema_indicator()

        macd_calc = ta.trend.MACD(
            close=df["close"],
            window_slow=26,
            window_fast=12,
            window_sign=9,
        )
        df["macd_line"] = macd_calc.macd()
        df["macd_signal"] = macd_calc.macd_signal()
        df["macd_histogram"] = macd_calc.macd_diff()

        df["atr"] = ta.volatility.AverageTrueRange(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=14,
        ).average_true_range()

        support, resistance, pivot, s2, r2 = (
            TechnicalAnalysisEngine._compute_support_resistance(df)
        )

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

        if indicators.macd_histogram > 0:
            indicators.macd_interpretation = "Positive"
        elif indicators.macd_histogram < 0:
            indicators.macd_interpretation = "Negative"
        else:
            indicators.macd_interpretation = "Neutral"

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
        latest_close = df.iloc[-1]["close"]
        recent = df.tail(30).copy()

        session_high = recent["high"].max()
        session_low = recent["low"].min()
        session_close = latest_close

        pivot = (session_high + session_low + session_close) / 3.0
        pivot_r1 = (2 * pivot) - session_low
        pivot_s1 = (2 * pivot) - session_high
        pivot_r2 = pivot + (session_high - session_low)
        pivot_s2 = pivot - (session_high - session_low)

        swing_support, swing_resistance = (
            TechnicalAnalysisEngine._detect_swings(df, lookback=40, window=5)
        )

        atr_series = df.get("atr")
        if atr_series is not None and pd.notna(atr_series.iloc[-1]):
            current_atr = atr_series.iloc[-1]
        else:
            current_atr = (session_high - session_low) / 3.0

        atr_support = latest_close - current_atr * 1.5
        atr_resistance = latest_close + current_atr * 1.5

        support_candidates = [pivot_s1, swing_support, atr_support]
        resistance_candidates = [pivot_r1, swing_resistance, atr_resistance]

        valid_supports = [
            s for s in support_candidates
            if s < latest_close and s > 0
        ]
        valid_resistances = [
            r for r in resistance_candidates
            if r > latest_close
        ]

        support = max(valid_supports) if valid_supports else latest_close - current_atr * 1.5
        resistance = min(valid_resistances) if valid_resistances else latest_close + current_atr * 1.5

        s2_candidates = [pivot_s2, support - current_atr]
        r2_candidates = [pivot_r2, resistance + current_atr]
        support_2 = min(
            [s for s in s2_candidates if s > 0] or [support - current_atr * 2]
        )
        resistance_2 = max(r2_candidates)

        if support >= latest_close:
            support = latest_close - current_atr
        if resistance <= latest_close:
            resistance = latest_close + current_atr
        if support_2 >= support:
            support_2 = support - current_atr
        if resistance_2 <= resistance:
            resistance_2 = resistance + current_atr

        return support, resistance, pivot, support_2, resistance_2

    @staticmethod
    def _detect_swings(
        df: pd.DataFrame, lookback: int = 40, window: int = 5
    ) -> tuple[float, float]:
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

        valid_lows = [s for s in swing_lows if s < latest_close]
        support = max(valid_lows) if valid_lows else recent["low"].min()

        valid_highs = [r for r in swing_highs if r > latest_close]
        resistance = min(valid_highs) if valid_highs else recent["high"].max()

        return support, resistance


ta_engine = TechnicalAnalysisEngine()


# =============================================================================
# MODULE 3: GEMINI AI ANALYSIS
# =============================================================================
class GeminiAnalyzer:

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = GEMINI_MODEL
        self._max_retries = 3
        self._retry_delay = 2.0
        logger.info(
            f"Gemini AI initialized | model: {self.model_name}"
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
                    f"Gemini request attempt {attempt}/{self._max_retries}"
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
                    last_error = "Empty response from AI"
                    if attempt < self._max_retries:
                        time.sleep(self._retry_delay * attempt)
                    continue

                analysis.raw_response = raw_text
                logger.info(
                    f"Gemini response received ({len(raw_text)} chars)"
                )
                logger.debug(f"Raw Gemini:\n{raw_text}")

                analysis = self._parse_response(raw_text, analysis)

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
                logger.info(f"Primary parse: {8 - na_count}/8 fields")

                if na_count > 0:
                    analysis = self._fallback_parse(raw_text, analysis)

                analysis = self._fill_missing_fields(
                    analysis, indicators, df
                )

                if analysis.bias not in ("N/A", "Error", ""):
                    return analysis

                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)

            except Exception as e:
                last_error = str(e)
                logger.error(f"Attempt {attempt} failed: {e}")
                logger.debug(traceback.format_exc())
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)

        logger.error(f"All attempts failed. Last error: {last_error}")
        return self._fill_missing_fields(
            AIAnalysis(raw_response="[Fallback]"), indicators, df
        )

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

        text = text.replace("**", "").replace("*", "").replace("```", "")
        text = text.replace("##", "").replace("###", "")
        lines = text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue
            colon_idx = line.find(":")
            if colon_idx == -1:
                continue
            key = line[:colon_idx].strip().upper()
            value = line[colon_idx + 1:].strip().strip("\"'- ")
            if not value:
                continue

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
        if not text:
            return analysis

        text_clean = (
            text.replace("**", "").replace("*", "")
                .replace("`", "").replace("#", "")
        )

        patterns = {
            "bias": [
                r"(?:BIAS|MARKET\s*BIAS|DIRECTION)\s*[:=]\s*(.+?)(?:\n|$)",
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
                continue
            for pattern in pattern_list:
                match = re.search(pattern, text_clean, re.IGNORECASE)
                if match:
                    value = (
                        match.group(1).strip()
                        if match.lastindex
                        else match.group(0).strip()
                    )
                    value = value.strip("\"'- ")
                    if value and value.upper() != "N/A":
                        setattr(analysis, field_name, value)
                        break

        return analysis

    def _fill_missing_fields(
        self,
        analysis: AIAnalysis,
        indicators: TechnicalIndicators,
        df: pd.DataFrame,
    ) -> AIAnalysis:
        latest_close = df.iloc[-1]["close"]
        atr = indicators.atr if indicators.atr > 0 else 5.0

        if analysis.bias == "N/A":
            analysis.bias = indicators.trend_direction

        if analysis.trade_idea == "N/A":
            if "bullish" in analysis.bias.lower():
                analysis.trade_idea = "Buy"
            elif "bearish" in analysis.bias.lower():
                analysis.trade_idea = "Sell"
            else:
                analysis.trade_idea = "Wait"

        is_buy = "buy" in analysis.trade_idea.lower()
        is_sell = "sell" in analysis.trade_idea.lower()

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
                analysis.entry = f"Wait near {latest_close:.2f}"

        if analysis.stop_loss == "N/A":
            if is_buy:
                analysis.stop_loss = f"{indicators.support - atr * 0.5:.2f}"
            elif is_sell:
                analysis.stop_loss = f"{indicators.resistance + atr * 0.5:.2f}"
            else:
                analysis.stop_loss = f"{indicators.support:.2f}"

        if analysis.take_profit_1 == "N/A":
            if is_buy:
                analysis.take_profit_1 = f"{latest_close + atr * 1.5:.2f}"
            elif is_sell:
                analysis.take_profit_1 = f"{latest_close - atr * 1.5:.2f}"
            else:
                analysis.take_profit_1 = f"{indicators.resistance:.2f}"

        if analysis.take_profit_2 == "N/A":
            if is_buy:
                analysis.take_profit_2 = f"{latest_close + atr * 2.5:.2f}"
            elif is_sell:
                analysis.take_profit_2 = f"{latest_close - atr * 2.5:.2f}"
            else:
                analysis.take_profit_2 = f"{indicators.resistance_2:.2f}"

        if analysis.risk_note == "N/A":
            analysis.risk_note = (
                f"{indicators.volatility_condition}. "
                f"ATR: {atr:.2f}. "
                f"RSI at {indicators.rsi:.1f} "
                f"({indicators.rsi_interpretation}). "
                f"Use proper position sizing."
            )

        if analysis.short_term_outlook == "N/A":
            pos = (
                "resistance"
                if latest_close > indicators.pivot_point
                else "support"
            )
            analysis.short_term_outlook = (
                f"EMA trend is {indicators.ema_trend}. "
                f"Price near {pos} zone. "
                f"MACD histogram {indicators.macd_interpretation.lower()}."
            )

        return analysis


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

            ax1 = axes[0]
            ax1.plot(
                plot_df["datetime"], plot_df["close"],
                color=COLOR_WHITE, linewidth=1.5,
                label="Close", zorder=5,
            )
            ax1.fill_between(
                plot_df["datetime"], plot_df["low"], plot_df["high"],
                alpha=0.1, color=COLOR_GOLD,
            )
            for _, row in plot_df.iterrows():
                c = COLOR_GREEN if row["close"] >= row["open"] else COLOR_RED
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [row["low"], row["high"]],
                    color=c, linewidth=0.8, alpha=0.6,
                )
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [min(row["open"], row["close"]),
                     max(row["open"], row["close"])],
                    color=c, linewidth=2.5,
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
                label=f"S1 ({indicators.support:.2f})",
            )
            ax1.axhline(
                y=indicators.resistance, color=COLOR_RED_BRIGHT,
                linestyle=":", linewidth=1.0, alpha=0.8,
                label=f"R1 ({indicators.resistance:.2f})",
            )
            ax1.axhline(
                y=indicators.support_2, color=COLOR_GREEN_BRIGHT,
                linestyle=":", linewidth=0.6, alpha=0.4,
            )
            ax1.axhline(
                y=indicators.resistance_2, color=COLOR_RED_BRIGHT,
                linestyle=":", linewidth=0.6, alpha=0.4,
            )
            ax1.axhline(
                y=indicators.pivot_point, color=COLOR_GOLD,
                linestyle="-.", linewidth=0.7, alpha=0.5,
                label=f"Pivot ({indicators.pivot_point:.2f})",
            )
            ax1.set_ylabel("Price (USD)", fontsize=10, color=COLOR_WHITE)
            ax1.legend(loc="upper left", fontsize=7, framealpha=0.3)
            ax1.grid(True, alpha=0.15)

            ax2 = axes[1]
            if "rsi" in plot_df.columns:
                ax2.plot(
                    plot_df["datetime"], plot_df["rsi"],
                    color=COLOR_PURPLE, linewidth=1.5,
                    label=f"RSI ({indicators.rsi:.1f})",
                )
                ax2.fill_between(
                    plot_df["datetime"], plot_df["rsi"], 50,
                    where=(plot_df["rsi"] >= 50),
                    alpha=0.2, color=COLOR_GREEN,
                )
                ax2.fill_between(
                    plot_df["datetime"], plot_df["rsi"], 50,
                    where=(plot_df["rsi"] < 50),
                    alpha=0.2, color=COLOR_RED,
                )
                ax2.axhline(y=70, color=COLOR_RED_BRIGHT,
                            linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=30, color=COLOR_GREEN_BRIGHT,
                            linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=50, color=COLOR_GRAY,
                            linestyle="-", linewidth=0.5, alpha=0.4)
            ax2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE)
            ax2.set_ylim(10, 90)
            ax2.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax2.grid(True, alpha=0.15)

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
                ax3.axhline(y=0, color=COLOR_GRAY,
                            linestyle="-", linewidth=0.5, alpha=0.4)
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
                0.99, 0.01, f"Generated: {now_str}",
                ha="right", va="bottom", fontsize=7,
                color=COLOR_GRAY, alpha=0.6,
            )
            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(
                buf, format="png", dpi=CHART_DPI,
                bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none",
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
    if not isinstance(text, str):
        text = str(text)
    special_chars = [
        "_", "*", "[", "]", "(", ")", "~", "`", ">",
        "#", "+", "-", "=", "|", "{", "}", ".", "!",
    ]
    for char in special_chars:
        text = text.replace(char, "\\" + char)
    return text


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def _track_user(update: Update):
    """Track user info in database."""
    user = update.effective_user
    if user:
        db.update_user_info(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
        )


async def _check_credits(
    update: Update, command_name: str
) -> bool:
    """Check if user has credits. Returns True if allowed."""
    user_id = update.effective_user.id

    allowed, remaining, limit = db.check_and_use_credit(user_id)

    if not allowed:
        is_prem = db.is_premium(user_id)
        tier = "Premium" if is_prem else "Free"
        reset_time = "midnight UTC"

        msg = (
            f"\u26d4 *Daily Limit Reached*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\n"
            f"Your *{_escape_md(tier)}* plan allows "
            f"*{limit}* commands/day\\.\n"
            f"All credits used for today\\.\n"
            f"\n"
            f"\U0001f504 Resets at: *{_escape_md(reset_time)}*\n"
        )
        if not is_prem:
            msg += (
                f"\n\u2b50 Upgrade to *Premium* for "
                f"*{PREMIUM_DAILY_LIMIT}* commands/day\\!\n"
                f"Contact {_escape_md(OWNER_USERNAME)} to upgrade\\."
            )

        await update.message.reply_text(
            msg, parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(
            f"User {user_id} blocked ({command_name}): "
            f"limit {limit} reached"
        )
        return False

    logger.info(
        f"User {user_id} used credit for {command_name}: "
        f"{remaining} remaining of {limit}"
    )
    return True


# ---------- /start ----------
async def cmd_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id
    is_prem = db.is_premium(user_id)
    tier = "Premium \u2b50" if is_prem else "Free"
    limit = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT

    if user_id == OWNER_ID:
        tier = "Owner \U0001f451"
        limit_str = "Unlimited"
    else:
        limit_str = str(limit)

    welcome = (
        "\U0001f947 *XAUUSD AI Analysis Bot v3\\.0*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\n"
        "Welcome\\! AI\\-powered technical analysis for "
        "*Gold \\(XAU/USD\\)*\\.\n"
        "\n"
        f"\U0001f464 *Your Plan:* {_escape_md(tier)}\n"
        f"\U0001f4ca *Daily Limit:* {_escape_md(limit_str)} commands\n"
        "\n"
        "\U0001f539 Real\\-time price from Twelve Data\n"
        "\U0001f539 Indicators: RSI, EMA, MACD, ATR\n"
        "\U0001f539 AI analysis by Google Gemini\n"
        "\U0001f539 Professional charts\n"
        "\n"
        "*Commands:*\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI analysis\n"
        "/chart \\- Technical chart\n"
        "/timeframe \\- Change timeframe\n"
        "/credits \\- Check remaining credits\n"
        "/help \\- All commands\n"
        "\n"
        "Default timeframe: *15 Min*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "_Not financial advice\\. Trade responsibly\\._"
    )
    await update.message.reply_text(
        welcome, parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"User {user_id} started bot (tier: {tier})")


# ---------- /help ----------
async def cmd_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    help_text = (
        "\U0001f539 *Bot Commands*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\n"
        "*Market Commands:*\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI technical analysis\n"
        "/chart \\- Send technical chart\n"
        "/timeframe <tf> \\- Change timeframe\n"
        "\n"
        "*Account Commands:*\n"
        "/credits \\- Check remaining daily credits\n"
        "/myid \\- Show your user ID\n"
        "\n"
        "*Timeframe Options:*\n"
        "  `5m` `15m` `1h` `4h` `1d`\n"
        "\n"
        "*Example:* `/timeframe 4h`\n"
    )

    if is_owner(user_id):
        help_text += (
            "\n"
            "\U0001f451 *Owner Commands:*\n"
            "/addpremium <user\\_id> \\- Add premium user\n"
            "/removepremium <user\\_id> \\- Remove premium\n"
            "/checkid <user\\_id> \\- Check user info\n"
            "/premiumlist \\- List all premium users\n"
            "/botstats \\- Bot statistics\n"
            "/broadcast <message> \\- Send to all users\n"
        )

    help_text += (
        "\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    )
    await update.message.reply_text(
        help_text, parse_mode=ParseMode.MARKDOWN_V2
    )


# ---------- /credits ----------
async def cmd_credits(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id
    is_prem = db.is_premium(user_id)
    usage = db.get_usage(user_id)
    used = usage["usage_count"]
    total_lifetime = usage["total_lifetime"]

    if user_id == OWNER_ID:
        tier = "Owner \U0001f451"
        remaining_str = "Unlimited"
        limit = "\u221e"
    else:
        tier = "Premium \u2b50" if is_prem else "Free"
        limit_num = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        remaining = max(0, limit_num - used)
        remaining_str = str(remaining)
        limit = str(limit_num)

    bar_length = 10
    if user_id != OWNER_ID:
        filled = int((used / int(limit)) * bar_length) if int(limit) > 0 else 0
        filled = min(filled, bar_length)
        bar = "\u2588" * filled + "\u2591" * (bar_length - filled)
    else:
        bar = "\u2588" * bar_length

    msg = (
        f"\U0001f4ca *Credit Status*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n"
        f"\U0001f464 *Plan:* {_escape_md(tier)}\n"
        f"\U0001f4b3 *Remaining:* {_escape_md(remaining_str)} / {_escape_md(str(limit))}\n"
        f"\U0001f4ca *Used Today:* {used}\n"
        f"\U0001f4c8 *Lifetime:* {total_lifetime}\n"
        f"\n"
        f"`[{_escape_md(bar)}]`\n"
        f"\n"
        f"\U0001f504 Resets daily at *midnight UTC*\n"
    )

    if not is_prem and user_id != OWNER_ID:
        msg += (
            f"\n\u2b50 Want more\\? Contact {_escape_md(OWNER_USERNAME)} "
            f"for *Premium* \\({PREMIUM_DAILY_LIMIT} cmds/day\\)\\!"
        )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )


# ---------- /myid ----------
async def cmd_myid(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user = update.effective_user
    user_id = user.id
    username = user.username or "Not set"
    first_name = user.first_name or "Not set"
    is_prem = db.is_premium(user_id)

    if user_id == OWNER_ID:
        role = "Owner \U0001f451"
    elif is_prem:
        role = "Premium \u2b50"
    else:
        role = "Free User"

    msg = (
        f"\U0001f4cb *Your Info*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n"
        f"\U0001f194 *User ID:* `{user_id}`\n"
        f"\U0001f464 *Name:* {_escape_md(first_name)}\n"
        f"\U0001f465 *Username:* @{_escape_md(username)}\n"
        f"\U0001f3ab *Role:* {_escape_md(role)}\n"
    )
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )


# ---------- /price ----------
async def cmd_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    if not await _check_credits(update, "price"):
        return

    await update.message.reply_text("Fetching latest XAU/USD price...")

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        price_data = await loop.run_in_executor(
            None, td_client.fetch_current_price
        )

        if price_data is None:
            await update.message.reply_text(
                "Failed to fetch price. Please try again later."
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
    except Exception as e:
        logger.error(f"Price command error: {e}")
        await update.message.reply_text(
            "An error occurred while fetching the price."
        )


# ---------- /analysis ----------
async def cmd_analysis(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    if not await _check_credits(update, "analysis"):
        return

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
            None, td_client.fetch_time_series,
            tf.value, DEFAULT_OUTPUTSIZE,
        )

        if df is None or len(df) < 50:
            await loading_msg.edit_text(
                "Failed to fetch sufficient market data. "
                "Please try again."
            )
            return

        df, indicators = ta_engine.compute_indicators(df)
        latest = df.iloc[-1]

        ai_result = await loop.run_in_executor(
            None, gemini_analyzer.generate_analysis,
            df, indicators, tf.display_name,
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

        # Get remaining credits for footer
        user_id = update.effective_user.id
        usage = db.get_usage(user_id)
        if user_id == OWNER_ID:
            credit_line = "\U0001f451 Owner \\- Unlimited"
        else:
            is_prem = db.is_premium(user_id)
            lim = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
            rem = max(0, lim - usage["usage_count"])
            credit_line = f"\U0001f4b3 Credits: {rem}/{lim} remaining"

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
            f"_{credit_line}_\n"
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


# ---------- /chart ----------
async def cmd_chart(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    if not await _check_credits(update, "chart"):
        return

    session = get_session(update.effective_user.id)
    tf = session.timeframe

    loading_msg = await update.message.reply_text(
        f"Generating chart for XAU/USD ({tf.display_name})..."
    )

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None, td_client.fetch_time_series,
            tf.value, DEFAULT_OUTPUTSIZE,
        )

        if df is None or len(df) < 20:
            await loading_msg.edit_text(
                "Insufficient data for chart generation."
            )
            return

        df, indicators = ta_engine.compute_indicators(df)

        chart_buf = await loop.run_in_executor(
            None, chart_gen.generate_chart,
            df, indicators, tf.display_name,
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


# ---------- /timeframe ----------
async def cmd_timeframe(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
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
        f"User {update.effective_user.id} -> {new_tf.value}"
    )


# =============================================================================
# MODULE 6: OWNER-ONLY COMMANDS
# =============================================================================

async def cmd_addpremium(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /addpremium <user\\_id>",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Invalid user ID. Must be a number."
        )
        return

    # Get username if available
    target_info = db.get_user_info(target_id)
    username = target_info["username"] if target_info else ""

    success = db.add_premium(target_id, user_id, username)
    if success:
        msg = (
            f"\u2705 *Premium Added*\n"
            f"\n"
            f"User ID: `{target_id}`\n"
            f"Username: {_escape_md(username or 'Unknown')}\n"
            f"Daily Limit: *{PREMIUM_DAILY_LIMIT}* commands\n"
            f"Added by: Owner"
        )
    else:
        msg = f"\u274c Failed to add premium for user `{target_id}`"

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Owner added premium for user {target_id}")


async def cmd_removepremium(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /removepremium <user\\_id>",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Invalid user ID. Must be a number."
        )
        return

    removed = db.remove_premium(target_id)
    if removed:
        msg = (
            f"\u2705 *Premium Removed*\n"
            f"\n"
            f"User `{target_id}` is now a Free user\\.\n"
            f"Daily limit: *{NORMAL_DAILY_LIMIT}* commands"
        )
    else:
        msg = (
            f"\u26a0\ufe0f User `{target_id}` was not in "
            f"the premium list\\."
        )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Owner removed premium for user {target_id}")


async def cmd_checkid(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /checkid <user\\_id>",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Invalid user ID. Must be a number."
        )
        return

    is_prem = db.is_premium(target_id)
    usage = db.get_usage(target_id)
    user_info = db.get_user_info(target_id)

    if target_id == OWNER_ID:
        role = "Owner \U0001f451"
        limit = "\u221e"
        remaining = "Unlimited"
    elif is_prem:
        role = "Premium \u2b50"
        limit = str(PREMIUM_DAILY_LIMIT)
        remaining = str(max(0, PREMIUM_DAILY_LIMIT - usage["usage_count"]))
    else:
        role = "Free User"
        limit = str(NORMAL_DAILY_LIMIT)
        remaining = str(max(0, NORMAL_DAILY_LIMIT - usage["usage_count"]))

    username = user_info["username"] if user_info else "Unknown"
    first_name = user_info["first_name"] if user_info else "Unknown"
    last_seen = user_info["last_seen"] if user_info else "Never"

    msg = (
        f"\U0001f50d *User Details*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n"
        f"\U0001f194 *ID:* `{target_id}`\n"
        f"\U0001f464 *Name:* {_escape_md(first_name)}\n"
        f"\U0001f465 *Username:* @{_escape_md(username)}\n"
        f"\U0001f3ab *Role:* {_escape_md(role)}\n"
        f"\n"
        f"\U0001f4ca *Usage Today:*\n"
        f"  Used: {usage['usage_count']}\n"
        f"  Remaining: {_escape_md(remaining)}\n"
        f"  Limit: {_escape_md(limit)}\n"
        f"\n"
        f"\U0001f4c8 *Lifetime Usage:* {usage['total_lifetime']}\n"
        f"\U0001f552 *Last Seen:* {_escape_md(last_seen)}\n"
    )
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_premiumlist(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    premium_users = db.get_all_premium_users()

    if not premium_users:
        await update.message.reply_text(
            "\U0001f4cb *Premium Users*\n\nNo premium users yet\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = [
        "\U0001f4cb *Premium Users*",
        "\u2501" * 27,
        "",
    ]
    for i, user in enumerate(premium_users, 1):
        uname = user["username"] or "Unknown"
        lines.append(
            f"{i}\\. `{user['user_id']}` \\- "
            f"@{_escape_md(uname)} "
            f"\\(added: {_escape_md(user['added_at'][:10])}\\)"
        )

    lines.append("")
    lines.append(f"*Total:* {len(premium_users)} premium users")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_botstats(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    stats = db.get_stats()

    # API key status
    key_status_lines = []
    for i, key in enumerate(TWELVEDATA_KEYS):
        masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
        failed = i in td_client._key_failures
        status = "\u274c Failed" if failed else "\u2705 Active"
        key_status_lines.append(
            f"  Key {i + 1}: `{_escape_md(masked)}` {_escape_md(status)}"
        )

    msg = (
        f"\U0001f4ca *Bot Statistics*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n"
        f"\U0001f465 *Users:*\n"
        f"  Total: {stats['total_users']}\n"
        f"  Premium: {stats['premium_users']}\n"
        f"  Active Today: {stats['active_today']}\n"
        f"\n"
        f"\U0001f4c8 *Usage:*\n"
        f"  Lifetime Total: {stats['total_lifetime_usage']}\n"
        f"\n"
        f"\U0001f511 *API Keys:*\n"
        + "\n".join(key_status_lines) +
        f"\n"
        f"\n"
        f"\U0001f4be *Database:* `{_escape_md(DB_PATH)}`\n"
        f"\U0001f916 *AI Model:* `{_escape_md(GEMINI_MODEL)}`\n"
    )
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_broadcast(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _track_user(update)
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text(
            "\u26d4 This command is owner-only."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <message>"
        )
        return

    broadcast_text = " ".join(context.args)

    # Get all known user IDs
    conn = db._get_conn()
    rows = conn.execute("SELECT user_id FROM user_info").fetchall()
    user_ids = [r[0] for r in rows]

    if not user_ids:
        await update.message.reply_text("No users to broadcast to.")
        return

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"\U0001f4e2 *Announcement*\n\n{broadcast_text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
            await asyncio.sleep(0.1)  # Rate limit
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"Broadcast complete: {sent} sent, {failed} failed."
    )
    logger.info(
        f"Broadcast by owner: {sent} sent, {failed} failed"
    )


# =============================================================================
# MODULE 7: ERROR HANDLER
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
# MODULE 8: MAIN ENTRY POINT
# =============================================================================
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("price", "Latest XAU/USD price"),
        BotCommand("analysis", "Full AI technical analysis"),
        BotCommand("chart", "Technical analysis chart"),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check remaining daily credits"),
        BotCommand("myid", "Show your user ID"),
        BotCommand("help", "Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  XAUUSD AI ANALYSIS BOT v3.0 - Starting...")
    logger.info(f"  Owner: {OWNER_ID} ({OWNER_USERNAME})")
    logger.info(f"  API Keys: {len(TWELVEDATA_KEYS)} loaded")
    logger.info(f"  Database: {DB_PATH}")
    logger.info(f"  Normal limit: {NORMAL_DAILY_LIMIT}/day")
    logger.info(f"  Premium limit: {PREMIUM_DAILY_LIMIT}/day")
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

    # Public commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("timeframe", cmd_timeframe))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Owner-only commands
    app.add_handler(CommandHandler("addpremium", cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("checkid", cmd_checkid))
    app.add_handler(CommandHandler("premiumlist", cmd_premiumlist))
    app.add_handler(CommandHandler("botstats", cmd_botstats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    app.add_error_handler(error_handler)

    logger.info("Bot polling... Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
