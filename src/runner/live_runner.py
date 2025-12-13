"""Live runner for the universe.

Flow:
Universe CSV -> Scheduler loop -> Fetch market data -> Fetch news -> Compute strategy -> State store -> Notify
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from ..marketdata import fetch_stock_ohlcv
from ..news import fetch_company_news, score_news_sentiment, classify_sentiment
from ..state import SqliteStateStore
from ..strategy.engine import StrategyEngine
from ..notify import MultiNotifier, TelegramNotifier, EmailNotifier


@dataclass(frozen=True)
class LiveRunConfig:
    timeframe: str
    interval_seconds: int
    lookback_days: int
    min_confidence: str
    cooldown_minutes: int
    news_query_mode: str  # "ticker" | "name"
    news_lookback_hours: int
    news_required_alignment: bool
    rate_limit_delay: float = 1.0  # Delay between API calls in seconds


def _confidence_rank(conf: str) -> int:
    order = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    return order.get((conf or "").upper(), 0)


def _build_notifier() -> MultiNotifier:
    notifiers = []
    tel = TelegramNotifier()
    if tel.enabled():
        notifiers.append(tel)
    email = EmailNotifier()
    if email.enabled():
        notifiers.append(email)
    return MultiNotifier(notifiers=notifiers)


def _news_allows(signal: str, sentiment_label: str, require_alignment: bool) -> bool:
    if not require_alignment:
        return True
    if signal == "LONG":
        return sentiment_label in {"POSITIVE", "NEUTRAL"}
    if signal == "SHORT":
        return sentiment_label in {"NEGATIVE", "NEUTRAL"}
    return True


def run_live_universe(
    universe: Iterable[tuple[str, str | None]],
    engine: StrategyEngine,
    config: LiveRunConfig,
    state: SqliteStateStore,
    verbose: bool = True,
) -> None:
    notifier = _build_notifier()

    for ticker, name in universe:
        try:
            df = fetch_stock_ohlcv(ticker=ticker, interval=config.timeframe, lookback_days=config.lookback_days)
            # Rate limit delay to avoid hitting API limits
            time.sleep(config.rate_limit_delay)
        except Exception as e:
            if verbose:
                print(f"[{ticker}] ❌ Data fetch error: {e}")
            continue

        # Need at least 220 bars for 200 EMA + some buffer
        if df is None or df.empty or len(df) < 220:
            if verbose:
                print(f"[{ticker}] ⏭️  Skipped (only {len(df) if df is not None else 0} bars)")
            continue

        analysis = engine.analyze_current_market(df)
        signal = analysis["signal"]["final_signal"]
        confidence = analysis["signal"]["confidence"]

        if verbose:
            price = analysis.get("price", 0)
            print(f"[{ticker}] ${price:.2f} | Signal: {signal} ({confidence})")

        if signal == "NEUTRAL":
            continue
        if _confidence_rank(confidence) < _confidence_rank(config.min_confidence):
            if verbose:
                print(f"[{ticker}] ⏭️  Skipped (confidence {confidence} < {config.min_confidence})")
            continue
        if state.recently_alerted(ticker, config.timeframe, signal, cooldown_minutes=config.cooldown_minutes):
            if verbose:
                print(f"[{ticker}] ⏭️  Skipped (alerted recently)")
            continue

        # News validation
        news_query = ticker if config.news_query_mode == "ticker" else (name or ticker)
        news_items = fetch_company_news(news_query, lookback_hours=config.news_lookback_hours)
        news_score = score_news_sentiment(news_items)
        sentiment_label = classify_sentiment(news_score)

        if not _news_allows(signal, sentiment_label, config.news_required_alignment):
            continue

        # Build notification
        title = f"{signal} {ticker} ({confidence})"
        parts = [
            f"Timeframe: {config.timeframe}",
            f"Price: {analysis['price']:.2f}",
            f"Reason: {analysis['signal']['reason']}",
            f"News sentiment: {sentiment_label} ({news_score:.3f})",
        ]
        if analysis["signal"].get("entry_price") is not None:
            s = analysis["signal"]
            parts.extend(
                [
                    f"Entry: {s.get('entry_price'):.2f}",
                    f"Stop: {s.get('stop_loss'):.2f}",
                    f"TP: {s.get('take_profit'):.2f}",
                    f"R/R: 1:{s.get('risk_reward'):.2f}",
                ]
            )

        if news_items:
            top = news_items[0]
            parts.append(f"Top headline: {top.title}")
            if top.url:
                parts.append(top.url)

        message = "\n".join(parts)

        # Always print alert to console
        if verbose:
            print(f"\n{'='*50}")
            print(f"🚨 ALERT: {title}")
            print(f"{'='*50}")
            print(message)
            print(f"{'='*50}\n")

        # Send via configured notifiers (Telegram/Email)
        if notifier.notifiers:
            notifier.send(title, message)
        elif verbose:
            print(f"[{ticker}] ℹ️  No notifiers configured (set TELEGRAM_BOT_TOKEN or SMTP_HOST)")

        state.record_alert(ticker, config.timeframe, signal, confidence)
