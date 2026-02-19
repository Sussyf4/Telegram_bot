#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    XAUUSD & BTC/USD AI BOT v4.0                    ║
║                                                                    ║
║  Multi-symbol, technical + fundamental, interactive selection.     ║
║  HTML parse mode, async-safe, credit system, Railway deploy.       ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import logging
import asyncio
import time
from datetime import datetime, timezone
from html import escape as html_escape
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv
from telegram import (
    Update, BotCommand,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

import db
from credit_manager import (
    require_credit, OWNER_ID, OWNER_USERNAME, is_owner,
)
import admin_commands
from symbols import (
    SymbolConfig, SYMBOLS, DEFAULT_SYMBOL_KEY,
    get_symbol, get_all_symbol_keys,
    get_symbol_choices_text,
)
from market_data import MarketDataClient
from technical_engine import (
    AdvancedTechnicalEngine,
    AdvancedTechnicalIndicators,
)
from fundamental_engine import (
    FundamentalEngine, FundamentalData,
)
from ai_analyzer import EnhancedAIAnalyzer, AIAnalysis
from chart_generator import MultiSymbolChartGenerator

# =============================================================================
# CONFIG
# =============================================================================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_missing = []
for var in [
    "TELEGRAM_BOT_TOKEN", "TWELVEDATA_API_KEY",
    "GEMINI_API_KEY", "DATABASE_URL",
]:
    if not os.getenv(var):
        _missing.append(var)
if _missing:
    raise EnvironmentError(
        f"Missing: {', '.join(_missing)}"
    )

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    format=(
        "%(asctime)s | %(name)-20s | "
        "%(levelname)-8s | %(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
for noisy in [
    "httpx", "telegram.ext", "urllib3", "asyncpg",
]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("XAUUSD_Bot")

# =============================================================================
# GLOBALS
# =============================================================================
DEFAULT_OUTPUTSIZE = 100

md_client = MarketDataClient(TWELVEDATA_API_KEY)
ta_engine = AdvancedTechnicalEngine()
fund_engine = FundamentalEngine()
ai_analyzer = EnhancedAIAnalyzer(GEMINI_API_KEY)
chart_gen = MultiSymbolChartGenerator()


def h(text) -> str:
    if not isinstance(text, str):
        text = str(text)
    return html_escape(text, quote=False)


# =============================================================================
# TIMEFRAME
# =============================================================================
class Timeframe(Enum):
    M5 = "5min"
    M15 = "15min"
    H1 = "1h"
    H4 = "4h"
    D1 = "1day"

    @classmethod
    def from_user_input(
        cls, text: str
    ) -> Optional["Timeframe"]:
        mapping = {
            "5m": cls.M5, "5min": cls.M5,
            "15m": cls.M15, "15min": cls.M15,
            "1h": cls.H1, "60m": cls.H1,
            "4h": cls.H4, "240m": cls.H4,
            "1d": cls.D1, "daily": cls.D1,
            "d1": cls.D1, "1day": cls.D1,
        }
        return mapping.get(text.lower().strip())

    @property
    def display_name(self) -> str:
        return {
            "5min": "5 Min", "15min": "15 Min",
            "1h": "1 Hour", "4h": "4 Hour",
            "1day": "Daily",
        }.get(self.value, self.value)


# =============================================================================
# USER SESSION
# =============================================================================
@dataclass
class UserSession:
    timeframe: Timeframe = Timeframe.M15
    symbol_key: str = DEFAULT_SYMBOL_KEY
    last_request_time: float = 0.0


user_sessions: dict[int, UserSession] = {}


def get_session(user_id: int) -> UserSession:
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession()
    return user_sessions[user_id]


# =============================================================================
# RATE LIMITER
# =============================================================================
class RateLimiter:
    def __init__(
        self, max_calls: int = 7,
        period_seconds: float = 60.0,
    ):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            self.calls = [
                t for t in self.calls
                if now - t < self.period
            ]
            if len(self.calls) >= self.max_calls:
                oldest = self.calls[0]
                wait = self.period - (now - oldest) + 0.5
                await asyncio.sleep(wait)
                now = time.monotonic()
                self.calls = [
                    t for t in self.calls
                    if now - t < self.period
                ]
            self.calls.append(time.monotonic())
            return True


api_limiter = RateLimiter(max_calls=7, period_seconds=60)


# =============================================================================
# INLINE KEYBOARD: SYMBOL SELECTION
# =============================================================================
def build_symbol_keyboard(
    action: str,
) -> InlineKeyboardMarkup:
    """
    Build inline keyboard for symbol selection.
    action: 'price', 'analysis', 'chart', 'fundamental'
    """
    buttons = []
    for key, sym in SYMBOLS.items():
        buttons.append(
            InlineKeyboardButton(
                text=f"{sym.emoji} {sym.display_name}",
                callback_data=f"{action}:{key}",
            )
        )
    return InlineKeyboardMarkup([buttons])


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

async def cmd_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    user_data = await db.get_or_create_user(
        user.id, user.username
    )
    role = user_data["role"]
    limit = user_data["daily_limit"]

    if user.id == OWNER_ID and role != "owner":
        await db.set_role(user.id, "owner", 999999)
        role = "owner"

    if role == "owner":
        role_line = "👑 Role: <b>Owner</b> (Unlimited)"
    elif role == "premium":
        role_line = (
            f"💎 Role: <b>Premium</b> "
            f"({limit} cmds/day)"
        )
    else:
        role_line = (
            f"🆓 Role: <b>Free</b> "
            f"({limit} cmds/day)"
        )

    symbols_text = get_symbol_choices_text()

    welcome = (
        "🥇 <b>Multi-Asset AI Analysis Bot v4.0</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "AI-powered technical + fundamental analysis.\n\n"
        f"{role_line}\n\n"
        f"<b>Supported Assets:</b>\n{symbols_text}\n\n"
        "<b>Commands:</b>\n"
        "/price — Live price (select symbol)\n"
        "/analysis — Full AI technical analysis\n"
        "/chart — Professional chart\n"
        "/fundamental — Fundamental data + macro\n"
        "/fullreport — Combined tech + fundamental\n"
        "/timeframe — Change timeframe\n"
        "/credits — Check credits\n"
        "/checkid — Your account info\n"
        "/upgrade — Premium info\n"
        "/help — All commands\n\n"
        "Default: <b>XAU/USD • 15 Min</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Not financial advice.</i>"
    )
    await update.message.reply_text(
        welcome,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    symbols_text = get_symbol_choices_text()
    msg = (
        "🔹 <b>Bot Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>📊 Analysis:</b>\n"
        "/price — Live price "
        "<i>(1 credit)</i>\n"
        "/analysis — Full AI analysis "
        "<i>(1 credit)</i>\n"
        "/chart — Technical chart "
        "<i>(1 credit)</i>\n"
        "/fundamental — Fundamental data "
        "<i>(1 credit)</i>\n"
        "/fullreport — Combined tech+fundamental "
        "<i>(⭐ 4 credits)</i>\n\n"
        "<b>⚙️ Settings:</b>\n"
        "/timeframe &lt;tf&gt; — Change timeframe "
        "<i>(free)</i>\n\n"
        "<b>👤 Account:</b>\n"
        "/credits — Daily credits <i>(free)</i>\n"
        "/checkid — Account info <i>(free)</i>\n"
        "/upgrade — Premium upgrade <i>(free)</i>\n\n"
        f"<b>Symbols:</b>\n{symbols_text}\n\n"
        "<b>Timeframes:</b> "
        "<code>5m 15m 1h 4h 1d</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML
    )


# ──────────────────────────────────────────────────
# /price — asks which symbol first
# ──────────────────────────────────────────────────
@require_credit
async def cmd_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("price")
    await update.message.reply_text(
        "📈 <b>Select symbol for price:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────────
# /analysis — asks which symbol first
# ──────────────────────────────────────────────────
@require_credit
async def cmd_analysis(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("analysis")
    await update.message.reply_text(
        "🤖 <b>Select symbol for AI analysis:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────────
# /chart — asks which symbol first
# ──────────────────────────────────────────────────
@require_credit
async def cmd_chart(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("chart")
    await update.message.reply_text(
        "📉 <b>Select symbol for chart:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────────
# /fundamental — asks which symbol first
# ──────────────────────────────────────────────────
@require_credit
async def cmd_fundamental(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("fundamental")
    await update.message.reply_text(
        "📋 <b>Select symbol for fundamental data:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────────
# /fullreport — costs 4 credits
# ──────────────────────────────────────────────────
@require_credit(cost=4)
async def cmd_fullreport(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("fullreport")
    await update.message.reply_text(
        "📊 <b>Select symbol for full report</b>\n"
        "💡 <i>This command costs 4 credits.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =============================================================================
# CALLBACK QUERY HANDLER — processes symbol selection
# =============================================================================
async def handle_symbol_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if ":" not in data:
        return

    action, symbol_key = data.split(":", 1)
    symbol = get_symbol(symbol_key)
    if symbol is None:
        await query.edit_message_text(
            "❌ Unknown symbol. Try again."
        )
        return

    session = get_session(query.from_user.id)
    session.symbol_key = symbol_key

    # Dispatch to the correct action handler
    dispatch = {
        "price": _execute_price,
        "analysis": _execute_analysis,
        "chart": _execute_chart,
        "fundamental": _execute_fundamental,
        "fullreport": _execute_fullreport,
    }

    handler = dispatch.get(action)
    if handler:
        await handler(query, context, symbol, session)
    else:
        await query.edit_message_text(
            "❌ Unknown action."
        )


# =============================================================================
# ACTION EXECUTORS
# =============================================================================

async def _execute_price(
    query, context, symbol: SymbolConfig,
    session: UserSession,
) -> None:
    await query.edit_message_text(
        f"Fetching {symbol.emoji} "
        f"{symbol.display_name} price..."
    )

    try:
        await api_limiter.acquire()
        loop = asyncio.get_running_loop()
        price_data = await loop.run_in_executor(
            None, md_client.fetch_current_price, symbol
        )
        await db.increment_api_counter("twelvedata_calls")

        if price_data is None:
            await query.edit_message_text(
                "❌ Failed to fetch price."
            )
            return

        price = price_data["price"]
        timestamp = h(price_data["timestamp"])

        msg = (
            f"{symbol.emoji} "
            f"<b>{h(symbol.display_name)} "
            f"— Live Price</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>Price:</b> "
            f"<code>${price:,.{symbol.decimal_places}f}"
            f"</code>\n"
            f"🕐 <b>Time:</b> "
            f"<code>{timestamp}</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            msg, parse_mode=ParseMode.HTML
        )

    except Exception as exc:
        logger.error(f"Price error: {exc}")
        await query.edit_message_text(
            "❌ Error fetching price."
        )


async def _execute_analysis(
    query, context, symbol: SymbolConfig,
    session: UserSession,
) -> None:
    tf = session.timeframe

    await query.edit_message_text(
        f"🔄 Generating {symbol.emoji} "
        f"{symbol.display_name} analysis "
        f"({tf.display_name})...\n"
        f"This may take 10-15 seconds."
    )

    try:
        await api_limiter.acquire()
        loop = asyncio.get_running_loop()

        # Fetch market data
        df = await loop.run_in_executor(
            None,
            md_client.fetch_time_series,
            symbol, tf.value, DEFAULT_OUTPUTSIZE,
        )
        await db.increment_api_counter("twelvedata_calls")

        if df is None or len(df) < 50:
            await query.edit_message_text(
                "❌ Insufficient market data."
            )
            return

        # Compute indicators
        df, ind = ta_engine.compute(df, symbol)

        # AI analysis (with fundamental data included)
        fund = await loop.run_in_executor(
            None,
            fund_engine.fetch_fundamentals,
            symbol,
        )

        ai_result = await loop.run_in_executor(
            None,
            ai_analyzer.generate_analysis,
            df, ind, symbol, tf.display_name, fund,
        )
        await db.increment_api_counter("gemini_calls")

        # Format
        msg = _format_analysis_html(
            symbol, tf, ind, ai_result, fund
        )
        await query.edit_message_text(
            msg, parse_mode=ParseMode.HTML
        )

    except Exception as exc:
        logger.error(
            f"Analysis error: {exc}", exc_info=True
        )
        await query.edit_message_text(
            "❌ Analysis failed. Try again."
        )


async def _execute_chart(
    query, context, symbol: SymbolConfig,
    session: UserSession,
) -> None:
    tf = session.timeframe

    await query.edit_message_text(
        f"📊 Generating {symbol.emoji} "
        f"{symbol.display_name} chart..."
    )

    try:
        await api_limiter.acquire()
        loop = asyncio.get_running_loop()

        df = await loop.run_in_executor(
            None,
            md_client.fetch_time_series,
            symbol, tf.value, DEFAULT_OUTPUTSIZE,
        )
        await db.increment_api_counter("twelvedata_calls")

        if df is None or len(df) < 20:
            await query.edit_message_text(
                "❌ Insufficient data for chart."
            )
            return

        df, ind = ta_engine.compute(df, symbol)

        chart_buf = await loop.run_in_executor(
            None,
            chart_gen.generate_chart,
            df, ind, symbol, tf.display_name,
        )

        if chart_buf is None:
            await query.edit_message_text(
                "❌ Chart generation failed."
            )
            return

        now_str = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")

        caption = (
            f"{symbol.emoji} "
            f"{symbol.display_name} — "
            f"{tf.display_name}\n"
            f"Price: ${ind.current_price:,.2f} | "
            f"Bias: {ind.overall_bias}\n"
            f"RSI: {ind.rsi} | "
            f"ADX: {ind.adx}\n"
            f"{now_str}"
        )

        await query.delete_message()
        await context.bot.send_photo(
            chat_id=query.from_user.id,
            photo=chart_buf,
            caption=caption,
        )

    except Exception as exc:
        logger.error(
            f"Chart error: {exc}", exc_info=True
        )
        try:
            await query.edit_message_text(
                "❌ Chart error. Try again."
            )
        except Exception:
            pass


async def _execute_fundamental(
    query, context, symbol: SymbolConfig,
    session: UserSession,
) -> None:
    await query.edit_message_text(
        f"📋 Fetching {symbol.emoji} "
        f"{symbol.display_name} fundamentals..."
    )

    try:
        loop = asyncio.get_running_loop()
        fund = await loop.run_in_executor(
            None,
            fund_engine.fetch_fundamentals,
            symbol,
        )

        msg = _format_fundamental_html(symbol, fund)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.HTML
        )

    except Exception as exc:
        logger.error(
            f"Fundamental error: {exc}", exc_info=True
        )
        await query.edit_message_text(
            "❌ Failed to fetch fundamental data."
        )


async def _execute_fullreport(
    query, context, symbol: SymbolConfig,
    session: UserSession,
) -> None:
    tf = session.timeframe

    await query.edit_message_text(
        f"📊 Generating full report for "
        f"{symbol.emoji} {symbol.display_name} "
        f"({tf.display_name})...\n"
        f"This may take 15-20 seconds."
    )

    try:
        await api_limiter.acquire()
        loop = asyncio.get_running_loop()

        # Market data
        df = await loop.run_in_executor(
            None,
            md_client.fetch_time_series,
            symbol, tf.value, DEFAULT_OUTPUTSIZE,
        )
        await db.increment_api_counter("twelvedata_calls")

        if df is None or len(df) < 50:
            await query.edit_message_text(
                "❌ Insufficient data."
            )
            return

        # Technical
        df, ind = ta_engine.compute(df, symbol)

        # Fundamental
        fund = await loop.run_in_executor(
            None,
            fund_engine.fetch_fundamentals,
            symbol,
        )

        # AI combined
        ai_result = await loop.run_in_executor(
            None,
            ai_analyzer.generate_analysis,
            df, ind, symbol, tf.display_name, fund,
        )
        await db.increment_api_counter("gemini_calls")

        # Send chart first
        chart_buf = await loop.run_in_executor(
            None,
            chart_gen.generate_chart,
            df, ind, symbol, tf.display_name,
        )

        if chart_buf:
            await query.delete_message()
            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=chart_buf,
                caption=(
                    f"{symbol.emoji} "
                    f"{symbol.display_name} "
                    f"— {tf.display_name} Chart"
                ),
            )

        # Then send full text report
        msg = _format_full_report_html(
            symbol, tf, ind, ai_result, fund
        )
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except Exception as exc:
        logger.error(
            f"Full report error: {exc}", exc_info=True
        )
        try:
            await query.edit_message_text(
                "❌ Report generation failed."
            )
        except Exception:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="❌ Report generation failed.",
            )


# =============================================================================
# HTML FORMATTERS
# =============================================================================

def _format_analysis_html(
    symbol: SymbolConfig,
    tf: Timeframe,
    ind: AdvancedTechnicalIndicators,
    ai: AIAnalysis,
    fund: Optional[FundamentalData],
) -> str:
    now_str = h(
        datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    msg = (
        f"{symbol.emoji} <b>{h(symbol.display_name)} "
        f"Analysis ({h(tf.display_name)})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        # Price
        "📊 <b>PRICE ACTION</b>\n"
        f"Price: <code>"
        f"${ind.current_price:,.{symbol.decimal_places}f}"
        f"</code> "
        f"({ind.price_change_pct:+.3f}%)\n"
        f"O: <code>{ind.open_price}</code> "
        f"H: <code>{ind.high_price}</code> "
        f"L: <code>{ind.low_price}</code>\n\n"
        # Trend
        "📈 <b>TREND</b>\n"
        f"Direction: {h(ind.trend_direction)}\n"
        f"Strength: {h(ind.trend_strength)}\n"
        f"EMA: {ind.ema_9} / {ind.ema_20} / "
        f"{ind.ema_50}\n\n"
        # Momentum
        "⚡ <b>MOMENTUM</b>\n"
        f"{h(ind.momentum_bias)}\n\n"
        # Volatility
        "🌊 <b>VOLATILITY</b>\n"
        f"{h(ind.volatility_condition)}\n\n"
        # Volume
        "📦 <b>VOLUME</b>\n"
        f"{h(ind.volume_analysis)}\n\n"
        # Key Levels
        "🛡 <b>KEY LEVELS</b>\n"
        f"R3: <code>{ind.resistance_3}</code> "
        f"R2: <code>{ind.resistance_2}</code> "
        f"R1: <code>{ind.resistance_1}</code>\n"
        f"Pivot: <code>{ind.pivot_point}</code>\n"
        f"S1: <code>{ind.support_1}</code> "
        f"S2: <code>{ind.support_2}</code> "
        f"S3: <code>{ind.support_3}</code>\n"
        f"VPOC: <code>{ind.vpoc}</code>\n"
        f"Fib 38.2%: <code>{ind.fib_382}</code> "
        f"| 61.8%: <code>{ind.fib_618}</code>\n\n"
        # Market Structure
        "🏗 <b>STRUCTURE</b>\n"
        f"{h(ind.market_structure)}\n\n"
        # Orderflow
        "🔄 <b>ORDERFLOW</b>\n"
        f"{h(ind.orderflow_bias)}\n\n"
        # Overall Signal
        "🎯 <b>SIGNAL: {bias} "
        "({conf}% confidence)</b>\n"
        f"💡 {h(ind.key_insight)}\n"
        f"📋 {h(ind.action_levels)}\n\n"
    ).format(
        bias=h(ind.overall_bias),
        conf=ind.confidence_score,
    )

    # AI section
    msg += (
        "🤖 <b>AI ANALYSIS</b>\n"
        f"Bias: {h(ai.bias)}\n"
        f"Trade: {h(ai.trade_idea)}\n"
        f"Entry: <code>{h(ai.entry)}</code>\n"
        f"SL: <code>{h(ai.stop_loss)}</code>\n"
        f"TP1: <code>{h(ai.take_profit_1)}</code>\n"
        f"TP2: <code>{h(ai.take_profit_2)}</code>\n"
        f"⚠️ {h(ai.risk_note)}\n"
        f"🔮 {h(ai.short_term_outlook)}\n"
    )

    if ai.fundamental_note != "N/A":
        msg += f"🏦 {h(ai.fundamental_note)}\n"
    if ai.combined_verdict != "N/A":
        msg += f"✅ {h(ai.combined_verdict)}\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{now_str} • Not financial advice.</i>"
    )
    return msg


def _format_fundamental_html(
    symbol: SymbolConfig,
    fund: FundamentalData,
) -> str:
    now_str = h(
        datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    msg = (
        f"{symbol.emoji} <b>{h(symbol.display_name)} "
        f"— Fundamental Analysis</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Macro
    msg += (
        "🏦 <b>MACRO</b>\n"
        f"Fed Rate: <code>{h(fund.fed_rate)}</code>\n"
        f"DXY: <code>{h(fund.dxy_index)}</code>\n"
        f"CPI YoY: <code>{h(fund.us_cpi_yoy)}</code>\n\n"
    )

    if symbol.asset_type == "crypto":
        msg += (
            "₿ <b>CRYPTO METRICS</b>\n"
            f"Fear &amp; Greed: "
            f"<code>{h(fund.fear_greed_index)}</code> "
            f"({h(fund.fear_greed_label)})\n"
            f"Market Cap: "
            f"<code>{h(fund.btc_market_cap)}</code>\n"
            f"24h Volume: "
            f"<code>{h(fund.btc_24h_volume)}</code>\n"
            f"Hashrate: "
            f"<code>{h(fund.btc_hashrate)}</code>\n"
            f"Dominance: "
            f"<code>{h(fund.btc_dominance)}</code>\n"
            f"ETF: {h(fund.btc_etf_note)}\n\n"
        )
    elif symbol.asset_type == "commodity":
        msg += (
            "🥇 <b>GOLD METRICS</b>\n"
            f"ETF Flows: "
            f"{h(fund.gold_etf_flows)}\n"
            f"Central Banks: "
            f"{h(fund.central_bank_buying)}\n"
            f"Supply: "
            f"{h(fund.gold_supply_note)}\n\n"
        )

    # Drivers & Risks
    if fund.key_drivers:
        msg += "✅ <b>KEY DRIVERS</b>\n"
        for d in fund.key_drivers:
            msg += f"  • {h(d)}\n"
        msg += "\n"

    if fund.risk_factors:
        msg += "⚠️ <b>RISK FACTORS</b>\n"
        for r in fund.risk_factors:
            msg += f"  • {h(r)}\n"
        msg += "\n"

    msg += (
        f"📊 <b>FUNDAMENTAL BIAS: "
        f"{h(fund.fundamental_bias)}</b>\n"
        f"🌍 Macro Outlook: "
        f"{h(fund.macro_outlook)}\n"
        f"📋 {h(fund.combined_score)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{now_str}</i>"
    )
    return msg


def _format_full_report_html(
    symbol: SymbolConfig,
    tf: Timeframe,
    ind: AdvancedTechnicalIndicators,
    ai: AIAnalysis,
    fund: Optional[FundamentalData],
) -> str:
    """Combined technical + fundamental report."""
    now_str = h(
        datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    msg = (
        f"{symbol.emoji} <b>{h(symbol.display_name)} "
        f"— FULL REPORT ({h(tf.display_name)})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # ─── Technical Summary ────────────────────────
    msg += (
        "📊 <b>TECHNICAL SUMMARY</b>\n"
        f"Price: <code>"
        f"${ind.current_price:,.{symbol.decimal_places}f}"
        f"</code> ({ind.price_change_pct:+.3f}%)\n"
        f"Trend: {h(ind.trend_direction)} | "
        f"ADX: {ind.adx:.1f}\n"
        f"RSI: {ind.rsi} | "
        f"MACD: {h('Bullish' if ind.macd_histogram > 0 else 'Bearish')}\n"
        f"Volatility: {h(ind.volatility_condition)}\n"
        f"Signal: <b>{h(ind.overall_bias)} "
        f"({ind.confidence_score}%)</b>\n\n"
    )

    # ─── Key Levels ───────────────────────────────
    msg += (
        "🛡 <b>KEY LEVELS</b>\n"
        f"Resistance: <code>{ind.resistance_1}</code> "
        f"→ <code>{ind.resistance_2}</code>\n"
        f"Support: <code>{ind.support_1}</code> "
        f"→ <code>{ind.support_2}</code>\n"
        f"Pivot: <code>{ind.pivot_point}</code> "
        f"| VPOC: <code>{ind.vpoc}</code>\n"
        f"Fib: 38.2% <code>{ind.fib_382}</code> "
        f"| 61.8% <code>{ind.fib_618}</code>\n\n"
    )

    # ─── Fundamental Summary ──────────────────────
    if fund:
        msg += "🏦 <b>FUNDAMENTAL SUMMARY</b>\n"
        if symbol.asset_type == "crypto":
            msg += (
                f"Fear &amp; Greed: "
                f"{h(fund.fear_greed_index)} "
                f"({h(fund.fear_greed_label)})\n"
                f"MCap: {h(fund.btc_market_cap)} "
                f"| Hash: {h(fund.btc_hashrate)}\n"
            )
        else:
            msg += (
                f"DXY: {h(fund.dxy_index)} "
                f"| Fed: {h(fund.fed_rate)}\n"
            )
        msg += (
            f"Fundamental Bias: "
            f"<b>{h(fund.fundamental_bias)}</b>\n\n"
        )

    # ─── AI Verdict ───────────────────────────────
    msg += (
        "🤖 <b>AI TRADE PLAN</b>\n"
        f"Bias: <b>{h(ai.bias)}</b>\n"
        f"Trade: <b>{h(ai.trade_idea)}</b>\n"
        f"Entry: <code>{h(ai.entry)}</code>\n"
        f"SL: <code>{h(ai.stop_loss)}</code>\n"
        f"TP1: <code>{h(ai.take_profit_1)}</code>\n"
        f"TP2: <code>{h(ai.take_profit_2)}</code>\n\n"
        f"⚠️ <b>Risk:</b> {h(ai.risk_note)}\n"
        f"🔮 <b>Outlook:</b> "
        f"{h(ai.short_term_outlook)}\n"
    )

    if ai.combined_verdict != "N/A":
        msg += (
            f"\n✅ <b>COMBINED VERDICT:</b> "
            f"{h(ai.combined_verdict)}\n"
        )

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{now_str} • Not financial advice.</i>"
    )
    return msg


# =============================================================================
# SETTINGS COMMANDS
# =============================================================================

async def cmd_timeframe(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    session = get_session(update.effective_user.id)

    if not context.args:
        msg = (
            f"Current Timeframe: "
            f"<b>{h(session.timeframe.display_name)}"
            f"</b>\n\n"
            "<b>Usage:</b> "
            "<code>/timeframe &lt;tf&gt;</code>\n\n"
            "<code>5m 15m 1h 4h 1d</code>"
        )
        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML
        )
        return

    new_tf = Timeframe.from_user_input(context.args[0])
    if new_tf is None:
        await update.message.reply_text(
            f"❌ Invalid: "
            f"<code>{h(context.args[0])}</code>\n"
            f"Valid: <code>5m 15m 1h 4h 1d</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    session.timeframe = new_tf
    await update.message.reply_text(
        f"✅ Timeframe → "
        f"<b>{h(new_tf.display_name)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_credits(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    user_data = await db.get_or_create_user(
        user.id, user.username
    )
    user_data = await db.reset_daily_if_needed(user.id)
    role = user_data["role"]
    used = user_data["daily_used"]
    limit = user_data["daily_limit"]

    if user.id == OWNER_ID or role == "owner":
        msg = (
            "👑 <b>Credits: Unlimited</b> ♾"
        )
    else:
        remaining = max(0, limit - used)
        emoji = "💎" if role == "premium" else "🆓"
        role_name = (
            "Premium" if role == "premium" else "Free"
        )
        msg = (
            f"{emoji} <b>Credit Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Role: <b>{role_name}</b>\n"
            f"Used Today: "
            f"<code>{used}/{limit}</code>\n"
            f"Remaining: <b>{remaining}</b>\n\n"
            "<b>Command Costs:</b>\n"
            "  /price, /analysis, /chart, "
            "/fundamental → 1 credit\n"
            "  /fullreport → 4 credits\n\n"
            "Resets at <code>00:00 UTC</code>"
        )
        if role == "free":
            msg += "\n\n💡 /upgrade for more credits!"

        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML
    )


# =============================================================================
# ERROR HANDLER
# =============================================================================
async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.error(
        f"Unhandled: {context.error}",
        exc_info=context.error,
    )
    if isinstance(update, Update):
        target = None
        if update.callback_query:
            target = update.callback_query.from_user.id
        elif update.message:
            target = update.message.chat_id

        if target:
            try:
                await context.bot.send_message(
                    chat_id=target,
                    text="❌ Unexpected error. "
                         "Try again.",
                )
            except Exception:
                pass


# =============================================================================
# LIFECYCLE
# =============================================================================
async def post_init(application: Application) -> None:
    await db.init_pool()
    logger.info("DB pool ready")

    await db.get_or_create_user(OWNER_ID, "EK_HENG")
    await db.set_role(OWNER_ID, "owner", 999999)
    logger.info(f"Owner {OWNER_ID} registered")

    commands = [
        BotCommand("start", "Welcome"),
        BotCommand("price", "Live price"),
        BotCommand("analysis", "AI technical analysis"),
        BotCommand("chart", "Technical chart"),
        BotCommand("fundamental", "Fundamental data"),
        BotCommand(
            "fullreport", "Combined tech+fundamental"
        ),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check credits"),
        BotCommand("checkid", "Your account info"),
        BotCommand("upgrade", "Premium info"),
        BotCommand("help", "All commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Commands registered")


async def post_shutdown(application: Application) -> None:
    await db.close_pool()
    logger.info("Shutdown complete")


def main() -> None:
    logger.info("=" * 60)
    logger.info("  AI Analysis Bot v4.0 — Multi-Symbol")
    logger.info("  Symbols: XAU/USD, BTC/USD")
    logger.info("  Features: Tech + Fundamental + AI")
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

    # User commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("credits", cmd_credits))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(
        CommandHandler("analysis", cmd_analysis)
    )
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(
        CommandHandler("fundamental", cmd_fundamental)
    )
    app.add_handler(
        CommandHandler("fullreport", cmd_fullreport)
    )
    app.add_handler(
        CommandHandler("timeframe", cmd_timeframe)
    )

    # Account commands
    app.add_handler(
        CommandHandler(
            "checkid", admin_commands.cmd_checkid
        )
    )
    app.add_handler(
        CommandHandler(
            "upgrade", admin_commands.cmd_upgrade
        )
    )
    app.add_handler(
        CommandHandler(
            "premium", admin_commands.cmd_upgrade
        )
    )
    app.add_handler(
        CommandHandler(
            "buypremium", admin_commands.cmd_upgrade
        )
    )

    # Admin commands
    app.add_handler(
        CommandHandler(
            "addprem", admin_commands.cmd_addprem
        )
    )
    app.add_handler(
        CommandHandler(
            "addpremium", admin_commands.cmd_addprem
        )
    )
    app.add_handler(
        CommandHandler(
            "delprem", admin_commands.cmd_delprem
        )
    )
    app.add_handler(
        CommandHandler(
            "removepremium", admin_commands.cmd_delprem
        )
    )
    app.add_handler(
        CommandHandler(
            "botstats", admin_commands.cmd_botstats
        )
    )

    # Callback handler for symbol selection
    app.add_handler(
        CallbackQueryHandler(handle_symbol_callback)
    )

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("Polling started...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
