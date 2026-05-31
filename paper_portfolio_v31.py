#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

import design_strategies
import eodhd_official_data as eodhd
import firm_structure
import paper_portfolio_v2 as v2
import paper_portfolio_v3_rebuild as v3


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

V2_SOURCE_TICKERS = {"AMD", "ANET", "AVGO", "NVDA"}
V3_SOURCE_TICKERS = {"LRCX", "MRVL", "PANW", "SHOP", "TSLA"}

TRADES_CSV = REPORTS / "paper_trades_v31.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v31.csv"
LEDGER_CSV = REPORTS / "paper_portfolio_v31_ledger.csv"
STRATEGIES_CSV = REPORTS / "selected_strategies_v31.csv"
COMPARISON_CSV = REPORTS / "v2_v3_v31_portfolio_comparison.csv"
TICKER_COMPARISON_CSV = REPORTS / "v2_v3_v31_ticker_comparison.csv"
DASHBOARD = REPORTS / "paper_portfolio_v31_dashboard.html"
SIMULATION_DASHBOARD = REPORTS / "paper_portfolio_v31_simulation.html"
OFFICIAL_DASHBOARD = REPORTS / "portfolio_dashboard.html"
OFFICIAL_SIMULATION_DASHBOARD = REPORTS / "portfolio_simulation.html"
OFFICIAL_TRADES_CSV = REPORTS / "portfolio_trades.csv"
OFFICIAL_EQUITY_CSV = REPORTS / "portfolio_equity_curve.csv"
OFFICIAL_LEDGER_CSV = REPORTS / "portfolio_ledger.csv"
OFFICIAL_STRATEGIES_CSV = REPORTS / "portfolio_strategies.csv"
OFFICIAL_COMPARISON_CSV = REPORTS / "portfolio_version_comparison.csv"
OFFICIAL_TICKER_COMPARISON_CSV = REPORTS / "portfolio_ticker_comparison.csv"
OFFICIAL_EXECUTION_METADATA_JSON = REPORTS / "portfolio_execution_metadata.json"
OFFICIAL_ANALYTICS_DASHBOARD = REPORTS / "portfolio_analytics.html"
OFFICIAL_BUSINESS_INTELLIGENCE_DASHBOARD = REPORTS / "portfolio_business_intelligence.html"
OFFICIAL_FINANCIAL_DASHBOARD = REPORTS / "portfolio_financial_diagnostics.html"
OFFICIAL_FINANCIAL_JSON = REPORTS / "portfolio_financial_diagnostics.json"
PAPER_PORTFOLIO_DASHBOARD = REPORTS / "paper_portfolio_dashboard.html"

AR_POLICY_LABEL = "\u0627\u0644\u0633\u064a\u0627\u0633\u0629 \u0627\u0644\u0645\u0639\u062a\u0645\u062f\u0629"
AR_APPROVED_LABEL = "\u0645\u0639\u062a\u0645\u062f"
AR_PORTFOLIO_NAME = str(CONFIG.get("portfolio_display_name_ar", "\u0627\u0644\u0645\u062d\u0641\u0638\u0629 \u0627\u0644\u0648\u0631\u0642\u064a\u0629 \u0627\u0644\u0645\u0639\u062a\u0645\u062f\u0629"))
AR_BREAKOUT = "\u0627\u062e\u062a\u0631\u0627\u0642"
AR_PULLBACK = "\u0627\u0631\u062a\u062f\u0627\u062f"
AR_TREND = "\u062a\u0631\u0646\u062f"
AR_MIXED = "\u0645\u062e\u062a\u0644\u0637"
AR_BREAKOUT_RULE = "\u0642\u0627\u0639\u062f\u0629 \u0627\u062e\u062a\u0631\u0627\u0642"
AR_PULLBACK_RULE = "\u0627\u0631\u062a\u062f\u0627\u062f \u0632\u062e\u0645"
AR_TREND_RULE = "\u0645\u062a\u0627\u0628\u0639\u0629 \u062a\u0631\u0646\u062f"
AR_APPROVED_STRATEGY = "\u0627\u0633\u062a\u0631\u0627\u062a\u064a\u062c\u064a\u0629 \u0645\u0639\u062a\u0645\u062f\u0629"
AR_LOCAL_PORTFOLIO_SERVER = "\u062e\u0627\u062f\u0645 \u0627\u0644\u0645\u062d\u0641\u0638\u0629 \u0627\u0644\u0645\u062d\u0644\u064a"


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_hybrid_strategies() -> list[dict[str, Any]]:
    v2_strategies, _quality = v2.selected_portfolio_strategies()
    v3_strategies = cap_strategy_sizes(read_csv(REPORTS / "selected_strategies_v3.csv"))
    hybrid: list[dict[str, Any]] = []
    for strategy in v2_strategies:
        if strategy["ticker"] in V2_SOURCE_TICKERS:
            row = dict(strategy)
            row["size_multiplier"] = min(fnum(row.get("size_multiplier"), 1.0), 1.0)
            row["strategy_source"] = "V2"
            row["selected_version"] = f"v31_from_v2:{row.get('selected_version', '')}"
            hybrid.append(row)
    for strategy in v3_strategies:
        if strategy["ticker"] in V3_SOURCE_TICKERS:
            row = dict(strategy)
            row["size_multiplier"] = min(fnum(row.get("size_multiplier"), 1.0), 1.0)
            row["strategy_source"] = "V3"
            row["selected_version"] = f"v31_from_v3:{row.get('selected_version', '')}"
            hybrid.append(row)
    return hybrid


