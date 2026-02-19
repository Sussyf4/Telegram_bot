#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    ENHANCED AI ANALYZER v4.1                       ║
║                                                                    ║
║  FIXED: Fallback logic respects bias direction for SL/TP.          ║
║  FIXED: Parser handles action_levels embedded in entry.            ║
║  Purely synchronous — runs inside run_in_executor().               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import re
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from google import genai
from google.genai import types

from symbols import SymbolConfig
from technical_engine import AdvancedTechnicalIndicators
from fundamental_engine import FundamentalData

logger = logging.getLogger("XAUUSD_Bot.ai")

GEMINI_MODEL = "gemini-2.5-flash"


@dataclass
class AIAnalysis:
    bias: str = "N/A"
    trade_idea: str = "N/A"
    entry: str = "N/A"
    stop_loss: str = "N/A"
    take_profit_1: str = "N/A"
    take_profit_2: str = "N/A"
    risk_note: str = "N/A"
    short_term_outlook: str = "N/A"
    fundamental_note: str = "N/A"
    combined_verdict: str = "N/A"
    raw_response: str = ""


class EnhancedAIAnalyzer:
    """Gemini AI with combined tech + fundamental prompts."""

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = GEMINI_MODEL
        self._max_retries = 3
        self._retry_delay = 2.0
        logger.info(
            f"Enhanced AI Analyzer initialized | "
            f"model: {self.model_name}"
        )

    def generate_analysis(
        self,
        df: pd.DataFrame,
        indicators: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        timeframe: str,
        fundamental: Optional[FundamentalData] = None,
    ) -> AIAnalysis:
        """Generate combined AI analysis."""
        analysis = AIAnalysis()

        if df is None or len(df) < 10:
            analysis.raw_response = (
                "Insufficient data for analysis."
            )
            return analysis

        prompt = self._build_combined_prompt(
            df, indicators, symbol, timeframe, fundamental
        )

        last_error = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(
                    f"AI request attempt "
                    f"{attempt}/{self._max_retries} "
                    f"for {symbol.display_name}..."
                )

                response = (
                    self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.3,
                            max_output_tokens=1500,
                        ),
                    )
                )

                raw_text = response.text

                if (
                    not raw_text
                    or len(raw_text.strip()) < 20
                ):
                    last_error = "Empty response"
                    if attempt < self._max_retries:
                        time.sleep(
                            self._retry_delay * attempt
                        )
                    continue

                analysis.raw_response = raw_text
                analysis = self._parse_response(
                    raw_text, analysis
                )

                # Validate critical fields
                if analysis.bias not in (
                    "N/A", "Error", ""
                ):
                    # Extra validation: ensure SL/TP
                    # make sense for the bias direction
                    analysis = self._validate_levels(
                        analysis, indicators
                    )
                    logger.info(
                        f"AI parsed OK: "
                        f"bias={analysis.bias}, "
                        f"trade={analysis.trade_idea}"
                    )
                    return analysis

                if attempt < self._max_retries:
                    time.sleep(
                        self._retry_delay * attempt
                    )

            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    f"AI attempt {attempt} failed: {exc}"
                )
                logger.debug(traceback.format_exc())
                if attempt < self._max_retries:
                    time.sleep(
                        self._retry_delay * attempt
                    )

        logger.error(
            f"All AI attempts failed: {last_error}"
        )
        return self._generate_fallback(
            indicators, symbol, fundamental
        )

    # ──────────────────────────────────────────────────
    # Prompt Builder
    # ──────────────────────────────────────────────────
    def _build_combined_prompt(
        self,
        df: pd.DataFrame,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        timeframe: str,
        fund: Optional[FundamentalData],
    ) -> str:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price_change = latest["close"] - prev["close"]
        price_change_pct = (
            (price_change / prev["close"]) * 100
            if prev["close"] > 0
            else 0
        )

        last_5 = ", ".join(
            [f"{c:.2f}" for c in
             df["close"].tail(5).tolist()]
        )

        prompt = (
            f"You are a senior {symbol.display_name} "
            f"analyst. Analyze this combined data.\n\n"
            f"=== MARKET DATA — "
            f"{symbol.display_name} ({timeframe}) ===\n"
            f"Current: {latest['close']:.2f}\n"
            f"Open: {latest['open']:.2f}\n"
            f"High: {latest['high']:.2f}\n"
            f"Low: {latest['low']:.2f}\n"
            f"Change: {price_change:+.2f} "
            f"({price_change_pct:+.3f}%)\n"
            f"Last 5 closes: {last_5}\n\n"
            f"=== TECHNICAL INDICATORS ===\n"
            f"Trend: {ind.trend_direction} "
            f"(ADX {ind.adx:.1f})\n"
            f"EMA9: {ind.ema_9}, EMA20: {ind.ema_20}, "
            f"EMA50: {ind.ema_50}\n"
            f"RSI(14): {ind.rsi} "
            f"| Stoch: {ind.stoch_k:.0f}K/"
            f"{ind.stoch_d:.0f}D\n"
            f"MACD Hist: {ind.macd_histogram:.4f}\n"
            f"ATR: {ind.atr} ({ind.atr_percent:.2f}%)\n"
            f"Support S1: {ind.support_1}, "
            f"S2: {ind.support_2}\n"
            f"Resistance R1: {ind.resistance_1}, "
            f"R2: {ind.resistance_2}\n"
            f"Pivot: {ind.pivot_point}\n"
            f"Fib 38.2%: {ind.fib_382}, "
            f"Fib 61.8%: {ind.fib_618}\n"
            f"VPOC: {ind.vpoc}\n"
            f"VWAP: {ind.vwap}\n"
            f"Volume ratio: {ind.volume_ratio:.1f}x\n"
            f"Overall Signal: {ind.overall_bias} "
            f"({ind.confidence_score}% confidence)\n\n"
        )

        if fund:
            prompt += "=== FUNDAMENTAL DATA ===\n"
            if symbol.asset_type == "crypto":
                prompt += (
                    f"Fear & Greed: "
                    f"{fund.fear_greed_index} "
                    f"({fund.fear_greed_label})\n"
                    f"Market Cap: "
                    f"{fund.btc_market_cap}\n"
                    f"24h Volume: "
                    f"{fund.btc_24h_volume}\n"
                    f"Hashrate: "
                    f"{fund.btc_hashrate}\n"
                    f"BTC Dominance: "
                    f"{fund.btc_dominance}\n"
                )
            else:
                prompt += (
                    f"DXY: {fund.dxy_index}\n"
                    f"Fed Rate: {fund.fed_rate}\n"
                    f"CPI YoY: {fund.us_cpi_yoy}\n"
                    f"ETF Flows: "
                    f"{fund.gold_etf_flows}\n"
                    f"Central Banks: "
                    f"{fund.central_bank_buying}\n"
                )

            if fund.key_drivers:
                prompt += (
                    f"Key Drivers: "
                    f"{'; '.join(fund.key_drivers)}\n"
                )
            if fund.risk_factors:
                prompt += (
                    f"Risk Factors: "
                    f"{'; '.join(fund.risk_factors)}\n"
                )
            prompt += (
                f"Fundamental Bias: "
                f"{fund.fundamental_bias}\n\n"
            )

        prompt += (
            "RESPOND IN EXACTLY THIS FORMAT "
            "(each field on its own line, "
            "use ONLY specific price numbers):\n\n"
            "BIAS: Bullish or Bearish or Neutral\n"
            "TRADE: Buy or Sell or Wait\n"
            "ENTRY: <lower_price>-<upper_price>\n"
            "STOP_LOSS: <single_price>\n"
            "TP1: <single_price>\n"
            "TP2: <single_price>\n"
            "RISK: One sentence.\n"
            "OUTLOOK: One-two sentences.\n"
            "FUNDAMENTAL: One sentence on macro impact.\n"
            "VERDICT: One sentence combining "
            "technical+fundamental.\n\n"
            "CRITICAL RULES:\n"
            "- For ENTRY, STOP_LOSS, TP1, TP2: "
            "use ONLY numbers (e.g. 2350.00)\n"
            "- Do NOT put text like 'Sell zone:' "
            "in the ENTRY field\n"
            "- Do NOT repeat SL or TP values "
            "in the ENTRY field\n"
            "- ENTRY must be just a price range: "
            "e.g. 2350.00-2355.00\n"
            "- STOP_LOSS must be a single number "
            "above entry for Sell, below entry for Buy\n"
            "- TP1 must be BELOW entry for Sell, "
            "ABOVE entry for Buy\n"
            "- TP2 must be further than TP1 "
            "in the trade direction\n"
            "- For Sell: SL > Entry > TP1 > TP2\n"
            "- For Buy: SL < Entry < TP1 < TP2\n"
            "- Account for ATR in stop loss distance\n"
            "- If unclear, recommend Wait\n"
            "- NO markdown formatting\n"
            "- Each field on its own line\n"
        )
        return prompt

    # ──────────────────────────────────────────────────
    # Response Parser
    # ──────────────────────────────────────────────────
    def _parse_response(
        self, text: str, analysis: AIAnalysis
    ) -> AIAnalysis:
        if not text:
            return analysis

        text = (
            text.replace("**", "")
            .replace("*", "")
            .replace("```", "")
        )

        field_map = {
            "BIAS": "bias",
            "MARKET BIAS": "bias",
            "TRADE": "trade_idea",
            "TRADE IDEA": "trade_idea",
            "ACTION": "trade_idea",
            "SIGNAL": "trade_idea",
            "ENTRY": "entry",
            "ENTRY ZONE": "entry",
            "ENTRY PRICE": "entry",
            "STOP_LOSS": "stop_loss",
            "STOP LOSS": "stop_loss",
            "SL": "stop_loss",
            "STOPLOSS": "stop_loss",
            "TP1": "take_profit_1",
            "TAKE PROFIT 1": "take_profit_1",
            "TARGET 1": "take_profit_1",
            "TP2": "take_profit_2",
            "TAKE PROFIT 2": "take_profit_2",
            "TARGET 2": "take_profit_2",
            "RISK": "risk_note",
            "RISK NOTE": "risk_note",
            "RISK ASSESSMENT": "risk_note",
            "OUTLOOK": "short_term_outlook",
            "SHORT TERM OUTLOOK": "short_term_outlook",
            "SHORT-TERM OUTLOOK": "short_term_outlook",
            "FUNDAMENTAL": "fundamental_note",
            "FUNDAMENTAL NOTE": "fundamental_note",
            "VERDICT": "combined_verdict",
            "COMBINED VERDICT": "combined_verdict",
        }

        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            key = parts[0].strip().upper()
            value = parts[1].strip()

            if value and key in field_map:
                setattr(
                    analysis, field_map[key], value
                )

        # ── Post-parse cleanup ────────────────────────
        # Clean entry field: strip text prefixes
        analysis.entry = self._clean_entry(
            analysis.entry
        )

        # Clean SL/TP: extract just the number
        analysis.stop_loss = self._extract_price(
            analysis.stop_loss
        )
        analysis.take_profit_1 = self._extract_price(
            analysis.take_profit_1
        )
        analysis.take_profit_2 = self._extract_price(
            analysis.take_profit_2
        )

        return analysis

    def _clean_entry(self, entry: str) -> str:
        """
        Clean entry field.
        Remove text like 'Sell zone:', 'Buy zone:',
        'SL:', 'TP1:', etc. Keep only the price range.
        """
        if entry in ("N/A", ""):
            return entry

        # If entry contains embedded SL/TP info,
        # extract just the price range
        # Pattern: "Sell zone: 1234-5678, SL: ..., TP1: ..."
        # We want just "1234-5678"

        # Try to find a price range pattern first
        range_match = re.search(
            r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)',
            entry,
        )
        if range_match:
            return (
                f"{range_match.group(1)}-"
                f"{range_match.group(2)}"
            )

        # Try single price
        single_match = re.search(
            r'(\d+\.?\d+)', entry
        )
        if single_match:
            return single_match.group(1)

        return entry

    def _extract_price(self, value: str) -> str:
        """
        Extract a clean price number from a field.
        Handles cases like 'around 2350.00',
        '\$2350.00', etc.
        """
        if value in ("N/A", ""):
            return value

        # Find first decimal number pattern
        match = re.search(r'(\d+\.?\d*)', value)
        if match:
            return match.group(1)

        return value

    # ──────────────────────────────────────────────────
    # Validate SL/TP Direction
    # ──────────────────────────────────────────────────
    def _validate_levels(
        self,
        analysis: AIAnalysis,
        ind: AdvancedTechnicalIndicators,
    ) -> AIAnalysis:
        """
        Validate that SL/TP make directional sense.
        For Sell: SL > entry > TP1 > TP2
        For Buy:  SL < entry < TP1 < TP2
        If wrong, recalculate from indicators + ATR.
        """
        try:
            # Parse entry midpoint
            entry_mid = self._get_entry_midpoint(
                analysis.entry
            )
            sl = self._parse_float(analysis.stop_loss)
            tp1 = self._parse_float(
                analysis.take_profit_1
            )
            tp2 = self._parse_float(
                analysis.take_profit_2
            )

            if entry_mid is None:
                entry_mid = ind.current_price

            is_sell = (
                "sell" in analysis.trade_idea.lower()
                or "bearish" in analysis.bias.lower()
            )
            is_buy = (
                "buy" in analysis.trade_idea.lower()
                or "bullish" in analysis.bias.lower()
            )

            needs_fix = False

            if is_sell:
                # SL should be ABOVE entry
                # TP1, TP2 should be BELOW entry
                # TP2 < TP1 < entry < SL
                if sl is not None and sl < entry_mid:
                    needs_fix = True
                    logger.warning(
                        f"SELL but SL({sl}) < "
                        f"Entry({entry_mid})"
                    )
                if tp1 is not None and tp1 > entry_mid:
                    needs_fix = True
                    logger.warning(
                        f"SELL but TP1({tp1}) > "
                        f"Entry({entry_mid})"
                    )
                if tp2 is not None and tp1 is not None:
                    if tp2 > tp1:
                        needs_fix = True
                        logger.warning(
                            f"SELL but TP2({tp2}) > "
                            f"TP1({tp1})"
                        )

            elif is_buy:
                # SL should be BELOW entry
                # TP1, TP2 should be ABOVE entry
                # SL < entry < TP1 < TP2
                if sl is not None and sl > entry_mid:
                    needs_fix = True
                    logger.warning(
                        f"BUY but SL({sl}) > "
                        f"Entry({entry_mid})"
                    )
                if tp1 is not None and tp1 < entry_mid:
                    needs_fix = True
                    logger.warning(
                        f"BUY but TP1({tp1}) < "
                        f"Entry({entry_mid})"
                    )
                if tp2 is not None and tp1 is not None:
                    if tp2 < tp1:
                        needs_fix = True
                        logger.warning(
                            f"BUY but TP2({tp2}) < "
                            f"TP1({tp1})"
                        )

            if needs_fix:
                logger.info(
                    "Recalculating SL/TP from "
                    "indicators..."
                )
                analysis = self._fix_levels_from_indicators(
                    analysis, ind, entry_mid,
                    is_sell, is_buy,
                )

        except Exception as exc:
            logger.warning(
                f"Level validation error: {exc}"
            )

        return analysis

    def _fix_levels_from_indicators(
        self,
        analysis: AIAnalysis,
        ind: AdvancedTechnicalIndicators,
        entry_mid: float,
        is_sell: bool,
        is_buy: bool,
    ) -> AIAnalysis:
        """Recalculate SL/TP using ATR and S/R levels."""
        atr = ind.atr if ind.atr > 0 else 1.0

        if is_sell:
            # SELL: SL above, TPs below
            sl = entry_mid + atr * 1.5
            tp1 = entry_mid - atr * 1.5
            tp2 = entry_mid - atr * 2.5

            # Prefer indicator levels if they
            # make directional sense
            if ind.resistance_1 > entry_mid:
                sl = ind.resistance_1 + atr * 0.3
            if ind.support_1 < entry_mid:
                tp1 = ind.support_1
            if ind.support_2 < tp1:
                tp2 = ind.support_2

            analysis.stop_loss = f"{sl:.2f}"
            analysis.take_profit_1 = f"{tp1:.2f}"
            analysis.take_profit_2 = f"{tp2:.2f}"

            logger.info(
                f"SELL fixed: SL={sl:.2f}, "
                f"TP1={tp1:.2f}, TP2={tp2:.2f}"
            )

        elif is_buy:
            # BUY: SL below, TPs above
            sl = entry_mid - atr * 1.5
            tp1 = entry_mid + atr * 1.5
            tp2 = entry_mid + atr * 2.5

            # Prefer indicator levels
            if ind.support_1 < entry_mid:
                sl = ind.support_1 - atr * 0.3
            if ind.resistance_1 > entry_mid:
                tp1 = ind.resistance_1
            if ind.resistance_2 > tp1:
                tp2 = ind.resistance_2

            analysis.stop_loss = f"{sl:.2f}"
            analysis.take_profit_1 = f"{tp1:.2f}"
            analysis.take_profit_2 = f"{tp2:.2f}"

            logger.info(
                f"BUY fixed: SL={sl:.2f}, "
                f"TP1={tp1:.2f}, TP2={tp2:.2f}"
            )

        return analysis

    def _get_entry_midpoint(
        self, entry: str
    ) -> Optional[float]:
        """Extract midpoint from entry range."""
        if not entry or entry == "N/A":
            return None

        # Try range: "1234.56-1240.00"
        range_match = re.search(
            r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)',
            entry,
        )
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            return (low + high) / 2

        # Try single price
        single_match = re.search(
            r'(\d+\.?\d+)', entry
        )
        if single_match:
            return float(single_match.group(1))

        return None

    def _parse_float(
        self, value: str
    ) -> Optional[float]:
        """Safely parse a price string to float."""
        if not value or value == "N/A":
            return None
        match = re.search(r'(\d+\.?\d*)', value)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    # ──────────────────────────────────────────────────
    # Fallback Generator (DIRECTION-AWARE)
    # ──────────────────────────────────────────────────
    def _generate_fallback(
        self,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        fund: Optional[FundamentalData],
    ) -> AIAnalysis:
        """
        Generate analysis from indicators when AI fails.
        CRITICAL: SL/TP must respect trade direction.
        """
        logger.warning(
            "Generating fallback analysis from indicators"
        )
        analysis = AIAnalysis()
        price = ind.current_price
        atr = ind.atr if ind.atr > 0 else 1.0

        is_bullish = "Bullish" in ind.overall_bias
        is_bearish = "Bearish" in ind.overall_bias

        if is_bullish:
            analysis.bias = "Bullish (Indicator-Based)"
            analysis.trade_idea = "Buy"

            # Entry: near current price / pullback zone
            entry_low = price - atr * 0.3
            entry_high = price
            analysis.entry = (
                f"{entry_low:.2f}-{entry_high:.2f}"
            )
            entry_mid = (entry_low + entry_high) / 2

            # BUY: SL below entry, TPs above entry
            # SL < entry < TP1 < TP2
            sl = ind.support_1 - atr * 0.3
            if sl >= entry_mid:
                sl = entry_mid - atr * 1.5

            tp1 = ind.resistance_1
            if tp1 <= entry_mid:
                tp1 = entry_mid + atr * 1.5

            tp2 = ind.resistance_2
            if tp2 <= tp1:
                tp2 = entry_mid + atr * 2.5

            analysis.stop_loss = f"{sl:.2f}"
            analysis.take_profit_1 = f"{tp1:.2f}"
            analysis.take_profit_2 = f"{tp2:.2f}"

        elif is_bearish:
            analysis.bias = "Bearish (Indicator-Based)"
            analysis.trade_idea = "Sell"

            # Entry: near current price / rally zone
            entry_low = price
            entry_high = price + atr * 0.3
            analysis.entry = (
                f"{entry_low:.2f}-{entry_high:.2f}"
            )
            entry_mid = (entry_low + entry_high) / 2

            # SELL: SL above entry, TPs below entry
            # TP2 < TP1 < entry < SL
            sl = ind.resistance_1 + atr * 0.3
            if sl <= entry_mid:
                sl = entry_mid + atr * 1.5

            tp1 = ind.support_1
            if tp1 >= entry_mid:
                tp1 = entry_mid - atr * 1.5

            tp2 = ind.support_2
            if tp2 >= tp1:
                tp2 = entry_mid - atr * 2.5

            analysis.stop_loss = f"{sl:.2f}"
            analysis.take_profit_1 = f"{tp1:.2f}"
            analysis.take_profit_2 = f"{tp2:.2f}"

        else:
            analysis.bias = "Neutral (Indicator-Based)"
            analysis.trade_idea = "Wait"
            analysis.entry = "Wait for clearer signal"
            analysis.stop_loss = "N/A"
            analysis.take_profit_1 = "N/A"
            analysis.take_profit_2 = "N/A"

        analysis.risk_note = (
            f"{ind.volatility_condition}. "
            f"AI unavailable — using indicator fallback. "
            f"Confidence: {ind.confidence_score}%."
        )
        analysis.short_term_outlook = ind.key_insight

        if fund:
            analysis.fundamental_note = (
                fund.combined_score
            )
            analysis.combined_verdict = (
                f"Technical: {ind.overall_bias}, "
                f"Fundamental: "
                f"{fund.fundamental_bias}"
            )
        else:
            analysis.fundamental_note = "N/A"
            analysis.combined_verdict = (
                f"Technical: {ind.overall_bias}"
            )

        analysis.raw_response = (
            "[Fallback: Generated from indicators]"
        )

        logger.info(
            f"Fallback: {analysis.trade_idea} | "
            f"Entry={analysis.entry} | "
            f"SL={analysis.stop_loss} | "
            f"TP1={analysis.take_profit_1} | "
            f"TP2={analysis.take_profit_2}"
        )

        return analysis
