#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║               ADVANCED TECHNICAL ANALYSIS ENGINE                   ║
║                                                                    ║
║  Full indicator suite with combined signal interpretation.         ║
║  Produces actionable text insights alongside raw numbers.          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import ta

from symbols import SymbolConfig

logger = logging.getLogger("XAUUSD_Bot.technical")


# ==========================================================================
# Advanced Indicators Dataclass
# ==========================================================================
@dataclass
class AdvancedTechnicalIndicators:
    """Complete technical indicator suite."""

    # ── Price Context ─────────────────────────────────
    current_price: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    price_change: float = 0.0
    price_change_pct: float = 0.0

    # ── Trend Indicators ──────────────────────────────
    ema_9: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    ema_200: float = 0.0
    sma_50: float = 0.0
    sma_200: float = 0.0
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    ichimoku_a: float = 0.0
    ichimoku_b: float = 0.0

    # ── Momentum Indicators ───────────────────────────
    rsi: float = 0.0
    stoch_k: float = 0.0
    stoch_d: float = 0.0
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    williams_r: float = 0.0
    cci: float = 0.0
    mfi: float = 0.0

    # ── Volatility Indicators ─────────────────────────
    atr: float = 0.0
    atr_percent: float = 0.0
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0
    keltner_upper: float = 0.0
    keltner_lower: float = 0.0

    # ── Volume Analysis ───────────────────────────────
    volume: float = 0.0
    volume_sma_20: float = 0.0
    volume_ratio: float = 0.0
    obv: float = 0.0
    cumulative_delta: float = 0.0
    vwap: float = 0.0

    # ── Support / Resistance ──────────────────────────
    support_1: float = 0.0
    support_2: float = 0.0
    support_3: float = 0.0
    resistance_1: float = 0.0
    resistance_2: float = 0.0
    resistance_3: float = 0.0
    pivot_point: float = 0.0

    # Fibonacci levels
    fib_236: float = 0.0
    fib_382: float = 0.0
    fib_500: float = 0.0
    fib_618: float = 0.0
    fib_786: float = 0.0

    # Volume profile
    vpoc: float = 0.0
    high_volume_node_1: float = 0.0
    high_volume_node_2: float = 0.0

    # ── Interpretations ───────────────────────────────
    trend_direction: str = ""
    trend_strength: str = ""
    momentum_bias: str = ""
    volatility_condition: str = ""
    volume_analysis: str = ""
    market_structure: str = ""
    orderflow_bias: str = ""

    # ── Combined Signal ───────────────────────────────
    overall_bias: str = ""
    confidence_score: int = 0
    key_insight: str = ""
    action_levels: str = ""

    # ── Raw signal scores ─────────────────────────────
    bullish_signals: int = 0
    bearish_signals: int = 0
    neutral_signals: int = 0


