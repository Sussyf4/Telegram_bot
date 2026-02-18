#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                       ADMIN COMMANDS                               ║
║                                                                    ║
║  Owner-only handlers: addprem, delprem, botstats                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
from datetime import datetime, timezone

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
    """Silently ignore (or warn) non-owner callers."""

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

    # Preserve __name__ so CommandHandler registration works
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
    # Strip leading @ just in case someone passes a username
    if raw.startswith("@"):
        return None  # we require numeric IDs
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
            "⚠️ Usage: /addprem <user_id>\n"
            "Example: /addprem 123456789\n\n"
            "User ID must be a positive number."
        )
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(
            "👑 Owner already has unlimited access."
        )
        return

    # Ensure user row exists first
    await db.get_or_create_user(target_id)

    updated = await db.set_role(target_id, "premium", PREMIUM_DAILY_LIMIT)

    if updated:
        await update.message.reply_text(
            f"✅ User `{target_id}` upgraded to *Premium*\\.\n"
            f"Daily limit: *{PREMIUM_DAILY_LIMIT}* commands/day\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(f"Owner promoted user {target_id} to premium")
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user `{target_id}`. "
            f"They may not exist yet (they need to /start first).",
            parse_mode=ParseMode.MARKDOWN_V2,
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
            "⚠️ Usage: /delprem <user_id>\n"
            "Example: /delprem 123456789\n\n"
            "User ID must be a positive number."
        )
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(
            "👑 Cannot demote the owner."
        )
        return

    # Ensure user row exists
    await db.get_or_create_user(target_id)

    updated = await db.set_role(target_id, "free", FREE_DAILY_LIMIT)

    if updated:
        await update.message.reply_text(
            f"✅ User `{target_id}` downgraded to *Free*\\.\n"
            f"Daily limit: *{FREE_DAILY_LIMIT}* commands/day\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(f"Owner demoted user {target_id} to free")
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user `{target_id}`.",
            parse_mode=ParseMode.MARKDOWN_V2,
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

        now_str = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )

        msg = (
            "📊 *BOT STATS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            f"👥 Total Users: `{total}`\n"
            f"💎 Premium Users: `{premium}`\n"
            f"🆓 Free Users: `{free}`\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Today Commands Used: `{today_cmds}`\n"
            "\n"
            "*API Usage Today:*\n"
            f"  TwelveData Calls: `{td_calls}`\n"
            f"  Gemini AI Calls:  `{gemini_calls}`\n"
            "\n"
            "*TwelveData Status:*\n"
            f"  API Key: `Active`\n"
            f"  Tracked Calls Today: `{td_calls}`\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_Generated: {now_str}_"
        )

        # MarkdownV2 requires escaping
        # We'll send as plain Markdown (v1) for stats to avoid
        # escaping headaches with numbers and colons.
        await loading.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
        logger.info("Bot stats delivered to owner")

    except Exception as e:
        logger.error(f"botstats error: {e}", exc_info=True)
        await loading.edit_text(
            "❌ Failed to gather stats. Check logs."
        )
