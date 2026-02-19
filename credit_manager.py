#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                      CREDIT MANAGER v4.1                           ║
║                                                                    ║
║  UPDATED: Support variable credit cost per command.                ║
║  @require_credit(cost=1) or @require_credit(cost=4)               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import functools
import logging
from html import escape as html_escape
from typing import Callable, Awaitable

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db

logger = logging.getLogger("XAUUSD_Bot.credits")

# ---------------------------------------------------------------------------
# Owner constants
# ---------------------------------------------------------------------------
OWNER_ID: int = 5482019561
OWNER_USERNAME: str = "@EK_HENG"

FREE_DAILY_LIMIT: int = 5
PREMIUM_DAILY_LIMIT: int = 50


# ==========================================================================
# HTML helper
# ==========================================================================
def h(text) -> str:
    if not isinstance(text, str):
        text = str(text)
    return html_escape(text, quote=False)


def _owner_link() -> str:
    username_clean = OWNER_USERNAME.lstrip("@")
    return (
        f'<a href="https://t.me/{username_clean}">'
        f'{h(OWNER_USERNAME)}</a>'
    )


# ==========================================================================
# Core credit check (supports variable cost)
# ==========================================================================
async def check_and_deduct(
    user_id: int,
    username: str | None = None,
    cost: int = 1,
) -> tuple[bool, str]:
    """
    Returns (allowed: bool, deny_message_html: str).

    cost: number of credits to deduct (default 1).
    Owner -> always allowed, no deduction.
    Others -> daily reset, limit check, deduct.
    """
    if user_id == OWNER_ID:
        return True, ""

    user = await db.get_or_create_user(user_id, username)
    user = await db.reset_daily_if_needed(user_id)

    role = user["role"]
    used = user["daily_used"]
    limit = user["daily_limit"]
    remaining = limit - used

    if remaining < cost:
        if role == "free":
            msg = (
                "🚫 <b>Insufficient credits</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"This command costs "
                f"<b>{cost}</b> credit(s).\n"
                f"You have <b>{max(0, remaining)}</b> "
                f"remaining "
                f"({used}/{limit} used).\n\n"
                f"Free users get "
                f"<b>{FREE_DAILY_LIMIT}</b> "
                f"commands/day.\n"
                "⏰ Resets at <code>00:00 UTC</code>.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "💎 <b>Want more?</b> "
                "Upgrade to Premium!\n"
                f"📩 Contact: {_owner_link()}\n"
                f"📋 Your ID: <code>{user_id}</code>\n\n"
                "Or use /upgrade for details."
            )
        else:
            msg = (
                "🚫 <b>Insufficient credits</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"This command costs "
                f"<b>{cost}</b> credit(s).\n"
                f"You have <b>{max(0, remaining)}</b> "
                f"remaining "
                f"({used}/{limit} used).\n\n"
                f"Premium users get "
                f"<b>{PREMIUM_DAILY_LIMIT}</b> "
                f"commands/day.\n"
                "⏰ Resets at <code>00:00 UTC</code>.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Need more? Contact: {_owner_link()}"
            )
        return False, msg

    # Deduct the cost
    await db.increment_usage(user_id, amount=cost)
    await db.increment_api_counter("total_commands")
    return True, ""


# ==========================================================================
# Decorator (supports variable cost)
# ==========================================================================
def require_credit(
    func: Callable[..., Awaitable] = None,
    *,
    cost: int = 1,
) -> Callable[..., Awaitable]:
    """
    Decorator for Telegram command handlers.

    Usage:
        @require_credit            # costs 1 credit
        async def cmd_price(...):

        @require_credit(cost=4)    # costs 4 credits
        async def cmd_fullreport(...):
    """
    def decorator(
        fn: Callable[..., Awaitable],
    ) -> Callable[..., Awaitable]:

        @functools.wraps(fn)
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            *args,
            **kwargs,
        ):
            user = update.effective_user
            if user is None:
                return

            user_id = user.id
            username = user.username

            allowed, deny_msg = await check_and_deduct(
                user_id, username, cost=cost
            )

            if not allowed:
                await update.message.reply_text(
                    deny_msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                logger.info(
                    f"Credit denied for {user_id} "
                    f"(@{username}) — "
                    f"needed {cost} credits"
                )
                return

            remaining = await get_remaining(user_id)
            logger.info(
                f"Credit OK for {user_id} "
                f"(@{username}) — "
                f"deducted {cost}, "
                f"{remaining} remaining"
            )

            return await fn(
                update, context, *args, **kwargs
            )

        return wrapper

    # Handle both @require_credit and
    # @require_credit(cost=4)
    if func is not None:
        # Called as @require_credit without parens
        return decorator(func)
    else:
        # Called as @require_credit(cost=4)
        return decorator


# ==========================================================================
# Helpers
# ==========================================================================
async def get_remaining(user_id: int) -> int | str:
    if user_id == OWNER_ID:
        return "∞"
    user = await db.get_or_create_user(user_id)
    user = await db.reset_daily_if_needed(user_id)
    return max(0, user["daily_limit"] - user["daily_used"])


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID
