#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                       ADMIN COMMANDS                               ║
║                                                                    ║
║  Owner-only handlers: addprem, delprem, botstats                   ║
║  User handlers: checkid                                            ║
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
    OWNER_USERNAME,
    PREMIUM_DAILY_LIMIT,
    FREE_DAILY_LIMIT,
    is_owner,
)

logger = logging.getLogger("XAUUSD_Bot.admin")


# ==========================================================================
# HTML escape helper
# ==========================================================================
def h(text) -> str:
    """Safely escape any value for Telegram HTML parse mode."""
    if not isinstance(text, str):
        text = str(text)
    return html_escape(text, quote=False)


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
# /checkid — Any user can check their own Telegram ID
# ==========================================================================
async def cmd_checkid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Let any user check their Telegram ID, role, and credits."""
    user = update.effective_user

    # Ensure user exists in DB
    user_data = await db.get_or_create_user(
        user.id, user.username
    )
    user_data = await db.reset_daily_if_needed(user.id)

    role = user_data["role"]
    used = user_data["daily_used"]
    limit = user_data["daily_limit"]
    created = user_data["created_at"]

    # Format created_at
    if created:
        created_str = created.strftime("%Y-%m-%d %H:%M UTC")
    else:
        created_str = "Unknown"

    # Role display
    if role == "owner":
        role_display = "👑 Owner"
        remaining = "Unlimited ♾"
    elif role == "premium":
        role_display = "💎 Premium"
        remaining = str(max(0, limit - used))
    else:
        role_display = "🆓 Free"
        remaining = str(max(0, limit - used))

    # Username display
    if user.username:
        username_display = f"@{h(user.username)}"
    else:
        username_display = "<i>Not set</i>"

    # First name display
    first_name = h(user.first_name) if user.first_name else "N/A"
    last_name = h(user.last_name) if user.last_name else ""
    full_name = f"{first_name} {last_name}".strip()

    msg = (
        "🆔 <b>Your Account Info</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        f"👤 <b>Name:</b> {full_name}\n"
        f"📛 <b>Username:</b> {username_display}\n"
        f"🔢 <b>Telegram ID:</b> <code>{user.id}</code>\n"
        "\n"
        f"🏷 <b>Role:</b> {role_display}\n"
        f"📊 <b>Used Today:</b> <code>{used}/{limit}</code>\n"
        f"✨ <b>Remaining:</b> <b>{remaining}</b>\n"
        f"📅 <b>Member Since:</b> <code>{h(created_str)}</code>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # If free user, add upgrade prompt
    if role == "free":
        msg += (
            "\n"
            "💡 <b>Want more credits?</b>\n"
            f"Upgrade to Premium! Contact the owner:\n"
            f"👉 <a href=\"https://t.me/"
            f"{OWNER_USERNAME.lstrip('@')}\">"
            f"{h(OWNER_USERNAME)}</a>\n"
            "\n"
            f"Send your ID: <code>{user.id}</code> "
            f"to the owner to get upgraded.\n"
        )

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    logger.info(
        f"User {user.id} checked their ID (role={role})"
    )


# ==========================================================================
# /upgrade, /premium, /buypremium — Contact owner to buy premium
# ==========================================================================
async def cmd_upgrade(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show premium benefits and direct link to contact owner."""
    user = update.effective_user

    # Check current role
    user_data = await db.get_or_create_user(
        user.id, user.username
    )
    role = user_data["role"]

    if role == "owner":
        await update.message.reply_text(
            "👑 You're the owner. You already have unlimited access!"
        )
        return

    if role == "premium":
        user_data = await db.reset_daily_if_needed(user.id)
        used = user_data["daily_used"]
        limit = user_data["daily_limit"]
        remaining = max(0, limit - used)

        msg = (
            "💎 <b>You're Already Premium!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            f"📊 Credits Today: <code>{used}/{limit}</code>\n"
            f"✨ Remaining: <b>{remaining}</b>\n"
            "\n"
            "Enjoy your premium access! 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML
        )
        return

    # Free user — show upgrade info
    owner_link = (
        f"https://t.me/{OWNER_USERNAME.lstrip('@')}"
    )

    msg = (
        "💎 <b>Upgrade to Premium</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "<b>🆓 Free Plan (Current):</b>\n"
        f"  • {FREE_DAILY_LIMIT} commands per day\n"
        "  • Basic access\n"
        "\n"
        "<b>💎 Premium Plan:</b>\n"
        f"  • {PREMIUM_DAILY_LIMIT} commands per day\n"
        "  • Priority access\n"
        "  • Full AI analysis\n"
        "  • Unlimited charts\n"
        "  • Daily reset at 00:00 UTC\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "📩 <b>How to Upgrade:</b>\n"
        "\n"
        "1️⃣ Copy your Telegram ID:\n"
        f"   <code>{user.id}</code>\n"
        "\n"
        f"2️⃣ Contact the owner directly:\n"
        f"   👉 <a href=\"{owner_link}\">"
        f"{h(OWNER_USERNAME)}</a>\n"
        "\n"
        "3️⃣ Send this message:\n"
        f"   <code>Hi! I want to upgrade to Premium.\n"
        f"My ID: {user.id}</code>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>Direct Link:</b> "
        f"<a href=\"{owner_link}\">Message Owner</a>"
    )

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    logger.info(
        f"User {user.id} viewed upgrade/premium info"
    )


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
        # Try to notify the upgraded user
        notification_sent = False
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 <b>Congratulations!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\n"
                    "You've been upgraded to "
                    "<b>💎 Premium</b>!\n"
                    "\n"
                    f"📊 Daily Limit: "
                    f"<b>{PREMIUM_DAILY_LIMIT}</b> "
                    f"commands/day\n"
                    "⏰ Resets at <code>00:00 UTC</code>\n"
                    "\n"
                    "Enjoy your premium access! 🚀\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                parse_mode=ParseMode.HTML,
            )
            notification_sent = True
        except Exception as exc:
            logger.warning(
                f"Could not notify user {target_id}: {exc}"
            )

        notify_status = (
            "✅ User notified"
            if notification_sent
            else "⚠️ Could not notify user "
                 "(they may need to /start first)"
        )

        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> upgraded to "
            f"<b>Premium</b>.\n"
            f"Daily limit: <b>{PREMIUM_DAILY_LIMIT}</b> "
            f"commands/day.\n\n"
            f"{notify_status}",
            parse_mode=ParseMode.HTML,
        )
        logger.info(
            f"Owner promoted user {target_id} to premium"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user "
            f"<code>{target_id}</code>. "
            f"They may not exist yet "
            f"(they need to /start first).",
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
        # Try to notify the downgraded user
        notification_sent = False
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "ℹ️ <b>Account Updated</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\n"
                    "Your account has been changed to "
                    "<b>🆓 Free</b>.\n"
                    "\n"
                    f"📊 Daily Limit: "
                    f"<b>{FREE_DAILY_LIMIT}</b> "
                    f"commands/day\n"
                    "⏰ Resets at <code>00:00 UTC</code>\n"
                    "\n"
                    "Contact the owner to re-upgrade.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                parse_mode=ParseMode.HTML,
            )
            notification_sent = True
        except Exception as exc:
            logger.warning(
                f"Could not notify user {target_id}: {exc}"
            )

        notify_status = (
            "✅ User notified"
            if notification_sent
            else "⚠️ Could not notify user"
        )

        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> downgraded to "
            f"<b>Free</b>.\n"
            f"Daily limit: <b>{FREE_DAILY_LIMIT}</b> "
            f"commands/day.\n\n"
            f"{notify_status}",
            parse_mode=ParseMode.HTML,
        )
        logger.info(
            f"Owner demoted user {target_id} to free"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Could not update user "
            f"<code>{target_id}</code>.",
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

        now_str = h(
            datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
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
            f"📈 Today Commands Used: "
            f"<code>{today_cmds}</code>\n"
            f"📊 Total API Commands: "
            f"<code>{total_api}</code>\n"
            "\n"
            "<b>API Usage Today:</b>\n"
            f"  TwelveData Calls: "
            f"<code>{td_calls}</code>\n"
            f"  Gemini AI Calls:  "
            f"<code>{gemini_calls}</code>\n"
            "\n"
            "<b>TwelveData Status:</b>\n"
            "  API Key: <code>Active</code>\n"
            f"  Tracked Calls Today: "
            f"<code>{td_calls}</code>\n"
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
