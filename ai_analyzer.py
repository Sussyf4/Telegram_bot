#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    ENHANCED AI ANALYZER v2                         ║
║                                                                    ║
║  FIXED: Fallback correctly assigns SL/TP based on bias.           ║
║  FIXED: Parse separates AI fields from indicator action_levels.    ║
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

GEMINI_MODEL = "gemini-2.0-flash"


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
            f"Enhanced AI Analyzer v2 | "
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
            df, indicators, symbol,
            timeframe, fundamental,
        )

        last_error = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(
                    f"AI attempt "
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

                if analysis.bias not in (
                    "N/A", "Error", ""
                ):
                    # Validate that SL/TP make sense
                    analysis = self._validate_levels(
                        analysis, indicators
                    )
                    logger.info(
                        f"AI parsed: bias={analysis.bias}, "
                        f"entry={analysis.entry}, "
                        f"sl={analysis.stop_loss}, "
                        f"tp1={analysis.take_profit_1}, "
                        f"tp2={analysis.take_profit_2}"
                    )
                    return analysis

                # Try fallback regex parse
                analysis = self._fallback_parse(
                    raw_text, analysis
                )
                if analysis.bias not in (
                    "N/A", "Error", ""
                ):
                    analysis = self._validate_levels(
                        analysis, indicators
                    )
                    return analysis

                if attempt < self._max_retries:
                    time.sleep(
                        self._retry_delay * attempt
                    )

            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    f"AI attempt {attempt} failed: "
                    f"{exc}"
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

    # ──────────────────────────────────────────────
    # Prompt Builder
    # ──────────────────────────────────────────────
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
            f"You are a senior "
            f"{symbol.display_name} analyst.\n\n"
            f"=== MARKET DATA — "
            f"{symbol.display_name} ({timeframe}) "
            f"===\n"
            f"Current: {latest['close']:.2f}\n"
            f"Open: {latest['open']:.2f}\n"
            f"High: {latest['high']:.2f}\n"
            f"Low: {latest['low']:.2f}\n"
            f"Change: {price_change:+.2f} "
            f"({price_change_pct:+.3f}%)\n"
            f"Last 5 closes: {last_5}\n\n"
            f"=== TECHNICAL ===\n"
            f"Trend: {ind.trend_direction} "
            f"(ADX {ind.adx:.1f})\n"
            f"EMA9: {ind.ema_9}, "
            f"EMA20: {ind.ema_20}, "
            f"EMA50: {ind.ema_50}\n"
            f"RSI(14): {ind.rsi} | "
            f"Stoch: {ind.stoch_k:.0f}K/"
            f"{ind.stoch_d:.0f}D\n"
            f"MACD Hist: {ind.macd_histogram:.4f}\n"
            f"ATR: {ind.atr} "
            f"({ind.atr_percent:.2f}%)\n"
            f"Support 1: {ind.support_1} | "
            f"Support 2: {ind.support_2}\n"
            f"Resistance 1: {ind.resistance_1} | "
            f"Resistance 2: {ind.resistance_2}\n"
            f"Pivot: {ind.pivot_point}\n"
            f"Fib 38.2%: {ind.fib_382} | "
            f"Fib 61.8%: {ind.fib_618}\n"
            f"VPOC: {ind.vpoc} | "
            f"VWAP: {ind.vwap}\n"
            f"Volume ratio: {ind.volume_ratio:.1f}x\n"
            f"Overall: {ind.overall_bias} "
            f"({ind.confidence_score}%)\n\n"
        )

        if fund:
            prompt += "=== FUNDAMENTAL ===\n"
            if symbol.asset_type == "crypto":
                prompt += (
                    f"Fear&Greed: "
                    f"{fund.fear_greed_index} "
                    f"({fund.fear_greed_label})\n"
                    f"MCap: {fund.btc_market_cap}\n"
                    f"24h Vol: "
                    f"{fund.btc_24h_volume}\n"
                    f"Hashrate: "
                    f"{fund.btc_hashrate}\n"
                )
            else:
                prompt += (
                    f"DXY: {fund.dxy_index}\n"
                    f"Fed Rate: {fund.fed_rate}\n"
                    f"CPI: {fund.us_cpi_yoy}\n"
                )
            if fund.key_drivers:
                prompt += (
                    f"Drivers: "
                    f"{'; '.join(fund.key_drivers)}\n"
                )
            if fund.risk_factors:
                prompt += (
                    f"Risks: "
                    f"{'; '.join(fund.risk_factors)}\n"
                )
            prompt += (
                f"Fund. Bias: "
                f"{fund.fundamental_bias}\n\n"
            )

        prompt += (
            "RESPOND IN EXACTLY THIS FORMAT "
            "(one field per line, "
            "specific numeric prices only):\n\n"
            "BIAS: Bullish or Bearish or Neutral\n"
            "TRADE: Buy or Sell or Wait\n"
            "ENTRY: <single price or price-price range>\n"
            "STOP_LOSS: <single price>\n"
            "TP1: <single price>\n"
            "TP2: <single price>\n"
            "RISK: <one sentence>\n"
            "OUTLOOK: <one-two sentences>\n"
            "FUNDAMENTAL: <one sentence on macro>\n"
            "VERDICT: <one sentence combining "
            "tech + fundamental>\n\n"
            "CRITICAL RULES:\n"
            "- For ENTRY, STOP_LOSS, TP1, TP2: "
            "use ONLY numeric prices like 2350.00 "
            "or 2350.00-2360.00\n"
            "- Do NOT put descriptions or text "
            "in price fields\n"
            "- For BUY trades: SL must be BELOW entry, "
            "TP1 and TP2 must be ABOVE entry\n"
            "- For SELL trades: SL must be ABOVE entry, "
            "TP1 and TP2 must be BELOW entry\n"
            "- TP1 is conservative (closer), "
            "TP2 is aggressive (further)\n"
            "- Stop loss should account for "
            "ATR volatility\n"
            "- If unclear, recommend Wait\n"
            "- NO markdown, NO asterisks\n"
            "- Each field MUST start at beginning "
            "of a new line\n"
        )
        return prompt

    # ──────────────────────────────────────────────
    # Primary Parser
    # ──────────────────────────────────────────────
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

            if not value:
                continue

            if key in field_map:
                attr_name = field_map[key]

                # Clean price fields — strip text,
                # keep only numbers and dashes
                if attr_name in (
                    "entry", "stop_loss",
                    "take_profit_1", "take_profit_2",
                ):
                    value = self._extract_price(value)

                setattr(analysis, attr_name, value)

        return analysis

    # ──────────────────────────────────────────────
    # Fallback Regex Parser
    # ──────────────────────────────────────────────
    def _fallback_parse(
        self, text: str, analysis: AIAnalysis
    ) -> AIAnalysis:
        if not text:
            return analysis

        text_clean = (
            text.replace("**", "")
            .replace("*", "")
            .replace("`", "")
        )

        patterns = {
            "bias": (
                r"(?:BIAS|MARKET\s*BIAS)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "trade_idea": (
                r"(?:TRADE|TRADE\s*IDEA|ACTION|SIGNAL)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "entry": (
                r"(?:ENTRY|ENTRY\s*(?:ZONE|PRICE)?)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "stop_loss": (
                r"(?:STOP[\s_]*LOSS|SL)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "take_profit_1": (
                r"(?:TP1|TAKE[\s_]*PROFIT[\s_]*1"
                r"|TARGET[\s_]*1)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "take_profit_2": (
                r"(?:TP2|TAKE[\s_]*PROFIT[\s_]*2"
                r"|TARGET[\s_]*2)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "risk_note": (
                r"(?:RISK|RISK[\s_]*"
                r"(?:NOTE|ASSESSMENT)?)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "short_term_outlook": (
                r"(?:OUTLOOK|SHORT[\s\-_]*"
                r"TERM[\s_]*OUTLOOK)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "fundamental_note": (
                r"(?:FUNDAMENTAL"
                r"(?:\s*NOTE)?)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
            "combined_verdict": (
                r"(?:VERDICT|COMBINED\s*VERDICT)"
                r"\s*[:=]\s*(.+?)(?:\n|$)"
            ),
        }

        price_fields = {
            "entry", "stop_loss",
            "take_profit_1", "take_profit_2",
        }

        for field_name, pattern in patterns.items():
            match = re.search(
                pattern, text_clean, re.IGNORECASE
            )
            if match:
                value = match.group(1).strip()
                if value and value != "N/A":
                    if field_name in price_fields:
                        value = self._extract_price(value)
                    setattr(analysis, field_name, value)

        return analysis

    # ──────────────────────────────────────────────
    # Extract clean price from messy AI output
    # ──────────────────────────────────────────────
    @staticmethod
    def _extract_price(text: str) -> str:
        """
        Extract numeric price(s) from AI response.
        Handles: "\$2,350.00", "around 2350-2360",
        "2350.00 (conservative)", etc.
        Returns clean format: "2350.00" or "2350.00-2360.00"
        """
        if not text:
            return "N/A"

        # Remove $, commas, and common words
        cleaned = text.replace("$", "").replace(",", "")

        # Find all decimal numbers
        numbers = re.findall(
            r'\d+\.?\d*', cleaned
        )

        if not numbers:
            return text.strip()

        if len(numbers) == 1:
            return numbers[0]
        elif len(numbers) == 2:
            return f"{numbers[0]}-{numbers[1]}"
        else:
            # Take first two meaningful numbers
            return f"{numbers[0]}-{numbers[1]}"

    # ──────────────────────────────────────────────
    # Validate that SL/TP are directionally correct
    # ──────────────────────────────────────────────
    def _validate_levels(
        self,
        analysis: AIAnalysis,
        ind: AdvancedTechnicalIndicators,
    ) -> AIAnalysis:
        """
        Ensure SL/TP make directional sense.
        For BUY: SL < entry < TP1 < TP2
        For SELL: SL > entry > TP1 > TP2
        If invalid, recalculate from indicators.
        """
        try:
            # Parse entry midpoint
            entry_mid = self._parse_mid_price(
                analysis.entry
            )
            sl = self._parse_single_price(
                analysis.stop_loss
            )
            tp1 = self._parse_single_price(
                analysis.take_profit_1
            )
            tp2 = self._parse_single_price(
                analysis.take_profit_2
            )

            if entry_mid is None:
                return analysis

            is_buy = analysis.trade_idea.strip().lower() in (
                "buy", "long",
            )
            is_sell = analysis.trade_idea.strip().lower() in (
                "sell", "short",
            )

            if not (is_buy or is_sell):
                return analysis

            needs_fix = False

            if is_buy:
                # SL should be below entry
                if sl is not None and sl >= entry_mid:
                    needs_fix = True
                # TP1 should be above entry
                if tp1 is not None and tp1 <= entry_mid:
                    needs_fix = True
                # TP2 should be above TP1
                if (
                    tp1 is not None
                    and tp2 is not None
                    and tp2 <= tp1
                ):
                    needs_fix = True

            elif is_sell:
                # SL should be above entry
                if sl is not None and sl <= entry_mid:
                    needs_fix = True
                # TP1 should be below entry
                if tp1 is not None and tp1 >= entry_mid:
                    needs_fix = True
                # TP2 should be below TP1
                if (
                    tp1 is not None
                    and tp2 is not None
                    and tp2 >= tp1
                ):
                    needs_fix = True

            if needs_fix:
                logger.warning(
                    f"AI levels invalid for "
                    f"{analysis.trade_idea}. "
                    f"Entry~{entry_mid}, SL={sl}, "
                    f"TP1={tp1}, TP2={tp2}. "
                    f"Recalculating..."
                )
                analysis = self._fix_levels_from_indicators(
                    analysis, ind, entry_mid
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
    ) -> AIAnalysis:
        """
        Recalculate SL/TP using indicator levels,
        respecting trade direction.
        """
        atr = ind.atr if ind.atr > 0 else 1.0

        is_buy = analysis.trade_idea.strip().lower() in (
            "buy", "long",
        )

        if is_buy:
            # SL below entry — use support or ATR
            sl_candidates = [
                ind.support_1,
                ind.support_2,
                entry_mid - atr * 1.5,
            ]
            sl = max(
                [s for s in sl_candidates
                 if s < entry_mid],
                default=entry_mid - atr * 1.5,
            )

            # TP above entry — use resistance
            tp1_candidates = [
                ind.resistance_1,
                ind.fib_618,
                entry_mid + atr * 1.5,
            ]
            tp1 = min(
                [t for t in tp1_candidates
                 if t > entry_mid],
                default=entry_mid + atr * 1.5,
            )

            tp2_candidates = [
                ind.resistance_2,
                ind.resistance_3,
                entry_mid + atr * 2.5,
            ]
            tp2 = min(
                [t for t in tp2_candidates
                 if t > tp1],
                default=tp1 + atr,
            )

        else:  # SELL
            # SL above entry — use resistance or ATR
            sl_candidates = [
                ind.resistance_1,
                ind.resistance_2,
                entry_mid + atr * 1.5,
            ]
            sl = min(
                [s for s in sl_candidates
                 if s > entry_mid],
                default=entry_mid + atr * 1.5,
            )

            # TP below entry — use support
            tp1_candidates = [
                ind.support_1,
                ind.fib_382,
                entry_mid - atr * 1.5,
            ]
            tp1 = max(
                [t for t in tp1_candidates
                 if t < entry_mid],
                default=entry_mid - atr * 1.5,
            )

            tp2_candidates = [
                ind.support_2,
                ind.support_3,
                entry_mid - atr * 2.5,
            ]
            tp2 = max(
                [t for t in tp2_candidates
                 if t < tp1],
                default=tp1 - atr,
            )

        analysis.stop_loss = f"{sl:.2f}"
        analysis.take_profit_1 = f"{tp1:.2f}"
        analysis.take_profit_2 = f"{tp2:.2f}"

        logger.info(
            f"Fixed levels for "
            f"{analysis.trade_idea}: "
            f"SL={sl:.2f}, "
            f"TP1={tp1:.2f}, TP2={tp2:.2f}"
        )

        return analysis

    # ──────────────────────────────────────────────
    # Price parsing helpers
    # ──────────────────────────────────────────────
    @staticmethod
    def _parse_single_price(
        text: str,
    ) -> Optional[float]:
        """Extract a single float from price text."""
        if not text or text == "N/A":
            return None
        cleaned = (
            text.replace("$", "")
            .replace(",", "")
            .strip()
        )
        numbers = re.findall(r'\d+\.?\d*', cleaned)
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_mid_price(
        text: str,
    ) -> Optional[float]:
        """
        Parse entry price — if range, return midpoint.
        "2350.00-2360.00" -> 2355.00
        "2350.00" -> 2350.00
        """
        if not text or text == "N/A":
            return None
        cleaned = (
            text.replace("$", "")
            .replace(",", "")
            .strip()
        )
        numbers = re.findall(r'\d+\.?\d*', cleaned)
        if not numbers:
            return None
        try:
            if len(numbers) >= 2:
                return (
                    float(numbers[0])
                    + float(numbers[1])
                ) / 2
            return float(numbers[0])
        except ValueError:
            return None

    # ──────────────────────────────────────────────
    # Fallback Generator (direction-aware)
    # ──────────────────────────────────────────────
    def _generate_fallback(
        self,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        fund: Optional[FundamentalData],
    ) -> AIAnalysis:
        """Generate indicator-based fallback with
        correct directional SL/TP."""
        logger.warning(
            "Using indicator-based fallback "
            "(AI unavailable)"
        )
        analysis = AIAnalysis()
        price = ind.current_price
        atr = ind.atr if ind.atr > 0 else 1.0

        is_bullish = "Bullish" in ind.overall_bias
        is_bearish = "Bearish" in ind.overall_bias

        analysis.bias = f"{ind.overall_bias} (Indicator)"

        if is_bullish:
            analysis.trade_idea = "Buy"

            # Entry: current price area
            entry_low = round(price - atr * 0.3, 2)
            entry_high = round(price, 2)
            analysis.entry = (
                f"{entry_low}-{entry_high}"
            )
            entry_mid = (entry_low + entry_high) / 2

            # SL: below support
            sl = round(
                min(ind.support_1, ind.support_2)
                - atr * 0.3,
                2,
            )
            if sl >= entry_mid:
                sl = round(entry_mid - atr * 1.5, 2)
            analysis.stop_loss = f"{sl}"

            # TP1: nearest resistance
            tp1 = round(ind.resistance_1, 2)
            if tp1 <= entry_mid:
                tp1 = round(entry_mid + atr * 1.5, 2)
            analysis.take_profit_1 = f"{tp1}"

            # TP2: further resistance
            tp2 = round(ind.resistance_2, 2)
            if tp2 <= tp1:
                tp2 = round(tp1 + atr, 2)
            analysis.take_profit_2 = f"{tp2}"

        elif is_bearish:
            analysis.trade_idea = "Sell"

            # Entry: current price area
            entry_low = round(price, 2)
            entry_high = round(price + atr * 0.3, 2)
            analysis.entry = (
                f"{entry_low}-{entry_high}"
            )
            entry_mid = (entry_low + entry_high) / 2

            # SL: above resistance
            sl = round(
                max(ind.resistance_1, ind.resistance_2)
                + atr * 0.3,
                2,
            )
            if sl <= entry_mid:
                sl = round(entry_mid + atr * 1.5, 2)
            analysis.stop_loss = f"{sl}"

            # TP1: nearest support
            tp1 = round(ind.support_1, 2)
            if tp1 >= entry_mid:
                tp1 = round(entry_mid - atr * 1.5, 2)
            analysis.take_profit_1 = f"{tp1}"

            # TP2: further support
            tp2 = round(ind.support_2, 2)
            if tp2 >= tp1:
                tp2 = round(tp1 - atr, 2)
            analysis.take_profit_2 = f"{tp2}"

        else:
            analysis.trade_idea = "Wait"
            analysis.entry = "Wait for clearer signal"
            analysis.stop_loss = f"{ind.support_1}"
            analysis.take_profit_1 = (
                f"{ind.resistance_1}"
            )
            analysis.take_profit_2 = (
                f"{ind.resistance_2}"
            )

        analysis.risk_note = (
            f"{ind.volatility_condition}. "
            f"Confidence: {ind.confidence_score}%. "
            f"AI unavailable — indicator fallback."
        )
        analysis.short_term_outlook = ind.key_insight

        if fund:
            analysis.fundamental_note = (
                fund.combined_score
            )
            analysis.combined_verdict = (
                f"Tech: {ind.overall_bias}, "
                f"Fundamental: "
                f"{fund.fundamental_bias}"
            )

        analysis.raw_response = (
            "[Fallback: indicator-based analysis]"
        )

        logger.info(
            f"Fallback: {analysis.trade_idea} "
            f"entry={analysis.entry} "
            f"sl={analysis.stop_loss} "
            f"tp1={analysis.take_profit_1} "
            f"tp2={analysis.take_profit_2}"
        )

        return analysis
