#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    DATABASE LAYER — NEON PostgreSQL                 ║
║                                                                    ║
║  Async pool via asyncpg.                                           ║
║  Neon-optimized: SSL required, connection keep-alive,              ║
║  serverless-aware reconnection, idle timeout handling.             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import ssl
import logging
import asyncio
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
# Neon requires SSL
# ---------------------------------------------------------------------------
def _create_ssl_context() -> ssl.SSLContext:
    """Create SSL context for Neon PostgreSQL."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


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
# Pool lifecycle — Neon optimized
# ==========================================================================
async def init_pool() -> asyncpg.Pool:
    """
    Create connection pool optimized for Neon serverless.
    
    Neon specifics:
    - Requires SSL (sslmode=require in connection string)
    - Connections can be cold-started (add timeout tolerance)
    - Serverless means connections may drop after idle
    - Keep pool small to avoid overwhelming Neon free tier
    """
    global _pool

    if not DATABASE_URL:
        raise EnvironmentError(
            "DATABASE_URL is not set. "
            "Set it to your Neon connection string."
        )

    logger.info("Connecting to Neon PostgreSQL...")

    # Ensure sslmode is set in the URL
    db_url = DATABASE_URL
    if "sslmode" not in db_url:
        separator = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{separator}sslmode=require"

    _pool = await asyncpg.create_pool(
        db_url,
        min_size=1,          # Neon free tier: keep min low
        max_size=5,           # Neon free tier: don't overwhelm
        command_timeout=30,   # Neon cold start can be slow
        statement_cache_size=0,
        # Neon serverless drops idle connections
        # These settings detect and replace dead connections
        max_inactive_connection_lifetime=60,
        ssl=_create_ssl_context(),
    )

    # Verify connection and create tables
    async with _pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
        await conn.execute(CREATE_API_STATS_TABLE_SQL)
        # Test query
        version = await conn.fetchval(
            "SELECT version()"
        )
        logger.info(
            f"Neon connected: "
            f"{version[:60]}..."
        )

    logger.info("Neon PostgreSQL pool ready.")
    return _pool


async def close_pool() -> None:
    """Gracefully close every connection in the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Neon pool closed.")


def get_pool() -> asyncpg.Pool:
    """Return the live pool or raise if not initialised."""
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialised. "
            "Call init_pool() first."
        )
    return _pool


# ==========================================================================
# Resilient query execution for Neon
# ==========================================================================
async def _execute_with_retry(
    query: str,
    *args,
    max_retries: int = 2,
    fetch: str = "execute",
) -> any:
    """
    Execute a query with automatic retry on connection errors.
    Neon serverless can drop connections during cold starts.
    """
    pool = get_pool()
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            async with pool.acquire() as conn:
                if fetch == "fetchrow":
                    return await conn.fetchrow(
                        query, *args
                    )
                elif fetch == "fetchval":
                    return await conn.fetchval(
                        query, *args
                    )
                elif fetch == "fetch":
                    return await conn.fetch(
                        query, *args
                    )
                else:
                    return await conn.execute(
                        query, *args
                    )
        except (
            asyncpg.ConnectionDoesNotExistError,
            asyncpg.InterfaceError,
            ConnectionResetError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt < max_retries:
                wait = 1.0 * (attempt + 1)
                logger.warning(
                    f"Neon connection error "
                    f"(attempt {attempt + 1}/"
                    f"{max_retries + 1}): {exc}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    f"Neon query failed after "
                    f"{max_retries + 1} attempts: "
                    f"{exc}"
                )
                raise last_error


# ==========================================================================
# Keep-alive ping for Neon
# ==========================================================================
async def ping() -> bool:
    """
    Ping database to keep connection alive.
    Called periodically by the keep-alive system.
    Returns True if healthy, False otherwise.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            return result == 1
    except Exception as exc:
        logger.warning(f"DB ping failed: {exc}")
        return False


# ==========================================================================
# User helpers — Neon resilient
# ==========================================================================
async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
) -> dict:
    """Fetch existing user or insert a new FREE user."""
    pool = get_pool()

    for attempt in range(3):
        try:
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
                        VALUES ($1, $2, 'free', 0, 5,
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
                        f"New user: {user_id} "
                        f"(@{username})"
                    )
                    return dict(row)

        except (
            asyncpg.ConnectionDoesNotExistError,
            asyncpg.InterfaceError,
            ConnectionResetError,
            OSError,
        ) as exc:
            if attempt < 2:
                logger.warning(
                    f"Neon conn error in "
                    f"get_or_create_user: {exc}. "
                    f"Retry {attempt + 1}..."
                )
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                raise


async def reset_daily_if_needed(user_id: int) -> dict:
    """Reset daily counter if new UTC day."""
    pool = get_pool()
    today = date.today()

    for attempt in range(3):
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT * FROM users "
                        "WHERE user_id = $1 "
                        "FOR UPDATE",
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

        except (
            asyncpg.ConnectionDoesNotExistError,
            asyncpg.InterfaceError,
            ConnectionResetError,
            OSError,
        ) as exc:
            if attempt < 2:
                logger.warning(
                    f"Neon conn error in "
                    f"reset_daily: {exc}. "
                    f"Retry {attempt + 1}..."
                )
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                raise


async def increment_usage(
    user_id: int, amount: int = 1
) -> None:
    """Atomically bump daily_used by amount."""
    await _execute_with_retry(
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
    """Change a user's role and daily_limit."""
    if role not in ("free", "premium", "owner"):
        raise ValueError(f"Invalid role: {role}")

    result = await _execute_with_retry(
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

    try:
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
    except Exception as exc:
        logger.error(f"Stats query error: {exc}")
        return {
            "total_users": 0,
            "premium_users": 0,
            "free_users": 0,
            "today_commands": 0,
        }

    return {
        "total_users": total,
        "premium_users": premium,
        "free_users": free,
        "today_commands": today_cmds,
    }


async def get_api_stats_today() -> dict:
    pool = get_pool()
    today = date.today()

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM api_stats "
                "WHERE stat_date = $1",
                today,
            )
    except Exception as exc:
        logger.error(f"API stats error: {exc}")
        row = None

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
            f"Invalid counter: {column}"
        )

    today = date.today()

    await _execute_with_retry(
        f"""
        INSERT INTO api_stats (stat_date, {column})
        VALUES ($1, $2)
        ON CONFLICT (stat_date)
        DO UPDATE SET {column} = api_stats.{column} + $2
        """,
        today,
        amount,
    )