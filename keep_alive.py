#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                     KEEP-ALIVE SYSTEM                              ║
║                                                                    ║
║  1. HTTP health endpoint on port 8080 for Fly.io health checks    ║
║  2. Periodic DB ping to keep Neon connection warm                  ║
║  3. Periodic bot self-check                                        ║
║                                                                    ║
║  Fly.io checks /health every 15s — if it fails, restarts app.    ║
║  Neon serverless drops idle connections after ~5 minutes.          ║
║  DB ping every 60s keeps it alive.                                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
from datetime import datetime, timezone

from aiohttp import web

import db

logger = logging.getLogger("XAUUSD_Bot.keepalive")

# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------
_state = {
    "bot_running": False,
    "db_healthy": False,
    "last_db_ping": None,
    "last_health_check": None,
    "start_time": None,
    "total_pings": 0,
    "failed_pings": 0,
}


# ==========================================================================
# HTTP Health Server
# ==========================================================================
async def health_handler(
    request: web.Request,
) -> web.Response:
    """
    GET /health — Fly.io checks this every 15 seconds.
    Returns 200 if bot is running and DB is reachable.
    Returns 503 if something is wrong.
    """
    _state["last_health_check"] = (
        datetime.now(timezone.utc).isoformat()
    )

    # Quick DB check — don't block long
    try:
        db_ok = await asyncio.wait_for(
            db.ping(), timeout=5.0
        )
    except (asyncio.TimeoutError, Exception):
        db_ok = False

    _state["db_healthy"] = db_ok

    if _state["bot_running"] and db_ok:
        uptime = ""
        if _state["start_time"]:
            delta = (
                datetime.now(timezone.utc)
                - _state["start_time"]
            )
            hours = int(delta.total_seconds() // 3600)
            minutes = int(
                (delta.total_seconds() % 3600) // 60
            )
            uptime = f"{hours}h {minutes}m"

        body = (
            f"OK\n"
            f"bot: running\n"
            f"db: healthy\n"
            f"uptime: {uptime}\n"
            f"db_pings: {_state['total_pings']}\n"
            f"failed_pings: {_state['failed_pings']}\n"
        )
        return web.Response(
            text=body,
            status=200,
            content_type="text/plain",
        )
    else:
        body = (
            f"UNHEALTHY\n"
            f"bot: "
            f"{'running' if _state['bot_running'] else 'stopped'}\n"
            f"db: "
            f"{'healthy' if db_ok else 'unreachable'}\n"
        )
        return web.Response(
            text=body,
            status=503,
            content_type="text/plain",
        )


async def root_handler(
    request: web.Request,
) -> web.Response:
    """GET / — Simple info page."""
    return web.Response(
        text=(
            "XAUUSD & BTC/USD AI Analysis Bot v4.0\n"
            "Status: Running\n"
            "Health: /health\n"
        ),
        status=200,
        content_type="text/plain",
    )


async def start_health_server(
    port: int = 8080,
) -> web.AppRunner:
    """
    Start the aiohttp health server.
    Fly.io will hit /health to verify the app is alive.
    """
    app = web.Application()
    app.router.add_get("/", root_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(
        f"Health server started on port {port}"
    )
    return runner


# ==========================================================================
# Periodic DB Ping — keeps Neon connection warm
# ==========================================================================
async def db_keepalive_loop(
    interval: int = 60,
) -> None:
    """
    Ping Neon database every `interval` seconds.
    
    Why: Neon serverless suspends compute after ~5 min idle.
    The first query after suspension has a cold start delay.
    Pinging every 60s keeps the connection warm.
    """
    logger.info(
        f"DB keep-alive loop started "
        f"(interval: {interval}s)"
    )

    while True:
        try:
            await asyncio.sleep(interval)

            ok = await db.ping()
            _state["total_pings"] += 1
            _state["last_db_ping"] = (
                datetime.now(timezone.utc).isoformat()
            )

            if ok:
                _state["db_healthy"] = True
                # Log every 10th ping to reduce noise
                if _state["total_pings"] % 10 == 0:
                    logger.info(
                        f"DB ping OK "
                        f"(#{_state['total_pings']})"
                    )
            else:
                _state["db_healthy"] = False
                _state["failed_pings"] += 1
                logger.warning(
                    f"DB ping FAILED "
                    f"(#{_state['failed_pings']})"
                )

        except asyncio.CancelledError:
            logger.info("DB keep-alive loop cancelled")
            break
        except Exception as exc:
            _state["failed_pings"] += 1
            logger.error(
                f"DB keep-alive error: {exc}"
            )
            await asyncio.sleep(5)


# ==========================================================================
# Lifecycle helpers
# ==========================================================================
def set_bot_running(running: bool) -> None:
    """Update bot running state."""
    _state["bot_running"] = running
    if running:
        _state["start_time"] = datetime.now(
            timezone.utc
        )


def get_state() -> dict:
    """Return current keep-alive state for diagnostics."""
    return dict(_state)