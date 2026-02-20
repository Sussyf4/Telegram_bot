#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    DATABASE LAYER (PostgreSQL)                      ║
║                                                                    ║
║  Optimized for Neon PostgreSQL on Replit.                          ║
║  Handles SSL, connection pooling, URL normalization.               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import ssl
import logging
from datetime import date
from typing import Optional

import asyncpg

logger = logging.getLogger("XAUUSD_Bot.db")

_pool: Optional[asyncpg.Pool] = None


# ==========================================================================
# URL Normalization
# ==========================================================================
def _get_database_url() -> str:
    """
    Get and normalize DATABASE_URL.
    Neon uses postgresql:// but some tools give postgres://.
    asyncpg requires postgresql://.
    """
    url = os.environ.get("DATABASE_URL", "")

    if not url:
        raise EnvironmentError(
            "DATABASE_URL is not set.\n"
            "Go to Replit → Tools → Secrets → "
            "add DATABASE_URL\n"
            "Get it from: Neon Dashboard → "
            "Connection Details → Direct connection"
        )

    # Fix postgres:// → postgresql://
    if url.startswith("postgres://"):
        url = url.replace(
            "postgres://", "postgresql://", 1
        )

    # Ensure sslmode is set for Neon
    if "sslmode" not in url:
        separator = "&" if "?" in url else "?"
        url += f"{separator}sslmode=require"

    return url


# ==========================================================================
# SSL Context for Neon
# ==========================================================================
def _create_ssl_context() -> ssl.SSLContext:
    """
    Neon requires SSL for all connections.
    This creates a permissive context that works
    with Neon's certificates.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ==========================================================================
# Schema
# ==========================================================================
CREATE_USERS_SQL = """
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

CREATE_API_STATS_SQL = """
CREATE TABLE IF NOT EXISTS api_stats (
    stat_date        DATE PRIMARY KEY DEFAULT CURRENT_DATE,
    twelvedata_calls INTEGER NOT NULL DEFAULT 0,
    gemini_calls     INTEGER NOT NULL DEFAULT 0,
    total_commands   INTEGER NOT NULL DEFAULT 0
);
"""


# ==========================================================================
# Pool Lifecycle
# ==========================================================================
async def init_pool() -> asyncpg.Pool:
    """Create connection pool optimized for Neon free tier."""
    global _pool

    database_url = _get_database_url()
    ssl_context = _create_ssl_context()

    logger.info("Connecting to Neon PostgreSQL...")

    try:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=1,         # Neon free = limited connections
            max_size=5,         # Neon free allows ~20 concurrent
            command_timeout=15,
            statement_cache_size=0,
            ssl=ssl_context,
        )
    except asyncpg.InvalidPasswordError:
        logger.error(
            "❌ Database authentication failed!\n"
            "Check your DATABASE_URL in Replit Secrets.\n"
            "Make sure you copied the FULL connection "
            "string from Neon Dashboard."
        )
        raise
    except asyncpg.InvalidCatalogNameError:
        logger.error(
            "❌ Database name not found!\n"
            "Check that 'neondb' (or your database name) "
            "exists in your Neon project."
        )
        raise
    except OSError as exc:
        logger.error(
            f"❌ Cannot connect to Neon: {exc}\n"
            "Check:\n"
            "  1. DATABASE_URL is correct\n"
            "  2. Neon project is not suspended\n"
            "  3. Region is accessible from Replit"
        )
        raise

    # Create tables
    async with _pool.acquire() as conn:
        await conn.execute(CREATE_USERS_SQL)
        await conn.execute(CREATE_API_STATS_SQL)

    logger.info(
        "✅ Neon PostgreSQL pool ready — "
        "tables verified."
    )
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed.")


def get_pool() -> asyncpg.Pool:
    """Return live pool or raise."""
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialised. "
            "Call init_pool() first."
        )
    return _pool


# ==========================================================================
# User Helpers
# ==========================================================================
async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
) -> dict:
    pool = get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users "
                "WHERE user_id = $1",
                user_id,
            )

            if row is not None:
                if (
                    username
                    and row["username"] != username
                ):
                    await conn.execute(
                        "UPDATE users "
                        "SET username = $1 "
                        "WHERE user_id = $2",
                        username,
                        user_id,
                    )
                return dict(row)

            await conn.execute(
                """
                INSERT INTO users
                    (user_id, username, role,
                     daily_used, daily_limit,
                     last_reset)
                VALUES
                    ($1, $2, 'free', 0, 5,
                     CURRENT_DATE)
                """,
                user_id,
                username or "",
            )

            row = await conn.fetchrow(
                "SELECT * FROM users "
                "WHERE user_id = $1",
                user_id,
            )
            logger.info(
                f"New free user: {user_id} "
                f"(@{username})"
            )
            return dict(row)


async def reset_daily_if_needed(
    user_id: int,
) -> dict:
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
                return await get_or_create_user(
                    user_id
                )

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
                    f"Daily reset: user {user_id}"
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
    """Atomically bump daily_used."""
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
    if role not in ("free", "premium", "owner"):
        raise ValueError(f"Invalid role: {role}")

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE users
               SET role = $1, daily_limit = $2
             WHERE user_id = $3
            """,
            role,
            daily_limit,
            user_id,
        )
        return result.endswith("1")


# ==========================================================================
# Stats Helpers
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
              FROM users WHERE last_reset = $1
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
    column: str, amount: int = 1
) -> None:
    allowed = {
        "twelvedata_calls",
        "gemini_calls",
        "total_commands",
    }
    if column not in allowed:
        raise ValueError(
            f"Invalid counter: {column}"
        )

    pool = get_pool()
    today = date.today()

    await pool.execute(
        f"""
        INSERT INTO api_stats (stat_date, {column})
        VALUES ($1, $2)
        ON CONFLICT (stat_date)
        DO UPDATE SET {column} =
            api_stats.{column} + $2
        """,
        today,
        amount,
    )