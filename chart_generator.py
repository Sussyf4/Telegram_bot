#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                  MULTI-SYMBOL CHART GENERATOR                      ║
║                                                                    ║
║  Generates professional charts for any symbol.                     ║
║  Purely synchronous — runs inside run_in_executor().               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import io
import logging
from datetime import datetime, timezone
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

from symbols import SymbolConfig
from technical_engine import AdvancedTechnicalIndicators

logger = logging.getLogger("XAUUSD_Bot.chart")

# Chart constants
CHART_DPI = 150
CHART_FIGSIZE = (14, 12)
COLOR_GREEN = "#26a69a"
COLOR_RED = "#ef5350"
COLOR_BLUE = "#2196F3"
COLOR_ORANGE = "#FF9800"
COLOR_PURPLE = "#AB47BC"
COLOR_GREEN_B = "#4CAF50"
COLOR_RED_B = "#f44336"
COLOR_GOLD = "gold"
COLOR_WHITE = "white"
COLOR_GRAY = "gray"
COLOR_CYAN = "#00BCD4"


class MultiSymbolChartGenerator:

    @staticmethod
    def generate_chart(
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        timeframe: str,
    ) -> Optional[io.BytesIO]:
        if df is None or len(df) < 20:
            return None

        try:
            plt.style.use("dark_background")
            plot_df = df.tail(60).copy()

            fig, axes = plt.subplots(
                4, 1,
                figsize=CHART_FIGSIZE,
                gridspec_kw={
                    "height_ratios": [3, 1, 1, 0.8]
                },
                sharex=True,
            )

            title_color = (
                COLOR_GOLD
                if symbol.asset_type == "commodity"
                else COLOR_ORANGE
            )
            fig.suptitle(
                f"{symbol.emoji} {symbol.display_name}"
                f" — {timeframe} | "
                f"{ind.overall_bias} "
                f"({ind.confidence_score}%)",
                fontsize=15,
                fontweight="bold",
                color=title_color,
                y=0.98,
            )

            # ── Panel 1: Price + EMAs + Levels ────────
            ax1 = axes[0]
            ax1.plot(
                plot_df["datetime"],
                plot_df["close"],
                color=COLOR_WHITE,
                linewidth=1.5,
                label="Close",
                zorder=5,
            )
            ax1.fill_between(
                plot_df["datetime"],
                plot_df["low"],
                plot_df["high"],
                alpha=0.08,
                color=title_color,
            )

            # Candlesticks
            for _, row in plot_df.iterrows():
                clr = (
                    COLOR_GREEN
                    if row["close"] >= row["open"]
                    else COLOR_RED
                )
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [row["low"], row["high"]],
                    color=clr, linewidth=0.8, alpha=0.6,
                )
                bl = min(row["open"], row["close"])
                bh = max(row["open"], row["close"])
                ax1.plot(
                    [row["datetime"], row["datetime"]],
                    [bl, bh],
                    color=clr, linewidth=2.5,
                )

            # EMAs
            for col, color, label in [
                ("ema_9", COLOR_CYAN,
                 f"EMA9 ({ind.ema_9})"),
                ("ema_20", COLOR_BLUE,
                 f"EMA20 ({ind.ema_20})"),
                ("ema_50", COLOR_ORANGE,
                 f"EMA50 ({ind.ema_50})"),
            ]:
                if col in plot_df.columns:
                    ax1.plot(
                        plot_df["datetime"],
                        plot_df[col],
                        color=color, linewidth=1.0,
                        linestyle="--",
                        label=label, alpha=0.8,
                    )

            # Bollinger Bands
            if "bb_upper" in plot_df.columns:
                ax1.fill_between(
                    plot_df["datetime"],
                    plot_df["bb_upper"],
                    plot_df["bb_lower"],
                    alpha=0.05,
                    color=COLOR_PURPLE,
                    label="Bollinger Bands",
                )

            # Support / Resistance
            ax1.axhline(
                y=ind.support_1,
                color=COLOR_GREEN_B,
                linestyle=":", linewidth=1.0, alpha=0.8,
                label=f"S1 ({ind.support_1})",
            )
            ax1.axhline(
                y=ind.resistance_1,
                color=COLOR_RED_B,
                linestyle=":", linewidth=1.0, alpha=0.8,
                label=f"R1 ({ind.resistance_1})",
            )

            # VPOC
            if ind.vpoc > 0:
                ax1.axhline(
                    y=ind.vpoc,
                    color=COLOR_PURPLE,
                    linestyle="-.", linewidth=0.8,
                    alpha=0.6,
                    label=f"VPOC ({ind.vpoc})",
                )

            ax1.set_ylabel(
                "Price (USD)", fontsize=9,
                color=COLOR_WHITE,
            )
            ax1.legend(
                loc="upper left",
                fontsize=7, framealpha=0.3, ncol=2,
            )
            ax1.grid(True, alpha=0.12)

            # ── Panel 2: RSI + Stochastic ─────────────
            ax2 = axes[1]
            if "rsi" in plot_df.columns:
                ax2.plot(
                    plot_df["datetime"],
                    plot_df["rsi"],
                    color=COLOR_PURPLE, linewidth=1.3,
                    label=f"RSI ({ind.rsi:.1f})",
                )
            if "stoch_k" in plot_df.columns:
                ax2.plot(
                    plot_df["datetime"],
                    plot_df["stoch_k"],
                    color=COLOR_CYAN, linewidth=0.8,
                    linestyle="--",
                    label=f"Stoch K ({ind.stoch_k:.0f})",
                    alpha=0.7,
                )

            ax2.axhline(
                y=70, color=COLOR_RED_B,
                linestyle="--",
                linewidth=0.7, alpha=0.5,
            )
            ax2.axhline(
                y=30, color=COLOR_GREEN_B,
                linestyle="--",
                linewidth=0.7, alpha=0.5,
            )
            ax2.axhline(
                y=50, color=COLOR_GRAY,
                linestyle="-",
                linewidth=0.4, alpha=0.4,
            )
            ax2.set_ylabel(
                "RSI / Stoch", fontsize=9,
                color=COLOR_WHITE,
            )
            ax2.set_ylim(5, 95)
            ax2.legend(
                loc="upper left",
                fontsize=7, framealpha=0.3,
            )
            ax2.grid(True, alpha=0.12)

            # ── Panel 3: MACD ─────────────────────────
            ax3 = axes[2]
            if "macd_line" in plot_df.columns:
                ax3.plot(
                    plot_df["datetime"],
                    plot_df["macd_line"],
                    color=COLOR_BLUE, linewidth=1.1,
                    label="MACD",
                )
                ax3.plot(
                    plot_df["datetime"],
                    plot_df["macd_signal"],
                    color=COLOR_ORANGE, linewidth=1.1,
                    label="Signal",
                )
                hist_colors = [
                    COLOR_GREEN if v >= 0 else COLOR_RED
                    for v in plot_df["macd_histogram"]
                ]
                ax3.bar(
                    plot_df["datetime"],
                    plot_df["macd_histogram"],
                    color=hist_colors,
                    alpha=0.5, width=0.6,
                )
            ax3.axhline(
                y=0, color=COLOR_GRAY,
                linestyle="-",
                linewidth=0.4, alpha=0.4,
            )
            ax3.set_ylabel(
                "MACD", fontsize=9,
                color=COLOR_WHITE,
            )
            ax3.legend(
                loc="upper left",
                fontsize=7, framealpha=0.3,
            )
            ax3.grid(True, alpha=0.12)

            # ── Panel 4: Volume ───────────────────────
            ax4 = axes[3]
            if "volume" in plot_df.columns:
                vol_colors = [
                    COLOR_GREEN
                    if plot_df.iloc[i]["close"]
                    >= plot_df.iloc[i]["open"]
                    else COLOR_RED
                    for i in range(len(plot_df))
                ]
                ax4.bar(
                    plot_df["datetime"],
                    plot_df["volume"],
                    color=vol_colors, alpha=0.5,
                    width=0.6,
                )
                if "volume_sma_20" in plot_df.columns:
                    ax4.plot(
                        plot_df["datetime"],
                        plot_df["volume_sma_20"],
                        color=COLOR_ORANGE,
                        linewidth=0.8,
                        label="Vol SMA20",
                    )
            ax4.set_ylabel(
                "Volume", fontsize=9,
                color=COLOR_WHITE,
            )
            ax4.legend(
                loc="upper left",
                fontsize=7, framealpha=0.3,
            )
            ax4.grid(True, alpha=0.12)

            ax4.xaxis.set_major_formatter(
                mdates.DateFormatter("%m/%d %H:%M")
            )
            plt.xticks(rotation=45, fontsize=7)

            now_str = datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            fig.text(
                0.99, 0.01,
                f"Generated: {now_str}",
                ha="right", va="bottom",
                fontsize=6, color=COLOR_GRAY, alpha=0.5,
            )

            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(
                buf, format="png",
                dpi=CHART_DPI, bbox_inches="tight",
                facecolor=fig.get_facecolor(),
                edgecolor="none",
            )
            buf.seek(0)
            plt.close(fig)

            logger.info(
                f"Chart generated for "
                f"{symbol.display_name}"
            )
            return buf

        except Exception as exc:
            logger.error(
                f"Chart error for "
                f"{symbol.display_name}: {exc}"
            )
            plt.close("all")
            return None
