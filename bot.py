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
import psycopg2.pool

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
    filters,
    MessageHandler,
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
    raise EnvironmentError(f"Missing: {', '.join(_missing)}")

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
# DATABASE MANAGER - PostgreSQL
# =============================================================================
class DatabaseManager:

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None
        self._connect()
        self._init_tables()

    def _connect(self):
        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=self.database_url,
            )
            logger.info("PostgreSQL connected")
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
                        added_by BIGINT NOT NULL,
                        added_at TIMESTAMPTZ DEFAULT NOW(),
                        username TEXT DEFAULT ''
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_credits (
                        user_id BIGINT PRIMARY KEY,
                        usage_count INTEGER DEFAULT 0,
                        last_reset_date DATE,
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
            logger.info("DB tables ready")
        except Exception as e:
            conn.rollback()
            logger.error(f"DB init error: {e}")
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
                result = cur.fetchone() is not None
            logger.info(f"is_premium({user_id}) = {result}")
            return result
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
            logger.info(f"DB: Premium ADDED for {user_id} by {added_by}")

            # Verify it was saved
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM premium_users WHERE user_id = %s", (user_id,))
                verify = cur.fetchone()
                logger.info(f"DB: Verify premium {user_id}: {'FOUND' if verify else 'NOT FOUND'}")

            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"add_premium error: {e}")
            logger.error(traceback.format_exc())
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
            logger.info(f"DB: Premium REMOVED for {user_id}: {removed}")
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
            logger.info(f"DB: Found {len(rows)} premium users")
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
                    (user_id,)
                )
                row = cur.fetchone()

                if row is None:
                    cur.execute(
                        "INSERT INTO user_credits (user_id, usage_count, last_reset_date, total_lifetime_usage) VALUES (%s, 0, %s, 0)",
                        (user_id, today)
                    )
                    conn.commit()
                    return {"usage_count": 0, "last_reset_date": today, "total_lifetime": 0}

                usage_count, last_reset, total_lifetime = row
                last_reset_str = str(last_reset) if last_reset else ""

                if last_reset_str != today:
                    cur.execute(
                        "UPDATE user_credits SET usage_count = 0, last_reset_date = %s WHERE user_id = %s",
                        (today, user_id)
                    )
                    conn.commit()
                    usage_count = 0

                return {"usage_count": usage_count, "last_reset_date": today, "total_lifetime": total_lifetime or 0}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
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
                    (user_id,)
                )
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
                total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM premium_users")
                prem = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM user_credits WHERE last_reset_date = %s AND usage_count > 0", (today,))
                active = cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(total_lifetime_usage), 0) FROM user_credits")
                lifetime = cur.fetchone()[0]
            return {"total_users": total, "premium_users": prem, "active_today": active, "total_lifetime_usage": lifetime}
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
            "1d": cls.D1, "daily": cls.D1, "d1": cls.D1,
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


twelvedata_limiter = RateLimiter(7, 60.0)
user_sessions: dict[int, UserSession] = {}


