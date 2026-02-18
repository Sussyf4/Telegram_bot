#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                       ADMIN COMMANDS                               ║
║                                                                    ║
║  Owner-only handlers: addprem, delprem, botstats                   ║
║  FIXED: HTML parse mode, no MarkdownV2 crashes.                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
from datetime import datetime, timezone
from html import escape as html_escape

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db
from credit_manager import (
    OWNER_ID,
    PREMIUM_DAILY_LIMIT,
    FREE_DAILY_LIMIT,
    is_owner,
)

logger = logging.getLogger("XAUUSD_Bot.admin")


# ==========================================================================
# Security gate
# ==========================================================================
def _owner_only(func):
    """Silently ignore or warn non-owner callers."""

    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args,
        **kwargs,
    ):
        user_id = update.effective_user.id
        if not is_owner(user_id):
            await update.message.reply_text(
                "🔒 This command is restricted to the bot owner."
            )
            logger.warning(
                f"Unauthorized admin attempt by {user_id}"
            )
            return
        return await func(update, context, *args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


# ==========================================================================
# Helper: parse target user_id from args
# ==========================================================================
def _parse_target_id(args: list[str]) -> int | None:
    """Return a validated int user_id or None."""
    if not args:
        return None
    raw = args[0].strip()
    if raw.startswith("@"):
        return None
    try:
        uid = int(raw)
        if uid <= 0:
            return None
        return uid
    except ValueError:
        return None


# ==========================================================================
# /addprem, /addpremium
# ==========================================================================
@_owner_only
async def cmd_addprem(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    target_id = _parse_target_id(context.args)

    if target_id is None:
        await update.message.reply_text(
            "⚠️ Usage: /addprem &lt;user_id&gt;\n"
            "Example: /addprem 123456789\n\n"
            "User ID must be a positive number.",
            parse_mode=ParseMode.HTML,
        )
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(
            "👑 Owner already has unlimited access."
        )
        return

    await db.get_or_create_user(target_id)
    updated = await db.set_role(
        target_id, "premium", PREMIUM_DAILY_LIMIT
    )

    if updated:
        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> upgraded to "
            f"<b>Premium</b>.\n"
            f"Daily limit: <b>{PREMIUM_DAILY_LIMIT}</b> commands/day.",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Owner promoted user {target_id} to premium")
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user <code>{target_id}</code>. "
            f"They may not exist yet (they need to /start first).",
            parse_mode=ParseMode.HTML,
        )


# ==========================================================================
# /delprem, /removepremium
# ==========================================================================
@_owner_only
async def cmd_delprem(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    target_id = _parse_target_id(context.args)

    if target_id is None:
        await update.message.reply_text(
            "⚠️ Usage: /delprem &lt;user_id&gt;\n"
            "Example: /delprem 123456789\n\n"
            "User ID must be a positive number.",
            parse_mode=ParseMode.HTML,
        )
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(
            "👑 Cannot demote the owner."
        )
        return

    await db.get_or_create_user(target_id)
    updated = await db.set_role(
        target_id, "free", FREE_DAILY_LIMIT
    )

    if updated:
        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> downgraded to "
            f"<b>Free</b>.\n"
            f"Daily limit: <b>{FREE_DAILY_LIMIT}</b> commands/day.",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Owner demoted user {target_id} to free")
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user <code>{target_id}</code>.",
            parse_mode=ParseMode.HTML,
        )


# ==========================================================================
# /botstats
# ==========================================================================
@_owner_only
async def cmd_botstats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    loading = await update.message.reply_text(
        "📊 Gathering stats..."
    )

    try:
        user_stats = await db.get_all_user_stats()
        api_stats = await db.get_api_stats_today()

        total = user_stats["total_users"]
        premium = user_stats["premium_users"]
        free = user_stats["free_users"]
        today_cmds = user_stats["today_commands"]

        td_calls = api_stats.get("twelvedata_calls", 0)
        gemini_calls = api_stats.get("gemini_calls", 0)
        total_api = api_stats.get("total_commands", 0)

        now_str = html_escape(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )

        msg = (
            "📊 <b>BOT STATS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            f"👥 Total Users: <code>{total}</code>\n"
            f"💎 Premium Users: <code>{premium}</code>\n"
            f"🆓 Free Users: <code>{free}</code>\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Today Commands Used: <code>{today_cmds}</code>\n"
            f"📊 Total API Commands: <code>{total_api}</code>\n"
            "\n"
            "<b>API Usage Today:</b>\n"
            f"  TwelveData Calls: <code>{td_calls}</code>\n"
            f"  Gemini AI Calls:  <code>{gemini_calls}</code>\n"
            "\n"
            "<b>TwelveData Status:</b>\n"
            "  API Key: <code>Active</code>\n"
            f"  Tracked Calls Today: <code>{td_calls}</code>\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Generated: {now_str}</i>"
        )

        await loading.edit_text(msg, parse_mode=ParseMode.HTML)
        logger.info("Bot stats delivered to owner")

    except Exception as e:
        logger.error(f"botstats error: {e}", exc_info=True)
        await loading.edit_text(
            "❌ Failed to gather stats. Check logs."
        )