def cap_strategy_sizes(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capped: list[dict[str, Any]] = []
    for strategy in strategies:
        row = dict(strategy)
        row["size_multiplier"] = min(fnum(row.get("size_multiplier"), 1.0), 1.0)
        capped.append(row)
    return capped


def hybrid_entry_signal(strategy: dict[str, Any], bars: list[design_strategies.Bar], index: int, market_cache: dict[str, Any]) -> bool:
    rule = str(strategy.get("entry_rule", ""))
    if rule.startswith("raw_"):
        return v3.entry_signal(strategy, bars, index, market_cache)
    return design_strategies.entry_signal(strategy, bars, index)


def stop_price(strategy: dict[str, Any], bars: list[design_strategies.Bar], index: int) -> float:
    stop_model = str(strategy.get("stop_model", ""))
    if stop_model in {"atr_support", "v1_atr_support"}:
        return v2.v1_stop_price(strategy, bars, index)
    return bars[index].close * (1 - fnum(strategy.get("initial_stop_pct"), 6.0) / 100)


def official_market_cache() -> dict[str, Any]:
    cache: dict[str, Any] = {}
    for ticker in ("SPY", "QQQ", "SOXX"):
        bars = eodhd.read_daily_bars(ticker)
        cache[ticker] = bars
        cache[f"{ticker}_index"] = {bar.date: idx for idx, bar in enumerate(bars)}
    return cache


def latest_common_execution_date(
    bars_by_ticker: dict[str, list[design_strategies.Bar]],
    intraday_by_ticker: dict[str, dict[str, list[dict[str, Any]]]],
) -> str:
    latest_dates: list[str] = []
    for ticker, bars in bars_by_ticker.items():
        daily_dates = {bar.date for bar in bars}
        execution_dates = set(intraday_by_ticker.get(ticker, {}))
        common_dates = sorted(daily_dates & execution_dates)
        if not common_dates:
            raise RuntimeError(f"No common daily and 5-minute execution data for {ticker}.")
        latest_dates.append(common_dates[-1])
    return min(latest_dates)


def append_ledger(state: dict[str, Any], trade: dict[str, Any], action: str, date: str, price: float, note: str = "") -> None:
    shares = int(trade.get("shares", 0) or 0)
    amount = shares * price
    pnl = fnum(trade.get("realized_pnl")) if action == "EXIT" else 0.0
    state["ledger"].append(
        {
            "date": date,
            "action": action,
            "trade_id": trade.get("id", ""),
            "ticker": trade.get("ticker", ""),
            "source": trade.get("strategy_source", ""),
            "timeframe": trade.get("timeframe", ""),
            "entry_rule": trade.get("entry_rule", ""),
            "shares": shares,
            "price": round(price, 4),
            "amount": round(amount, 2),
            "cash_after": round(fnum(state.get("cash")), 2),
            "portfolio_value_after": round(v2.portfolio_value(state), 2),
            "pnl": round(pnl, 2),
            "pnl_pct": trade.get("realized_pnl_pct", 0.0) if action == "EXIT" else 0.0,
            "outcome": trade.get("outcome", ""),
            "note": note,
        }
    )


def simulate_hybrid_portfolio(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    tickers = sorted({str(strategy["ticker"]) for strategy in strategies})
    bars_by_ticker = {ticker: eodhd.read_daily_bars(ticker) for ticker in tickers}
    intraday_by_ticker = {ticker: eodhd.intraday_by_date(ticker) for ticker in tickers}
    index_maps = {
        ticker: {bar.date: idx for idx, bar in enumerate(bars)}
        for ticker, bars in bars_by_ticker.items()
    }
    market_cache = official_market_cache()
    data_cutoff_date = latest_common_execution_date(bars_by_ticker, intraday_by_ticker)
    all_dates = sorted(
        {
            bar.date
            for bars in bars_by_ticker.values()
            for bar in bars
            if CONFIG["start_date"] <= bar.date <= data_cutoff_date
        }
    )
    state: dict[str, Any] = {
        "initial_capital": v2.INITIAL_CAPITAL,
        "cash": v2.INITIAL_CAPITAL,
        "trades": [],
        "snapshots": [],
        "ledger": [],
        "skipped": [],
        "quality_gate": [],
        "next_id": 1,
        "market_data_source": "EODHD EOD-IntraDay All World",
        "market_data_interval": "5m",
        "data_cutoff_date": data_cutoff_date,
        "execution_model": str(CONFIG.get("execution_model", "five_minute_target_stop_daily_high_next_session_trailing")),
        "trailing_stop_update_timing": str(CONFIG.get("trailing_stop_update_timing", "completed_daily_high_next_session")),
        "execution_diagnostics": {
            "intraday_exit_trades": 0,
            "same_bar_stop_target_ambiguities": 0,
            "daily_fallback_sessions": 0,
            "next_session_stop_raises": 0,
        },
    }
    if all_dates:
        state["ledger"].append(
            {
                "date": all_dates[0],
                "action": "START",
                "trade_id": "",
                "ticker": "PORTFOLIO",
                "source": "",
                "timeframe": "",
                "entry_rule": "",
                "shares": "",
                "price": "",
                "amount": "",
                "cash_after": round(fnum(state["cash"]), 2),
                "portfolio_value_after": round(v2.portfolio_value(state), 2),
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "outcome": "",
                "note": "بداية المحاكاة",
            }
        )
    open_trades: list[dict[str, Any]] = []

    for current_date in all_dates:
        for trade in list(open_trades):
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or current_date <= str(trade["entry_date"]):
                continue
            bar = bars_by_ticker[ticker][idx]
            trade["held_sessions"] = int(trade.get("held_sessions", 0)) + 1
            intraday_bars = intraday_by_ticker[ticker].get(current_date, [])
            if not intraday_bars:
                raise RuntimeError(f"Missing approved EODHD 5m execution session for {ticker} on {current_date}.")
            target = fnum(trade["exit_price"])
            closed_during_session = False
            for intraday_bar in intraday_bars:
                stop = fnum(trade["stop_price"])
                stop_hit = fnum(intraday_bar["low"]) <= stop
                target_hit = fnum(intraday_bar["high"]) >= target
                if stop_hit and target_hit:
                    state["execution_diagnostics"]["same_bar_stop_target_ambiguities"] += 1
                if stop_hit:
                    outcome = "TRAILING_WIN" if stop >= fnum(trade["entry_price"]) else "LOSS"
                    reason = "ضرب الوقف المتحرك/الفني - تنفيذ خمس دقائق"
                    v2.close_trade(state, trade, current_date, stop, reason, outcome)
                    trade["close_time_et"] = str(intraday_bar["time_et"])
                    append_ledger(state, trade, "EXIT", current_date, stop, reason)
                    state["execution_diagnostics"]["intraday_exit_trades"] += 1
                    open_trades.remove(trade)
                    closed_during_session = True
                    break
                if target_hit:
                    reason = "تحقق الهدف - تنفيذ خمس دقائق"
                    v2.close_trade(state, trade, current_date, target, reason, "WIN")
                    trade["close_time_et"] = str(intraday_bar["time_et"])
                    append_ledger(state, trade, "EXIT", current_date, target, reason)
                    state["execution_diagnostics"]["intraday_exit_trades"] += 1
                    open_trades.remove(trade)
                    closed_during_session = True
                    break
            if closed_during_session:
                continue
            if int(trade["held_sessions"]) >= int(trade["hold_days"]):
                pnl_pct = (bar.close / fnum(trade["entry_price"]) - 1) * 100
                outcome = "TIMEOUT_WIN" if pnl_pct > 0 else "TIMEOUT_LOSS"
                v2.close_trade(state, trade, current_date, bar.close, "انتهاء مدة الاحتفاظ", outcome)
                trade["close_time_et"] = "16:00:00"
                append_ledger(state, trade, "EXIT", current_date, bar.close, "انتهاء مدة الاحتفاظ")
                open_trades.remove(trade)
                continue
            previous_stop = fnum(trade["stop_price"])
            session_high = max(fnum(intraday_bar["high"]) for intraday_bar in intraday_bars)
            # Compute protection after the completed session; it is executable next session only.
            v2.update_trailing_stop(trade, session_high)
            if fnum(trade["stop_price"]) > previous_stop:
                state["execution_diagnostics"]["next_session_stop_raises"] += 1

        for strategy in strategies:
            ticker = str(strategy["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or idx == 0:
                continue
            bars = bars_by_ticker[ticker]
            if not hybrid_entry_signal(strategy, bars, idx, market_cache):
                continue
            duplicate = any(
                trade["status"] == "OPEN"
                and trade["ticker"] == ticker
                and trade.get("strategy_id") == strategy.get("strategy_id")
                for trade in open_trades
            )
            if duplicate:
                continue
            bar = bars[idx]
            cash = fnum(state["cash"])
            target_alloc = cash * v2.POSITION_CAP_PCT * min(fnum(strategy.get("size_multiplier"), 1.0), 1.0)
            adv = v2.avg_dollar_volume(bars, idx)
            liquidity_cap = adv * v2.MAX_TRADE_ADV_PCT if adv else target_alloc
            allocation = min(cash, target_alloc, liquidity_cap)
            shares = math.floor(allocation / bar.close) if bar.close > 0 else 0
            if shares <= 0:
                state["skipped"].append({"date": current_date, "ticker": ticker, "reason": "cash_or_liquidity_below_one_share"})
                continue
            entry = bar.close
            technical_stop = stop_price(strategy, bars, idx)
            target = entry * (1 + fnum(strategy["target_pct"]) / 100)
            capital = shares * entry
            trade = {
                "id": f"V31-{state['next_id']:04d}",
                "ticker": ticker,
                "strategy_source": strategy.get("strategy_source", ""),
                "strategy_id": strategy.get("strategy_id", ""),
                "behavior": strategy.get("behavior", ""),
                "entry_rule": strategy.get("entry_rule", ""),
                "timeframe": strategy.get("timeframe", ""),
                "selected_version": strategy.get("selected_version", ""),
                "v3_quality_score": strategy.get("v3_quality_score", ""),
                "v3_reason": strategy.get("v3_reason", ""),
                "status": "OPEN",
                "outcome": "OPEN",
                "entry_date": current_date,
                "entry_price": round(entry, 4),
                "shares": shares,
                "capital": round(capital, 2),
                "avg_dollar_volume": round(adv, 2),
                "liquidity_cap": round(liquidity_cap, 2),
                "technical_initial_stop_price": round(technical_stop, 4),
                "stop_cap_pct": "",
                "initial_stop_price": round(technical_stop, 4),
                "stop_price": round(technical_stop, 4),
                "highest_price": round(entry, 4),
                "exit_price": round(target, 4),
                "hold_days": int(fnum(strategy["hold_days"])),
                "held_sessions": 0,
                "latest_price": round(entry, 4),
                "market_value": round(capital, 2),
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "realized_pnl": 0.0,
                "realized_pnl_pct": 0.0,
                "close_date": "",
                "close_time_et": "",
                "close_price": "",
                "close_reason": "",
            }
            state["next_id"] += 1
            state["cash"] = round(cash - capital, 2)
            state["trades"].append(trade)
            open_trades.append(trade)
            append_ledger(state, trade, "ENTRY", current_date, entry, "دخول بناء على إشارة V3.1")

        for trade in open_trades:
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None:
                continue
            close = bars_by_ticker[ticker][idx].close
            market_value = int(trade["shares"]) * close
            trade["latest_price"] = round(close, 4)
            trade["market_value"] = round(market_value, 2)
            trade["unrealized_pnl"] = round(market_value - fnum(trade["capital"]), 2)
            trade["unrealized_pnl_pct"] = round((close / fnum(trade["entry_price"]) - 1) * 100, 2)
        state["snapshots"].append({"date": current_date, "value": v2.portfolio_value(state), "cash": round(fnum(state["cash"]), 2), "open_trades": len(open_trades)})

    return state


def portfolio_summary(state: dict[str, Any], label: str) -> dict[str, Any]:
    trades = state["trades"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if fnum(trade.get("realized_pnl")) >= 0]
    losses = [trade for trade in closed if fnum(trade.get("realized_pnl")) < 0]
    value = v2.portfolio_value(state)
    snapshots = state.get("snapshots", [])
    end_date = snapshots[-1]["date"] if snapshots else ""
    elapsed = max((dt.date.fromisoformat(end_date) - v2.START_DATE).days / 365.25, 1 / 365.25) if end_date else 1
    annual = ((value / v2.INITIAL_CAPITAL) ** (1 / elapsed) - 1) * 100 if value > 0 else -100
    drawdown = v2.max_drawdown(snapshots)
    return {
        "version": label,
        "portfolio_value": round(value, 2),
        "pnl": round(value - v2.INITIAL_CAPITAL, 2),
        "period_return_pct": round((value / v2.INITIAL_CAPITAL - 1) * 100, 2),
        "annual_return_pct": round(annual, 2),
        "trades": len(trades),
        "closed": len(closed),
        "open": len([trade for trade in trades if trade.get("status") == "OPEN"]),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "avg_win_pct": round(mean([v2.trade_pnl_pct(trade) for trade in wins]), 2),
        "avg_loss_pct": round(mean([v2.trade_pnl_pct(trade) for trade in losses]), 2),
        "worst_loss_pct": round(min([v2.trade_pnl_pct(trade) for trade in trades], default=0.0), 2),
        "max_drawdown_pct": round(fnum(drawdown.get("drawdown")), 2),
        "end_date": end_date,
    }


def ticker_pnl(state: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for trade in state["trades"]:
        ticker = str(trade["ticker"])
        out[ticker] = out.get(ticker, 0.0) + v2.trade_pnl(trade)
    return {ticker: round(value, 2) for ticker, value in out.items()}


def comparison_rows(v2_state: dict[str, Any], v3_state: dict[str, Any], v31_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        portfolio_summary(v2_state, "V2"),
        portfolio_summary(v3_state, "V3 Raw Rebuild"),
        portfolio_summary(v31_state, "V3.1 Hybrid"),
    ]
    best = max(rows, key=lambda row: fnum(row["portfolio_value"]))
    for row in rows:
        row["delta_vs_best"] = round(fnum(row["portfolio_value"]) - fnum(best["portfolio_value"]), 2)
    return rows


def ticker_comparison_rows(v2_state: dict[str, Any], v3_state: dict[str, Any], v31_state: dict[str, Any]) -> list[dict[str, Any]]:
    v2_pnl = ticker_pnl(v2_state)
    v3_pnl = ticker_pnl(v3_state)
    v31_pnl = ticker_pnl(v31_state)
    rows: list[dict[str, Any]] = []
    for ticker in sorted(set(v2_pnl) | set(v3_pnl) | set(v31_pnl)):
        values = {"V2": v2_pnl.get(ticker, 0.0), "V3": v3_pnl.get(ticker, 0.0), "V3.1": v31_pnl.get(ticker, 0.0)}
        winner = max(values, key=values.get)
        rows.append({
            "ticker": ticker,
            "v2_pnl": values["V2"],
            "v3_pnl": values["V3"],
            "v31_pnl": values["V3.1"],
            "v31_source": "V2" if ticker in V2_SOURCE_TICKERS else "V3",
            "best_by_ticker": winner,
        })
    return rows


def equity_points(state: dict[str, Any]) -> str:
    return json.dumps([[row["date"], fnum(row["value"])] for row in state.get("snapshots", [])], ensure_ascii=False)


def render_dashboard(
    comparison: list[dict[str, Any]],
    ticker_rows: list[dict[str, Any]],
    strategies: list[dict[str, Any]],
    v2_state: dict[str, Any],
    v3_state: dict[str, Any],
    v31_state: dict[str, Any],
) -> str:
    v2_row, v3_row, v31_row = comparison
    v31_trades = v31_state["trades"]
    v31_closed = [trade for trade in v31_trades if trade.get("status") == "CLOSED"]
    v31_open = [trade for trade in v31_trades if trade.get("status") == "OPEN"]
    realized_pnl = sum(fnum(trade.get("realized_pnl")) for trade in v31_closed)
    unrealized_pnl = sum(fnum(trade.get("unrealized_pnl")) for trade in v31_open)
    max_open = max((int(fnum(row.get("open_trades"))) for row in v31_state.get("snapshots", [])), default=0)
    largest_position = max((fnum(trade.get("market_value")) for trade in v31_open), default=0.0)
    current_cash = fnum(v31_state.get("cash"))
    open_trade_rows = "\n".join(
        f"<tr><td><strong class='ltr'>{html.escape(str(row['ticker']))}</strong></td><td>{html.escape(str(row.get('strategy_source','')))}</td><td>{html.escape(str(row.get('timeframe','')))}</td><td class='ltr'>{html.escape(str(row.get('entry_date','')))}</td><td class='num'>{int(fnum(row.get('shares')))}</td><td class='num'>{money(row.get('entry_price'))}</td><td class='num'>{money(row.get('latest_price'))}</td><td class='num {tone(row.get('unrealized_pnl'))}'>{money(row.get('unrealized_pnl'))}</td><td class='num {tone(row.get('unrealized_pnl_pct'))}'>{pct(row.get('unrealized_pnl_pct'))}</td></tr>"
        for row in sorted(v31_open, key=lambda item: fnum(item.get("market_value")), reverse=True)
    )
    recent_closed_rows = "\n".join(
        f"<tr><td class='ltr'>{html.escape(str(row.get('close_date','')))}</td><td><strong class='ltr'>{html.escape(str(row['ticker']))}</strong></td><td>{html.escape(str(row.get('strategy_source','')))}</td><td>{html.escape(str(row.get('outcome','')))}</td><td class='num'>{money(row.get('entry_price'))}</td><td class='num'>{money(row.get('close_price'))}</td><td class='num {tone(row.get('realized_pnl'))}'>{money(row.get('realized_pnl'))}</td><td class='num {tone(row.get('realized_pnl_pct'))}'>{pct(row.get('realized_pnl_pct'))}</td></tr>"
        for row in sorted(v31_closed, key=lambda item: str(item.get("close_date", "")), reverse=True)[:40]
    )
    monthly_rows = "\n".join(
        f"<tr><td class='ltr'>{row['month']}</td><td class='num'>{money(row['ending_value'])}</td><td class='num {tone(row['pnl'])}'>{money(row['pnl'])}</td><td class='num {tone(row['return_pct'])}'>{pct(row['return_pct'])}</td><td class='num'>{money(row['cash'])}</td><td class='num'>{row['open_trades']}</td></tr>"
        for row in monthly_summary_rows(v31_state)
    )
    def decision_row(
        label: str,
        key: str,
        formatter: Any,
        note: str,
        higher_is_better: bool = True,
    ) -> str:
        values = {
            "V2": fnum(v2_row[key]),
            "V3": fnum(v3_row[key]),
            "V3.1": fnum(v31_row[key]),
        }
        winner = max(values, key=values.get) if higher_is_better else min(values, key=values.get)
        return (
            "<tr>"
            f"<th class='metric'>{html.escape(label)}</th>"
            f"<td class='num'>{formatter(v2_row[key])}</td>"
            f"<td class='num'>{formatter(v3_row[key])}</td>"
            f"<td class='num strong {tone(v31_row[key]) if key in {'portfolio_value', 'pnl', 'period_return_pct', 'annual_return_pct'} else ''}'>{formatter(v31_row[key])}</td>"
            f"<td><span class='badge'>{winner}</span></td>"
            f"<td>{html.escape(note)}</td>"
            "</tr>"
        )

    decision_rows = "\n".join(
        [
            decision_row("قيمة المحفظة", "portfolio_value", money, "الأعلى يعني نتيجة نهائية أفضل."),
            decision_row("الربح بالدولار", "pnl", money, "يقيس الربح الفعلي فوق رأس المال."),
            decision_row("عائد الفترة", "period_return_pct", pct, "العائد من بداية 2024 حتى آخر تحديث."),
            decision_row("العائد السنوي", "annual_return_pct", pct, "مفيد للمقارنة، وليس رقمًا منفصلًا عن عائد الفترة."),
            decision_row("نسبة الفوز", "win_rate", pct, "الأعلى يعني صفقات رابحة أكثر نسبيًا."),
            decision_row("عدد الخسائر", "losses", lambda value: f"{int(fnum(value))}", "الأقل أفضل في ضبط المخاطر.", higher_is_better=False),
            decision_row("السحب الأقصى", "max_drawdown_pct", pct, "الأقرب للصفر أفضل لأنه يعني هبوطًا أقل."),
            decision_row("متوسط ربح الصفقة", "avg_win_pct", pct, "الأعلى أفضل للصفقات الرابحة."),
            decision_row("متوسط خسارة الصفقة", "avg_loss_pct", pct, "الأقرب للصفر أفضل للخسائر."),
            decision_row("عدد الصفقات", "trades", lambda value: f"{int(fnum(value))}", "معلومة تشغيلية، ليست وحدها معيار تفوق."),
        ]
    )
    strategy_rows = "\n".join(
        f"<tr><td><strong class='ltr'>{html.escape(str(row['ticker']))}</strong></td><td>{html.escape(str(row.get('strategy_source','')))}</td><td>{html.escape(str(row.get('timeframe','')))}</td><td><span class='ltr'>{html.escape(str(row.get('entry_rule','')))}</span></td><td><span class='ltr'>{html.escape(str(row.get('strategy_id','')))}</span></td></tr>"
        for row in sorted(strategies, key=lambda item: (str(item["ticker"]), str(item.get("timeframe", ""))))
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>محفظة V3.1 الهجينة</title>
  <style>
    :root {{ --bg:#f4f7fa; --panel:#fff; --text:#061629; --muted:#61738a; --line:#d7e2ec; --blue:#1d6597; --green:#14745f; --red:#a8373d; --soft:#eaf1f7; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    main {{ max-width:1540px; margin:0 auto; padding:22px; }} header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:30px; }} h2 {{ margin:0 0 12px; font-size:22px; }} .sub,small {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }} .btn {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; color:var(--blue); text-decoration:none; }} .btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }} .card,.panel,.chart-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .card span {{ display:block; color:var(--muted); }} .card strong {{ display:block; direction:ltr; text-align:right; font-size:30px; margin-top:7px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }} th {{ background:var(--soft); color:#24364d; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }} .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }} .positive {{ color:var(--green); font-weight:800; }} .negative {{ color:var(--red); font-weight:800; }}
    .metric {{ width:190px; font-weight:800; }} .strong {{ font-weight:900; }} .badge {{ display:inline-block; padding:3px 9px; border-radius:999px; background:#e7f3ee; color:var(--green); font-weight:800; direction:ltr; unicode-bidi:isolate; }}
    .decision-table td:nth-child(5), .decision-table th:nth-child(5) {{ text-align:center; }}
    canvas {{ width:100%; height:320px; }} .stack {{ display:grid; gap:14px; margin-top:14px; }} @media (max-width:1000px) {{ header {{ display:block; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>محفظة V3.1 الهجينة</h1>
      <div class="sub">اختيار V2 للأسهم التي تفوقت فيها، واختيار V3 للأسهم التي حسنت المخاطر/الربح، ثم محاكاة المحفظة كاملة بالكاش والسيولة وتداخل الصفقات.</div>
    </div>
    <nav class="nav">
      <a class="btn" href="paper_portfolio_v2_dashboard.html">V2</a>
      <a class="btn" href="paper_portfolio_v3_dashboard.html">V3</a>
      <a class="btn primary" href="portfolio_dashboard.html">V3.1</a>
      <a class="btn" href="portfolio_simulation.html">محاكاة V3.1</a>
    </nav>
  </header>

  <section class="grid">
    <article class="card"><span>قيمة V3.1</span><strong class="{tone(v31_row['portfolio_value'])}">{money(v31_row['portfolio_value'])}</strong><small>آخر تحديث {v31_row['end_date']}</small></article>
    <article class="card"><span>الربح على رأس المال</span><strong class="{tone(v31_row['pnl'])}">{money(v31_row['pnl'])}</strong><small>عائد الفترة {pct(v31_row['period_return_pct'])}</small></article>
    <article class="card"><span>فرقها عن V2</span><strong class="{tone(fnum(v31_row['portfolio_value']) - fnum(v2_row['portfolio_value']))}">{money(fnum(v31_row['portfolio_value']) - fnum(v2_row['portfolio_value']))}</strong><small>فرق قيمة المحفظة</small></article>
    <article class="card"><span>الكاش الحالي</span><strong>{money(current_cash)}</strong><small>غير محقق {money(unrealized_pnl)}</small></article>
    <article class="card"><span>صفقات مفتوحة / مغلقة</span><strong>{len(v31_open)} / {len(v31_closed)}</strong><small>أقصى صفقات مفتوحة {max_open}</small></article>
    <article class="card"><span>نسبة الفوز</span><strong>{pct(v31_row['win_rate'])}</strong><small>رابحة {int(v31_row['wins'])} / خاسرة {int(v31_row['losses'])}</small></article>
    <article class="card"><span>السحب الأقصى</span><strong class="negative">{pct(v31_row['max_drawdown_pct'])}</strong><small>V2 {pct(v2_row['max_drawdown_pct'])} / V3 {pct(v3_row['max_drawdown_pct'])}</small></article>
    <article class="card"><span>أكبر مركز مفتوح</span><strong>{money(largest_position)}</strong><small>متوسط خسارة {pct(v31_row['avg_loss_pct'])}</small></article>
  </section>

  <section class="chart-wrap" style="margin-top:14px;">
    <h2>منحنى المحفظة</h2>
    <canvas id="equityChart" width="1300" height="340"></canvas>
  </section>

  <div class="stack">
    <section class="panel">
      <h2>الصفقات المفتوحة الآن</h2>
      <table>
        <thead><tr><th>السهم</th><th>المصدر</th><th>الإطار</th><th>تاريخ الدخول</th><th>الأسهم</th><th>الدخول</th><th>آخر سعر</th><th>ربح/خسارة</th><th>%</th></tr></thead>
        <tbody>{open_trade_rows or '<tr><td colspan="9">لا توجد صفقات مفتوحة.</td></tr>'}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>مؤشرات المخاطر والتشغيل</h2>
      <table class="decision-table">
        <thead><tr><th>المؤشر</th><th>القيمة</th><th>قراءة سريعة</th></tr></thead>
        <tbody>
          <tr><th class="metric">السحب الأقصى</th><td class="num negative">{pct(v31_row['max_drawdown_pct'])}</td><td>أفضل من V2 وV3 في الهبوط التاريخي.</td></tr>
          <tr><th class="metric">متوسط الربح</th><td class="num positive">{pct(v31_row['avg_win_pct'])}</td><td>متوسط الصفقة الرابحة في V3.1.</td></tr>
          <tr><th class="metric">متوسط الخسارة</th><td class="num negative">{pct(v31_row['avg_loss_pct'])}</td><td>قريب من V2، لكنه أعلى من V2 بقليل.</td></tr>
          <tr><th class="metric">أكبر مركز مفتوح</th><td class="num">{money(largest_position)}</td><td>لقياس تركز المحفظة الحالي.</td></tr>
          <tr><th class="metric">أقصى عدد صفقات مفتوحة</th><td class="num">{max_open}</td><td>مهم لمتابعة التزاحم على الكاش.</td></tr>
          <tr><th class="metric">الربح المحقق</th><td class="num positive">{money(realized_pnl)}</td><td>ربح الصفقات التي أغلقت فقط.</td></tr>
          <tr><th class="metric">الربح غير المحقق</th><td class="num {tone(unrealized_pnl)}">{money(unrealized_pnl)}</td><td>ربح أو خسارة الصفقات المفتوحة الآن.</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>المسار الشهري للمحفظة</h2>
      <table>
        <thead><tr><th>الشهر</th><th>قيمة نهاية الشهر</th><th>ربح/خسارة الشهر</th><th>عائد الشهر</th><th>الكاش</th><th>صفقات مفتوحة</th></tr></thead>
        <tbody>{monthly_rows}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>مصفوفة القرار</h2>
      <table class="decision-table">
        <thead><tr><th>المعيار</th><th>V2</th><th>V3</th><th>V3.1</th><th>الفائز</th><th>الملاحظة</th></tr></thead>
        <tbody>{decision_rows}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>مقارنة حسب السهم</h2>
      <table>
        <thead><tr><th>السهم</th><th>ربح V2</th><th>ربح V3</th><th>ربح V3.1</th><th>مصدر V3.1</th><th>الفائز سهميًا</th></tr></thead>
        <tbody>
          {''.join(f"<tr><td><strong class='ltr'>{row['ticker']}</strong></td><td class='num {tone(row['v2_pnl'])}'>{money(row['v2_pnl'])}</td><td class='num {tone(row['v3_pnl'])}'>{money(row['v3_pnl'])}</td><td class='num {tone(row['v31_pnl'])}'>{money(row['v31_pnl'])}</td><td>{row['v31_source']}</td><td><span class='badge'>{row['best_by_ticker']}</span></td></tr>" for row in ticker_rows)}
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>الاستراتيجيات المستخدمة</h2>
      <table>
        <thead><tr><th>السهم</th><th>المصدر</th><th>الإطار</th><th>الدخول</th><th>الاستراتيجية</th></tr></thead>
        <tbody>{strategy_rows}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>آخر الصفقات المغلقة</h2>
      <table>
        <thead><tr><th>تاريخ الإغلاق</th><th>السهم</th><th>المصدر</th><th>النتيجة</th><th>الدخول</th><th>الخروج</th><th>ربح/خسارة</th><th>%</th></tr></thead>
        <tbody>{recent_closed_rows}</tbody>
      </table>
      <small>لرؤية السجل الكامل افتح صفحة المحاكاة التفصيلية.</small>
    </section>
  </div>
</main>
<script>
const V2_POINTS = {equity_points(v2_state)};
const V3_POINTS = {equity_points(v3_state)};
const V31_POINTS = {equity_points(v31_state)};
function drawChart() {{
  const canvas = document.getElementById('equityChart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, pad = 42;
  const all = V2_POINTS.concat(V3_POINTS, V31_POINTS);
  const values = all.map(p => p[1]);
  const min = Math.min(...values), max = Math.max(...values);
  function x(i, n) {{ return pad + i * (w - pad * 2) / Math.max(n - 1, 1); }}
  function y(value) {{ return h - pad - (value - min) * (h - pad * 2) / Math.max(max - min, 1); }}
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#d7e2ec'; ctx.lineWidth = 1;
  for (let i=0;i<5;i++) {{ const yy = pad + i*(h-pad*2)/4; ctx.beginPath(); ctx.moveTo(pad, yy); ctx.lineTo(w-pad, yy); ctx.stroke(); }}
  function line(points, color) {{ ctx.strokeStyle=color; ctx.lineWidth=3; ctx.beginPath(); points.forEach((p,i)=>{{const xx=x(i,points.length), yy=y(p[1]); if(i===0)ctx.moveTo(xx,yy); else ctx.lineTo(xx,yy);}}); ctx.stroke(); }}
  line(V2_POINTS, '#8192a8'); line(V3_POINTS, '#1d6597'); line(V31_POINTS, '#14745f');
  ctx.fillStyle = '#061629'; ctx.font = '16px Tahoma';
  ctx.fillText('V2', w - 95, y(V2_POINTS[V2_POINTS.length-1][1]) - 8);
  ctx.fillText('V3', w - 95, y(V3_POINTS[V3_POINTS.length-1][1]) + 18);
  ctx.fillText('V3.1', w - 115, y(V31_POINTS[V31_POINTS.length-1][1]) + 32);
}}
drawChart();
</script>
</body>
</html>"""


def monthly_summary_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    month_end: dict[str, dict[str, Any]] = {}
    for row in state.get("snapshots", []):
        month_end[str(row["date"])[:7]] = row
    rows: list[dict[str, Any]] = []
    previous_value = v2.INITIAL_CAPITAL
    for month, row in sorted(month_end.items()):
        value = fnum(row["value"])
        rows.append(
            {
                "month": month,
                "ending_value": round(value, 2),
                "pnl": round(value - previous_value, 2),
                "return_pct": round((value / previous_value - 1) * 100, 2) if previous_value else 0.0,
                "cash": round(fnum(row.get("cash")), 2),
                "open_trades": int(fnum(row.get("open_trades"))),
            }
        )
        previous_value = value
    return rows


def official_signal_text(trade: dict[str, Any]) -> str:
    return " ".join(
        str(trade.get(field, "")).lower()
        for field in ("behavior", "entry_rule", "strategy_id")
    )


def official_behavior_label(trade: dict[str, Any]) -> str:
    text = official_signal_text(trade)
    if "breakout" in text:
        return AR_BREAKOUT
    if "pullback" in text or "recovery" in text or "rsi" in text:
        return AR_PULLBACK
    if "trend" in text:
        return AR_TREND
    return AR_MIXED


def official_entry_rule_label(trade: dict[str, Any]) -> str:
    text = official_signal_text(trade)
    if "breakout" in text:
        return AR_BREAKOUT_RULE
    if "pullback" in text or "recovery" in text or "rsi" in text:
        return AR_PULLBACK_RULE
    if "trend" in text:
        return AR_TREND_RULE
    return AR_APPROVED_STRATEGY


def official_behavior_key(label: str) -> str:
    return {
        AR_BREAKOUT: "breakout",
        AR_PULLBACK: "rebound",
        AR_TREND: "trend",
        AR_MIXED: "mixed",
    }.get(label, "approved")


def officialize_common_html(source: str) -> str:
    replacements = {
        "paper_portfolio_v2_dashboard.html": "portfolio_dashboard.html",
        "paper_portfolio_v2_analytics.html": "portfolio_analytics.html",
        "strategy_v2_dashboard.html": "portfolio_financial_diagnostics.html",
        "decision_hypothesis_preview.html": "portfolio_analytics.html",
        "business_intelligence_lab.html": "portfolio_business_intelligence.html",
        "financial_diagnostics_lab.html": "portfolio_financial_diagnostics.html",
        "settings_server_v2.py": AR_LOCAL_PORTFOLIO_SERVER,
        "v1_benchmark_tickers": "approved_tickers",
        'data-filter="breakout"': f'data-filter="{AR_BREAKOUT}"',
        'data-filter="pullback_recovery"': f'data-filter="{AR_PULLBACK}"',
        'data-filter="trend_following"': f'data-filter="{AR_TREND}"',
        'data-filter="mixed_or_choppy"': f'data-filter="{AR_MIXED}"',
        "محفظة ورقية V2": AR_PORTFOLIO_NAME,
        "محفظة النسخة الثانية": AR_PORTFOLIO_NAME,
        "محفظة V2": AR_PORTFOLIO_NAME,
        "تحليلات محفظة V2": "تحليلات المحفظة المعتمدة",
        "صفحة مشتقة من صفقات ومنحنى محفظة V2": "صفحة مشتقة من صفقات ومنحنى المحفظة المعتمدة",
        "خادم إعدادات V2": "خادم إعدادات المحفظة",
        "خادم تحديث V2": "خادم تحديث المحفظة",
        "V2 settings server": "Portfolio settings server",
        "الرابط المنشور للعرض ويتحدث تلقائيا كل ساعة من جهاز مصدر البيانات.": "الرابط المنشور للعرض ويتحدث تلقائيا مرة يوميا من EODHD عبر GitHub.",
        "الرابط المنشور للعرض، أما التحديث التلقائي فيعمل كل ساعة من جهاز مصدر البيانات.": "الرابط المنشور للعرض، أما التحديث التلقائي فيعمل مرة يوميا من EODHD عبر GitHub.",
        "خطوة رفع الوقف %": "خطوة الوقف اليومي للجلسة التالية %",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    update_marker = '<div class="last-update">'
    update_index = source.find(update_marker)
    if update_index >= 0 and "EODHD 5m" not in source[update_index : update_index + 500]:
        update_end = source.find("</div>", update_index) + len("</div>")
        data_source_note = (
            '<div class="last-update">مصدر بيانات التداول والتنفيذ: '
            '<strong class="ltr">EODHD 5m</strong> | '
            'الوقف المتحرك يحسب من أعلى يوم مكتمل ويتفعل في جلسة التداول التالية '
            'بدرجة <strong class="ltr">0.5%</strong>.</div>'
            '<div class="last-update">تنبيه منهجي: بداية العرض الرسمية '
            '<strong class="ltr">2021-01-01</strong>، واستُخدمت سنة '
            '<strong class="ltr">2021</strong> لاختيار درجة الوقف. '
            'القراءة المحافظة خارج الاختيار تبدأ من '
            '<strong class="ltr">2022-01-01</strong>.</div>'
        )
        source = source[:update_end] + data_source_note + source[update_end:]
    source = re.sub(r'\s*<button[^>]*data-filter="v2_refined"[^>]*>.*?</button>', "", source, flags=re.S)
    source = re.sub(r'\s*<button[^>]*data-filter="v1_original"[^>]*>.*?</button>', "", source, flags=re.S)
    source = re.sub(
        r'\s*<a[^>]+href="portfolio_analytics\.html"[^>]*>\s*\u0645\u0639\u0627\u064a\u0646\u0629 \u0627\u0644\u062f\u0645\u062c\s*</a>',
        "",
        source,
        flags=re.S,
    )
    return source


def remove_bi_comparison_sections(source: str) -> str:
    source = re.sub(
        r"\s*<article class=\"metric\">(?:(?!</article>).)*V2(?:(?!</article>).)*</article>",
        "",
        source,
        flags=re.S,
    )
    source = re.sub(
        r"\s*<div class=\"decision-card[^\"]*\">(?:(?!</div>).)*V2(?:(?!</div>).)*</div>",
        "",
        source,
        flags=re.S,
    )
    source = re.sub(
        r"\s*<div class=\"panel table-wrap\">\s*<h2>[^<]*V2[^<]*V1(?:(?!</div>).)*</div>",
        "",
        source,
        count=1,
        flags=re.S,
    )
    return source


def build_official_financial_payload() -> dict[str, Any]:
    import financial_diagnostics_lab as financial_lab

    original = (financial_lab.TRADES_CSV, financial_lab.OUT, financial_lab.JSON_OUT)
    try:
        financial_lab.TRADES_CSV = OFFICIAL_TRADES_CSV
        financial_lab.OUT = OFFICIAL_FINANCIAL_DASHBOARD
        financial_lab.JSON_OUT = OFFICIAL_FINANCIAL_JSON
        payload = financial_lab.build_payload()
        OFFICIAL_FINANCIAL_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        html_text = officialize_common_html(financial_lab.render(payload))
        OFFICIAL_FINANCIAL_DASHBOARD.write_text(html_text, encoding="utf-8", newline="\n")
        return payload
    finally:
        financial_lab.TRADES_CSV, financial_lab.OUT, financial_lab.JSON_OUT = original


def build_official_business_payload() -> dict[str, Any]:
    import business_intelligence_lab as business_lab

    original = (
        business_lab.TRADES_CSV,
        business_lab.EQUITY_CSV,
        business_lab.FINANCIAL_JSON,
        business_lab.OUT,
    )
    try:
        business_lab.TRADES_CSV = OFFICIAL_TRADES_CSV
        business_lab.EQUITY_CSV = OFFICIAL_EQUITY_CSV
        business_lab.FINANCIAL_JSON = OFFICIAL_FINANCIAL_JSON
        business_lab.OUT = OFFICIAL_BUSINESS_INTELLIGENCE_DASHBOARD
        payload = business_lab.build_payload()
        payload["decisions"] = [
            item
            for item in payload.get("decisions", [])
            if "V2" not in json.dumps(item, ensure_ascii=False)
            and "V1" not in json.dumps(item, ensure_ascii=False)
        ]
        html_text = business_lab.render(payload)
        html_text = remove_bi_comparison_sections(html_text)
        html_text = officialize_common_html(html_text)
        OFFICIAL_BUSINESS_INTELLIGENCE_DASHBOARD.write_text(html_text, encoding="utf-8", newline="\n")
        return payload
    finally:
        business_lab.TRADES_CSV, business_lab.EQUITY_CSV, business_lab.FINANCIAL_JSON, business_lab.OUT = original


def build_official_analytics_dashboard(financial_payload: dict[str, Any], business_payload: dict[str, Any]) -> None:
    import experimental_decision_center as decision_center
    from business_intelligence_overlay_preview import apply_analytics_bi_overlay
    from dashboard_financial_overlay_preview import apply_analytics_financial_overlay

    original = (
        decision_center.TRADES_CSV,
        decision_center.EQUITY_CSV,
        decision_center.OUT,
        decision_center.LOCAL_PREVIEW_OUT,
    )
    try:
        decision_center.TRADES_CSV = OFFICIAL_TRADES_CSV
        decision_center.EQUITY_CSV = OFFICIAL_EQUITY_CSV
        decision_center.OUT = OFFICIAL_ANALYTICS_DASHBOARD
        decision_center.LOCAL_PREVIEW_OUT = REPORTS / "portfolio_analytics_preview.html"
        decision_center.main()
    finally:
        (
            decision_center.TRADES_CSV,
            decision_center.EQUITY_CSV,
            decision_center.OUT,
            decision_center.LOCAL_PREVIEW_OUT,
        ) = original

    analytics_html = OFFICIAL_ANALYTICS_DASHBOARD.read_text(encoding="utf-8")
    analytics_html = apply_analytics_financial_overlay(analytics_html, financial_payload)
    analytics_html = apply_analytics_bi_overlay(analytics_html, business_payload)
    analytics_html = officialize_common_html(analytics_html)
    OFFICIAL_ANALYTICS_DASHBOARD.write_text(analytics_html, encoding="utf-8", newline="\n")


def official_display_state(state: dict[str, Any]) -> dict[str, Any]:
    display_state = dict(state)
    display_trades: list[dict[str, Any]] = []
    for trade in state.get("trades", []):
        row = dict(trade)
        row["behavior"] = official_behavior_label(row)
        row["entry_rule"] = official_entry_rule_label(row)
        row["strategy_id"] = (
            f"{row.get('ticker', '')}_{row.get('timeframe', '')}_"
            f"{official_behavior_key(row['behavior'])}_approved"
        )
        row.pop("v3_quality_score", None)
        row.pop("v3_reason", None)
        row["selected_version"] = AR_POLICY_LABEL
        row["strategy_source"] = AR_APPROVED_LABEL
        display_trades.append(row)
    display_state["trades"] = display_trades
    return display_state


def official_simulation_state(state: dict[str, Any]) -> dict[str, Any]:
    display_state = official_display_state(state)
    display_ledger: list[dict[str, Any]] = []
    for ledger_row in state.get("ledger", []):
        row = dict(ledger_row)
        row["source"] = AR_APPROVED_LABEL
        row["note"] = str(row.get("note", "")).replace("V3.1", AR_POLICY_LABEL)
        display_ledger.append(row)
    display_state["ledger"] = display_ledger
    return display_state


def build_official_dashboard(state: dict[str, Any]) -> None:
    from business_intelligence_overlay_preview import apply_dashboard_bi_overlay
    from dashboard_financial_overlay_preview import apply_dashboard_financial_overlay

    financial_payload = build_official_financial_payload()
    business_payload = build_official_business_payload()
    dashboard_html = v2.render_dashboard(official_display_state(state))
    dashboard_html = apply_dashboard_financial_overlay(dashboard_html, financial_payload)
    dashboard_html = apply_dashboard_bi_overlay(dashboard_html, business_payload)
    dashboard_html = officialize_common_html(dashboard_html)
    OFFICIAL_DASHBOARD.write_text(dashboard_html, encoding="utf-8", newline="\n")
    shutil.copy2(OFFICIAL_DASHBOARD, PAPER_PORTFOLIO_DASHBOARD)
    build_official_analytics_dashboard(financial_payload, business_payload)


def render_simulation_dashboard(state: dict[str, Any], strategies: list[dict[str, Any]]) -> str:
    trades = state["trades"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    open_trades = [trade for trade in trades if trade.get("status") == "OPEN"]
    ledger = state.get("ledger", [])
    snapshots = state.get("snapshots", [])
    realized_pnl = sum(fnum(trade.get("realized_pnl")) for trade in closed)
    unrealized_pnl = sum(fnum(trade.get("unrealized_pnl")) for trade in open_trades)
    max_open = max((int(fnum(row.get("open_trades"))) for row in snapshots), default=0)
    drawdown = v2.max_drawdown(snapshots)
    final_value = v2.portfolio_value(state)

    month_rows = "\n".join(
        f"<tr><td class='ltr'>{row['month']}</td><td class='num'>{money(row['ending_value'])}</td><td class='num {tone(row['pnl'])}'>{money(row['pnl'])}</td><td class='num {tone(row['return_pct'])}'>{pct(row['return_pct'])}</td><td class='num'>{money(row['cash'])}</td><td class='num'>{row['open_trades']}</td></tr>"
        for row in monthly_summary_rows(state)
    )
    open_rows = "\n".join(
        f"<tr><td><strong class='ltr'>{html.escape(str(row['ticker']))}</strong></td><td>{html.escape(str(row.get('strategy_source','')))}</td><td>{html.escape(str(row.get('timeframe','')))}</td><td class='ltr'>{html.escape(str(row.get('entry_date','')))}</td><td class='num'>{int(fnum(row.get('shares')))}</td><td class='num'>{money(row.get('entry_price'))}</td><td class='num'>{money(row.get('latest_price'))}</td><td class='num {tone(row.get('unrealized_pnl'))}'>{money(row.get('unrealized_pnl'))}</td><td class='num {tone(row.get('unrealized_pnl_pct'))}'>{pct(row.get('unrealized_pnl_pct'))}</td></tr>"
        for row in sorted(open_trades, key=lambda item: fnum(item.get("market_value")), reverse=True)
    )
    ledger_rows = "\n".join(
        f"<tr><td class='ltr'>{html.escape(str(row.get('date','')))}</td><td><span class='badge {str(row.get('action','')).lower()}'>{html.escape(str(row.get('action','')))}</span></td><td class='ltr'>{html.escape(str(row.get('trade_id','')))}</td><td><strong class='ltr'>{html.escape(str(row.get('ticker','')))}</strong></td><td>{html.escape(str(row.get('source','')))}</td><td class='num'>{html.escape(str(row.get('shares','')))}</td><td class='num'>{money(row.get('price')) if row.get('price') != '' else ''}</td><td class='num'>{money(row.get('amount')) if row.get('amount') != '' else ''}</td><td class='num'>{money(row.get('cash_after'))}</td><td class='num'>{money(row.get('portfolio_value_after'))}</td><td class='num {tone(row.get('pnl'))}'>{money(row.get('pnl'))}</td><td>{html.escape(str(row.get('note','')))}</td></tr>"
        for row in ledger
    )
    source_counts: dict[str, int] = {}
    for strategy in strategies:
        source = str(strategy.get("strategy_source", ""))
        source_counts[source] = source_counts.get(source, 0) + 1
    source_text = " / ".join(f"{html.escape(source)}: {count}" for source, count in sorted(source_counts.items()))

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>محاكاة محفظة V3.1</title>
  <style>
    :root {{ --bg:#f4f7fa; --panel:#fff; --text:#061629; --muted:#61738a; --line:#d7e2ec; --blue:#1d6597; --green:#14745f; --red:#a8373d; --soft:#eaf1f7; --amber:#9b6400; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    main {{ max-width:1580px; margin:0 auto; padding:22px; }} header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:30px; }} h2 {{ margin:0 0 12px; font-size:22px; }} .sub,small {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }} .btn {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; color:var(--blue); text-decoration:none; }} .btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }} .card,.panel,.chart-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .card span {{ display:block; color:var(--muted); }} .card strong {{ display:block; direction:ltr; text-align:right; font-size:30px; margin-top:7px; }}
    .stack {{ display:grid; gap:14px; margin-top:14px; }} table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:9px 10px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }} th {{ background:var(--soft); color:#24364d; position:sticky; top:0; z-index:1; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }} .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .positive {{ color:var(--green); font-weight:800; }} .negative {{ color:var(--red); font-weight:800; }} canvas {{ width:100%; height:320px; }}
    .badge {{ display:inline-block; min-width:58px; text-align:center; padding:2px 8px; border-radius:999px; background:#eef4f8; color:#24364d; font-weight:800; direction:ltr; unicode-bidi:isolate; }}
    .badge.entry {{ background:#e7f3ee; color:var(--green); }} .badge.exit {{ background:#f8eeee; color:var(--red); }} .badge.start {{ background:#fff4df; color:var(--amber); }}
    .table-wrap {{ max-height:620px; overflow:auto; border-radius:8px; border:1px solid var(--line); }} .table-wrap table {{ border:0; border-radius:0; }}
    @media (max-width:1000px) {{ header {{ display:block; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>محاكاة المحفظة المعتمدة</h1>
      <div class="sub">هذه الصفحة تعرض مسار المحفظة الكامل بعد اعتماد الوقف اليومي الذي يتفعل من الجلسة التالية.</div>
      <small>الاستراتيجيات المستخدمة: {source_text}</small>
    </div>
    <nav class="nav">
      <a class="btn" href="portfolio_dashboard.html">المحفظة</a>
      <a class="btn primary" href="portfolio_simulation.html">المحاكاة</a>
      <a class="btn" href="paper_portfolio_v2_dashboard.html">V2</a>
      <a class="btn" href="paper_portfolio_v3_dashboard.html">V3</a>
    </nav>
  </header>

  <section class="grid">
    <article class="card"><span>رأس المال الابتدائي</span><strong>{money(v2.INITIAL_CAPITAL)}</strong><small>بداية {CONFIG['start_date']}</small></article>
    <article class="card"><span>قيمة المحفظة النهائية</span><strong class="positive">{money(final_value)}</strong><small>حتى {snapshots[-1]['date'] if snapshots else ''}</small></article>
    <article class="card"><span>الكاش الحالي</span><strong>{money(state.get('cash'))}</strong><small>بعد آخر يوم محاكاة</small></article>
    <article class="card"><span>الربح المحقق</span><strong class="{tone(realized_pnl)}">{money(realized_pnl)}</strong><small>الربح غير المحقق {money(unrealized_pnl)}</small></article>
    <article class="card"><span>الصفقات المغلقة</span><strong>{len(closed)}</strong><small>من أصل {len(trades)} صفقة</small></article>
    <article class="card"><span>الصفقات المفتوحة</span><strong>{len(open_trades)}</strong><small>أقصى تركز مفتوح {max_open}</small></article>
    <article class="card"><span>السحب الأقصى</span><strong class="negative">{pct(drawdown.get('drawdown'))}</strong><small>أقل هبوط تاريخي في المسار</small></article>
    <article class="card"><span>سجل العمليات</span><strong>{len(ledger)}</strong><small>دخول وخروج وبداية المحفظة</small></article>
  </section>

  <section class="chart-wrap" style="margin-top:14px;">
    <h2>القيمة والكاش عبر الزمن</h2>
    <canvas id="simChart" width="1300" height="340"></canvas>
  </section>

  <div class="stack">
    <section class="panel">
      <h2>الصفقات المفتوحة الآن</h2>
      <table>
        <thead><tr><th>السهم</th><th>المصدر</th><th>الإطار</th><th>الدخول</th><th>الأسهم</th><th>سعر الدخول</th><th>آخر سعر</th><th>ربح/خسارة</th><th>%</th></tr></thead>
        <tbody>{open_rows or '<tr><td colspan="9">لا توجد صفقات مفتوحة.</td></tr>'}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>ملخص شهري للمحفظة</h2>
      <table>
        <thead><tr><th>الشهر</th><th>قيمة نهاية الشهر</th><th>ربح/خسارة الشهر</th><th>عائد الشهر</th><th>الكاش</th><th>صفقات مفتوحة</th></tr></thead>
        <tbody>{month_rows}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>سجل المحاكاة الكامل</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>التاريخ</th><th>العملية</th><th>رقم الصفقة</th><th>السهم</th><th>المصدر</th><th>الأسهم</th><th>السعر</th><th>القيمة</th><th>الكاش بعد العملية</th><th>قيمة المحفظة بعدها</th><th>ربح/خسارة</th><th>الملاحظة</th></tr></thead>
          <tbody>{ledger_rows}</tbody>
        </table>
      </div>
    </section>
  </div>
</main>
<script>
const POINTS = {json.dumps([[row["date"], fnum(row["value"]), fnum(row.get("cash"))] for row in snapshots], ensure_ascii=False)};
function drawChart() {{
  const canvas = document.getElementById('simChart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, pad = 42;
  const vals = POINTS.flatMap(p => [p[1], p[2]]);
  const min = Math.min(...vals), max = Math.max(...vals);
  function x(i,n) {{ return pad + i * (w - pad*2) / Math.max(n-1,1); }}
  function y(v) {{ return h - pad - (v-min) * (h-pad*2) / Math.max(max-min,1); }}
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle = '#d7e2ec'; ctx.lineWidth = 1;
  for (let i=0;i<5;i++) {{ const yy = pad + i*(h-pad*2)/4; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(w-pad,yy); ctx.stroke(); }}
  function line(col, color) {{ ctx.strokeStyle=color; ctx.lineWidth=3; ctx.beginPath(); POINTS.forEach((p,i)=>{{ const xx=x(i,POINTS.length), yy=y(p[col]); if(i===0)ctx.moveTo(xx,yy); else ctx.lineTo(xx,yy); }}); ctx.stroke(); }}
  line(1, '#14745f'); line(2, '#1d6597');
  ctx.fillStyle = '#061629'; ctx.font = '16px Tahoma';
  ctx.fillText('القيمة', w-120, y(POINTS[POINTS.length-1][1]) - 8);
  ctx.fillText('الكاش', w-120, y(POINTS[POINTS.length-1][2]) + 18);
}}
drawChart();
</script>
</body>
</html>"""


def render_official_simulation_dashboard(state: dict[str, Any], strategies: list[dict[str, Any]]) -> str:
    official_strategies = [{**strategy, "strategy_source": AR_APPROVED_LABEL} for strategy in strategies]
    source = render_simulation_dashboard(official_simulation_state(state), official_strategies)
    source = re.sub(r'\s*<a class="btn" href="paper_portfolio_v2_dashboard\.html">V2</a>', "", source)
    source = re.sub(r'\s*<a class="btn" href="paper_portfolio_v3_dashboard\.html">V3</a>', "", source)
    return officialize_common_html(source)


def build_historical_comparison_reports(
    v31_strategies: list[dict[str, Any]],
    v31_state: dict[str, Any],
) -> None:
    v2_strategies, v2_quality = v2.selected_portfolio_strategies()
    v2_state = v2.simulate_portfolio(v2_strategies, v2_quality)
    v3_strategies = read_csv(REPORTS / "selected_strategies_v3.csv")
    v3_state = v3.simulate_rebuild_portfolio(v3_strategies)
    comparison = comparison_rows(v2_state, v3_state, v31_state)
    ticker_rows = ticker_comparison_rows(v2_state, v3_state, v31_state)
    write_csv(COMPARISON_CSV, comparison)
    write_csv(TICKER_COMPARISON_CSV, ticker_rows)
    write_csv(OFFICIAL_COMPARISON_CSV, comparison)
    write_csv(OFFICIAL_TICKER_COMPARISON_CSV, ticker_rows)
    DASHBOARD.write_text(render_dashboard(comparison, ticker_rows, v31_strategies, v2_state, v3_state, v31_state), encoding="utf-8", newline="\n")


def main(include_comparisons: bool = False) -> int:
    v31_strategies = load_hybrid_strategies()
    v31_state = simulate_hybrid_portfolio(v31_strategies)
    official_state = official_display_state(v31_state)
    write_csv(STRATEGIES_CSV, v31_strategies)
    write_csv(TRADES_CSV, v31_state["trades"])
    write_csv(EQUITY_CSV, v31_state["snapshots"])
    write_csv(LEDGER_CSV, v31_state["ledger"])
    write_csv(OFFICIAL_TRADES_CSV, official_state["trades"])
    write_csv(OFFICIAL_EQUITY_CSV, official_state["snapshots"])
    write_csv(OFFICIAL_LEDGER_CSV, official_state["ledger"])
    write_csv(OFFICIAL_STRATEGIES_CSV, v31_strategies)
    OFFICIAL_EXECUTION_METADATA_JSON.write_text(
        json.dumps(
            {
                "market_data_source": v31_state.get("market_data_source"),
                "market_data_interval": v31_state.get("market_data_interval"),
                "execution_model": v31_state.get("execution_model"),
                "execution_diagnostics": v31_state.get("execution_diagnostics"),
                "trailing_stop_step_pct": fnum(CONFIG.get("trailing_stop_step_pct")),
                "trailing_stop_update_timing": v31_state.get("trailing_stop_update_timing"),
                "trailing_stop_selection_period": CONFIG.get("trailing_stop_selection_period"),
                "conservative_evaluation_period_start": CONFIG.get("conservative_evaluation_period_start"),
                "portfolio_summary": portfolio_summary(v31_state, "V3.1 approved / daily-high next-session trailing"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    SIMULATION_DASHBOARD.write_text(render_simulation_dashboard(v31_state, v31_strategies), encoding="utf-8", newline="\n")
    OFFICIAL_SIMULATION_DASHBOARD.write_text(
        render_official_simulation_dashboard(v31_state, v31_strategies),
        encoding="utf-8",
        newline="\n",
    )
    build_official_dashboard(v31_state)
    organized_portfolio = firm_structure.sync_active_portfolio_outputs(CONFIG)
    if include_comparisons:
        build_historical_comparison_reports(v31_strategies, v31_state)
    print(f"V3.1 strategies: {len(v31_strategies)}")
    print(f"V3.1 value: {v2.portfolio_value(v31_state):.2f}")
    if include_comparisons:
        print(f"Comparison dashboard: {DASHBOARD}")
    print(f"Official dashboard: {OFFICIAL_DASHBOARD}")
    print(f"Official analytics: {OFFICIAL_ANALYTICS_DASHBOARD}")
    print(f"Simulation: {SIMULATION_DASHBOARD}")
    print(f"Organized portfolio workspace: {organized_portfolio}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the approved portfolio dashboards.")
    parser.add_argument(
        "--include-comparisons",
        action="store_true",
        help="Rebuild archived V2 and V3 comparison reports for a board review.",
    )
    args = parser.parse_args()
    raise SystemExit(main(include_comparisons=args.include_comparisons))