# =============================================================================
# TWELVE DATA CLIENT WITH FALLBACK
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
            self._key_failures.pop(i, None)
            self.current_key_index = i
            return self.api_keys[i]
        self.current_key_index = 0
        return self.api_keys[0] if self.api_keys else None

    def _mark_failed(self, idx: int):
        self._key_failures[idx] = time.time()

    def _is_quota_error(self, data: dict) -> bool:
        code = data.get("code", 0)
        msg = str(data.get("message", "")).lower()
        if code in (429, 401, 403):
            return True
        return any(w in msg for w in ["quota", "limit", "exceeded", "too many", "rate limit"])

    def fetch_time_series(self, interval: str, outputsize: int = DEFAULT_OUTPUTSIZE) -> Optional[pd.DataFrame]:
        for _ in range(len(self.api_keys)):
            key = self._get_next_key()
            if not key:
                break
            try:
                resp = self.session.get(f"{TWELVEDATA_BASE_URL}/time_series", params={
                    "symbol": SYMBOL, "interval": interval, "outputsize": outputsize,
                    "apikey": key, "format": "JSON", "dp": 2,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if "code" in data and self._is_quota_error(data):
                    self._mark_failed(self.current_key_index)
                    continue
                if "values" not in data:
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
                if e.response and e.response.status_code in (429, 401, 403):
                    self._mark_failed(self.current_key_index)
                    continue
                break
            except requests.exceptions.Timeout:
                self._mark_failed(self.current_key_index)
            except Exception:
                break
        return None

    def fetch_current_price(self) -> Optional[dict]:
        for _ in range(len(self.api_keys)):
            key = self._get_next_key()
            if not key:
                return None
            try:
                resp = self.session.get(f"{TWELVEDATA_BASE_URL}/price", params={
                    "symbol": SYMBOL, "apikey": key, "dp": 2,
                }, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "code" in data and self._is_quota_error(data):
                    self._mark_failed(self.current_key_index)
                    continue
                if "price" in data:
                    return {"price": float(data["price"]), "timestamp": datetime.now(GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7")}
            except Exception:
                self._mark_failed(self.current_key_index)
        return None


td_client = TwelveDataClient(TWELVEDATA_KEYS)


# =============================================================================
# TECHNICAL ANALYSIS
# =============================================================================
class TechnicalAnalysisEngine:
    @staticmethod
    def compute_indicators(df):
        ind = TechnicalIndicators()
        if df is None or len(df) < 50:
            return df, ind
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
        df["ema_20"] = ta.trend.EMAIndicator(close=df["close"], window=20).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(close=df["close"], window=50).ema_indicator()
        macd = ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd_line"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_histogram"] = macd.macd_diff()
        df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

        s1, r1, piv, s2, r2 = TechnicalAnalysisEngine._compute_sr(df)
        latest = df.iloc[-1]

        ind.rsi = round(latest["rsi"], 2) if pd.notna(latest["rsi"]) else 0.0
        ind.ema_20 = round(latest["ema_20"], 2) if pd.notna(latest["ema_20"]) else 0.0
        ind.ema_50 = round(latest["ema_50"], 2) if pd.notna(latest["ema_50"]) else 0.0
        ind.macd_line = round(latest["macd_line"], 4) if pd.notna(latest["macd_line"]) else 0.0
        ind.macd_signal = round(latest["macd_signal"], 4) if pd.notna(latest["macd_signal"]) else 0.0
        ind.macd_histogram = round(latest["macd_histogram"], 4) if pd.notna(latest["macd_histogram"]) else 0.0
        ind.atr = round(latest["atr"], 2) if pd.notna(latest["atr"]) else 0.0
        ind.support, ind.resistance = round(s1, 2), round(r1, 2)
        ind.pivot_point, ind.support_2, ind.resistance_2 = round(piv, 2), round(s2, 2), round(r2, 2)

        ind.rsi_interpretation = "Overbought" if ind.rsi >= 70 else "Bullish Momentum" if ind.rsi >= 60 else "Neutral" if ind.rsi >= 40 else "Bearish Momentum" if ind.rsi >= 30 else "Oversold"

        if ind.ema_20 > ind.ema_50:
            ind.ema_trend = "Strong Bullish" if latest["close"] > ind.ema_20 else "Bullish Crossover"
        elif ind.ema_20 < ind.ema_50:
            ind.ema_trend = "Strong Bearish" if latest["close"] < ind.ema_20 else "Bearish Crossover"
        else:
            ind.ema_trend = "Neutral"

        ind.macd_interpretation = "Positive" if ind.macd_histogram > 0 else "Negative" if ind.macd_histogram < 0 else "Neutral"
        atr_pct = (ind.atr / latest["close"] * 100) if latest["close"] > 0 else 0
        ind.volatility_condition = "High Volatility" if atr_pct > 1.0 else "Moderate Volatility" if atr_pct > 0.5 else "Low Volatility"
        bull = sum([ind.rsi > 50, ind.ema_20 > ind.ema_50, ind.macd_histogram > 0])
        ind.trend_direction = "Bullish" if bull >= 2 else "Bearish" if bull == 0 else "Mixed/Neutral"
        return df, ind

    @staticmethod
    def _compute_sr(df):
        close = df.iloc[-1]["close"]
        r = df.tail(30)
        hi, lo = r["high"].max(), r["low"].min()
        piv = (hi + lo + close) / 3
        r1, s1 = (2 * piv) - lo, (2 * piv) - hi
        r2, s2 = piv + (hi - lo), piv - (hi - lo)

        sw_s, sw_r = TechnicalAnalysisEngine._swings(df)
        atr = df["atr"].iloc[-1] if "atr" in df.columns and pd.notna(df["atr"].iloc[-1]) else (hi - lo) / 3

        vs = [x for x in [s1, sw_s, close - atr * 1.5] if 0 < x < close]
        vr = [x for x in [r1, sw_r, close + atr * 1.5] if x > close]
        sup = max(vs) if vs else close - atr * 1.5
        res = min(vr) if vr else close + atr * 1.5
        su2 = min([x for x in [s2, sup - atr] if x > 0] or [sup - atr * 2])
        re2 = max([r2, res + atr])
        if sup >= close: sup = close - atr
        if res <= close: res = close + atr
        if su2 >= sup: su2 = sup - atr
        if re2 <= res: re2 = res + atr
        return sup, res, piv, su2, re2

    @staticmethod
    def _swings(df, lookback=40, window=5):
        r = df.tail(lookback)
        p = df.iloc[-1]["close"]
        lows, highs = [], []
        for i in range(window, len(r) - window):
            seg = r.iloc[i - window: i + window + 1]
            if r.iloc[i]["low"] == seg["low"].min(): lows.append(r.iloc[i]["low"])
            if r.iloc[i]["high"] == seg["high"].max(): highs.append(r.iloc[i]["high"])
        vl = [s for s in lows if s < p]
        vh = [h for h in highs if h > p]
        return (max(vl) if vl else r["low"].min()), (min(vh) if vh else r["high"].max())


ta_engine = TechnicalAnalysisEngine()


# =============================================================================
# GEMINI AI
# =============================================================================
class GeminiAnalyzer:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = GEMINI_MODEL

    def generate_analysis(self, df, indicators, timeframe) -> AIAnalysis:
        a = AIAnalysis()
        if df is None or len(df) < 10:
            return self._fill(a, indicators, df)
        latest, prev = df.iloc[-1], df.iloc[-2]
        prompt = self._prompt(latest, prev, indicators, timeframe, df)
        for attempt in range(1, 4):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024),
                )
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
            except Exception as e:
                logger.error(f"Gemini attempt {attempt}: {e}")
                time.sleep(2 * attempt)
        return self._fill(AIAnalysis(raw_response="[Fallback]"), indicators, df)

    def _prompt(self, latest, prev, ind, tf, df):
        chg = latest["close"] - prev["close"]
        pct = (chg / prev["close"] * 100) if prev["close"] > 0 else 0
        c5 = ", ".join(f"{c:.2f}" for c in df["close"].tail(5))
        return (
            "You are a senior XAUUSD analyst. Respond with ALL 8 fields.\n"
            "RULES: Each on own line, exact prices 2dp, NO markdown.\n\n"
            f"XAU/USD ({tf}) | Price: {latest['close']:.2f} | Chg: {chg:+.2f} ({pct:+.3f}%)\n"
            f"OHLC: {latest['open']:.2f}/{latest['high']:.2f}/{latest['low']:.2f}/{latest['close']:.2f}\n"
            f"Last5: {c5}\n"
            f"RSI: {ind.rsi:.2f} ({ind.rsi_interpretation}) | EMA20: {ind.ema_20:.2f} EMA50: {ind.ema_50:.2f} ({ind.ema_trend})\n"
            f"MACD: {ind.macd_histogram:.4f} ({ind.macd_interpretation}) | ATR: {ind.atr:.2f} ({ind.volatility_condition})\n"
            f"S1: {ind.support:.2f} S2: {ind.support_2:.2f} | R1: {ind.resistance:.2f} R2: {ind.resistance_2:.2f} | Pivot: {ind.pivot_point:.2f}\n"
            f"Trend: {ind.trend_direction}\n\n"
            "RESPOND EXACTLY:\nBIAS: Bullish\nTRADE: Buy\nENTRY: 2350.00-2352.00\nSTOP_LOSS: 2340.00\nTP1: 2360.00\nTP2: 2370.00\nRISK: One sentence.\nOUTLOOK: One sentence.\n"
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
            "OUTLOOK": "short_term_outlook", "SHORT TERM OUTLOOK": "short_term_outlook", "MARKET OUTLOOK": "short_term_outlook",
        }
        for line in text.strip().split("\n"):
            line = line.strip()
            idx = line.find(":")
            if idx == -1: continue
            k, v = line[:idx].strip().upper(), line[idx + 1:].strip().strip("\"'- ")
            if v and k in km:
                setattr(a, km[k], v)
        return a

    def _regex_parse(self, text, a):
        text = text.replace("**", "").replace("*", "").replace("`", "").replace("#", "")
        pats = {
            "bias": r"(?:BIAS|DIRECTION)\s*[:=]\s*(.+?)(?:\n|$)",
            "trade_idea": r"(?:TRADE|ACTION|SIGNAL)\s*[:=]\s*(.+?)(?:\n|$)",
            "entry": r"ENTRY\s*[:=]\s*(.+?)(?:\n|$)",
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
        c = df.iloc[-1]["close"]
        atr = ind.atr if ind.atr > 0 else 5.0
        if a.bias == "N/A": a.bias = ind.trend_direction
        if a.trade_idea == "N/A":
            a.trade_idea = "Buy" if "bullish" in a.bias.lower() else "Sell" if "bearish" in a.bias.lower() else "Wait"
        buy = "buy" in a.trade_idea.lower()
        sell = "sell" in a.trade_idea.lower()
        if a.entry == "N/A":
            a.entry = f"{c - atr * 0.3:.2f}-{c:.2f}" if buy else f"{c:.2f}-{c + atr * 0.3:.2f}" if sell else f"Wait near {c:.2f}"
        if a.stop_loss == "N/A":
            a.stop_loss = f"{ind.support - atr * 0.5:.2f}" if buy else f"{ind.resistance + atr * 0.5:.2f}" if sell else f"{ind.support:.2f}"
        if a.take_profit_1 == "N/A":
            a.take_profit_1 = f"{c + atr * 1.5:.2f}" if buy else f"{c - atr * 1.5:.2f}" if sell else f"{ind.resistance:.2f}"
        if a.take_profit_2 == "N/A":
            a.take_profit_2 = f"{c + atr * 2.5:.2f}" if buy else f"{c - atr * 2.5:.2f}" if sell else f"{ind.resistance_2:.2f}"
        if a.risk_note == "N/A":
            a.risk_note = f"{ind.volatility_condition}. ATR: {atr:.2f}. RSI: {ind.rsi:.1f} ({ind.rsi_interpretation})."
        if a.short_term_outlook == "N/A":
            a.short_term_outlook = f"EMA: {ind.ema_trend}. MACD {ind.macd_interpretation.lower()}."
        return a


gemini_analyzer = GeminiAnalyzer(GEMINI_API_KEY)


# =============================================================================
# CHART GENERATOR
# =============================================================================
class ChartGenerator:
    @staticmethod
    def generate_chart(df, indicators, timeframe) -> Optional[io.BytesIO]:
        if df is None or len(df) < 20: return None
        try:
            plt.style.use(CHART_STYLE)
            plot_df = df.tail(60).copy()
            fig, axes = plt.subplots(3, 1, figsize=CHART_FIGSIZE, gridspec_kw={"height_ratios": [3, 1, 1]}, sharex=True)
            fig.suptitle(f"XAU/USD - {timeframe}", fontsize=16, fontweight="bold", color=COLOR_GOLD, y=0.98)

            ax1 = axes[0]
            ax1.plot(plot_df["datetime"], plot_df["close"], color=COLOR_WHITE, linewidth=1.5, label="Close", zorder=5)
            ax1.fill_between(plot_df["datetime"], plot_df["low"], plot_df["high"], alpha=0.1, color=COLOR_GOLD)
            for _, r in plot_df.iterrows():
                c = COLOR_GREEN if r["close"] >= r["open"] else COLOR_RED
                ax1.plot([r["datetime"]] * 2, [r["low"], r["high"]], color=c, linewidth=0.8, alpha=0.6)
                ax1.plot([r["datetime"]] * 2, [min(r["open"], r["close"]), max(r["open"], r["close"])], color=c, linewidth=2.5)
            if "ema_20" in plot_df: ax1.plot(plot_df["datetime"], plot_df["ema_20"], color=COLOR_BLUE, linewidth=1.2, linestyle="--", label=f"EMA20", alpha=0.9)
            if "ema_50" in plot_df: ax1.plot(plot_df["datetime"], plot_df["ema_50"], color=COLOR_ORANGE, linewidth=1.2, linestyle="--", label=f"EMA50", alpha=0.9)
            ax1.axhline(y=indicators.support, color=COLOR_GREEN_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"S1 ({indicators.support:.2f})")
            ax1.axhline(y=indicators.resistance, color=COLOR_RED_BRIGHT, linestyle=":", linewidth=1, alpha=0.8, label=f"R1 ({indicators.resistance:.2f})")
            ax1.axhline(y=indicators.pivot_point, color=COLOR_GOLD, linestyle="-.", linewidth=0.7, alpha=0.5, label=f"Pivot")
            ax1.set_ylabel("Price", fontsize=10, color=COLOR_WHITE)
            ax1.legend(loc="upper left", fontsize=7, framealpha=0.3)
            ax1.grid(True, alpha=0.15)

            ax2 = axes[1]
            if "rsi" in plot_df:
                ax2.plot(plot_df["datetime"], plot_df["rsi"], color=COLOR_PURPLE, linewidth=1.5, label=f"RSI ({indicators.rsi:.1f})")
                ax2.axhline(y=70, color=COLOR_RED_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
                ax2.axhline(y=30, color=COLOR_GREEN_BRIGHT, linestyle="--", linewidth=0.8, alpha=0.6)
            ax2.set_ylabel("RSI", fontsize=10, color=COLOR_WHITE)
            ax2.set_ylim(10, 90)
            ax2.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax2.grid(True, alpha=0.15)

            ax3 = axes[2]
            if "macd_line" in plot_df:
                ax3.plot(plot_df["datetime"], plot_df["macd_line"], color=COLOR_BLUE, linewidth=1.2, label="MACD")
                ax3.plot(plot_df["datetime"], plot_df["macd_signal"], color=COLOR_ORANGE, linewidth=1.2, label="Signal")
                colors = [COLOR_GREEN if v >= 0 else COLOR_RED for v in plot_df["macd_histogram"]]
                ax3.bar(plot_df["datetime"], plot_df["macd_histogram"], color=colors, alpha=0.5, width=0.6)
            ax3.set_ylabel("MACD", fontsize=10, color=COLOR_WHITE)
            ax3.legend(loc="upper left", fontsize=8, framealpha=0.3)
            ax3.grid(True, alpha=0.15)
            ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            plt.xticks(rotation=45, fontsize=8)
            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            logger.error(f"Chart error: {e}")
            plt.close("all")
            return None


chart_gen = ChartGenerator()


# =============================================================================
# HELPERS
# =============================================================================
def get_session(uid: int) -> UserSession:
    if uid not in user_sessions:
        user_sessions[uid] = UserSession()
    return user_sessions[uid]


def _e(text) -> str:
    if not isinstance(text, str): text = str(text)
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


def _track(update: Update):
    u = update.effective_user
    if u: db.update_user_info(u.id, u.username or "", u.first_name or "")


def _now_str() -> str:
    return datetime.now(GMT7).strftime("%Y-%m-%d %H:%M GMT+7")


async def _check_credits(update: Update, cmd: str) -> bool:
    uid = update.effective_user.id
    ok, rem, lim = db.check_and_use_credit(uid)
    if not ok:
        is_prem = db.is_premium(uid)
        tier = "Premium" if is_prem else "Free"
        msg = (
            f"\u26d4 *Daily Limit Reached*\n\n"
            f"*{_e(tier)}* plan: *{lim}* commands/day\\.\n"
            f"All credits used today\\.\n\n"
            f"\U0001f504 Resets at *midnight GMT\\+7*\n"
        )
        if not is_prem:
            msg += f"\n\u2b50 [Get Premium \\({PREMIUM_DAILY_LIMIT}/day\\)]({_e(OWNER_LINK)})"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return False
    return True


# =============================================================================
# PUBLIC COMMANDS
# =============================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    uid = update.effective_user.id
    if uid == OWNER_ID:
        tier, lim = "Owner \U0001f451", "Unlimited"
    elif db.is_premium(uid):
        tier, lim = "Premium \u2b50", str(PREMIUM_DAILY_LIMIT)
    else:
        tier, lim = "Free", str(NORMAL_DAILY_LIMIT)

    await update.message.reply_text(
        f"\U0001f947 *XAUUSD AI Bot v3\\.2*\n{'━' * 27}\n\n"
        f"AI analysis for *Gold \\(XAU/USD\\)*\n\n"
        f"\U0001f464 *Plan:* {_e(tier)}\n\U0001f4ca *Limit:* {_e(lim)}/day\n\n"
        f"/price \\- Live price\n/analysis \\- AI analysis\n"
        f"/chart \\- Chart\n/credits \\- Credits\n/help \\- Help\n\n"
        f"\u2b50 [Upgrade to Premium]({_e(OWNER_LINK)})\n\n"
        f"_Not financial advice\\._",
        parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    uid = update.effective_user.id
    txt = (
        "\U0001f539 *Commands*\n━━━━━━━━━━━━━━━\n\n"
        "/price \\- Live price\n/analysis \\- AI analysis\n"
        "/chart \\- Chart\n/timeframe `5m` `15m` `1h` `4h` `1d`\n"
        "/credits \\- Check credits\n/myid \\- Your ID\n\n"
        f"\u2b50 [Get Premium \\({PREMIUM_DAILY_LIMIT}/day\\)]({_e(OWNER_LINK)})\n"
    )
    if uid == OWNER_ID:
        txt += (
            "\n\U0001f451 *Owner Commands:*\n"
            "/ap <id> \\- Add premium\n"
            "/rp <id> \\- Remove premium\n"
            "/ci <id> \\- Check user\n"
            "/pl \\- Premium list\n"
            "/stats \\- Bot stats\n"
            "/bc <msg> \\- Broadcast\n"
        )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


async def cmd_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    uid = update.effective_user.id
    usage = db.get_usage(uid)
    used = usage["usage_count"]

    if uid == OWNER_ID:
        tier, rem_s, lim_s, bar = "Owner \U0001f451", "Unlimited", "\u221e", "\u2588" * 10
    else:
        is_prem = db.is_premium(uid)
        tier = "Premium \u2b50" if is_prem else "Free"
        lim = PREMIUM_DAILY_LIMIT if is_prem else NORMAL_DAILY_LIMIT
        rem = max(0, lim - used)
        rem_s, lim_s = str(rem), str(lim)
        filled = min(int(used / lim * 10), 10) if lim > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (10 - filled)

    msg = (
        f"\U0001f4ca *Credits*\n━━━━━━━━━━━━━━━\n\n"
        f"\U0001f464 {_e(tier)}\n"
        f"Remaining: *{_e(rem_s)}* / {_e(lim_s)}\n"
        f"Used today: {used} | Lifetime: {usage['total_lifetime']}\n\n"
        f"`[{_e(bar)}]`\n\n"
        f"\U0001f504 Resets *midnight GMT\\+7*\n"
    )
    if uid != OWNER_ID and not db.is_premium(uid):
        msg += f"\n\u2b50 [Upgrade to Premium]({_e(OWNER_LINK)})"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    u = update.effective_user
    role = "Owner" if u.id == OWNER_ID else "Premium" if db.is_premium(u.id) else "Free"
    await update.message.reply_text(
        f"\U0001f4cb *Your Info*\n━━━━━━━━━━━━━━━\n\n"
        f"ID: `{u.id}`\nName: {_e(u.first_name or 'N/A')}\n"
        f"Username: @{_e(u.username or 'none')}\nRole: {_e(role)}\n",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            f"\U0001f947 *XAU/USD*\n━━━━━━━━━━━━━━━\n\n"
            f"\U0001f4b0 `${data['price']:,.2f}`\n\U0001f550 `{data['timestamp']}`\n",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.error(f"Price: {e}")
        await update.message.reply_text("Error fetching price.")


async def cmd_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    if not await _check_credits(update, "analysis"): return
    tf = get_session(update.effective_user.id).timeframe
    loading = await update.message.reply_text(f"Analyzing ({tf.display_name})...")
    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 50:
            await loading.edit_text("Failed to fetch data.")
            return
        df, ind = ta_engine.compute_indicators(df)
        latest = df.iloc[-1]
        ai = await loop.run_in_executor(None, gemini_analyzer.generate_analysis, df, ind, tf.display_name)

        uid = update.effective_user.id
        usage = db.get_usage(uid)
        if uid == OWNER_ID:
            cred = "\U0001f451 Owner"
        else:
            lim = PREMIUM_DAILY_LIMIT if db.is_premium(uid) else NORMAL_DAILY_LIMIT
            cred = f"\U0001f4b3 {max(0, lim - usage['usage_count'])}/{lim}"

        await loading.edit_text(
            f"\U0001f947 *XAU/USD \\({_e(tf.display_name)}\\)*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"\U0001f4ca *PRICE*\n"
            f"Close: `${latest['close']:,.2f}` | Open: `${latest['open']:,.2f}`\n"
            f"High: `${latest['high']:,.2f}` | Low: `${latest['low']:,.2f}`\n\n"
            f"\U0001f4c8 *INDICATORS*\n"
            f"RSI: `{ind.rsi}` {_e(ind.rsi_interpretation)}\n"
            f"EMA: `{ind.ema_20}` / `{ind.ema_50}` {_e(ind.ema_trend)}\n"
            f"MACD: {_e(ind.macd_interpretation)} | ATR: `{ind.atr}` {_e(ind.volatility_condition)}\n\n"
            f"\U0001f6e1 *LEVELS*\n"
            f"R2: `${ind.resistance_2:,.2f}` | R1: `${ind.resistance:,.2f}`\n"
            f"Pivot: `${ind.pivot_point:,.2f}`\n"
            f"S1: `${ind.support:,.2f}` | S2: `${ind.support_2:,.2f}`\n\n"
            f"\U0001f916 *AI ANALYSIS*\n"
            f"Bias: {_e(ai.bias)} | Trade: {_e(ai.trade_idea)}\n"
            f"Entry: `{_e(ai.entry)}`\n"
            f"SL: `{_e(ai.stop_loss)}` | TP1: `{_e(ai.take_profit_1)}` | TP2: `{_e(ai.take_profit_2)}`\n\n"
            f"\u26a0\ufe0f {_e(ai.risk_note)}\n"
            f"\U0001f52e {_e(ai.short_term_outlook)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_{_e(_now_str())} | {_e(cred)}_\n"
            f"_Not financial advice\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.error(f"Analysis: {e}", exc_info=True)
        await loading.edit_text("Error. Try again.")


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    if not await _check_credits(update, "chart"): return
    tf = get_session(update.effective_user.id).timeframe
    loading = await update.message.reply_text(f"Chart ({tf.display_name})...")
    try:
        await twelvedata_limiter.acquire()
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, td_client.fetch_time_series, tf.value, DEFAULT_OUTPUTSIZE)
        if df is None or len(df) < 20:
            await loading.edit_text("No data.")
            return
        df, ind = ta_engine.compute_indicators(df)
        buf = await loop.run_in_executor(None, chart_gen.generate_chart, df, ind, tf.display_name)
        if not buf:
            await loading.edit_text("Chart failed.")
            return
        await loading.delete()
        await update.message.reply_photo(photo=buf, caption=f"XAU/USD {tf.display_name} | ${df.iloc[-1]['close']:,.2f} | {_now_str()}")
    except Exception as e:
        logger.error(f"Chart: {e}", exc_info=True)
        await loading.edit_text("Error.")


async def cmd_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _track(update)
    s = get_session(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(f"Current: *{_e(s.timeframe.display_name)}*\n\nUse: `/timeframe 4h`\nOptions: `5m` `15m` `1h` `4h` `1d`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    tf = Timeframe.from_user_input(context.args[0])
    if not tf:
        await update.message.reply_text(f"Invalid\\. Use: `5m` `15m` `1h` `4h` `1d`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    s.timeframe = tf
    await update.message.reply_text(f"Timeframe: *{_e(tf.display_name)}*", parse_mode=ParseMode.MARKDOWN_V2)


# =============================================================================
# OWNER COMMANDS - USING SHORT ALIASES THAT DEFINITELY WORK
# =============================================================================

async def cmd_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /ap and /addpremium - Add premium user"""
    _track(update)
    uid = update.effective_user.id
    logger.info(f"=== ADD PREMIUM called by {uid} ===")

    if uid != OWNER_ID:
        logger.warning(f"Non-owner {uid} tried /addpremium")
        await update.message.reply_text("\u26d4 Owner only.")
        return

    if not context.args:
        logger.info("No args provided")
        await update.message.reply_text(
            "\u2139\ufe0f *Add Premium*\n\n"
            "Usage:\n"
            "`/ap 123456789`\n"
            "`/addpremium 123456789`\n",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    raw_arg = context.args[0]
    logger.info(f"Raw arg: '{raw_arg}'")

    try:
        target_id = int(raw_arg)
    except ValueError:
        logger.error(f"Invalid ID: '{raw_arg}'")
        await update.message.reply_text(f"Invalid ID: `{_e(raw_arg)}`\\. Must be a number\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    logger.info(f"Adding premium for target_id={target_id}")

    # Get username if we know them
    info = db.get_user_info(target_id)
    uname = info["username"] if info else ""
    logger.info(f"Target info: {info}")

    success = db.add_premium(target_id, uid, uname)
    logger.info(f"add_premium result: {success}")

    if success:
        # Double check
        is_now_premium = db.is_premium(target_id)
        logger.info(f"Verify is_premium({target_id}): {is_now_premium}")

        msg = (
            f"\u2705 *Premium Added\\!*\n\n"
            f"User: `{target_id}`\n"
            f"Username: @{_e(uname or 'unknown')}\n"
            f"Limit: *{PREMIUM_DAILY_LIMIT}* commands/day\n"
            f"Verified in DB: {'Yes' if is_now_premium else 'NO \\- ERROR'}"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

        # Try to notify the user
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"\u2b50 You've been upgraded to Premium!\n\nDaily limit: {PREMIUM_DAILY_LIMIT} commands/day\nEnjoy! \U0001f389",
            )
            logger.info(f"Notified user {target_id}")
        except Exception as notify_err:
            logger.warning(f"Could not notify {target_id}: {notify_err}")
            await update.message.reply_text(f"_Note: Could not notify user \\(they may need to /start the bot first\\)_", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(f"\u274c Failed to add premium for `{target_id}`\\. Check logs\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /rp and /removepremium - Remove premium user"""
    _track(update)
    uid = update.effective_user.id
    logger.info(f"=== REMOVE PREMIUM called by {uid} ===")

    if uid != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "\u2139\ufe0f *Remove Premium*\n\n"
            "Usage:\n"
            "`/rp 123456789`\n"
            "`/removepremium 123456789`\n",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    logger.info(f"Removing premium for {target_id}")

    # Check if they're actually premium first
    was_premium = db.is_premium(target_id)
    logger.info(f"Was premium: {was_premium}")

    removed = db.remove_premium(target_id)
    logger.info(f"remove_premium result: {removed}")

    if removed:
        msg = (
            f"\u2705 *Premium Removed*\n\n"
            f"User `{target_id}` is now Free\\.\n"
            f"Limit: *{NORMAL_DAILY_LIMIT}* commands/day"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"\u26a0\ufe0f Your premium has been removed.\nDaily limit: {NORMAL_DAILY_LIMIT} commands/day\n\nContact {OWNER_LINK} to renew.",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(
            f"\u26a0\ufe0f User `{target_id}` {'was not premium' if not was_premium else 'removal failed'}\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def cmd_check_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /ci and /checkid"""
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ci 123456789`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    prem = db.is_premium(tid)
    usage = db.get_usage(tid)
    info = db.get_user_info(tid)

    if tid == OWNER_ID: role, lim, rem = "Owner", "\u221e", "Unlimited"
    elif prem: role, lim, rem = "Premium", str(PREMIUM_DAILY_LIMIT), str(max(0, PREMIUM_DAILY_LIMIT - usage["usage_count"]))
    else: role, lim, rem = "Free", str(NORMAL_DAILY_LIMIT), str(max(0, NORMAL_DAILY_LIMIT - usage["usage_count"]))

    await update.message.reply_text(
        f"\U0001f50d *User {tid}*\n━━━━━━━━━━━━━━━\n\n"
        f"Name: {_e(info['first_name'] if info else 'Unknown')}\n"
        f"Username: @{_e(info['username'] if info else 'unknown')}\n"
        f"Role: {_e(role)} | Premium: {'Yes' if prem else 'No'}\n\n"
        f"Used: {usage['usage_count']} | Remaining: {_e(rem)}/{_e(lim)}\n"
        f"Lifetime: {usage['total_lifetime']}\n"
        f"Last seen: {_e(info['last_seen'] if info else 'Never')}\n",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_premium_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /pl and /premiumlist"""
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner only.")
        return

    users = db.get_all_premium_users()
    logger.info(f"Premium list: {len(users)} users found")

    if not users:
        await update.message.reply_text("\U0001f4cb *Premium Users*\n\nNone yet\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    lines = ["\U0001f4cb *Premium Users*", "━" * 20, ""]
    for i, u in enumerate(users, 1):
        lines.append(f"{i}\\. `{u['user_id']}` @{_e(u['username'] or '?')} \\({_e(u['added_at'][:10] if u['added_at'] else '?')}\\)")
    lines.append(f"\n*Total:* {len(users)}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /stats and /botstats"""
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner only.")
        return

    s = db.get_stats()
    key_lines = []
    for i, k in enumerate(TWELVEDATA_KEYS):
        masked = k[:4] + "\\.\\.\\." + k[-4:] if len(k) > 8 else "\\*\\*\\*"
        status = "\u274c" if i in td_client._key_failures else "\u2705"
        key_lines.append(f"  {status} Key {i + 1}: `{masked}`")

    await update.message.reply_text(
        f"\U0001f4ca *Bot Stats*\n━━━━━━━━━━━━━━━\n\n"
        f"Users: {s['total_users']} | Premium: {s['premium_users']} | Active: {s['active_today']}\n"
        f"Lifetime usage: {s['total_lifetime_usage']}\n\n"
        f"API Keys:\n" + "\n".join(key_lines) + f"\n\n"
        f"DB: PostgreSQL\nAI: `{_e(GEMINI_MODEL)}`\n"
        f"Time: `{_e(_now_str())}`\n",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /bc and /broadcast"""
    _track(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("\u26d4 Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/bc your message here`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    text = " ".join(context.args)
    ids = db.get_all_user_ids()
    if not ids:
        await update.message.reply_text("No users.")
        return

    status = await update.message.reply_text(f"Broadcasting to {len(ids)}...")
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
# DEBUG: CATCH ALL UNKNOWN COMMANDS
# =============================================================================
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log any command that doesn't match a handler"""
    cmd = update.message.text
    uid = update.effective_user.id
    logger.warning(f"UNKNOWN COMMAND: '{cmd}' from user {uid}")
    await update.message.reply_text(f"Unknown command: {cmd}\n\nType /help for available commands.")


# =============================================================================
# ERROR HANDLER
# =============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("Error occurred. Try again.")
        except Exception:
            pass


# =============================================================================
# MAIN
# =============================================================================
async def post_init(app: Application):
    cmds = [
        BotCommand("start", "Welcome"), BotCommand("price", "Live price"),
        BotCommand("analysis", "AI analysis"), BotCommand("chart", "Chart"),
        BotCommand("timeframe", "Change timeframe"), BotCommand("credits", "Credits"),
        BotCommand("myid", "Your ID"), BotCommand("help", "Help"),
    ]
    await app.bot.set_my_commands(cmds)
    logger.info("Commands registered")


def main():
    logger.info("=" * 60)
    logger.info("  XAUUSD AI BOT v3.2")
    logger.info(f"  Owner: {OWNER_ID} (@{OWNER_USERNAME})")
    logger.info(f"  Keys: {len(TWELVEDATA_KEYS)} | DB: PostgreSQL | TZ: GMT+7")
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

    # === OWNER COMMANDS - BOTH LONG AND SHORT ALIASES ===
    # /addpremium AND /ap both work
    app.add_handler(CommandHandler("addpremium", cmd_add_premium))
    app.add_handler(CommandHandler("ap", cmd_add_premium))

    # /removepremium AND /rp both work
    app.add_handler(CommandHandler("removepremium", cmd_remove_premium))
    app.add_handler(CommandHandler("rp", cmd_remove_premium))

    # /checkid AND /ci both work
    app.add_handler(CommandHandler("checkid", cmd_check_id))
    app.add_handler(CommandHandler("ci", cmd_check_id))

    # /premiumlist AND /pl both work
    app.add_handler(CommandHandler("premiumlist", cmd_premium_list))
    app.add_handler(CommandHandler("pl", cmd_premium_list))

    # /botstats AND /stats both work
    app.add_handler(CommandHandler("botstats", cmd_bot_stats))
    app.add_handler(CommandHandler("stats", cmd_bot_stats))

    # /broadcast AND /bc both work
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("bc", cmd_broadcast))

    # === CATCH UNKNOWN COMMANDS (DEBUG) ===
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    app.add_error_handler(error_handler)

    logger.info("Handlers registered:")
    logger.info("  Public: start, help, price, analysis, chart, timeframe, credits, myid")
    logger.info("  Owner: addpremium/ap, removepremium/rp, checkid/ci, premiumlist/pl, botstats/stats, broadcast/bc")
    logger.info("  Debug: unknown command catcher")
    logger.info("Polling started...")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
