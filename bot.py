#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD AI ANALYSIS BOT v3.1                     ║
║                                                                    ║
║  Production-ready Telegram bot for XAU/USD technical analysis      ║
║  Features: Credits, Premium, Owner Controls, API Fallback          ║
║  Uses: google-genai, Twelve Data, python-telegram-bot, PostgreSQL  ║
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
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import psycopg2
import psycopg2.extras
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
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Owner configuration
OWNER_ID = 5482019561
OWNER_USERNAME = "EK_HENG"  # without @, used for tg:// deep link

# Timezone: GMT+7
GMT7 = timezone(timedelta(hours=7))

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
if not DATABASE_URL:
    _missing.append("DATABASE_URL")
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


def get_owner_link() -> str:
    """Generate a clickable Telegram deep link to the owner."""
    return f"tg://user?id={OWNER_ID}"


def now_gmt7() -> datetime:
    """Get current datetime in GMT+7."""
    return datetime.now(GMT7)


def today_gmt7() -> str:
    """Get today's date string in GMT+7."""
    return now_gmt7().strftime("%Y-%m-%d")


# =============================================================================
# MODULE 0: POSTGRESQL DATABASE MANAGER
# =============================================================================
class DatabaseManager:
    """PostgreSQL database for premium users and credit tracking."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._init_db()
        logger.info("PostgreSQL database initialized")

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Get a new database connection."""
        conn = psycopg2.connect(self.database_url, connect_timeout=10)
        conn.autocommit = False
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS premium_users (
                        user_id BIGINT PRIMARY KEY,
                        added_by BIGINT NOT NULL,
                        added_at TIMESTAMPTZ DEFAULT NOW(),
                        username TEXT DEFAULT ''
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_credits (
                        user_id BIGINT PRIMARY KEY,
                        usage_count INTEGER DEFAULT 0,
                        last_reset_date TEXT,
                        total_lifetime_usage INTEGER DEFAULT 0
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_info (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT DEFAULT '',
                        first_name TEXT DEFAULT '',
                        last_seen TIMESTAMPTZ DEFAULT NOW()
                    );
                """)
            conn.commit()
            logger.info("PostgreSQL tables verified/created")
        except Exception as e:
            conn.rollback()
            logger.error(f"Database init error: {e}")
            raise
        finally:
            conn.close()

    # ---- Premium User Methods ----

    def is_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM premium_users WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"is_premium error: {e}")
            return False
        finally:
            conn.close()

    def add_premium(self, user_id: int, added_by: int, username: str = "") -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO premium_users (user_id, added_by, added_at, username)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET added_by = EXCLUDED.added_by,
                        added_at = EXCLUDED.added_at,
                        username = EXCLUDED.username
                """, (user_id, added_by, now_gmt7(), username))
            conn.commit()
            logger.info(f"Premium ADDED: user_id={user_id} by={added_by}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"add_premium error: {e}")
            return False
        finally:
            conn.close()

    def remove_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM premium_users WHERE user_id = %s",
                    (user_id,)
                )
                removed = cur.rowcount > 0
            conn.commit()
            if removed:
                logger.info(f"Premium REMOVED: user_id={user_id}")
            else:
                logger.info(f"Premium remove: user_id={user_id} NOT FOUND")
            return removed
        except Exception as e:
            conn.rollback()
            logger.error(f"remove_premium error: {e}")
            return False
        finally:
            conn.close()

    def get_all_premium_users(self) -> list[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT user_id, username, added_by, added_at "
                    "FROM premium_users ORDER BY added_at DESC"
                )
                rows = cur.fetchall()
            return [
                {
                    "user_id": r["user_id"],
                    "username": r["username"] or "",
                    "added_by": r["added_by"],
                    "added_at": str(r["added_at"])[:19] if r["added_at"] else "",
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"get_all_premium error: {e}")
            return []
        finally:
            conn.close()

    # ---- Credit / Usage Methods ----

    def get_usage(self, user_id: int) -> dict:
        conn = self._get_conn()
        today = today_gmt7()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT usage_count, last_reset_date, total_lifetime_usage "
                    "FROM user_credits WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()

                if row is None:
                    # New user - insert
                    cur.execute(
                        "INSERT INTO user_credits "
                        "(user_id, usage_count, last_reset_date, total_lifetime_usage) "
                        "VALUES (%s, 0, %s, 0)",
                        (user_id, today)
                    )
                    conn.commit()
                    return {
                        "usage_count": 0,
                        "last_reset_date": today,
                        "total_lifetime": 0,
                    }

                usage_count, last_reset, total_lifetime = row

                # Auto-reset if new day in GMT+7
                if last_reset != today:
                    cur.execute(
                        "UPDATE user_credits "
                        "SET usage_count = 0, last_reset_date = %s "
                        "WHERE user_id = %s",
                        (today, user_id)
                    )
                    conn.commit()
                    usage_count = 0

            return {
                "usage_count": usage_count,
                "last_reset_date": today,
                "total_lifetime": total_lifetime or 0,
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"get_usage error: {e}")
            return {"usage_count": 0, "last_reset_date": today, "total_lifetime": 0}
        finally:
            conn.close()

    def use_credit(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_credits "
                    "SET usage_count = usage_count + 1, "
                    "    total_lifetime_usage = total_lifetime_usage + 1 "
                    "WHERE user_id = %s",
                    (user_id,)
                )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"use_credit error: {e}")
            return False
        finally:
            conn.close()

    def check_and_use_credit(self, user_id: int) -> tuple[bool, int, int]:
        """
        Check credits and consume one if available.
        Returns: (allowed, remaining, limit)
        """
        if user_id == OWNER_ID:
            return True, 999, 999

        is_prem = self.is_premium(user_id)
        limit = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        usage = self.get_usage(user_id)
        current_count = usage["usage_count"]

        if current_count >= limit:
            return False, 0, limit

        self.use_credit(user_id)
        remaining = limit - current_count - 1
        return True, remaining, limit

    # ---- User Info Methods ----

    def update_user_info(
        self, user_id: int, username: str = "", first_name: str = ""
    ):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_info (user_id, username, first_name, last_seen)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_seen = EXCLUDED.last_seen
                """, (user_id, username, first_name, now_gmt7()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"update_user_info error: {e}")
        finally:
            conn.close()

    def get_user_info(self, user_id: int) -> Optional[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT username, first_name, last_seen "
                    "FROM user_info WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
            if row:
                return {
                    "username": row["username"] or "",
                    "first_name": row["first_name"] or "",
                    "last_seen": str(row["last_seen"])[:19] if row["last_seen"] else "",
                }
            return None
        except Exception as e:
            logger.error(f"get_user_info error: {e}")
            return None
        finally:
            conn.close()

    def get_all_user_ids(self) -> list[int]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM user_info")
                rows = cur.fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            logger.error(f"get_all_user_ids error: {e}")
            return []
        finally:
            conn.close()

    def get_stats(self) -> dict:
        conn = self._get_conn()
        today = today_gmt7()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM user_credits")
                total_users = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM premium_users")
                premium_count = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM user_credits "
                    "WHERE last_reset_date = %s AND usage_count > 0",
                    (today,)
                )
                active_today = cur.fetchone()[0]

                cur.execute(
                    "SELECT COALESCE(SUM(total_lifetime_usage), 0) "
                    "FROM user_credits"
                )
                total_usage = cur.fetchone()[0]

            return {
                "total_users": total_users,
                "premium_users": premium_count,
                "active_today": active_today,
                "total_lifetime_usage": total_usage,
            }
        except Exception as e:
            logger.error(f"get_stats error: {e}")
            return {
                "total_users": 0, "premium_users": 0,
                "active_today": 0, "total_lifetime_usage": 0,
            }
        finally:
            conn.close()


# Initialize database
db = DatabaseManager(DATABASE_URL)


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
            "5min": "5 Min", "15min": "15 Min",
            "1h": "1 Hour", "4h": "4 Hour", "1day": "Daily",
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
                logger.warning(f"Rate limit wait {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())
            return True


twelvedata_limiter = RateLimiter(max_calls=7, period_seconds=60.0)
user_sessions: dict[int, UserSession] = {}


# =============================================================================
# MODULE 1: TWELVE DATA CLIENT WITH API FALLBACK
# =============================================================================
class TwelveDataClient:

    def __init__(self, api_keys: list[str]):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "XAUUSD-AI-Bot/3.1"})
        self._key_failures: dict[int, float] = {}
        logger.info(f"TwelveData: {len(api_keys)} API key(s) loaded")

    def _get_next_working_key(self) -> Optional[str]:
        now = time.time()
        for i in range(len(self.api_keys)):
            if i in self._key_failures:
                if now - self._key_failures[i] < 60:
                    continue
                else:
                    del self._key_failures[i]
            self.current_key_index = i
            return self.api_keys[i]
        self.current_key_index = 0
        return self.api_keys[0] if self.api_keys else None

    def _mark_key_failed(self, index: int):
        self._key_failures[index] = time.time()
        logger.warning(f"API key #{index + 1} marked failed (60s cooldown)")

    def _is_quota_error(self, data: dict) -> bool:
        code = data.get("code", 0)
        message = str(data.get("message", "")).lower()
        if code in (429, 401, 403):
            return True
        if any(w in message for w in [
            "quota", "limit", "exceeded", "too many",
            "rate limit", "api key", "unauthorized", "forbidden"
        ]):
            return True
        return False

    def fetch_time_series(
        self, interval: str, outputsize: int = DEFAULT_OUTPUTSIZE,
    ) -> Optional[pd.DataFrame]:
        last_error = None
        for _ in range(len(self.api_keys)):
            api_key = self._get_next_working_key()
            if not api_key:
                logger.error("No working API keys")
                return None

            key_num = self.current_key_index + 1
            params = {
                "symbol": SYMBOL, "interval": interval,
                "outputsize": outputsize, "apikey": api_key,
                "format": "JSON", "dp": 2,
            }
            try:
                logger.info(f"Fetch {SYMBOL} key#{key_num}/{len(self.api_keys)}")
                resp = self.session.get(
                    f"{TWELVEDATA_BASE_URL}/time_series",
                    params=params, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                if "code" in data:
                    if self._is_quota_error(data):
                        self._mark_key_failed(self.current_key_index)
                        last_error = data.get("message", "Quota exceeded")
                        continue
                    elif data["code"] != 200:
                        last_error = data.get("message", "Unknown")
                        continue

                if "values" not in data or not data["values"]:
                    return None

                df = pd.DataFrame(data["values"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["volume"] = pd.to_numeric(
                    df.get("volume", 0), errors="coerce"
                ).fillna(0)
                df = (df.sort_values("datetime")
                        .dropna(subset=["open", "high", "low", "close"])
                        .reset_index(drop=True))
                logger.info(f"Got {len(df)} candles via key#{key_num}")
                return df

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (429, 401, 403):
                    self._mark_key_failed(self.current_key_index)
                    continue
                last_error = str(e)
                break
            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
                break
            except Exception as e:
                last_error = str(e)
                break

        logger.error(f"All API keys failed: {last_error}")
        return None

    def fetch_current_price(self) -> Optional[dict]:
        for _ in range(len(self.api_keys)):
            api_key = self._get_next_working_key()
            if not api_key:
                return None
            key_num = self.current_key_index + 1
            try:
                resp = self.session.get(
                    f"{TWELVEDATA_BASE_URL}/price",
                    params={"symbol": SYMBOL, "apikey": api_key, "dp": 2},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if "code" in data and self._is_quota_error(data):
                    self._mark_key_failed(self.current_key_index)
                    continue
                if "price" not in data:
                    continue
                return {
                    "price": float(data["price"]),
                    "timestamp": now_gmt7().strftime("%Y-%m-%d %H:%M:%S GMT+7"),
                }
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (429, 401, 403):
                    self._mark_key_failed(self.current_key_index)
                    continue
                break
            except Exception as e:
                logger.error(f"Price error: {e}")
                break
        return None


td_client = TwelveDataClient(TWELVEDATA_KEYS)


# =============================================================================
# MODULE 2: TECHNICAL ANALYSIS ENGINE
# =============================================================================
class TechnicalAnalysisEngine:

    @staticmethod
    def compute_indicators(df: pd.DataFrame) -> tuple[pd.DataFrame, TechnicalIndicators]:
        indicators = TechnicalIndicators()
        if df is None or len(df) < 50:
            return df, indicators

        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
        df["ema_20"] = ta.trend.EMAIndicator(close=df["close"], window=20).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(close=df["close"], window=50).ema_indicator()
        macd_calc = ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd_line"] = macd_calc.macd()
        df["macd_signal"] = macd_calc.macd_signal()
        df["macd_histogram"] = macd_calc.macd_diff()
        df["atr"] = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=14
        ).average_true_range()

        support, resistance, pivot, s2, r2 = TechnicalAnalysisEngine._compute_sr(df)
        latest = df.iloc[-1]

        for attr, col in [
            ("rsi", "rsi"), ("ema_20", "ema_20"), ("ema_50", "ema_50"),
            ("atr", "atr"),
        ]:
            val = latest[col]
            setattr(indicators, attr, round(val, 2) if pd.notna(val) else 0.0)

        for attr, col in [
            ("macd_line", "macd_line"), ("macd_signal", "macd_signal"),
            ("macd_histogram", "macd_histogram"),
        ]:
            val = latest[col]
            setattr(indicators, attr, round(val, 4) if pd.notna(val) else 0.0)

        indicators.support = round(support, 2)
        indicators.resistance = round(resistance, 2)
        indicators.pivot_point = round(pivot, 2)
        indicators.support_2 = round(s2, 2)
        indicators.resistance_2 = round(r2, 2)

        # RSI interpretation
        if indicators.rsi >= 70: indicators.rsi_interpretation = "Overbought"
        elif indicators.rsi >= 60: indicators.rsi_interpretation = "Bullish Momentum"
        elif indicators.rsi >= 40: indicators.rsi_interpretation = "Neutral"
        elif indicators.rsi >= 30: indicators.rsi_interpretation = "Bearish Momentum"
        else: indicators.rsi_interpretation = "Oversold"

        # EMA trend
        if indicators.ema_20 > indicators.ema_50:
            indicators.ema_trend = "Strong Bullish" if latest["close"] > indicators.ema_20 else "Bullish Crossover"
        elif indicators.ema_20 < indicators.ema_50:
            indicators.ema_trend = "Strong Bearish" if latest["close"] < indicators.ema_20 else "Bearish Crossover"
        else:
            indicators.ema_trend = "Neutral"

        # MACD
        if indicators.macd_histogram > 0: indicators.macd_interpretation = "Positive"
        elif indicators.macd_histogram < 0: indicators.macd_interpretation = "Negative"
        else: indicators.macd_interpretation = "Neutral"

        # Volatility
        atr_pct = (indicators.atr / latest["close"]) * 100 if latest["close"] > 0 else 0
        if atr_pct > 1.0: indicators.volatility_condition = "High Volatility"
        elif atr_pct > 0.5: indicators.volatility_condition = "Moderate Volatility"
        else: indicators.volatility_condition = "Low Volatility"

        # Overall
        bullish = sum([indicators.rsi > 50, indicators.ema_20 > indicators.ema_50, indicators.macd_histogram > 0])
        if bullish >= 2: indicators.trend_direction = "Bullish"
        elif bullish <= 0: indicators.trend_direction = "Bearish"
        else: indicators.trend_direction = "Mixed/Neutral"

        return df, indicators

    @staticmethod
    def _compute_sr(df: pd.DataFrame) -> tuple[float, float, float, float, float]:
        latest_close = df.iloc[-1]["close"]
        recent = df.tail(30)
        hi, lo = recent["high"].max(), recent["low"].min()

        pivot = (hi + lo + latest_close) / 3.0
        r1 = (2 * pivot) - lo
        s1 = (2 * pivot) - hi
        r2 = pivot + (hi - lo)
        s2 = pivot - (hi - lo)

        sw_s, sw_r = TechnicalAnalysisEngine._detect_swings(df)

        atr_val = df["atr"].iloc[-1] if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else (hi - lo) / 3.0

        valid_s = [s for s in [s1, sw_s, latest_close - atr_val * 1.5] if 0 < s < latest_close]
        valid_r = [r for r in [r1, sw_r, latest_close + atr_val * 1.5] if r > latest_close]

        support = max(valid_s) if valid_s else latest_close - atr_val * 1.5
        resistance = min(valid_r) if valid_r else latest_close + atr_val * 1.5

        support_2 = min([s for s in [s2, support - atr_val] if s > 0] or [support - atr_val * 2])
        resistance_2 = max([r2, resistance + atr_val])

        if support >= latest_close: support = latest_close - atr_val
        if resistance <= latest_close: resistance = latest_close + atr_val
        if support_2 >= support: support_2 = support - atr_val
        if resistance_2 <= resistance: resistance_2 = resistance + atr_val

        return support, resistance, pivot, support_2, resistance_2

    @staticmethod
    def _detect_swings(df: pd.DataFrame, lookback: int = 40, window: int = 5) -> tuple[float, float]:
        recent = df.tail(lookback)
        latest_close = df.iloc[-1]["close"]
        lows, highs = [], []
        for i in range(window, len(recent) - window):
            seg = recent.iloc[i - window: i + window + 1]
            if recent.iloc[i]["low"] == seg["low"].min():
                lows.append(recent.iloc[i]["low"])
            if recent.iloc[i]["high"] == seg["high"].max():
                highs.append(recent.iloc[i]["high"])
        vl = [s for s in lows if s < latest_close]
        vh = [r for r in highs if r > latest_close]
        return (max(vl) if vl else recent["low"].min()), (min(vh) if vh else recent["high"].max())


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
        logger.info(f"Gemini AI: {self.model_name}")

    def generate_analysis(self, df, indicators, timeframe):
        analysis = AIAnalysis()
        if df is None or len(df) < 10:
            analysis.raw_response = "Insufficient data"
            return self._fill_missing(analysis, indicators, df)

        latest, prev = df.iloc[-1], df.iloc[-2]
        prompt = self._build_prompt(latest, prev, indicators, timeframe, df)

        for attempt in range(1, self._max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024),
                )
                raw = response.text
                if not raw or len(raw.strip()) < 20:
                    if attempt < self._max_retries: time.sleep(self._retry_delay * attempt)
                    continue

                analysis.raw_response = raw
                analysis = self._parse_response(raw, analysis)
                analysis = self._fallback_parse(raw, analysis)
                analysis = self._fill_missing(analysis, indicators, df)
                if analysis.bias not in ("N/A", ""):
                    return analysis
            except Exception as e:
                logger.error(f"Gemini attempt {attempt}: {e}")
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)

        return self._fill_missing(AIAnalysis(raw_response="[Fallback]"), indicators, df)

    def _build_prompt(self, latest, prev, ind, timeframe, df):
        pc = latest["close"] - prev["close"]
        pcp = (pc / prev["close"]) * 100 if prev["close"] > 0 else 0
        l5 = ", ".join([f"{c:.2f}" for c in df["close"].tail(5).tolist()])
        sh, sl = df["high"].tail(20).max(), df["low"].tail(20).min()

        return (
            "You are a senior XAUUSD (Gold) technical analyst.\n"
            "IMPORTANT: Respond with ALL 8 fields. Each on its own line.\n"
            "NO markdown, NO asterisks, NO extra text.\n\n"
            f"=== XAU/USD ({timeframe}) ===\n"
            f"Price: {latest['close']:.2f} | Open: {latest['open']:.2f}\n"
            f"High: {latest['high']:.2f} | Low: {latest['low']:.2f}\n"
            f"Change: {pc:+.2f} ({pcp:+.3f}%)\n"
            f"Last 5: {l5}\n"
            f"Session: {sh:.2f} / {sl:.2f}\n\n"
            f"RSI(14): {ind.rsi:.2f} ({ind.rsi_interpretation})\n"
            f"EMA20: {ind.ema_20:.2f} | EMA50: {ind.ema_50:.2f} ({ind.ema_trend})\n"
            f"MACD: {ind.macd_line:.4f} / {ind.macd_signal:.4f} / {ind.macd_histogram:.4f} ({ind.macd_interpretation})\n"
            f"ATR(14): {ind.atr:.2f} ({ind.volatility_condition})\n"
            f"S1: {ind.support:.2f} | S2: {ind.support_2:.2f}\n"
            f"R1: {ind.resistance:.2f} | R2: {ind.resistance_2:.2f}\n"
            f"Pivot: {ind.pivot_point:.2f} | Trend: {ind.trend_direction}\n\n"
            "RESPOND EXACTLY:\n"
            "BIAS: Bullish/Bearish/Neutral\n"
            "TRADE: Buy/Sell/Wait\n"
            "ENTRY: price-price\n"
            "STOP_LOSS: price\n"
            "TP1: price\n"
            "TP2: price\n"
            "RISK: one sentence\n"
            "OUTLOOK: one-two sentences\n"
        )

    def _parse_response(self, text, analysis):
        if not text: return analysis
        text = text.replace("**", "").replace("*", "").replace("```", "").replace("##", "")
        key_map = {
            "BIAS": "bias", "MARKET BIAS": "bias", "DIRECTION": "bias",
            "TRADE": "trade_idea", "TRADE IDEA": "trade_idea", "ACTION": "trade_idea",
            "SIGNAL": "trade_idea", "RECOMMENDATION": "trade_idea",
            "ENTRY": "entry", "ENTRY ZONE": "entry", "ENTRY PRICE": "entry", "ENTRY RANGE": "entry",
            "STOP_LOSS": "stop_loss", "STOP LOSS": "stop_loss", "SL": "stop_loss",
            "STOPLOSS": "stop_loss", "STOP": "stop_loss",
            "TP1": "take_profit_1", "TAKE PROFIT 1": "take_profit_1", "TARGET 1": "take_profit_1",
            "TAKE_PROFIT_1": "take_profit_1", "TP 1": "take_profit_1", "FIRST TARGET": "take_profit_1",
            "TARGET1": "take_profit_1",
            "TP2": "take_profit_2", "TAKE PROFIT 2": "take_profit_2", "TARGET 2": "take_profit_2",
            "TAKE_PROFIT_2": "take_profit_2", "TP 2": "take_profit_2", "SECOND TARGET": "take_profit_2",
            "TARGET2": "take_profit_2",
            "RISK": "risk_note", "RISK NOTE": "risk_note", "RISK ASSESSMENT": "risk_note",
            "RISK LEVEL": "risk_note", "RISK WARNING": "risk_note",
            "OUTLOOK": "short_term_outlook", "SHORT TERM OUTLOOK": "short_term_outlook",
            "SHORT-TERM OUTLOOK": "short_term_outlook", "MARKET OUTLOOK": "short_term_outlook",
            "SUMMARY": "short_term_outlook",
        }
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line: continue
            ci = line.find(":")
            if ci == -1: continue
            k = line[:ci].strip().upper()
            v = line[ci + 1:].strip().strip("\"'- ")
            if not v: continue
            field = key_map.get(k)
            if field:
                setattr(analysis, field, v)
        return analysis

    def _fallback_parse(self, text, analysis):
        if not text: return analysis
        tc = text.replace("**", "").replace("*", "").replace("`", "").replace("#", "")
        patterns = {
            "bias": r"(?:BIAS|MARKET\s*BIAS)\s*[:=]\s*(.+?)(?:\n|$)",
            "trade_idea": r"(?:TRADE|ACTION|SIGNAL)\s*[:=]\s*(.+?)(?:\n|$)",
            "entry": r"(?:ENTRY)\s*[:=]\s*(.+?)(?:\n|$)",
            "stop_loss": r"(?:STOP[\s_]*LOSS|SL)\s*[:=]\s*(.+?)(?:\n|$)",
            "take_profit_1": r"(?:TP[\s_]*1|TARGET[\s_]*1)\s*[:=]\s*(.+?)(?:\n|$)",
            "take_profit_2": r"(?:TP[\s_]*2|TARGET[\s_]*2)\s*[:=]\s*(.+?)(?:\n|$)",
            "risk_note": r"(?:RISK)\s*[:=]\s*(.+?)(?:\n|$)",
            "short_term_outlook": r"(?:OUTLOOK|SUMMARY)\s*[:=]\s*(.+?)(?:\n|$)",
        }
        for field, pat in patterns.items():
            if getattr(analysis, field, "N/A") != "N/A": continue
            m = re.search(pat, tc, re.IGNORECASE)
            if m:
                v = m.group(1).strip().strip("\"'- ")
                if v and v.upper() != "N/A":
                    setattr(analysis, field, v)
        return analysis

    def _fill_missing(self, analysis, indicators, df):
        if df is None or len(df) < 2:
            return analysis
        close = df.iloc[-1]["close"]
        atr = indicators.atr if indicators.atr > 0 else 5.0

        if analysis.bias == "N/A": analysis.bias = indicators.trend_direction
        if analysis.trade_idea == "N/A":
            if "bullish" in analysis.bias.lower(): analysis.trade_idea = "Buy"
            elif "bearish" in analysis.bias.lower(): analysis.trade_idea = "Sell"
            else: analysis.trade_idea = "Wait"

        buy = "buy" in analysis.trade_idea.lower()
        sell = "sell" in analysis.trade_idea.lower()

        if analysis.entry == "N/A":
            if buy: analysis.entry = f"{close - atr * 0.3:.2f}-{close:.2f}"
            elif sell: analysis.entry = f"{close:.2f}-{close + atr * 0.3:.2f}"
            else: analysis.entry = f"Wait near {close:.2f}"
        if analysis.stop_loss == "N/A":
            if buy: analysis.stop_loss = f"{indicators.support - atr * 0.5:.2f}"
            elif sell: analysis.stop_loss = f"{indicators.resistance + atr * 0.5:.2f}"
            else: analysis.stop_loss = f"{indicators.support:.2f}"
        if analysis.take_profit_1 == "N/A":
            if buy: analysis.take_profit_1 = f"{close + atr * 1.5:.2f}"
            elif sell: analysis.take_profit_1 = f"{close - atr * 1.5:.2f}"
            else: analysis.take_profit_1 = f"{indicators.resistance:.2f}"
        if analysis.take_profit_2 == "N/A":
            if buy: analysis.take_profit_2 = f"{close + atr * 2.5:.2f}"
            elif sell: analysis.take_profit_2 = f"{close - atr * 2.5:.2f}"
            else: analysis.take_profit_2 = f"{indicators.resistance_2:.2f}"
        if analysis.risk_note == "N/A":
            analysis.risk_note = (
                f"{indicators.volatility_condition}. ATR: {atr:.2f}. "
                f"RSI: {indicators.rsi:.1f} ({indicators.rsi_interpretation})."
            )
        if analysis.short_term_outlook == "N/A":
            pos = "resistance" if close > indicators.pivot_point else "support"
            analysis.short_term_outlook = (
                f"EMA: {indicators.ema_trend}. Near {pos}. "
                f"MACD: {indicators.macd_interpretation.lower()}."
            )
        return analysis


gemini_analyzer = GeminiAnalyzer(GEMINI_API_KEY)


# =============================================================================
# MODULE 4: CHART GENERATOR
# =============================================================================
class ChartGenerator:

    @staticmethod
    def generate_chart(df, indicators, timeframe) -> Optional[io.BytesIO]:
        if df is None or len(df) < 20: return None
        try:
            plt.style.use(CHART_STYLE)
            plot_df = df.tail(60).copy()
            fig, axes = plt.subplots(3, 1, figsize=CHART_FIGSIZE,
                                     gridspec_kw={"height_ratios": [3, 1, 1]}, sharex=True)
            fig.suptitle(f"XAU/USD - {timeframe}", fontsize=16, fontweight="bold", color=COLOR_GOLD, y=0.98)

            ax1 = axes[0]
            ax1.plot(plot_df["datetime"], plot_df["close"], color=COLOR_WHITE, linewidth=1.5, label="Close", zorder=5)
            ax1.fill_between(plot_df["datetime"], plot_df["low"], plot_df["high"], alpha=0.1, color=COLOR_GOLD)
            for _, r in plot_df.iterrows():
                c = COLOR_GREEN if r["close"] >= r["open"] else COLOR_RED
                ax1.plot([r["datetime"]]*2, [r["low"], r["high"]], color=c, linewidth=0.8, alpha=0.6)
                ax1.plot([r["datetime"]]*2, [min(r["open"], r["close"]), max(r["open"], r["close"])], color=c, linewidth=2.5)
            if "ema_20" in plot_df: ax1.plot(plot_df["datetime"], plot_df["ema_20"], color=COLOR_BLUE, linewidth=1.2, linestyle="--", label=f"EMA20 ({indicators.ema_20:.2f})", alpha=0.9)
            if "ema_50" in plot_df: ax1.plot(plot_df["datetime"], plot_df["ema_50"], color=COLOR_ORANGE, linewidth=1.2, linestyle="--", label=f"EMA50 ({indicators.ema_50:.2f})", alpha=0.9)
            ax1.axhline(y=indicators.support, color=COLOR_GREEN_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"S1 ({indicators.support:.2f})")
            ax1.axhline(y=indicators.resistance, color=COLOR_RED_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"R1 ({indicators.resistance:.2f})")
            ax1.axhline(y=indicators.support_2, color=COLOR_GREEN_BRIGHT, linestyle=":", linewidth=0.6, alpha=0.4)
            ax1.axhline(y=indicators.resistance_2, color=COLOR_RED_BRIGHT, linestyle=":", linewidth=0.6, alpha=0.4)
            ax1.axhline(y=indicators.pivot_point, color=COLOR_GOLD, linestyle="-.", linewidth=0.7, alpha=0.5, label=f"Pivot ({indicators.pivot_point:.2f})")
            ax1.set_ylabel("Price (USD)", fontsize=10, color=COLOR_WHITE)
            ax1.legend(loc="upper left", fontsize=7, framealpha=0.3)
            ax1.grid(True, alpha=0.15)

            ax2 = axes[1]
            if "rsi" in plot_df:
                ax2.plot(plot_df["datetime"], plot_df["rsi"], color=COLOR_PURPLE, linewidth=1.5, label=f"RSI ({indicators.rsi:.1f})")
                ax2.fill_between(plot_df["datetime"], plot_df["rsi"], 50, where=(plot_df["rsi"] >= 50), alpha=0.2, color=COLOR_GREEN)
                ax2.fill_between(plot_df["datetime"], plot_df["rsi"], 50, where=(plot_df["rsi"] < 50), alpha=0.2, color=COLOR_RED)
                ax2.axhline(y=70, color=COLOR_RED_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=30, color=COLOR_GREEN_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=50, color=COLOR_GRAY, linestyle="-", linewidth=0.5, alpha=0.4)
            ax2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE); ax2.set_ylim(10, 90)
            ax2.legend(loc="upper left", fontsize=8, framealpha=0.3); ax2.grid(True, alpha=0.15)

            ax3 = axes[2]
            if "macd_line" in plot_df:
                ax3.plot(plot_df["datetime"], plot_df["macd_line"], color=COLOR_BLUE, linewidth=1.2, label="MACD")
                ax3.plot(plot_df["datetime"], plot_df["macd_signal"], color=COLOR_ORANGE, linewidth=1.2, label="Signal")
                hc = [COLOR_GREEN if v >= 0 else COLOR_RED for v in plot_df["macd_histogram"]]
                ax3.bar(plot_df["datetime"], plot_df["macd_histogram"], color=hc, alpha=0.5, width=0.6)
                ax3.axhline(y=0, color=COLOR_GRAY, linestyle="-", linewidth=0.5, alpha=0.4)
            ax3.set_ylabel("MACD", fontsize=10, color=COLOR_WHITE)
            ax3.legend(loc="upper left", fontsize=8, framealpha=0.3); ax3.grid(True, alpha=0.15)
            ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            plt.xticks(rotation=45, fontsize=8)

            fig.text(0.99, 0.01, f"Generated: {now_gmt7().strftime('%Y-%m-%d %H:%M GMT+7')}",
                     ha="right", va="bottom", fontsize=7, color=COLOR_GRAY, alpha=0.6)
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight",
                        facecolor=fig.get_facecolor(), edgecolor="none")
            buf.seek(0); plt.close(fig)
            return buf
        except Exception as e:
            logger.error(f"Chart error: {e}"); plt.close("all"); return None


chart_gen = ChartGenerator()


# =============================================================================
# MODULE 5: TELEGRAM HELPERS
# =============================================================================

def get_session(user_id: int) -> UserSession:
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession()
    return user_sessions[user_id]


def _escape_md(text: str) -> str:
    if not isinstance(text, str): text = str(text)
    for ch in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(ch, "\\" + ch)
    return text


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def _track_user(update: Update):
    user = update.effective_user
    if user:
        db.update_user_info(user.id, user.username or "", user.first_name or "")


def _owner_link_md() -> str:
    """Generate a clickable owner link for MarkdownV2."""
    return f"[Contact Owner](tg://user?id={OWNER_ID})"


async def _check_credits(update: Update, command_name: str) -> bool:
    user_id = update.effective_user.id
    allowed, remaining, limit = db.check_and_use_credit(user_id)

    if not allowed:
        is_prem = db.is_premium(user_id)
        tier = "Premium" if is_prem else "Free"
        owner_link = _owner_link_md()

        msg = (
            f"\u26d4 *Daily Limit Reached*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"Your *{_escape_md(tier)}* plan allows *{limit}* commands/day\\.\n"
            f"All credits used for today\\.\n\n"
            f"\U0001f504 Resets at: *12:00 AM GMT\\+7*\n"
        )
        if not is_prem:
            msg += (
                f"\n\u2b50 Want *{PREMIUM_DAILY_LIMIT}* commands/day\\?\n"
                f"\U0001f449 {owner_link} for Premium\\!"
            )

        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"User {user_id} blocked ({command_name}): limit {limit}")
        return False

    return True


# =============================================================================
# MODULE 6: PUBLIC COMMANDS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    uid = update.effective_user.id
    is_prem = db.is_premium(uid)
    owner_link = _owner_link_md()

    if uid == OWNER_ID:
        tier, limit_str = "Owner \U0001f451", "Unlimited"
    elif is_prem:
        tier, limit_str = "Premium \u2b50", str(PREMIUM_DAILY_LIMIT)
    else:
        tier, limit_str = "Free", str(NORMAL_DAILY_LIMIT)

    welcome = (
        "\U0001f947 *XAUUSD AI Analysis Bot v3\\.1*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "Welcome\\! AI\\-powered analysis for *Gold \\(XAU/USD\\)*\\.\n\n"
        f"\U0001f464 *Your Plan:* {_escape_md(tier)}\n"
        f"\U0001f4ca *Daily Limit:* {_escape_md(limit_str)} commands\n"
        f"\U0001f504 *Resets:* 12:00 AM GMT\\+7\n\n"
        "*Commands:*\n"
        "/price \\- Latest price\n"
        "/analysis \\- Full AI analysis\n"
        "/chart \\- Technical chart\n"
        "/timeframe \\- Change timeframe\n"
        "/credits \\- Check remaining credits\n"
        "/myid \\- Your user ID\n"
        "/help \\- All commands\n\n"
    )
    if uid != OWNER_ID and not is_prem:
        welcome += f"\u2b50 {owner_link} for Premium \\({PREMIUM_DAILY_LIMIT}/day\\)\\!\n\n"

    welcome += (
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "_Not financial advice\\. Trade responsibly\\._"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    uid = update.effective_user.id
    owner_link = _owner_link_md()

    txt = (
        "\U0001f539 *Bot Commands*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "*Market:*\n"
        "/price \\- Latest XAU/USD price\n"
        "/analysis \\- Full AI analysis\n"
        "/chart \\- Technical chart\n"
        "/timeframe `<5m|15m|1h|4h|1d>`\n\n"
        "*Account:*\n"
        "/credits \\- Check daily credits\n"
        "/myid \\- Show your user ID\n\n"
    )

    if is_owner(uid):
        txt += (
            "\U0001f451 *Owner Commands:*\n"
            "/addpremium `<user_id>` \\- Add premium\n"
            "/removepremium `<user_id>` \\- Remove premium\n"
            "/checkid `<user_id>` \\- Check user info\n"
            "/premiumlist \\- All premium users\n"
            "/botstats \\- Bot statistics\n"
            "/broadcast `<message>` \\- Announce to all\n\n"
        )
    else:
        txt += f"\u2b50 {owner_link} for Premium\\!\n\n"

    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    uid = update.effective_user.id
    is_prem = db.is_premium(uid)
    usage = db.get_usage(uid)
    used = usage["usage_count"]
    total_lt = usage["total_lifetime"]
    owner_link = _owner_link_md()

    if uid == OWNER_ID:
        tier, remaining_str, limit_str = "Owner \U0001f451", "Unlimited", "\u221e"
        bar = "\u2588" * 10
    else:
        limit_num = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        tier = "Premium \u2b50" if is_prem else "Free"
        remaining = max(0, limit_num - used)
        remaining_str, limit_str = str(remaining), str(limit_num)
        filled = min(int((used / limit_num) * 10), 10) if limit_num > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (10 - filled)

    msg = (
        f"\U0001f4ca *Credit Status*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f464 *Plan:* {_escape_md(tier)}\n"
        f"\U0001f4b3 *Remaining:* {_escape_md(remaining_str)} / {_escape_md(limit_str)}\n"
        f"\U0001f4ca *Used Today:* {used}\n"
        f"\U0001f4c8 *Lifetime:* {total_lt}\n\n"
        f"`[{_escape_md(bar)}]`\n\n"
        f"\U0001f504 Resets at *12:00 AM GMT\\+7*\n"
    )
    if not is_prem and uid != OWNER_ID:
        msg += f"\n\u2b50 {owner_link} for Premium \\({PREMIUM_DAILY_LIMIT}/day\\)\\!"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    user = update.effective_user
    is_prem = db.is_premium(user.id)
    if user.id == OWNER_ID: role = "Owner \U0001f451"
    elif is_prem: role = "Premium \u2b50"
    else: role = "Free User"

    msg = (
        f"\U0001f4cb *Your Info*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f194 *User ID:* `{user.id}`\n"
        f"\U0001f464 *Name:* {_escape_md(user.first_name or 'N/A')}\n"
        f"\U0001f465 *Username:* @{_escape_md(user.username or 'N/A')}\n"
        f"\U0001f3ab *Role:* {_escape_md(role)}\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not await _check_credits(update, "price"): return

    await update.message.reply_text("Fetching latest XAU/USD price...")
    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        price_data = await loop.run_in_executor(None, td_client.fetch_current_price)
        if price_data is None:
            await update.message.reply_text("Failed to fetch price. Try again later.")
            return

        msg = (
            "\U0001f947 *XAU/USD \\- Live Price*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f4b0 *Price:* `${price_data['price']:,.2f}`\n"
            f"\U0001f550 *Time:*  `{price_data['timestamp']}`\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Price error: {e}")
        await update.message.reply_text("Error fetching price.")


async def cmd_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not await _check_credits(update, "analysis"): return

    session = get_session(update.effective_user.id)
    tf = session.timeframe
    loading = await update.message.reply_text(
        f"Generating AI analysis for XAU/USD ({tf.display_name})...\nThis may take a few seconds."
    )

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 50:
            await loading.edit_text("Failed to fetch market data. Try again.")
            return

        df, indicators = ta_engine.compute_indicators(df)
        latest = df.iloc[-1]
        ai = await loop.run_in_executor(None, gemini_analyzer.generate_analysis, df, indicators, tf.display_name)

        uid = update.effective_user.id
        usage = db.get_usage(uid)
        if uid == OWNER_ID:
            credit_line = "\U0001f451 Owner \\- Unlimited"
        else:
            is_prem = db.is_premium(uid)
            lim = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
            rem = max(0, lim - usage["usage_count"])
            credit_line = f"\U0001f4b3 Credits: {rem}/{lim} remaining"

        e = _escape_md
        now_str = e(now_gmt7().strftime("%Y-%m-%d %H:%M GMT+7"))

        msg = (
            f"\U0001f947 *XAU/USD Analysis \\({e(tf.display_name)}\\)*\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "\U0001f4ca *PRICE ACTION*\n"
            f"Price: `${latest['close']:,.2f}`\n"
            f"Open: `${latest['open']:,.2f}`\n"
            f"High: `${latest['high']:,.2f}`\n"
            f"Low:  `${latest['low']:,.2f}`\n\n"
            "\U0001f4c8 *TECHNICAL INDICATORS*\n"
            f"RSI \\(14\\): `{indicators.rsi}` \\- {e(indicators.rsi_interpretation)}\n"
            f"EMA 20: `{indicators.ema_20}` | EMA 50: `{indicators.ema_50}`\n"
            f"EMA Trend: {e(indicators.ema_trend)}\n"
            f"MACD: {e(indicators.macd_interpretation)}\n"
            f"ATR \\(14\\): `{indicators.atr}` \\- {e(indicators.volatility_condition)}\n\n"
            "\U0001f6e1 *KEY LEVELS*\n"
            f"R2: `${indicators.resistance_2:,.2f}`\n"
            f"R1: `${indicators.resistance:,.2f}`\n"
            f"Pivot: `${indicators.pivot_point:,.2f}`\n"
            f"S1: `${indicators.support:,.2f}`\n"
            f"S2: `${indicators.support_2:,.2f}`\n\n"
            "\U0001f916 *AI ANALYSIS*\n"
            f"Bias:  {e(ai.bias)}\n"
            f"Trade: {e(ai.trade_idea)}\n"
            f"Entry: `{e(ai.entry)}`\n"
            f"SL:    `{e(ai.stop_loss)}`\n"
            f"TP1:   `{e(ai.take_profit_1)}`\n"
            f"TP2:   `{e(ai.take_profit_2)}`\n\n"
            f"\u26a0\ufe0f *Risk:* {e(ai.risk_note)}\n"
            f"\U0001f52e *Outlook:* {e(ai.short_term_outlook)}\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"_{now_str}_\n"
            f"_{credit_line}_\n"
            "_Not financial advice\\. Trade at your own risk\\._"
        )
        await loading.edit_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        await loading.edit_text("Error during analysis. Try again.")


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not await _check_credits(update, "chart"): return

    session = get_session(update.effective_user.id)
    tf = session.timeframe
    loading = await update.message.reply_text(f"Generating chart ({tf.display_name})...")

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 20:
            await loading.edit_text("Insufficient data for chart."); return
        df, indicators = ta_engine.compute_indicators(df)
        buf = await loop.run_in_executor(None, chart_gen.generate_chart, df, indicators, tf.display_name)
        if buf is None:
            await loading.edit_text("Chart generation failed."); return

        caption = (
            f"XAU/USD - {tf.display_name}\n"
            f"Price: ${df.iloc[-1]['close']:,.2f}\n"
            f"RSI: {indicators.rsi} | ATR: {indicators.atr}\n"
            f"S1: $${indicators.support:,.2f} | R1: $${indicators.resistance:,.2f}\n"
            f"{now_gmt7().strftime('%Y-%m-%d %H:%M GMT+7')}"
        )
        await loading.delete()
        await update.message.reply_photo(photo=buf, caption=caption)
    except Exception as e:
        logger.error(f"Chart error: {e}", exc_info=True)
        await loading.edit_text("Error generating chart.")


async def cmd_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    session = get_session(update.effective_user.id)
    if not context.args:
        msg = (
            f"Current: *{_escape_md(session.timeframe.display_name)}*\n\n"
            "*Usage:* `/timeframe <5m|15m|1h|4h|1d>`\n"
            "*Example:* `/timeframe 4h`"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
        return

    new_tf = Timeframe.from_user_input(context.args[0])
    if new_tf is None:
        await update.message.reply_text(
            f"Invalid\\. Options: `5m`, `15m`, `1h`, `4h`, `1d`",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    session.timeframe = new_tf
    await update.message.reply_text(
        f"Timeframe: *{_escape_md(new_tf.display_name)}*",
        parse_mode=ParseMode.MARKDOWN_V2)


# =============================================================================
# MODULE 7: OWNER-ONLY COMMANDS
# =============================================================================

async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/addpremium <user_id>`\n\n*Example:* `/addpremium 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID\\. Must be a number\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Check if already premium
    if db.is_premium(target_id):
        await update.message.reply_text(
            f"\u26a0\ufe0f User `{target_id}` is *already* Premium\\!",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    target_info = db.get_user_info(target_id)
    username = target_info["username"] if target_info else ""

    success = db.add_premium(target_id, update.effective_user.id, username)

    if success:
        # Verify it was actually saved
        verify = db.is_premium(target_id)
        if verify:
            msg = (
                f"\u2705 *Premium Added Successfully*\n\n"
                f"\U0001f194 User ID: `{target_id}`\n"
                f"\U0001f464 Username: @{_escape_md(username or 'Unknown')}\n"
                f"\U0001f4ca Daily Limit: *{PREMIUM_DAILY_LIMIT}* commands\n"
                f"\u2705 Verified in database: Yes"
            )
        else:
            msg = f"\u26a0\ufe0f Added but verification failed for `{target_id}`\\. Check database\\."
    else:
        msg = f"\u274c *Failed* to add premium for `{target_id}`\\. Check logs\\."

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"OWNER addpremium: target={target_id} success={success}")


async def cmd_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/removepremium <user_id>`\n\n*Example:* `/removepremium 123456789`",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID\\. Must be a number\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Check if currently premium
    was_premium = db.is_premium(target_id)
    if not was_premium:
        await update.message.reply_text(
            f"\u26a0\ufe0f User `{target_id}` is *not* in the premium list\\.",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    removed = db.remove_premium(target_id)

    if removed:
        verify = not db.is_premium(target_id)
        msg = (
            f"\u2705 *Premium Removed*\n\n"
            f"User `{target_id}` is now a *Free* user\\.\n"
            f"Daily limit: *{NORMAL_DAILY_LIMIT}* commands\n"
            f"\u2705 Verified removal: {'Yes' if verify else 'No'}"
        )
    else:
        msg = f"\u274c *Failed* to remove premium for `{target_id}`\\. Check logs\\."

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"OWNER removepremium: target={target_id} removed={removed}")


async def cmd_checkid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/checkid <user_id>`",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    is_prem = db.is_premium(target_id)
    usage = db.get_usage(target_id)
    info = db.get_user_info(target_id)

    if target_id == OWNER_ID:
        role, limit_s, rem_s = "Owner \U0001f451", "\u221e", "Unlimited"
    elif is_prem:
        role = "Premium \u2b50"
        limit_s = str(PREMIUM_DAILY_LIMIT)
        rem_s = str(max(0, PREMIUM_DAILY_LIMIT - usage["usage_count"]))
    else:
        role = "Free User"
        limit_s = str(NORMAL_DAILY_LIMIT)
        rem_s = str(max(0, NORMAL_DAILY_LIMIT - usage["usage_count"]))

    uname = info["username"] if info else "Unknown"
    fname = info["first_name"] if info else "Unknown"
    last_seen = info["last_seen"] if info else "Never"

    msg = (
        f"\U0001f50d *User Details*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f194 *ID:* `{target_id}`\n"
        f"\U0001f464 *Name:* {_escape_md(fname)}\n"
        f"\U0001f465 *Username:* @{_escape_md(uname)}\n"
        f"\U0001f3ab *Role:* {_escape_md(role)}\n\n"
        f"\U0001f4ca *Usage Today:*\n"
        f"  Used: {usage['usage_count']}\n"
        f"  Remaining: {_escape_md(rem_s)}\n"
        f"  Limit: {_escape_md(limit_s)}\n\n"
        f"\U0001f4c8 *Lifetime:* {usage['total_lifetime']}\n"
        f"\U0001f552 *Last Seen:* {_escape_md(last_seen)}\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_premiumlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return

    users = db.get_all_premium_users()
    if not users:
        await update.message.reply_text(
            "\U0001f4cb *Premium Users*\n\nNo premium users yet\\.",
            parse_mode=ParseMode.MARKDOWN_V2)
        return

    lines = ["\U0001f4cb *Premium Users*", "\u2501" * 27, ""]
    for i, u in enumerate(users, 1):
        uname = u["username"] or "Unknown"
        added = u["added_at"][:10] if u["added_at"] else "?"
        lines.append(
            f"{i}\\. `{u['user_id']}` \\- @{_escape_md(uname)} \\(added: {_escape_md(added)}\\)"
        )
    lines.append("")
    lines.append(f"*Total:* {len(users)} premium users")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_botstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return

    stats = db.get_stats()
    key_lines = []
    for i, key in enumerate(TWELVEDATA_KEYS):
        masked = key[:4] + "\\.\\.\\." + key[-4:] if len(key) > 8 else "\\*\\*\\*\\*"
        failed = i in td_client._key_failures
        status = "\u274c Failed" if failed else "\u2705 Active"
        key_lines.append(f"  Key {i+1}: `{masked}` {_escape_md(status)}")

    msg = (
        f"\U0001f4ca *Bot Statistics*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f465 *Users:*\n"
        f"  Total: {stats['total_users']}\n"
        f"  Premium: {stats['premium_users']}\n"
        f"  Active Today: {stats['active_today']}\n\n"
        f"\U0001f4c8 *Lifetime Usage:* {stats['total_lifetime_usage']}\n\n"
        f"\U0001f511 *API Keys \\({len(TWELVEDATA_KEYS)}\\):*\n"
        + "\n".join(key_lines) +
        f"\n\n\U0001f916 *AI Model:* `{_escape_md(GEMINI_MODEL)}`\n"
        f"\U0001f552 *Timezone:* GMT\\+7\n"
        f"\U0001f4be *DB:* PostgreSQL\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_user(update)
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("\u26d4 Owner-only command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    text = " ".join(context.args)
    user_ids = db.get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("No users to broadcast to.")
        return

    status_msg = await update.message.reply_text(f"Broadcasting to {len(user_ids)} users...")
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"\U0001f4e2 *Announcement*\n\n{text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(f"Broadcast done: {sent} sent, {failed} failed.")
    logger.info(f"Broadcast: {sent} sent, {failed} failed")


# =============================================================================
# MODULE 8: ERROR HANDLER
# =============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Unhandled: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("An error occurred. Try again later.")
        except Exception:
            pass


# =============================================================================
# MODULE 9: MAIN
# =============================================================================
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("price", "Latest XAU/USD price"),
        BotCommand("analysis", "Full AI technical analysis"),
        BotCommand("chart", "Technical analysis chart"),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check remaining credits"),
        BotCommand("myid", "Show your user ID"),
        BotCommand("help", "Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Commands registered")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  XAUUSD AI BOT v3.1 - Starting...")
    logger.info(f"  Owner: {OWNER_ID}")
    logger.info(f"  API Keys: {len(TWELVEDATA_KEYS)}")
    logger.info(f"  DB: PostgreSQL")
    logger.info(f"  Timezone: GMT+7")
    logger.info(f"  Free: {NORMAL_DAILY_LIMIT}/day | Premium: {PREMIUM_DAILY_LIMIT}/day")
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

    # Public
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("timeframe", cmd_timeframe))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Owner-only
    app.add_handler(CommandHandler("addpremium", cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("checkid", cmd_checkid))
    app.add_handler(CommandHandler("premiumlist", cmd_premiumlist))
    app.add_handler(CommandHandler("botstats", cmd_botstats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    app.add_error_handler(error_handler)

    logger.info("Bot polling... Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
