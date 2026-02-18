#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                      CREDIT MANAGER                                ║
║                                                                    ║
║  Provides the @require_credit decorator and credit helpers.        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import functools
import logging
from typing import Callable, Awaitable

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db

logger = logging.getLogger("XAUUSD_Bot.credits")

# ---------------------------------------------------------------------------
# Owner constants (single source of truth)
# ---------------------------------------------------------------------------
OWNER_ID: int = 5482019561
OWNER_USERNAME: str = "@EK_HENG"

FREE_DAILY_LIMIT: int = 5
PREMIUM_DAILY_LIMIT: int = 50


# ==========================================================================
# Core credit check
# ==========================================================================
async def check_and_deduct(
    user_id: int,
    username: str | None = None,
) -> tuple[bool, str]:
    """
    Returns (allowed: bool, message: str).

    * Owner → always allowed, no deduction.
    * Others → daily reset check, limit check, then deduct.
    """
    # Owner bypass
    if user_id == OWNER_ID:
        return True, ""

    # Ensure user exists
    user = await db.get_or_create_user(user_id, username)

    # Daily reset
    user = await db.reset_daily_if_needed(user_id)

    role = user["role"]
    used = user["daily_used"]
    limit = user["daily_limit"]

    if used >= limit:
        if role == "free":
            msg = (
                "🚫 *Daily limit reached*\n\n"
                f"Free users get *{FREE_DAILY_LIMIT}* commands/day\\.\n"
                f"You've used *{used}/{limit}*\\.\n\n"
                "Resets at `00:00 UTC`\\.\n"
                "Contact the owner to upgrade to Premium\\!"
            )
        else:
            msg = (
                "🚫 *Daily limit reached*\n\n"
                f"Premium users get *{PREMIUM_DAILY_LIMIT}* commands/day\\.\n"
                f"You've used *{used}/{limit}*\\.\n\n"
                "Resets at `00:00 UTC`\\."
            )
        return False, msg

    # Deduct
    await db.increment_usage(user_id)
    await db.increment_api_counter("total_commands")
    return True, ""


# ==========================================================================
# Decorator
# ==========================================================================
def require_credit(
    func: Callable[..., Awaitable],
) -> Callable[..., Awaitable]:
    """
    Decorator for Telegram command handlers.

    Usage:
        @require_credit
        async def cmd_analysis(update, context):
            ...

    Before the wrapped handler executes:
        1. Checks / creates user in DB.
        2. Resets daily counter if new UTC day.
        3. Blocks if over limit (sends a message).
        4. Deducts 1 credit.
        5. Owner is never blocked or deducted.
    """

    @functools.wraps(func)
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

        allowed, deny_msg = await check_and_deduct(user_id, username)

        if not allowed:
            await update.message.reply_text(
                deny_msg, parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(
                f"Credit denied for user {user_id} (@{username})"
            )
            return

        remaining = await get_remaining(user_id)
        logger.info(
            f"Credit OK for user {user_id} (@{username}) — "
            f"{remaining} remaining today"
        )

        return await func(update, context, *args, **kwargs)

    return wrapper


# ==========================================================================
# Helpers
# ==========================================================================
async def get_remaining(user_id: int) -> int | str:
    """Return credits left today, or '∞' for the owner."""
    if user_id == OWNER_ID:
        return "∞"

    user = await db.get_or_create_user(user_id)
    user = await db.reset_daily_if_needed(user_id)
    return max(0, user["daily_limit"] - user["daily_used"])


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID
