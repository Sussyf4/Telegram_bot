#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║              XAUUSD & BTC/USD AI BOT v4.1 — Fly.io                ║
║                                                                    ║
║  Fly.io + Neon PostgreSQL + HTTP health + DB keep-alive.          ║
║  Polling mode with keep-alive for serverless DB.                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# =============================================================================
# IMPORTS
# =============================================================================
import os
import logging
import asyncio
import signal
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
import keep_alive
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
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

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
    "httpx", "telegram.ext", "urllib3",
    "asyncpg", "aiohttp.access",
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

# Keep-alive background tasks
_keepalive_tasks: list[asyncio.Task] = []
_health_runner = None


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
# INLINE KEYBOARD
# =============================================================================
def build_symbol_keyboard(
    action: str,
) -> InlineKeyboardMarkup:
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
# ALL COMMAND HANDLERS (identical to v4.0 — paste them here)
# =============================================================================

# ... (cmd_start, cmd_help, cmd_price, cmd_analysis,
#      cmd_chart, cmd_fundamental, cmd_credits,
#      cmd_timeframe, handle_symbol_callback,
#      _execute_price, _execute_analysis, _execute_chart,
#      _execute_fundamental, _execute_fullreport,
#      _format_analysis_html, _format_fundamental_html,
#      _format_full_report_html, error_handler)
#
# ALL IDENTICAL to the previous version.
# Copy them from the v4.0 bot.py with the
# updated formatters from the SL/TP fix.

# For /fullreport — 4 credits:
@require_credit(cost=4)
async def cmd_fullreport(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    keyboard = build_symbol_keyboard("fullreport")
    await update.message.reply_text(
        "📊 <b>Full Report</b> "
        "(costs <b>4 credits</b>)\n"
        "Select symbol:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =============================================================================
# LIFECYCLE — Fly.io + Neon + Keep-Alive
# =============================================================================
async def post_init(application: Application) -> None:
    """
    Called after Application.initialize().
    Sets up: DB pool, health server, keep-alive loops.
    """
    global _health_runner

    # 1. Initialize Neon database
    await db.init_pool()
    logger.info("Neon PostgreSQL pool ready")

    # 2. Register owner
    await db.get_or_create_user(OWNER_ID, "EK_HENG")
    await db.set_role(OWNER_ID, "owner", 999999)
    logger.info(f"Owner {OWNER_ID} registered")

    # 3. Start HTTP health server for Fly.io
    _health_runner = await keep_alive.start_health_server(
        port=HEALTH_PORT
    )
    logger.info(
        f"Health server on port {HEALTH_PORT}"
    )

    # 4. Start DB keep-alive loop
    db_task = asyncio.create_task(
        keep_alive.db_keepalive_loop(interval=60)
    )
    db_task.set_name("db_keepalive")
    _keepalive_tasks.append(db_task)
    logger.info("DB keep-alive loop started (60s)")

    # 5. Mark bot as running
    keep_alive.set_bot_running(True)

    # 6. Register bot commands
    commands = [
        BotCommand("start", "Welcome"),
        BotCommand("price", "Live price (1 credit)"),
        BotCommand(
            "analysis",
            "AI technical analysis (1 credit)",
        ),
        BotCommand(
            "chart",
            "Technical chart (1 credit)",
        ),
        BotCommand(
            "fundamental",
            "Fundamental data (1 credit)",
        ),
        BotCommand(
            "fullreport",
            "Full report (4 credits)",
        ),
        BotCommand("timeframe", "Change timeframe"),
        BotCommand("credits", "Check credits"),
        BotCommand("checkid", "Your account info"),
        BotCommand("upgrade", "Premium info"),
        BotCommand("help", "All commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered")


async def post_shutdown(
    application: Application,
) -> None:
    """
    Graceful shutdown: cancel tasks, close DB, stop health server.
    """
    global _health_runner

    logger.info("Shutting down...")

    # Mark bot as stopped
    keep_alive.set_bot_running(False)

    # Cancel keep-alive tasks
    for task in _keepalive_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _keepalive_tasks.clear()
    logger.info("Keep-alive tasks cancelled")

    # Stop health server
    if _health_runner:
        await _health_runner.cleanup()
        _health_runner = None
        logger.info("Health server stopped")

    # Close DB pool
    await db.close_pool()
    logger.info("Shutdown complete")


def main() -> None:
    logger.info("=" * 60)
    logger.info(
        "  AI Analysis Bot v4.1 — Fly.io Edition"
    )
    logger.info("  Hosting: Fly.io (polling)")
    logger.info("  Database: Neon PostgreSQL")
    logger.info("  Keep-alive: HTTP + DB ping")
    logger.info("  Symbols: XAU/USD, BTC/USD")
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

    # ── User commands ─────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(
        CommandHandler("credits", cmd_credits)
    )
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

    # ── Account commands ──────────────────────────
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

    # ── Admin commands ────────────────────────────
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

    # ── Callback handler ─────────────────────────
    app.add_handler(
        CallbackQueryHandler(handle_symbol_callback)
    )

    # ── Error handler ─────────────────────────────
    app.add_error_handler(error_handler)

    logger.info("Polling started...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()