#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    DATABASE LAYER (PostgreSQL)                      ║
║                                                                    ║
║  Async PostgreSQL connection pool using asyncpg.                   ║
║  UPDATED: increment_usage supports variable amount.                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import logging
from datetime import date
from typing import Optional

import asyncpg

logger = logging.getLogger("XAUUSD_Bot.db")

# ---------------------------------------------------------------------------
# Singleton pool holder
# ---------------------------------------------------------------------------
_pool: Optional[asyncpg.Pool] = None

DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    role        TEXT        NOT NULL DEFAULT 'free',
    daily_used  INTEGER     NOT NULL DEFAULT 0,
    daily_limit INTEGER     NOT NULL DEFAULT 5,
    last_reset  DATE        NOT NULL DEFAULT CURRENT_DATE,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
"""

CREATE_API_STATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS api_stats (
    stat_date        DATE PRIMARY KEY DEFAULT CURRENT_DATE,
    twelvedata_calls INTEGER NOT NULL DEFAULT 0,
    gemini_calls     INTEGER NOT NULL DEFAULT 0,
    total_commands   INTEGER NOT NULL DEFAULT 0
);
"""


# ==========================================================================
# Pool lifecycle
# ==========================================================================
async def init_pool() -> asyncpg.Pool:
    """Create the connection pool and ensure tables exist."""
    global _pool

    if not DATABASE_URL:
        raise EnvironmentError(
            "DATABASE_URL environment variable is not set. "
            "Please configure it for Railway PostgreSQL."
        )

    logger.info("Connecting to PostgreSQL...")

    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=15,
        statement_cache_size=0,
    )

    async with _pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
        await conn.execute(CREATE_API_STATS_TABLE_SQL)

    logger.info("PostgreSQL pool ready — tables verified.")
    return _pool


async def close_pool() -> None:
    """Gracefully close every connection in the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed.")


def get_pool() -> asyncpg.Pool:
    """Return the live pool or raise if not initialised."""
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. "
            "Call init_pool() first."
        )
    return _pool


# ==========================================================================
# User helpers
# ==========================================================================
async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
) -> dict:
    """
    Fetch existing user or insert a new FREE user.
    Returns a dict with all column values.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id,
            )

            if row is not None:
                if username and row["username"] != username:
                    await conn.execute(
                        "UPDATE users SET username = $1 "
                        "WHERE user_id = $2",
                        username,
                        user_id,
                    )
                return dict(row)

            await conn.execute(
                """
                INSERT INTO users
                    (user_id, username, role, daily_used,
                     daily_limit, last_reset)
                VALUES ($1, $2, 'free', 0, 5, CURRENT_DATE)
                """,
                user_id,
                username or "",
            )

            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id,
            )
            logger.info(
                f"New free user created: {user_id} "
                f"(@{username})"
            )
            return dict(row)


async def reset_daily_if_needed(user_id: int) -> dict:
    """
    If the user's last_reset is before today (UTC),
    zero out daily_used and stamp today.
    """
    pool = get_pool()
    today = date.today()

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users "
                "WHERE user_id = $1 FOR UPDATE",
                user_id,
            )

            if row is None:
                return await get_or_create_user(user_id)

            if row["last_reset"] < today:
                await conn.execute(
                    """
                    UPDATE users
                       SET daily_used = 0,
                           last_reset = $1
                     WHERE user_id = $2
                    """,
                    today,
                    user_id,
                )
                logger.info(
                    f"Daily reset for user {user_id}"
                )
                row = await conn.fetchrow(
                    "SELECT * FROM users "
                    "WHERE user_id = $1",
                    user_id,
                )

            return dict(row)


async def increment_usage(
    user_id: int, amount: int = 1
) -> None:
    """Atomically bump daily_used by `amount`."""
    pool = get_pool()
    await pool.execute(
        "UPDATE users "
        "SET daily_used = daily_used + $1 "
        "WHERE user_id = $2",
        amount,
        user_id,
    )


async def set_role(
    user_id: int,
    role: str,
    daily_limit: int,
) -> bool:
    """
    Change a user's role and daily_limit.
    Returns True if a row was actually updated.
    """
    if role not in ("free", "premium", "owner"):
        raise ValueError(f"Invalid role: {role}")

    pool = get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE users
               SET role = $1,
                   daily_limit = $2
             WHERE user_id = $3
            """,
            role,
            daily_limit,
            user_id,
        )
        return result.endswith("1")


# ==========================================================================
# Stats helpers
# ==========================================================================
async def get_all_user_stats() -> dict:
    pool = get_pool()
    today = date.today()

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM users"
        )
        premium = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE role = 'premium'"
        )
        free = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE role = 'free'"
        )
        today_cmds = await conn.fetchval(
            """
            SELECT COALESCE(SUM(daily_used), 0)
              FROM users
             WHERE last_reset = $1
            """,
            today,
        )

    return {
        "total_users": total,
        "premium_users": premium,
        "free_users": free,
        "today_commands": today_cmds,
    }


async def get_api_stats_today() -> dict:
    pool = get_pool()
    today = date.today()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM api_stats "
            "WHERE stat_date = $1",
            today,
        )

    if row is None:
        return {
            "twelvedata_calls": 0,
            "gemini_calls": 0,
            "total_commands": 0,
        }

    return dict(row)


async def increment_api_counter(
    column: str,
    amount: int = 1,
) -> None:
    allowed = {
        "twelvedata_calls",
        "gemini_calls",
        "total_commands",
    }
    if column not in allowed:
        raise ValueError(
            f"Invalid counter column: {column}"
        )

    pool = get_pool()
    today = date.today()

    await pool.execute(
        f"""
        INSERT INTO api_stats (stat_date, {column})
        VALUES ($1, $2)
        ON CONFLICT (stat_date)
        DO UPDATE SET {column} = api_stats.{column} + $2
        """,
        today,
        amount,
    )
