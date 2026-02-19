#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    ENHANCED AI ANALYZER                            ║
║                                                                    ║
║  Gemini AI with combined technical + fundamental analysis.         ║
║  Purely synchronous — runs inside run_in_executor().               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
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

                if analysis.bias not in (
                    "N/A", "Error", ""
                ):
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
            f"Support: {ind.support_1}, "
            f"Resistance: {ind.resistance_1}\n"
            f"Pivot: {ind.pivot_point}\n"
            f"Fib 38.2%: {ind.fib_382}, "
            f"Fib 61.8%: {ind.fib_618}\n"
            f"VPOC: {ind.vpoc}\n"
            f"VWAP: {ind.vwap}\n"
            f"Volume ratio: {ind.volume_ratio:.1f}x\n"
            f"Overall Signal: {ind.overall_bias} "
            f"({ind.confidence_score}% confidence)\n"
            f"Insight: {ind.key_insight}\n\n"
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
            "RESPOND IN EXACTLY THIS FORMAT:\n\n"
            "BIAS: Bullish/Bearish/Neutral\n"
            "TRADE: Buy/Sell/Wait\n"
            "ENTRY: price-range\n"
            "STOP_LOSS: price\n"
            "TP1: price\n"
            "TP2: price\n"
            "RISK: One sentence.\n"
            "OUTLOOK: One-two sentences.\n"
            "FUNDAMENTAL: One sentence on macro impact.\n"
            "VERDICT: One sentence combining "
            "technical+fundamental.\n\n"
            "RULES:\n"
            "- Use specific prices\n"
            "- Account for ATR in stop loss\n"
            "- If unclear, recommend Wait\n"
            "- NO markdown formatting\n"
            "- Each field on its own line\n"
        )
        return prompt

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
                setattr(analysis, field_map[key], value)

        return analysis

    def _generate_fallback(
        self,
        ind: AdvancedTechnicalIndicators,
        symbol: SymbolConfig,
        fund: Optional[FundamentalData],
    ) -> AIAnalysis:
        analysis = AIAnalysis()
        analysis.bias = ind.overall_bias
        analysis.trade_idea = (
            "Buy"
            if "Bullish" in ind.overall_bias
            else "Sell"
            if "Bearish" in ind.overall_bias
            else "Wait"
        )
        analysis.entry = ind.action_levels
        analysis.stop_loss = str(ind.support_2)
        analysis.take_profit_1 = str(ind.resistance_1)
        analysis.take_profit_2 = str(ind.resistance_2)
        analysis.risk_note = (
            f"{ind.volatility_condition}. "
            f"Confidence: {ind.confidence_score}%."
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
        analysis.raw_response = "[Fallback analysis]"
        return analysis
