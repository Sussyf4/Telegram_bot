#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD AI ANALYSIS BOT v3.2                     ║
║                                                                    ║
║  Production-ready Telegram bot for XAU/USD technical analysis      ║
║  Features: Credits, Premium, Owner Controls, API Fallback          ║
║  Storage: PostgreSQL | Timezone: GMT+7 | SDK: google-genai         ║
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
from psycopg2 import pool

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
    MessageHandler,
    ContextTypes,
    filters,
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
DATABASE_URL = os.getenv("DATABASE_URL")

# Owner configuration
OWNER_ID = 5482019561
OWNER_USERNAME = "EK_HENG"
OWNER_LINK = f"https://t.me/{OWNER_USERNAME}"

# Credit limits
NORMAL_DAILY_LIMIT = 5
PREMIUM_DAILY_LIMIT = 25

# Timezone: GMT+7
GMT7 = timezone(timedelta(hours=7))

# API keys
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
        f"Missing required environment variables: {', '.join(_missing)}"
    )

# =============================================================================
# LOGGING
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
# MODULE 0: POSTGRESQL DATABASE MANAGER
# =============================================================================
class DatabaseManager:

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None
        self._connect()
        self._init_tables()
        logger.info("PostgreSQL database initialized")

    def _connect(self):
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=10, dsn=self.database_url,
            )
            logger.info("PostgreSQL connection pool created")
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            raise

    def _get_conn(self):
        try:
            conn = self._pool.getconn()
            conn.autocommit = False
            return conn
        except Exception:
            self._connect()
            conn = self._pool.getconn()
            conn.autocommit = False
            return conn

    def _put_conn(self, conn):
        try:
            self._pool.putconn(conn)
        except Exception:
            pass

    def _init_tables(self):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS premium_users (
                        user_id BIGINT PRIMARY KEY,
                        added_by BIGINT,
                        added_at TIMESTAMPTZ DEFAULT NOW(),
                        username TEXT DEFAULT ''
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_credits (
                        user_id BIGINT PRIMARY KEY,
                        usage_count INTEGER DEFAULT 0,
                        last_reset_date DATE,
                        total_lifetime_usage INTEGER DEFAULT 0
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_info (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT DEFAULT '',
                        first_name TEXT DEFAULT '',
                        last_seen TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Table init failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    def _today_gmt7(self) -> str:
        return datetime.now(GMT7).strftime("%Y-%m-%d")

    # ---- Premium ----

    def is_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM premium_users WHERE user_id = %s", (user_id,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"is_premium error: {e}")
            return False
        finally:
            self._put_conn(conn)

    def add_premium(self, user_id: int, added_by: int, username: str = "") -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO premium_users (user_id, added_by, added_at, username)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET added_by = EXCLUDED.added_by,
                                  added_at = NOW(),
                                  username = EXCLUDED.username
                """, (user_id, added_by, username))
            conn.commit()
            logger.info(f"Premium ADDED: {user_id} by {added_by}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"add_premium error: {e}")
            return False
        finally:
            self._put_conn(conn)

    def remove_premium(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM premium_users WHERE user_id = %s", (user_id,))
                removed = cur.rowcount > 0
            conn.commit()
            if removed:
                logger.info(f"Premium REMOVED: {user_id}")
            return removed
        except Exception as e:
            conn.rollback()
            logger.error(f"remove_premium error: {e}")
            return False
        finally:
            self._put_conn(conn)

    def get_all_premium_users(self) -> list[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, username, added_at FROM premium_users ORDER BY added_at DESC")
                rows = cur.fetchall()
            return [{"user_id": r[0], "username": r[1] or "", "added_at": str(r[2])[:19] if r[2] else ""} for r in rows]
        except Exception as e:
            logger.error(f"get_all_premium error: {e}")
            return []
        finally:
            self._put_conn(conn)

    # ---- Credits ----

    def get_usage(self, user_id: int) -> dict:
        conn = self._get_conn()
        today = self._today_gmt7()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT usage_count, last_reset_date, total_lifetime_usage FROM user_credits WHERE user_id = %s",
                    (user_id,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "INSERT INTO user_credits (user_id, usage_count, last_reset_date, total_lifetime_usage) VALUES (%s, 0, %s, 0)",
                        (user_id, today))
                    conn.commit()
                    return {"usage_count": 0, "last_reset_date": today, "total_lifetime": 0}
                usage_count, last_reset, total = row
                last_reset_str = str(last_reset) if last_reset else ""
                if last_reset_str != today:
                    cur.execute("UPDATE user_credits SET usage_count = 0, last_reset_date = %s WHERE user_id = %s", (today, user_id))
                    conn.commit()
                    usage_count = 0
                return {"usage_count": usage_count, "last_reset_date": today, "total_lifetime": total or 0}
        except Exception as e:
            conn.rollback()
            logger.error(f"get_usage error: {e}")
            return {"usage_count": 0, "last_reset_date": today, "total_lifetime": 0}
        finally:
            self._put_conn(conn)

    def use_credit(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_credits SET usage_count = usage_count + 1, total_lifetime_usage = total_lifetime_usage + 1 WHERE user_id = %s",
                    (user_id,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"use_credit error: {e}")
            return False
        finally:
            self._put_conn(conn)

    def check_and_use_credit(self, user_id: int) -> tuple[bool, int, int]:
        if user_id == OWNER_ID:
            return True, 999, 999
        is_prem = self.is_premium(user_id)
        limit = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        usage = self.get_usage(user_id)
        current = usage["usage_count"]
        if current >= limit:
            return False, 0, limit
        self.use_credit(user_id)
        return True, limit - current - 1, limit

    # ---- User Info ----

    def update_user_info(self, user_id: int, username: str = "", first_name: str = ""):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_info (user_id, username, first_name, last_seen)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (user_id)
                    DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, last_seen = NOW()
                """, (user_id, username, first_name))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"update_user_info error: {e}")
        finally:
            self._put_conn(conn)

    def get_user_info(self, user_id: int) -> Optional[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT username, first_name, last_seen FROM user_info WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
            if row:
                return {"username": row[0] or "", "first_name": row[1] or "", "last_seen": str(row[2])[:19] if row[2] else "Never"}
            return None
        except Exception as e:
            logger.error(f"get_user_info error: {e}")
            return None
        finally:
            self._put_conn(conn)

    def get_all_user_ids(self) -> list[int]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM user_info")
                return [r[0] for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_all_user_ids error: {e}")
            return []
        finally:
            self._put_conn(conn)

    def get_stats(self) -> dict:
        conn = self._get_conn()
        today = self._today_gmt7()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM user_credits")
                total_users = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM premium_users")
                premium_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM user_credits WHERE last_reset_date = %s AND usage_count > 0", (today,))
                active_today = cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(total_lifetime_usage), 0) FROM user_credits")
                total_usage = cur.fetchone()[0]
            return {"total_users": total_users, "premium_users": premium_count, "active_today": active_today, "total_lifetime_usage": total_usage}
        except Exception as e:
            logger.error(f"get_stats error: {e}")
            return {"total_users": 0, "premium_users": 0, "active_today": 0, "total_lifetime_usage": 0}
        finally:
            self._put_conn(conn)


db = DatabaseManager(DATABASE_URL)


# =============================================================================
# ENUMS & DATA CLASSES
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
            "5m": cls.M5, "5min": cls.M5, "15m": cls.M15, "15min": cls.M15,
            "1h": cls.H1, "60m": cls.H1, "4h": cls.H4, "240m": cls.H4,
            "1d": cls.D1, "daily": cls.D1, "d1": cls.D1, "1day": cls.D1,
        }
        return mapping.get(text.lower().strip())

    @property
    def display_name(self) -> str:
        return {"5min": "5 Min", "15min": "15 Min", "1h": "1 Hour", "4h": "4 Hour", "1day": "Daily"}.get(self.value, self.value)


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


# =============================================================================
# RATE LIMITER
# =============================================================================
class RateLimiter:
    def __init__(self, max_calls: int = 7, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self.calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                wait = self.period - (now - self.calls[0]) + 0.5
                await asyncio.sleep(wait)
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())


twelvedata_limiter = RateLimiter(max_calls=7, period=60.0)
user_sessions: dict[int, UserSession] = {}


# =============================================================================
# MODULE 1: TWELVE DATA CLIENT WITH FALLBACK
# =============================================================================
class TwelveDataClient:

    def __init__(self, api_keys: list[str]):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "XAUUSD-Bot/3.2"})
        self._key_failures: dict[int, float] = {}

    def _get_next_key(self) -> Optional[str]:
        now = time.time()
        for i in range(len(self.api_keys)):
            if i in self._key_failures and now - self._key_failures[i] < 60:
                continue
            elif i in self._key_failures:
                del self._key_failures[i]
            self.current_key_index = i
            return self.api_keys[i]
        self.current_key_index = 0
        return self.api_keys[0] if self.api_keys else None

    def _fail_key(self, idx: int):
        self._key_failures[idx] = time.time()

    def _is_quota_error(self, data: dict) -> bool:
        code = data.get("code", 0)
        msg = str(data.get("message", "")).lower()
        if code in (429, 401, 403):
            return True
        return any(w in msg for w in ["quota", "limit", "exceeded", "rate limit", "unauthorized"])

    def fetch_time_series(self, interval: str, outputsize: int = DEFAULT_OUTPUTSIZE) -> Optional[pd.DataFrame]:
        for _ in range(len(self.api_keys)):
            key = self._get_next_key()
            if not key:
                break
            kn = self.current_key_index + 1
            try:
                resp = self.session.get(f"{TWELVEDATA_BASE_URL}/time_series",
                    params={"symbol": SYMBOL, "interval": interval, "outputsize": outputsize, "apikey": key, "format": "JSON", "dp": 2},
                    timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if "code" in data:
                    if self._is_quota_error(data):
                        self._fail_key(self.current_key_index)
                        continue
                    elif data["code"] != 200:
                        continue
                if "values" not in data or not data["values"]:
                    return None
                df = pd.DataFrame(data["values"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                for c in ["open", "high", "low", "close"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
                df = df.sort_values("datetime").reset_index(drop=True)
                df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
                return df
            except requests.exceptions.HTTPError as e:
                s = e.response.status_code if e.response else 0
                if s in (429, 401, 403):
                    self._fail_key(self.current_key_index)
                    continue
                break
            except requests.exceptions.Timeout:
                self._fail_key(self.current_key_index)
            except requests.exceptions.ConnectionError:
                break
            except Exception:
                break
        return None

    def fetch_current_price(self) -> Optional[dict]:
        for _ in range(len(self.api_keys)):
            key = self._get_next_key()
            if not key:
                return None
            try:
                resp = self.session.get(f"{TWELVEDATA_BASE_URL}/price",
                    params={"symbol": SYMBOL, "apikey": key, "dp": 2}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "code" in data and self._is_quota_error(data):
                    self._fail_key(self.current_key_index)
                    continue
                if "price" not in data:
                    continue
                return {"price": float(data["price"]), "timestamp": datetime.now(GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7")}
            except requests.exceptions.HTTPError as e:
                s = e.response.status_code if e.response else 0
                if s in (429, 401, 403):
                    self._fail_key(self.current_key_index)
                    continue
                break
            except Exception:
                break
        return None


td_client = TwelveDataClient(TWELVEDATA_KEYS)


# =============================================================================
# MODULE 2: TECHNICAL ANALYSIS
# =============================================================================
class TAEngine:

    @staticmethod
    def compute(df: pd.DataFrame) -> tuple[pd.DataFrame, TechnicalIndicators]:
        ind = TechnicalIndicators()
        if df is None or len(df) < 50:
            return df, ind

        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
        df["ema_20"] = ta.trend.EMAIndicator(close=df["close"], window=20).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(close=df["close"], window=50).ema_indicator()
        m = ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd_line"] = m.macd()
        df["macd_signal"] = m.macd_signal()
        df["macd_histogram"] = m.macd_diff()
        df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

        s1, r1, piv, s2, r2 = TAEngine._sr(df)
        lat = df.iloc[-1]

        for a, c, d in [("rsi", "rsi", 2), ("ema_20", "ema_20", 2), ("ema_50", "ema_50", 2), ("atr", "atr", 2)]:
            setattr(ind, a, round(lat[c], d) if pd.notna(lat[c]) else 0.0)
        for a, c in [("macd_line", "macd_line"), ("macd_signal", "macd_signal"), ("macd_histogram", "macd_histogram")]:
            setattr(ind, a, round(lat[c], 4) if pd.notna(lat[c]) else 0.0)

        ind.support, ind.resistance, ind.pivot_point = round(s1, 2), round(r1, 2), round(piv, 2)
        ind.support_2, ind.resistance_2 = round(s2, 2), round(r2, 2)

        ind.rsi_interpretation = "Overbought" if ind.rsi >= 70 else "Bullish Momentum" if ind.rsi >= 60 else "Neutral" if ind.rsi >= 40 else "Bearish Momentum" if ind.rsi >= 30 else "Oversold"

        if ind.ema_20 > ind.ema_50:
            ind.ema_trend = "Strong Bullish" if lat["close"] > ind.ema_20 else "Bullish Crossover"
        elif ind.ema_20 < ind.ema_50:
            ind.ema_trend = "Strong Bearish" if lat["close"] < ind.ema_20 else "Bearish Crossover"
        else:
            ind.ema_trend = "Neutral"

        ind.macd_interpretation = "Positive" if ind.macd_histogram > 0 else "Negative" if ind.macd_histogram < 0 else "Neutral"

        atr_pct = (ind.atr / lat["close"] * 100) if lat["close"] > 0 else 0
        ind.volatility_condition = "High Volatility" if atr_pct > 1.0 else "Moderate Volatility" if atr_pct > 0.5 else "Low Volatility"

        b = sum([ind.rsi > 50, ind.ema_20 > ind.ema_50, ind.macd_histogram > 0])
        ind.trend_direction = "Bullish" if b >= 2 else "Bearish" if b == 0 else "Mixed/Neutral"

        return df, ind

    @staticmethod
    def _sr(df):
        close = df.iloc[-1]["close"]
        rec = df.tail(30)
        hi, lo = rec["high"].max(), rec["low"].min()
        piv = (hi + lo + close) / 3
        r1, s1 = (2 * piv) - lo, (2 * piv) - hi
        r2, s2 = piv + (hi - lo), piv - (hi - lo)

        sw_s, sw_r = TAEngine._swings(df)
        atr_val = df["atr"].iloc[-1] if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else (hi - lo) / 3

        vs = [x for x in [s1, sw_s, close - atr_val * 1.5] if 0 < x < close]
        vr = [x for x in [r1, sw_r, close + atr_val * 1.5] if x > close]
        sup = max(vs) if vs else close - atr_val * 1.5
        res = min(vr) if vr else close + atr_val * 1.5
        sup2 = min([x for x in [s2, sup - atr_val] if x > 0] or [sup - atr_val * 2])
        res2 = max([r2, res + atr_val])

        if sup >= close: sup = close - atr_val
        if res <= close: res = close + atr_val
        if sup2 >= sup: sup2 = sup - atr_val
        if res2 <= res: res2 = res + atr_val
        return sup, res, piv, sup2, res2

    @staticmethod
    def _swings(df, lookback=40, window=5):
        rec = df.tail(lookback)
        p = df.iloc[-1]["close"]
        lows, highs = [], []
        for i in range(window, len(rec) - window):
            seg = rec.iloc[i - window:i + window + 1]
            if rec.iloc[i]["low"] == seg["low"].min(): lows.append(rec.iloc[i]["low"])
            if rec.iloc[i]["high"] == seg["high"].max(): highs.append(rec.iloc[i]["high"])
        vl = [x for x in lows if x < p]
        vh = [x for x in highs if x > p]
        return (max(vl) if vl else rec["low"].min()), (min(vh) if vh else rec["high"].max())


ta_engine = TAEngine()


# =============================================================================
# MODULE 3: GEMINI AI
# =============================================================================
class GeminiAnalyzer:

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model = GEMINI_MODEL

    def analyze(self, df, indicators, timeframe) -> AIAnalysis:
        a = AIAnalysis()
        if df is None or len(df) < 10:
            return self._fill(a, indicators, df)

        lat, prev = df.iloc[-1], df.iloc[-2]
        prompt = self._prompt(lat, prev, indicators, timeframe, df)

        for attempt in range(1, 4):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024))
                raw = resp.text
                if not raw or len(raw.strip()) < 20:
                    time.sleep(2 * attempt)
                    continue
                a.raw_response = raw
                a = self._parse(raw, a)
                a = self._regex_parse(raw, a)
                a = self._fill(a, indicators, df)
                if a.bias not in ("N/A", ""):
                    return a
                time.sleep(2 * attempt)
            except Exception as e:
                logger.error(f"Gemini attempt {attempt}: {e}")
                time.sleep(2 * attempt)

        return self._fill(AIAnalysis(raw_response="[Fallback]"), indicators, df)

    def _prompt(self, lat, prev, ind, tf, df):
        chg = lat["close"] - prev["close"]
        pct = (chg / prev["close"] * 100) if prev["close"] > 0 else 0
        c5 = ", ".join(f"{c:.2f}" for c in df["close"].tail(5).tolist())
        sh, sl = df["high"].tail(20).max(), df["low"].tail(20).min()
        return (
            "You are a senior XAUUSD analyst. Respond with ALL 8 fields.\n\n"
            "RULES: Each field on own line. Exact prices (2 decimals). NO markdown.\n\n"
            f"=== XAU/USD ({tf}) ===\n"
            f"Price: {lat['close']:.2f} Open: {lat['open']:.2f} High: {lat['high']:.2f} Low: {lat['low']:.2f}\n"
            f"Change: {chg:+.2f} ({pct:+.3f}%) Last5: {c5} Range: {sh:.2f}/{sl:.2f}\n"
            f"RSI: {ind.rsi:.2f}({ind.rsi_interpretation}) EMA20: {ind.ema_20:.2f} EMA50: {ind.ema_50:.2f} {ind.ema_trend}\n"
            f"MACD: {ind.macd_line:.4f} Signal: {ind.macd_signal:.4f} Hist: {ind.macd_histogram:.4f}({ind.macd_interpretation})\n"
            f"ATR: {ind.atr:.2f}({ind.volatility_condition}) S1:{ind.support:.2f} S2:{ind.support_2:.2f} R1:{ind.resistance:.2f} R2:{ind.resistance_2:.2f} Pivot:{ind.pivot_point:.2f}\n\n"
            "RESPOND EXACTLY:\nBIAS: Bullish\nTRADE: Buy\nENTRY: 2350.00-2352.00\nSTOP_LOSS: 2340.00\nTP1: 2360.00\nTP2: 2370.00\nRISK: sentence.\nOUTLOOK: sentence.\n"
        )

    def _parse(self, text, a):
        text = text.replace("**", "").replace("*", "").replace("```", "").replace("##", "")
        km = {
            "BIAS": "bias", "MARKET BIAS": "bias", "DIRECTION": "bias",
            "TRADE": "trade_idea", "TRADE IDEA": "trade_idea", "ACTION": "trade_idea",
            "SIGNAL": "trade_idea", "RECOMMENDATION": "trade_idea",
            "ENTRY": "entry", "ENTRY ZONE": "entry", "ENTRY PRICE": "entry", "ENTRY RANGE": "entry",
            "STOP_LOSS": "stop_loss", "STOP LOSS": "stop_loss", "SL": "stop_loss", "STOPLOSS": "stop_loss",
            "TP1": "take_profit_1", "TAKE PROFIT 1": "take_profit_1", "TARGET 1": "take_profit_1", "TP 1": "take_profit_1",
            "TP2": "take_profit_2", "TAKE PROFIT 2": "take_profit_2", "TARGET 2": "take_profit_2", "TP 2": "take_profit_2",
            "RISK": "risk_note", "RISK NOTE": "risk_note", "RISK ASSESSMENT": "risk_note",
            "OUTLOOK": "short_term_outlook", "SHORT TERM OUTLOOK": "short_term_outlook", "MARKET OUTLOOK": "short_term_outlook", "SUMMARY": "short_term_outlook",
        }
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line: continue
            idx = line.find(":")
            if idx == -1: continue
            k = line[:idx].strip().upper()
            v = line[idx + 1:].strip().strip("\"'- ")
            if v and k in km:
                setattr(a, km[k], v)
        return a

    def _regex_parse(self, text, a):
        text = text.replace("**", "").replace("*", "").replace("`", "").replace("#", "")
        pats = {
            "bias": r"(?:BIAS|DIRECTION)\s*[:=]\s*(.+?)(?:\n|$)",
            "trade_idea": r"(?:TRADE|ACTION|SIGNAL)\s*[:=]\s*(.+?)(?:\n|$)",
            "entry": r"ENTRY(?:\s*\w*)?\s*[:=]\s*(.+?)(?:\n|$)",
            "stop_loss": r"(?:STOP[\s_]*LOSS|SL)\s*[:=]\s*(.+?)(?:\n|$)",
            "take_profit_1": r"(?:TP[\s_]*1|TARGET[\s_]*1)\s*[:=]\s*(.+?)(?:\n|$)",
            "take_profit_2": r"(?:TP[\s_]*2|TARGET[\s_]*2)\s*[:=]\s*(.+?)(?:\n|$)",
            "risk_note": r"RISK\s*[:=]\s*(.+?)(?:\n|$)",
            "short_term_outlook": r"OUTLOOK\s*[:=]\s*(.+?)(?:\n|$)",
        }
        for f, p in pats.items():
            if getattr(a, f) != "N/A": continue
            m = re.search(p, text, re.IGNORECASE)
            if m:
                v = m.group(1).strip().strip("\"'- ")
                if v and v.upper() != "N/A":
                    setattr(a, f, v)
        return a

    def _fill(self, a, ind, df):
        if df is None or len(df) < 2: return a
        close = df.iloc[-1]["close"]
        atr = ind.atr if ind.atr > 0 else 5.0
        if a.bias == "N/A": a.bias = ind.trend_direction
        if a.trade_idea == "N/A":
            b = a.bias.lower()
            a.trade_idea = "Buy" if "bullish" in b else "Sell" if "bearish" in b else "Wait"
        buy = "buy" in a.trade_idea.lower()
        sell = "sell" in a.trade_idea.lower()
        if a.entry == "N/A":
            a.entry = f"{close - atr * 0.3:.2f}-{close:.2f}" if buy else f"{close:.2f}-{close + atr * 0.3:.2f}" if sell else f"Wait near {close:.2f}"
        if a.stop_loss == "N/A":
            a.stop_loss = f"{ind.support - atr * 0.5:.2f}" if buy else f"{ind.resistance + atr * 0.5:.2f}" if sell else f"{ind.support:.2f}"
        if a.take_profit_1 == "N/A":
            a.take_profit_1 = f"{close + atr * 1.5:.2f}" if buy else f"{close - atr * 1.5:.2f}" if sell else f"{ind.resistance:.2f}"
        if a.take_profit_2 == "N/A":
            a.take_profit_2 = f"{close + atr * 2.5:.2f}" if buy else f"{close - atr * 2.5:.2f}" if sell else f"{ind.resistance_2:.2f}"
        if a.risk_note == "N/A":
            a.risk_note = f"{ind.volatility_condition}. ATR: {atr:.2f}. RSI: {ind.rsi:.1f} ({ind.rsi_interpretation})."
        if a.short_term_outlook == "N/A":
            pos = "resistance" if close > ind.pivot_point else "support"
            a.short_term_outlook = f"EMA: {ind.ema_trend}. Near {pos}. MACD {ind.macd_interpretation.lower()}."
        return a


gemini = GeminiAnalyzer(GEMINI_API_KEY)


# =============================================================================
# MODULE 4: CHART
# =============================================================================
class ChartGen:
    @staticmethod
    def make(df, ind, tf) -> Optional[io.BytesIO]:
        if df is None or len(df) < 20: return None
        try:
            plt.style.use(CHART_STYLE)
            p = df.tail(60).copy()
            fig, ax = plt.subplots(3, 1, figsize=CHART_FIGSIZE, gridspec_kw={"height_ratios": [3, 1, 1]}, sharex=True)
            fig.suptitle(f"XAU/USD - {tf}", fontsize=16, fontweight="bold", color=COLOR_GOLD, y=0.98)

            a1 = ax[0]
            a1.plot(p["datetime"], p["close"], color=COLOR_WHITE, linewidth=1.5, label="Close", zorder=5)
            a1.fill_between(p["datetime"], p["low"], p["high"], alpha=0.1, color=COLOR_GOLD)
            for _, r in p.iterrows():
                c = COLOR_GREEN if r["close"] >= r["open"] else COLOR_RED
                a1.plot([r["datetime"]] * 2, [r["low"], r["high"]], color=c, linewidth=0.8, alpha=0.6)
                a1.plot([r["datetime"]] * 2, [min(r["open"], r["close"]), max(r["open"], r["close"])], color=c, linewidth=2.5)
            if "ema_20" in p: a1.plot(p["datetime"], p["ema_20"], color=COLOR_BLUE, linewidth=1.2, linestyle="--", label=f"EMA20 ({ind.ema_20:.2f})", alpha=0.9)
            if "ema_50" in p: a1.plot(p["datetime"], p["ema_50"], color=COLOR_ORANGE, linewidth=1.2, linestyle="--", label=f"EMA50 ({ind.ema_50:.2f})", alpha=0.9)
            a1.axhline(y=ind.support, color=COLOR_GREEN_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"S1 ({ind.support:.2f})")
            a1.axhline(y=ind.resistance, color=COLOR_RED_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"R1 ({ind.resistance:.2f})")
            a1.axhline(y=ind.support_2, color=COLOR_GREEN_BRIGHT, linestyle=":", linewidth=0.6, alpha=0.4)
            a1.axhline(y=ind.resistance_2, color=COLOR_RED_BRIGHT, linestyle=":", linewidth=0.6, alpha=0.4)
            a1.axhline(y=ind.pivot_point, color=COLOR_GOLD, linestyle="-.", linewidth=0.7, alpha=0.5, label=f"Pivot ({ind.pivot_point:.2f})")
            a1.set_ylabel("Price (USD)", fontsize=10, color=COLOR_WHITE)
            a1.legend(loc="upper left", fontsize=7, framealpha=0.3)
            a1.grid(True, alpha=0.15)

            a2 = ax[1]
            if "rsi" in p:
                a2.plot(p["datetime"], p["rsi"], color=COLOR_PURPLE, linewidth=1.5, label=f"RSI ({ind.rsi:.1f})")
                a2.fill_between(p["datetime"], p["rsi"], 50, where=p["rsi"] >= 50, alpha=0.2, color=COLOR_GREEN)
                a2.fill_between(p["datetime"], p["rsi"], 50, where=p["rsi"] < 50, alpha=0.2, color=COLOR_RED)
                a2.axhline(y=70, color=COLOR_RED_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                a2.axhline(y=30, color=COLOR_GREEN_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
            a2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE)
            a2.set_ylim(10, 90)
            a2.legend(loc="upper left", fontsize=8, framealpha=0.3)
            a2.grid(True, alpha=0.15)

            a3 = ax[2]
            if "macd_line" in p:
                a3.plot(p["datetime"], p["macd_line"], color=COLOR_BLUE, linewidth=1.2, label="MACD")
                a3.plot(p["datetime"], p["macd_signal"], color=COLOR_ORANGE, linewidth=1.2, label="Signal")
                colors = [COLOR_GREEN if v >= 0 else COLOR_RED for v in p["macd_histogram"]]
                a3.bar(p["datetime"], p["macd_histogram"], color=colors, alpha=0.5, width=0.6)
                a3.axhline(y=0, color=COLOR_GRAY, linestyle="-", linewidth=0.5, alpha=0.4)
            a3.set_ylabel("MACD", fontsize=10, color=COLOR_WHITE)
            a3.legend(loc="upper left", fontsize=8, framealpha=0.3)
            a3.grid(True, alpha=0.15)
            a3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            plt.xticks(rotation=45, fontsize=8)

            fig.text(0.99, 0.01, f"Generated: {datetime.now(GMT7).strftime('%Y-%m-%d %H:%M GMT+7')}", ha="right", va="bottom", fontsize=7, color=COLOR_GRAY, alpha=0.6)
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            logger.error(f"Chart error: {e}")
            plt.close("all")
            return None


chart_gen = ChartGen()


# =============================================================================
# MODULE 5: HELPERS
# =============================================================================
def get_session(uid: int) -> UserSession:
    if uid not in user_sessions:
        user_sessions[uid] = UserSession()
    return user_sessions[uid]


def _e(text) -> str:
    if not isinstance(text, str): text = str(text)
    for c in "_*[]()~`>#+-=|{}.!":
        text = text.replace(c, "\\" + c)
    return text


def _track(update: Update):
    u = update.effective_user
    if u: db.update_user_info(u.id, u.username or "", u.first_name or "")


def _now7() -> str:
    return datetime.now(GMT7).strftime("%Y-%m-%d %H:%M GMT+7")


async def _check_credits(update: Update, cmd: str) -> bool:
    uid = update.effective_user.id
    ok, rem, lim = db.check_and_use_credit(uid)
    if not ok:
        prem = db.is_premium(uid)
        tier = "Premium" if prem else "Free"
        msg = (
            f"\u26d4 *Daily Limit Reached*\n\n"
            f"Your *{_e(tier)}* plan: *{lim}* commands/day\\.\n"
            f"All credits used\\.\n\n"
            f"\U0001f504 Resets at *midnight GMT\\+7*\n"
        )
        if not prem:
            msg += f"\n\u2b50 [Upgrade to Premium \\({PREMIUM_DAILY_LIMIT}/day\\)]({_e(OWNER_LINK)})"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return False
    return True


# =============================================================================
# MODULE 6: PUBLIC COMMANDS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    uid = update.effective_user.id
    prem = db.is_premium(uid)
    if uid == OWNER_ID:
        tier, lim = "Owner \U0001f451", "Unlimited"
    elif prem:
        tier, lim = "Premium \u2b50", str(PREMIUM_DAILY_LIMIT)
    else:
        tier, lim = "Free", str(NORMAL_DAILY_LIMIT)

    await update.message.reply_text(
        f"\U0001f947 *XAUUSD AI Bot v3\\.2*\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"AI analysis for *Gold \\(XAU/USD\\)*\\.\n\n"
        f"\U0001f464 *Plan:* {_e(tier)}\n"
        f"\U0001f4ca *Limit:* {_e(lim)} commands/day\n\n"
        f"/price \\- Live price\n"
        f"/analysis \\- AI analysis\n"
        f"/chart \\- Technical chart\n"
        f"/timeframe \\- Change TF\n"
        f"/credits \\- Check credits\n"
        f"/myid \\- Your ID\n"
        f"/help \\- All commands\n\n"
        f"\u2b50 [Get Premium \\({PREMIUM_DAILY_LIMIT}/day\\)]({_e(OWNER_LINK)})\n\n"
        f"_Not financial advice\\._",
        parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    uid = update.effective_user.id
    txt = (
        "\U0001f539 *Commands*\n\n"
        "/price \\- Live price\n"
        "/analysis \\- AI analysis\n"
        "/chart \\- Chart\n"
        "/timeframe `5m` `15m` `1h` `4h` `1d`\n"
        "/credits \\- Daily credits\n"
        "/myid \\- Your user ID\n\n"
        f"\u2b50 [Get Premium]({_e(OWNER_LINK)})\n"
    )
    if uid == OWNER_ID:
        txt += (
            "\n\U0001f451 *Owner:*\n"
            "/addprem <id> \\- Add premium\n"
            "/delprem <id> \\- Remove premium\n"
            "/checkid <id> \\- User info\n"
            "/premlist \\- Premium list\n"
            "/stats \\- Bot stats\n"
            "/broadcast <msg> \\- Announce\n"
        )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


async def cmd_credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    uid = update.effective_user.id
    prem = db.is_premium(uid)
    usage = db.get_usage(uid)
    used = usage["usage_count"]

    if uid == OWNER_ID:
        tier, rems, lims = "Owner \U0001f451", "Unlimited", "\u221e"
        bar = "\u2588" * 10
    else:
        tier = "Premium \u2b50" if prem else "Free"
        l = PREMIUM_DAILY_LIMIT if prem else NORMAL_DAILY_LIMIT
        r = max(0, l - used)
        rems, lims = str(r), str(l)
        f = min(int(used / l * 10), 10) if l > 0 else 0
        bar = "\u2588" * f + "\u2591" * (10 - f)

    msg = (
        f"\U0001f4ca *Credits*\n\n"
        f"\U0001f464 {_e(tier)}\n"
        f"\U0001f4b3 {_e(rems)} / {_e(lims)} remaining\n"
        f"Used today: {used} | Lifetime: {usage['total_lifetime']}\n\n"
        f"`[{_e(bar)}]`\n\n"
        f"Resets at *midnight GMT\\+7*\n"
    )
    if not prem and uid != OWNER_ID:
        msg += f"\n\u2b50 [Upgrade to Premium]({_e(OWNER_LINK)})"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    u = update.effective_user
    prem = db.is_premium(u.id)
    role = "Owner \U0001f451" if u.id == OWNER_ID else ("Premium \u2b50" if prem else "Free")
    await update.message.reply_text(
        f"\U0001f4cb *Your Info*\n\n"
        f"ID: `{u.id}`\n"
        f"Name: {_e(u.first_name or 'N/A')}\n"
        f"Username: @{_e(u.username or 'not set')}\n"
        f"Role: {_e(role)}",
        parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if not await _check_credits(update, "price"): return
    await update.message.reply_text("Fetching price...")
    try:
        await twelvedata_limiter.acquire()
        data = await asyncio.get_event_loop().run_in_executor(None, td_client.fetch_current_price)
        if not data:
            await update.message.reply_text("Failed to fetch price.")
            return
        await update.message.reply_text(
            f"\U0001f947 *XAU/USD*\n\n\U0001f4b0 `${data['price']:,.2f}`\n\U0001f550 `{data['timestamp']}`",
            parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Price: {e}")
        await update.message.reply_text("Error fetching price.")


async def cmd_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if not await _check_credits(update, "analysis"): return
    s = get_session(update.effective_user.id)
    tf = s.timeframe
    loading = await update.message.reply_text(f"Analyzing XAU/USD ({tf.display_name})...")

    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 50:
            await loading.edit_text("Failed to fetch data. Try again.")
            return

        df, ind = ta_engine.compute(df)
        lat = df.iloc[-1]
        ai = await loop.run_in_executor(None, gemini.analyze, df, ind, tf.display_name)

        uid = update.effective_user.id
        usage = db.get_usage(uid)
        if uid == OWNER_ID:
            cl = "\U0001f451 Owner"
        else:
            p = db.is_premium(uid)
            l = PREMIUM_DAILY_LIMIT if p else NORMAL_DAILY_LIMIT
            cl = f"\U0001f4b3 {max(0, l - usage['usage_count'])}/{l}"

        msg = (
            f"\U0001f947 *XAU/USD \\({_e(tf.display_name)}\\)*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f4ca *PRICE*\n"
            f"Close: `${lat['close']:,.2f}` Open: `${lat['open']:,.2f}`\n"
            f"High: `${lat['high']:,.2f}` Low: `${lat['low']:,.2f}`\n\n"
            f"\U0001f4c8 *INDICATORS*\n"
            f"RSI: `{ind.rsi}` {_e(ind.rsi_interpretation)}\n"
            f"EMA20: `{ind.ema_20}` EMA50: `{ind.ema_50}` {_e(ind.ema_trend)}\n"
            f"MACD: {_e(ind.macd_interpretation)} ATR: `{ind.atr}` {_e(ind.volatility_condition)}\n\n"
            f"\U0001f6e1 *LEVELS*\n"
            f"R2: `${ind.resistance_2:,.2f}` R1: `${ind.resistance:,.2f}`\n"
            f"Pivot: `${ind.pivot_point:,.2f}`\n"
            f"S1: `${ind.support:,.2f}` S2: `${ind.support_2:,.2f}`\n\n"
            f"\U0001f916 *AI ANALYSIS*\n"
            f"Bias: {_e(ai.bias)}\n"
            f"Trade: {_e(ai.trade_idea)}\n"
            f"Entry: `{_e(ai.entry)}`\n"
            f"SL: `{_e(ai.stop_loss)}`\n"
            f"TP1: `{_e(ai.take_profit_1)}`\n"
            f"TP2: `{_e(ai.take_profit_2)}`\n\n"
            f"\u26a0\ufe0f {_e(ai.risk_note)}\n"
            f"\U0001f52e {_e(ai.short_term_outlook)}\n\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"_{_e(_now7())}_ \\| _{cl}_\n"
            f"_Not financial advice\\._"
        )
        await loading.edit_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Analysis: {e}", exc_info=True)
        await loading.edit_text("Error. Try again.")


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if not await _check_credits(update, "chart"): return
    s = get_session(update.effective_user.id)
    tf = s.timeframe
    loading = await update.message.reply_text(f"Generating chart ({tf.display_name})...")
    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 20:
            await loading.edit_text("Insufficient data.")
            return
        df, ind = ta_engine.compute(df)
        buf = await loop.run_in_executor(None, chart_gen.make, df, ind, tf.display_name)
        if not buf:
            await loading.edit_text("Chart failed.")
            return
        await loading.delete()
        await update.message.reply_photo(photo=buf,
            caption=f"XAU/USD {tf.display_name}\nPrice: $${df.iloc[-1]['close']:,.2f}\nRSI: {ind.rsi} ATR: {ind.atr}\nS1: $${ind.support:,.2f} R1: ${ind.resistance:,.2f}\n{_now7()}")
    except Exception as e:
        logger.error(f"Chart: {e}", exc_info=True)
        await loading.edit_text("Chart error.")


async def cmd_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    s = get_session(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(
            f"Current: *{_e(s.timeframe.display_name)}*\n\nUsage: `/timeframe 4h`\nOptions: `5m` `15m` `1h` `4h` `1d`",
            parse_mode=ParseMode.MARKDOWN_V2)
        return
    tf = Timeframe.from_user_input(context.args[0])
    if not tf:
        await update.message.reply_text(f"Invalid\\. Use: `5m` `15m` `1h` `4h` `1d`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    s.timeframe = tf
    await update.message.reply_text(f"Timeframe: *{_e(tf.display_name)}*", parse_mode=ParseMode.MARKDOWN_V2)


# =============================================================================
# MODULE 7: OWNER COMMANDS (SHORT NAMES THAT WORK)
# =============================================================================

async def cmd_addprem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add premium user. Works with /addprem and /addpremium"""
    _track(update)
    uid = update.effective_user.id
    logger.info(f"addprem called by {uid} with args: {context.args}")

    if uid != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only command.")
        logger.warning(f"Non-owner {uid} tried /addprem")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/addprem 123456789\n/addpremium 123456789")
        return

    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"Invalid ID: {context.args[0]}\nMust be a number.")
        return

    logger.info(f"Owner adding premium for user {target}")
    info = db.get_user_info(target)
    uname = info["username"] if info else ""
    ok = db.add_premium(target, uid, uname)

    if ok:
        msg = (
            f"\u2705 *Premium Added*\n\n"
            f"User ID: `{target}`\n"
            f"Username: @{_e(uname or 'unknown')}\n"
            f"Limit: *{PREMIUM_DAILY_LIMIT}* commands/day"
        )
        # Try to notify the user
        try:
            await context.bot.send_message(
                chat_id=target,
                text=f"\u2b50 You've been upgraded to Premium!\nDaily limit: {PREMIUM_DAILY_LIMIT} commands/day\nEnjoy! \U0001f389")
            msg += "\n\n_User notified \\u2705_"
        except Exception as notify_err:
            logger.warning(f"Could not notify user {target}: {notify_err}")
            msg += "\n\n_Could not notify user_"
    else:
        msg = f"\u274c Failed to add premium for `{target}`"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"addprem result for {target}: {'OK' if ok else 'FAILED'}")


async def cmd_delprem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove premium user. Works with /delprem and /removepremium"""
    _track(update)
    uid = update.effective_user.id
    logger.info(f"delprem called by {uid} with args: {context.args}")

    if uid != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only command.")
        logger.warning(f"Non-owner {uid} tried /delprem")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/delprem 123456789\n/removepremium 123456789")
        return

    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"Invalid ID: {context.args[0]}\nMust be a number.")
        return

    logger.info(f"Owner removing premium for user {target}")
    removed = db.remove_premium(target)

    if removed:
        msg = (
            f"\u2705 *Premium Removed*\n\n"
            f"User `{target}` is now Free\\.\n"
            f"Limit: *{NORMAL_DAILY_LIMIT}* commands/day"
        )
        try:
            await context.bot.send_message(
                chat_id=target,
                text=f"\u26a0\ufe0f Your premium access has been removed.\nDaily limit: {NORMAL_DAILY_LIMIT} commands/day\nContact {OWNER_LINK} to renew.")
        except Exception:
            pass
    else:
        msg = f"\u26a0\ufe0f User `{target}` was not premium\\."

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"delprem result for {target}: {'removed' if removed else 'not found'}")


async def cmd_checkid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /checkid 123456789")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID.")
        return

    prem = db.is_premium(target)
    usage = db.get_usage(target)
    info = db.get_user_info(target)

    if target == OWNER_ID:
        role, lim, rem = "Owner", "\u221e", "Unlimited"
    elif prem:
        role, lim = "Premium", str(PREMIUM_DAILY_LIMIT)
        rem = str(max(0, PREMIUM_DAILY_LIMIT - usage["usage_count"]))
    else:
        role, lim = "Free", str(NORMAL_DAILY_LIMIT)
        rem = str(max(0, NORMAL_DAILY_LIMIT - usage["usage_count"]))

    await update.message.reply_text(
        f"\U0001f50d *User {target}*\n\n"
        f"Name: {_e(info['first_name'] if info else 'Unknown')}\n"
        f"Username: @{_e(info['username'] if info else 'unknown')}\n"
        f"Role: {_e(role)}\n"
        f"Used: {usage['usage_count']} Remaining: {_e(rem)}/{_e(lim)}\n"
        f"Lifetime: {usage['total_lifetime']}\n"
        f"Last seen: {_e(info['last_seen'] if info else 'Never')}",
        parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_premlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only.")
        return
    users = db.get_all_premium_users()
    if not users:
        await update.message.reply_text("No premium users yet.")
        return
    lines = ["\U0001f4cb *Premium Users*\n"]
    for i, u in enumerate(users, 1):
        lines.append(f"{i}\\. `{u['user_id']}` @{_e(u['username'] or '?')} \\({_e(u['added_at'][:10])}\\)")
    lines.append(f"\n*Total:* {len(users)}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only.")
        return
    s = db.get_stats()
    kl = []
    for i, k in enumerate(TWELVEDATA_KEYS):
        m = k[:4] + "..." + k[-4:] if len(k) > 8 else "****"
        st = "\u274c" if i in td_client._key_failures else "\u2705"
        kl.append(f"  Key{i + 1}: `{_e(m)}` {st}")
    await update.message.reply_text(
        f"\U0001f4ca *Bot Stats*\n\n"
        f"Users: {s['total_users']} \\| Premium: {s['premium_users']} \\| Active: {s['active_today']}\n"
        f"Lifetime usage: {s['total_lifetime_usage']}\n\n"
        f"API Keys:\n" + "\n".join(kl) + f"\n\nTime: `{_e(_now7())}`",
        parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner-only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text = " ".join(context.args)
    ids = db.get_all_user_ids()
    if not ids:
        await update.message.reply_text("No users.")
        return
    status = await update.message.reply_text(f"Broadcasting to {len(ids)} users...")
    sent, fail = 0, 0
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"\U0001f4e2 *Announcement*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await status.edit_text(f"Done: {sent} sent, {fail} failed.")


# =============================================================================
# MODULE 8: DEBUG - CATCH ALL MESSAGES (helps find issues)
# =============================================================================
async def debug_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every message for debugging command issues."""
    if update.message and update.message.text:
        logger.info(f"MSG from {update.effective_user.id}: {update.message.text}")


# =============================================================================
# MODULE 9: ERROR HANDLER
# =============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("Unexpected error. Try again.")
        except Exception:
            pass


# =============================================================================
# MODULE 10: MAIN
# =============================================================================
async def post_init(app: Application) -> None:
    commands = [
        BotCommand("start", "Welcome"),
        BotCommand("price", "Live XAU/USD price"),
        BotCommand("analysis", "AI technical analysis"),
        BotCommand("chart", "Technical chart"),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check credits"),
        BotCommand("myid", "Your user ID"),
        BotCommand("help", "All commands"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Commands registered")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  XAUUSD AI BOT v3.2")
    logger.info(f"  Owner: {OWNER_ID} (@{OWNER_USERNAME})")
    logger.info(f"  API Keys: {len(TWELVEDATA_KEYS)}")
    logger.info(f"  DB: PostgreSQL")
    logger.info(f"  TZ: GMT+7")
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

    # === PUBLIC COMMANDS ===
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("timeframe", cmd_timeframe))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # === OWNER COMMANDS - MULTIPLE ALIASES FOR EACH ===
    # Add premium: /addprem, /addpremium, /ap
    app.add_handler(CommandHandler("addprem", cmd_addprem))
    app.add_handler(CommandHandler("addpremium", cmd_addprem))
    app.add_handler(CommandHandler("ap", cmd_addprem))

    # Remove premium: /delprem, /removepremium, /rp
    app.add_handler(CommandHandler("delprem", cmd_delprem))
    app.add_handler(CommandHandler("removepremium", cmd_delprem))
    app.add_handler(CommandHandler("rp", cmd_delprem))

    # Check user: /checkid, /check
    app.add_handler(CommandHandler("checkid", cmd_checkid))
    app.add_handler(CommandHandler("check", cmd_checkid))

    # Premium list: /premlist, /premiumlist, /pl
    app.add_handler(CommandHandler("premlist", cmd_premlist))
    app.add_handler(CommandHandler("premiumlist", cmd_premlist))
    app.add_handler(CommandHandler("pl", cmd_premlist))

    # Stats: /stats, /botstats
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("botstats", cmd_stats))

    # Broadcast
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Debug: log all messages (low priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_all_messages))

    app.add_error_handler(error_handler)

    logger.info("Bot polling... Ctrl+C to stop.")
    logger.info("Owner commands: /addprem /delprem /checkid /premlist /stats /broadcast")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