# ==========================================================================
# Engine
# ==========================================================================
class AdvancedTechnicalEngine:
    """Compute all indicators and produce combined insights."""

    def compute(
        self,
        df: pd.DataFrame,
        symbol: SymbolConfig,
    ) -> tuple[pd.DataFrame, AdvancedTechnicalIndicators]:
        """Full computation pipeline."""
        ind = AdvancedTechnicalIndicators()

        if df is None or len(df) < 50:
            logger.warning(
                f"Insufficient data for "
                f"{symbol.display_name}: "
                f"{len(df) if df is not None else 0} rows"
            )
            return df, ind

        df = self._compute_all_indicators(df)
        ind = self._extract_latest(df, ind, symbol)
        ind = self._compute_support_resistance(df, ind)
        ind = self._compute_fibonacci(df, ind)
        ind = self._compute_volume_profile(df, ind)
        ind = self._interpret_signals(ind, symbol)

        return df, ind

    # ──────────────────────────────────────────────────
    # Step 1: Compute all raw indicators on DataFrame
    # ──────────────────────────────────────────────────
    def _compute_all_indicators(
        self, df: pd.DataFrame
    ) -> pd.DataFrame:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # EMAs
        df["ema_9"] = ta.trend.EMAIndicator(
            close=close, window=9
        ).ema_indicator()
        df["ema_20"] = ta.trend.EMAIndicator(
            close=close, window=20
        ).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(
            close=close, window=50
        ).ema_indicator()
        if len(df) >= 200:
            df["ema_200"] = ta.trend.EMAIndicator(
                close=close, window=200
            ).ema_indicator()
        else:
            df["ema_200"] = df["ema_50"]

        # SMAs
        df["sma_50"] = ta.trend.SMAIndicator(
            close=close, window=50
        ).sma_indicator()
        if len(df) >= 200:
            df["sma_200"] = ta.trend.SMAIndicator(
                close=close, window=200
            ).sma_indicator()
        else:
            df["sma_200"] = df["sma_50"]

        # ADX
        adx_calc = ta.trend.ADXIndicator(
            high=high, low=low, close=close, window=14
        )
        df["adx"] = adx_calc.adx()
        df["plus_di"] = adx_calc.adx_pos()
        df["minus_di"] = adx_calc.adx_neg()

        # Ichimoku
        ichi = ta.trend.IchimokuIndicator(
            high=high, low=low
        )
        df["ichimoku_a"] = ichi.ichimoku_a()
        df["ichimoku_b"] = ichi.ichimoku_b()

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(
            close=close, window=14
        ).rsi()

        # Stochastic
        stoch = ta.momentum.StochasticOscillator(
            high=high, low=low, close=close,
            window=14, smooth_window=3,
        )
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()

        # MACD
        macd = ta.trend.MACD(
            close=close,
            window_slow=26, window_fast=12,
            window_sign=9,
        )
        df["macd_line"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_histogram"] = macd.macd_diff()

        # Williams %R
        df["williams_r"] = (
            ta.momentum.WilliamsRIndicator(
                high=high, low=low, close=close,
                lbp=14,
            ).williams_r()
        )

        # CCI
        df["cci"] = ta.trend.CCIIndicator(
            high=high, low=low, close=close, window=20,
        ).cci()

        # MFI
        if volume.sum() > 0:
            df["mfi"] = (
                ta.volume.MFIIndicator(
                    high=high, low=low,
                    close=close, volume=volume,
                    window=14,
                ).money_flow_index()
            )
        else:
            df["mfi"] = 50.0

        # ATR
        df["atr"] = ta.volatility.AverageTrueRange(
            high=high, low=low, close=close, window=14,
        ).average_true_range()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=close, window=20, window_dev=2,
        )
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_width"] = bb.bollinger_wband()

        # Keltner Channels
        kc = ta.volatility.KeltnerChannel(
            high=high, low=low, close=close, window=20,
        )
        df["keltner_upper"] = kc.keltner_channel_hband()
        df["keltner_lower"] = kc.keltner_channel_lband()

        # Volume indicators
        if volume.sum() > 0:
            df["obv"] = ta.volume.OnBalanceVolumeIndicator(
                close=close, volume=volume,
            ).on_balance_volume()
            df["volume_sma_20"] = (
                volume.rolling(window=20).mean()
            )
        else:
            df["obv"] = 0
            df["volume_sma_20"] = 0

        # Cumulative delta approximation
        df["delta"] = (
            (close - df["open"])
            / (high - low + 0.0001)
        ) * volume
        df["cumulative_delta"] = df["delta"].cumsum()

        # VWAP approximation
        tp = (high + low + close) / 3
        df["vwap"] = (
            (tp * volume).cumsum()
            / (volume.cumsum() + 0.0001)
        )

        return df

    # ──────────────────────────────────────────────────
    # Step 2: Extract latest values
    # ──────────────────────────────────────────────────
    def _extract_latest(
        self,
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
    ) -> AdvancedTechnicalIndicators:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        dp = symbol.decimal_places

        def safe(val, decimals=dp):
            if pd.notna(val):
                return round(float(val), decimals)
            return 0.0

        # Price
        ind.current_price = safe(latest["close"])
        ind.open_price = safe(latest["open"])
        ind.high_price = safe(latest["high"])
        ind.low_price = safe(latest["low"])
        ind.price_change = safe(
            latest["close"] - prev["close"]
        )
        ind.price_change_pct = round(
            (ind.price_change / prev["close"]) * 100
            if prev["close"] > 0
            else 0.0,
            3,
        )

        # Trend
        ind.ema_9 = safe(latest["ema_9"])
        ind.ema_20 = safe(latest["ema_20"])
        ind.ema_50 = safe(latest["ema_50"])
        ind.ema_200 = safe(latest["ema_200"])
        ind.sma_50 = safe(latest["sma_50"])
        ind.sma_200 = safe(latest["sma_200"])
        ind.adx = safe(latest["adx"], 2)
        ind.plus_di = safe(latest["plus_di"], 2)
        ind.minus_di = safe(latest["minus_di"], 2)
        ind.ichimoku_a = safe(latest["ichimoku_a"])
        ind.ichimoku_b = safe(latest["ichimoku_b"])

        # Momentum
        ind.rsi = safe(latest["rsi"], 2)
        ind.stoch_k = safe(latest["stoch_k"], 2)
        ind.stoch_d = safe(latest["stoch_d"], 2)
        ind.macd_line = safe(latest["macd_line"], 4)
        ind.macd_signal = safe(latest["macd_signal"], 4)
        ind.macd_histogram = safe(
            latest["macd_histogram"], 4
        )
        ind.williams_r = safe(latest["williams_r"], 2)
        ind.cci = safe(latest["cci"], 2)
        ind.mfi = safe(latest["mfi"], 2)

        # Volatility
        ind.atr = safe(latest["atr"])
        ind.atr_percent = round(
            (ind.atr / ind.current_price * 100)
            if ind.current_price > 0
            else 0.0,
            3,
        )
        ind.bb_upper = safe(latest["bb_upper"])
        ind.bb_middle = safe(latest["bb_middle"])
        ind.bb_lower = safe(latest["bb_lower"])
        ind.bb_width = safe(latest["bb_width"], 4)
        ind.keltner_upper = safe(latest["keltner_upper"])
        ind.keltner_lower = safe(latest["keltner_lower"])

        # Volume
        ind.volume = safe(latest["volume"], 0)
        ind.volume_sma_20 = safe(
            latest["volume_sma_20"], 0
        )
        ind.volume_ratio = round(
            ind.volume / ind.volume_sma_20
            if ind.volume_sma_20 > 0
            else 0.0,
            2,
        )
        ind.obv = safe(latest["obv"], 0)
        ind.cumulative_delta = safe(
            latest["cumulative_delta"], 0
        )
        ind.vwap = safe(latest["vwap"])

        return ind

    # ──────────────────────────────────────────────────
    # Step 3: Support / Resistance via Pivot Points
    # ──────────────────────────────────────────────────
    def _compute_support_resistance(
        self,
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
    ) -> AdvancedTechnicalIndicators:
        # Use last completed session's H/L/C
        recent = df.tail(20)
        h = recent["high"].max()
        l = recent["low"].min()
        c = df.iloc[-1]["close"]

        # Classic pivot
        pp = (h + l + c) / 3
        ind.pivot_point = round(pp, 2)

        ind.resistance_1 = round(2 * pp - l, 2)
        ind.resistance_2 = round(pp + (h - l), 2)
        ind.resistance_3 = round(
            h + 2 * (pp - l), 2
        )

        ind.support_1 = round(2 * pp - h, 2)
        ind.support_2 = round(pp - (h - l), 2)
        ind.support_3 = round(l - 2 * (h - pp), 2)

        # Override with swing detection if available
        swing_sup, swing_res = self._swing_levels(df)
        if swing_sup > 0:
            ind.support_1 = round(swing_sup, 2)
        if swing_res > 0:
            ind.resistance_1 = round(swing_res, 2)

        return ind

    def _swing_levels(
        self, df: pd.DataFrame, window: int = 10
    ) -> tuple[float, float]:
        if len(df) < window * 2:
            return 0.0, 0.0

        recent = df.tail(60).copy()
        swing_lows = []
        swing_highs = []

        for i in range(window, len(recent) - window):
            seg = recent.iloc[i - window: i + window + 1]
            if recent.iloc[i]["low"] == seg["low"].min():
                swing_lows.append(recent.iloc[i]["low"])
            if recent.iloc[i]["high"] == seg["high"].max():
                swing_highs.append(recent.iloc[i]["high"])

        support = (
            max(swing_lows[-3:]) if swing_lows else 0.0
        )
        resistance = (
            min(swing_highs[-3:]) if swing_highs else 0.0
        )
        return support, resistance

    # ──────────────────────────────────────────────────
    # Step 4: Fibonacci Retracement
    # ──────────────────────────────────────────────────
    def _compute_fibonacci(
        self,
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
    ) -> AdvancedTechnicalIndicators:
        recent = df.tail(60)
        swing_high = recent["high"].max()
        swing_low = recent["low"].min()
        diff = swing_high - swing_low

        # If price is in uptrend, fibs from low
        if ind.current_price > ind.ema_50:
            ind.fib_236 = round(
                swing_high - 0.236 * diff, 2
            )
            ind.fib_382 = round(
                swing_high - 0.382 * diff, 2
            )
            ind.fib_500 = round(
                swing_high - 0.500 * diff, 2
            )
            ind.fib_618 = round(
                swing_high - 0.618 * diff, 2
            )
            ind.fib_786 = round(
                swing_high - 0.786 * diff, 2
            )
        else:
            ind.fib_236 = round(
                swing_low + 0.236 * diff, 2
            )
            ind.fib_382 = round(
                swing_low + 0.382 * diff, 2
            )
            ind.fib_500 = round(
                swing_low + 0.500 * diff, 2
            )
            ind.fib_618 = round(
                swing_low + 0.618 * diff, 2
            )
            ind.fib_786 = round(
                swing_low + 0.786 * diff, 2
            )

        return ind

    # ──────────────────────────────────────────────────
    # Step 5: Volume Profile Approximation
    # ──────────────────────────────────────────────────
    def _compute_volume_profile(
        self,
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
    ) -> AdvancedTechnicalIndicators:
        recent = df.tail(60).copy()

        if recent["volume"].sum() == 0:
            ind.vpoc = ind.current_price
            ind.high_volume_node_1 = ind.support_1
            ind.high_volume_node_2 = ind.resistance_1
            return ind

        price_range = (
            recent["high"].max() - recent["low"].min()
        )
        if price_range <= 0:
            return ind

        n_bins = 30
        bins = np.linspace(
            recent["low"].min(),
            recent["high"].max(),
            n_bins + 1,
        )

        vol_profile = np.zeros(n_bins)
        for _, row in recent.iterrows():
            for j in range(n_bins):
                if bins[j] <= row["close"] <= bins[j + 1]:
                    vol_profile[j] += row["volume"]
                    break

        if vol_profile.sum() > 0:
            vpoc_idx = np.argmax(vol_profile)
            ind.vpoc = round(
                (bins[vpoc_idx] + bins[vpoc_idx + 1]) / 2,
                2,
            )

            sorted_idx = np.argsort(vol_profile)[::-1]
            if len(sorted_idx) > 1:
                hvn1_idx = sorted_idx[1]
                ind.high_volume_node_1 = round(
                    (bins[hvn1_idx] + bins[hvn1_idx + 1])
                    / 2,
                    2,
                )
            if len(sorted_idx) > 2:
                hvn2_idx = sorted_idx[2]
                ind.high_volume_node_2 = round(
                    (bins[hvn2_idx] + bins[hvn2_idx + 1])
                    / 2,
                    2,
                )

        return ind

    # ──────────────────────────────────────────────────
    # Step 6: Combined Signal Interpretation
    # ──────────────────────────────────────────────────
    def _interpret_signals(
        self,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
    ) -> AdvancedTechnicalIndicators:
        bullish = 0
        bearish = 0
        neutral = 0

        # ── Trend (RSI + EMA + ADX) ──────────────────
        # EMA alignment
        ema_bull = (
            ind.ema_9 > ind.ema_20 > ind.ema_50
        )
        ema_bear = (
            ind.ema_9 < ind.ema_20 < ind.ema_50
        )

        if ema_bull:
            bullish += 2
        elif ema_bear:
            bearish += 2
        else:
            neutral += 1

        # ADX trend strength
        if ind.adx > 25:
            if ind.plus_di > ind.minus_di:
                bullish += 2
                trend_str = "Strong"
            else:
                bearish += 2
                trend_str = "Strong"
        elif ind.adx > 20:
            trend_str = "Moderate"
            if ind.plus_di > ind.minus_di:
                bullish += 1
            else:
                bearish += 1
        else:
            trend_str = "Weak/Ranging"
            neutral += 1

        # RSI
        if ind.rsi > 70:
            bearish += 1  # overbought = reversal risk
            rsi_note = "Overbought"
        elif ind.rsi > 60:
            bullish += 1
            rsi_note = "Bullish Momentum"
        elif ind.rsi > 40:
            neutral += 1
            rsi_note = "Neutral"
        elif ind.rsi > 30:
            bearish += 1
            rsi_note = "Bearish Momentum"
        else:
            bullish += 1  # oversold = bounce potential
            rsi_note = "Oversold"

        # Golden/Death cross
        if ind.sma_50 > ind.sma_200:
            bullish += 1
            cross_note = "Golden Cross active"
        elif ind.sma_50 < ind.sma_200:
            bearish += 1
            cross_note = "Death Cross active"
        else:
            cross_note = "No major cross"

        # Price vs Ichimoku cloud
        if (
            ind.current_price > ind.ichimoku_a
            and ind.current_price > ind.ichimoku_b
        ):
            bullish += 1
            cloud_note = "Above cloud"
        elif (
            ind.current_price < ind.ichimoku_a
            and ind.current_price < ind.ichimoku_b
        ):
            bearish += 1
            cloud_note = "Below cloud"
        else:
            neutral += 1
            cloud_note = "Inside cloud"

        if ema_bull and ind.adx > 25:
            ind.trend_direction = "Strong Uptrend"
        elif ema_bear and ind.adx > 25:
            ind.trend_direction = "Strong Downtrend"
        elif ema_bull:
            ind.trend_direction = "Uptrend"
        elif ema_bear:
            ind.trend_direction = "Downtrend"
        else:
            ind.trend_direction = "Ranging/Choppy"

        ind.trend_strength = (
            f"{trend_str} (ADX: {ind.adx:.1f}, "
            f"+DI: {ind.plus_di:.1f}, "
            f"-DI: {ind.minus_di:.1f})"
        )

        # ── Momentum (MACD + Stoch + CCI) ────────────
        if ind.macd_histogram > 0:
            bullish += 1
            macd_note = "Bullish"
            if ind.macd_line > ind.macd_signal:
                bullish += 1
                macd_note = "Strong Bullish"
        elif ind.macd_histogram < 0:
            bearish += 1
            macd_note = "Bearish"
            if ind.macd_line < ind.macd_signal:
                bearish += 1
                macd_note = "Strong Bearish"
        else:
            neutral += 1
            macd_note = "Neutral"

        if ind.stoch_k > 80:
            bearish += 1
        elif ind.stoch_k < 20:
            bullish += 1
        else:
            neutral += 1

        if ind.cci > 100:
            bullish += 1
        elif ind.cci < -100:
            bearish += 1
        else:
            neutral += 1

        if ind.cumulative_delta > 0:
            bullish += 1
            delta_note = "Net buying pressure"
        elif ind.cumulative_delta < 0:
            bearish += 1
            delta_note = "Net selling pressure"
        else:
            neutral += 1
            delta_note = "Balanced flow"

        ind.momentum_bias = (
            f"MACD: {macd_note}, "
            f"RSI: {rsi_note}, "
            f"Stoch: {ind.stoch_k:.0f}K/"
            f"{ind.stoch_d:.0f}D, "
            f"CCI: {ind.cci:.0f}"
        )

        # ── Volatility ───────────────────────────────
        atr_pct = ind.atr_percent
        if atr_pct > symbol.typical_atr_pct * 1.5:
            vol_state = "Very High"
        elif atr_pct > symbol.typical_atr_pct:
            vol_state = "High"
        elif atr_pct > symbol.typical_atr_pct * 0.5:
            vol_state = "Moderate"
        else:
            vol_state = "Low"

        # Bollinger squeeze detection
        squeeze = (
            ind.bb_upper < ind.keltner_upper
            and ind.bb_lower > ind.keltner_lower
        )
        squeeze_note = (
            "⚡ Squeeze detected (breakout imminent)"
            if squeeze
            else "No squeeze"
        )

        ind.volatility_condition = (
            f"{vol_state} Volatility "
            f"(ATR: {ind.atr:.2f}, "
            f"{ind.atr_percent:.2f}%), "
            f"{squeeze_note}"
        )

        # ── Volume ────────────────────────────────────
        if ind.volume_ratio > 1.5:
            vol_note = "High volume (confirming)"
            if bullish > bearish:
                bullish += 1
            else:
                bearish += 1
        elif ind.volume_ratio > 1.0:
            vol_note = "Above average volume"
        elif ind.volume_ratio > 0.5:
            vol_note = "Below average volume"
        else:
            vol_note = "Low volume (caution)"

        price_vs_vwap = (
            "above" if ind.current_price > ind.vwap
            else "below"
        )
        ind.volume_analysis = (
            f"{vol_note} "
            f"(ratio: {ind.volume_ratio:.1f}x), "
            f"Price {price_vs_vwap} VWAP "
            f"({ind.vwap:.2f})"
        )

        # ── Market Structure ──────────────────────────
        ind.market_structure = (
            f"{ind.trend_direction}, "
            f"{cloud_note}, "
            f"{cross_note}"
        )

        # ── Orderflow Bias ────────────────────────────
        ind.orderflow_bias = (
            f"{delta_note}, "
            f"MFI: {ind.mfi:.0f}, "
            f"OBV trend: "
            f"{'Rising' if ind.obv > 0 else 'Falling'}"
        )

        # ── Combined Score ────────────────────────────
        ind.bullish_signals = bullish
        ind.bearish_signals = bearish
        ind.neutral_signals = neutral
        total = bullish + bearish + neutral

        if total > 0:
            confidence = abs(bullish - bearish) / total
            ind.confidence_score = min(
                round(confidence * 100), 95
            )
        else:
            ind.confidence_score = 0

        if bullish > bearish + 2:
            ind.overall_bias = "Strong Bullish"
        elif bullish > bearish:
            ind.overall_bias = "Bullish"
        elif bearish > bullish + 2:
            ind.overall_bias = "Strong Bearish"
        elif bearish > bullish:
            ind.overall_bias = "Bearish"
        else:
            ind.overall_bias = "Neutral"

        # ── Key Insight ───────────────────────────────
        ind.key_insight = self._build_insight(ind, symbol)
        ind.action_levels = self._build_action_levels(ind)

        return ind

    def _build_insight(
        self,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
    ) -> str:
        parts = []
        parts.append(
            f"{ind.trend_direction} confirmed"
        )

        if "Bullish" in ind.overall_bias:
            parts.append("buy bias")
        elif "Bearish" in ind.overall_bias:
            parts.append("sell bias")
        else:
            parts.append("neutral bias — wait")

        parts.append(
            f"key support at {ind.support_1}"
        )
        parts.append(
            f"resistance at {ind.resistance_1}"
        )

        if ind.adx > 25:
            parts.append("strong trend momentum")
        if ind.rsi > 70 or ind.rsi < 30:
            parts.append(
                "extreme RSI — reversal risk"
            )

        return ", ".join(parts) + "."

    def _build_action_levels(
        self, ind: AdvancedTechnicalIndicators
    ) -> str:
        if "Bullish" in ind.overall_bias:
            return (
                f"Buy zone: {ind.support_1}-"
                f"{ind.fib_382}, "
                f"SL: {ind.support_2}, "
                f"TP1: {ind.resistance_1}, "
                f"TP2: {ind.resistance_2}"
            )
        elif "Bearish" in ind.overall_bias:
            return (
                f"Sell zone: {ind.resistance_1}-"
                f"{ind.fib_618}, "
                f"SL: {ind.resistance_2}, "
                f"TP1: {ind.support_1}, "
                f"TP2: {ind.support_2}"
            )
        else:
            return (
                f"Wait for breakout. "
                f"Watch: {ind.support_1} support, "
                f"{ind.resistance_1} resistance"
            )
