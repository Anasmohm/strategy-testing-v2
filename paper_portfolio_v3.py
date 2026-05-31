#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import math
from pathlib import Path
from typing import Any

import design_strategies
import paper_portfolio_v2 as v2


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

TRADES_CSV = REPORTS / "paper_trades_v3.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v3.csv"
DEFENSIVE_TRADES_CSV = REPORTS / "paper_trades_v3_defensive.csv"
DEFENSIVE_EQUITY_CSV = REPORTS / "paper_equity_curve_v3_defensive.csv"
STRATEGIES_CSV = REPORTS / "selected_strategies_v3.csv"
QUALITY_CSV = REPORTS / "strategy_quality_v3.csv"
COMPARISON_CSV = REPORTS / "v2_vs_v3_portfolio_comparison.csv"
DASHBOARD = REPORTS / "paper_portfolio_v3_dashboard.html"

START_DATE = dt.date.fromisoformat(CONFIG["start_date"])
INITIAL_CAPITAL = float(CONFIG.get("initial_capital", 10000.0))
POSITION_CAP_PCT = float(CONFIG.get("position_cap_pct", 0.4))
LIQUIDITY_LOOKBACK_DAYS = int(CONFIG.get("liquidity_lookback_days", 20))
MAX_TRADE_ADV_PCT = float(CONFIG.get("max_trade_adv_pct", 0.01))
TRAILING_STOP_STEP_PCT = float(CONFIG.get("trailing_stop_step_pct", 1.0))
MIN_ACCEPTABLE_ANNUAL_RETURN_PCT = float(CONFIG.get("min_acceptable_annual_return_pct", 70.0))

MARKET_TICKERS = ("SPY", "QQQ", "SOXX")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def moving_average(values: list[float], index: int, lookback: int) -> float | None:
    if index + 1 < lookback:
        return None
    return mean(values[index - lookback + 1 : index + 1])


def return_pct(values: list[float], index: int, sessions: int) -> float:
    if index - sessions < 0 or values[index - sessions] == 0:
        return 0.0
    return (values[index] / values[index - sessions] - 1) * 100


def rsi_value(values: list[float], index: int, period: int = 14) -> float | None:
    series = design_strategies.rsi(values, period)
    if index >= len(series):
        return None
    return series[index]


def bars_by_ticker(tickers: set[str]) -> dict[str, list[design_strategies.Bar]]:
    return {ticker: v2.read_bars(ticker) for ticker in sorted(tickers)}


def index_by_date(bars: list[design_strategies.Bar]) -> dict[str, int]:
    return {bar.date: idx for idx, bar in enumerate(bars)}


def market_context_ok(market_bars: dict[str, list[design_strategies.Bar]], market_index: dict[str, dict[str, int]], date: str) -> tuple[bool, str]:
    checks: list[str] = []
    passed = 0
    for ticker in MARKET_TICKERS:
        bars = market_bars.get(ticker, [])
        idx = market_index.get(ticker, {}).get(date)
        if idx is None or idx < 200:
            continue
        closes = [bar.close for bar in bars]
        ma50 = moving_average(closes, idx, 50)
        ma200 = moving_average(closes, idx, 200)
        ret20 = return_pct(closes, idx, 20)
        ok = bool(ma50 and ma200 and closes[idx] > ma50 and (ma50 > ma200 or ret20 > -4.0))
        passed += 1 if ok else 0
        checks.append(f"{ticker}:{'داعم' if ok else 'ضغط'}")
    if not checks:
        return True, "لا توجد قراءة سوقية"
    return passed >= 2, " / ".join(checks)


def stock_context_ok(strategy: dict[str, Any], bars: list[design_strategies.Bar], index: int) -> tuple[bool, str]:
    closes = [bar.close for bar in bars]
    close = closes[index]
    ma20 = moving_average(closes, index, 20)
    ma50 = moving_average(closes, index, 50)
    ma200 = moving_average(closes, index, 200)
    ret20 = return_pct(closes, index, 20)
    rsi14 = rsi_value(closes, index, 14)
    entry_rule = str(strategy.get("entry_rule", ""))
    if entry_rule == "v1_breakout":
        ok = bool(ma20 and ma50 and close >= ma20 and (close >= ma50 or ret20 >= 0))
        return ok, f"اختراق: close/MA20 {close:.2f}/{ma20 or 0:.2f}, ret20 {ret20:.2f}%"
    if entry_rule == "v1_rsi_recovery":
        ok = bool(ma200 and close >= ma200 * 0.92 and ret20 > -18 and (rsi14 is None or rsi14 < 72))
        return ok, f"RSI: rsi14 {rsi14 or 0:.2f}, close/MA200 {close:.2f}/{ma200 or 0:.2f}"
    ok = bool(ma50 and ma200 and close >= ma50 * 0.96 and ret20 > -10)
    return ok, f"عام: ret20 {ret20:.2f}%"


def entry_signal_v3(
    strategy: dict[str, Any],
    bars: list[design_strategies.Bar],
    index: int,
    market_bars: dict[str, list[design_strategies.Bar]],
    market_index: dict[str, dict[str, int]],
) -> tuple[bool, str]:
    if not design_strategies.entry_signal(strategy, bars, index):
        return False, ""
    market_ok, market_note = market_context_ok(market_bars, market_index, bars[index].date)
    stock_ok, stock_note = stock_context_ok(strategy, bars, index)
    if not market_ok:
        return False, f"رفض سوقي: {market_note}"
    if not stock_ok:
        return False, f"رفض فني: {stock_note}"
    return True, f"{market_note}; {stock_note}"


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if fnum(trade.get("realized_pnl")) >= 0]
    losses = [trade for trade in closed if fnum(trade.get("realized_pnl")) < 0]
    pnl_values = [v2.trade_pnl(trade) for trade in trades]
    pct_values = [v2.trade_pnl_pct(trade) for trade in trades]
    positive_months: dict[str, float] = {}
    total_pnl = sum(pnl_values)
    for trade in trades:
        month = str(trade.get("entry_date", ""))[:7]
        positive_months[month] = positive_months.get(month, 0.0) + v2.trade_pnl(trade)
    top_month_pnl = max(positive_months.values(), default=0.0)
    concentration = top_month_pnl / total_pnl * 100 if total_pnl > 0 else 0.0
    return {
        "trades": len(trades),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
        "pnl": total_pnl,
        "avg_pct": mean(pct_values),
        "avg_win_pct": mean([v2.trade_pnl_pct(trade) for trade in wins]),
        "avg_loss_pct": mean([v2.trade_pnl_pct(trade) for trade in losses]),
        "worst_pct": min(pct_values, default=0.0),
        "best_pct": max(pct_values, default=0.0),
        "month_concentration_pct": concentration,
    }


def quality_score(stats: dict[str, Any]) -> float:
    score = 50.0
    score += (fnum(stats["win_rate"]) - 70.0) * 0.55
    score += fnum(stats["avg_pct"]) * 7.0
    score += min(fnum(stats["pnl"]) / 1000.0, 20.0)
    score += max(fnum(stats["worst_pct"]), -20.0) * 1.2
    score -= max(fnum(stats["month_concentration_pct"]) - 35.0, 0.0) * 0.15
    if fnum(stats["trades"]) < 8:
        score -= 12
    return round(score, 2)


def choose_size_multiplier(strategy: dict[str, Any], stats: dict[str, Any], score: float) -> tuple[float, str]:
    current = fnum(strategy.get("size_multiplier", 1.0), 1.0)
    reasons: list[str] = []
    multiplier = current
    if score >= 82 and fnum(stats["worst_pct"]) > -8 and fnum(stats["avg_pct"]) >= 2.2:
        multiplier = min(1.15, current * 1.15)
        reasons.append("رفع محدود لجودة عالية وسحب مقبول")
    elif score < 60 or fnum(stats["avg_pct"]) < 1.2:
        multiplier = min(multiplier, 0.55)
        reasons.append("خفض بسبب متوسط عائد ضعيف")
    if fnum(stats["worst_pct"]) <= -12:
        multiplier = min(multiplier, 0.65)
        reasons.append("خفض بسبب خسارة تاريخية عميقة")
    if fnum(stats["month_concentration_pct"]) >= 55:
        multiplier = min(multiplier, 0.75)
        reasons.append("خفض بسبب تركيز الربح في شهر واحد")
    if not reasons:
        reasons.append("إبقاء الحجم مع بوابات السوق والسهم")
    return round(max(multiplier, 0.35), 2), "؛ ".join(reasons)


def build_v3_strategies() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base_strategies, _ = v2.selected_portfolio_strategies()
    strategies: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    for strategy in base_strategies:
        proxy_state = v2.simulate_portfolio([strategy], [])
        stats = trade_stats(proxy_state["trades"])
        score = quality_score(stats)
        size_multiplier, reason = choose_size_multiplier(strategy, stats, score)
        approved = fnum(stats["pnl"]) > 0 and fnum(stats["win_rate"]) >= 70 and fnum(stats["trades"]) >= 8
        row = {
            "ticker": strategy.get("ticker"),
            "strategy_id": strategy.get("strategy_id"),
            "timeframe": strategy.get("timeframe"),
            "entry_rule": strategy.get("entry_rule"),
            "v2_size_multiplier": strategy.get("size_multiplier", 1.0),
            "v3_size_multiplier": size_multiplier,
            "quality_score": score,
            "approved": approved,
            "v3_reason": reason,
            **{f"quality_{key}": value for key, value in stats.items()},
        }
        quality_rows.append(row)
        if not approved:
            continue
        updated = dict(strategy)
        updated["selected_version"] = "v3_quality_context"
        updated["version"] = "v3_quality_context"
        updated["size_multiplier"] = size_multiplier
        updated["v3_quality_score"] = score
        updated["v3_reason"] = reason
        updated["v3_context_gate"] = "market_and_stock"
        strategies.append(updated)
    return strategies, quality_rows


def tune_strategy_parameters(strategy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    timeframe = str(strategy.get("timeframe", ""))
    targets = [4, 5, 6, 7] if timeframe == "swing" else [6, 7, 8, 10, 12]
    holds = [5, 7, 10, 12] if timeframe == "swing" else [10, 14, 17, 21, 25]
    original_state = v2.simulate_portfolio([strategy], [])
    original_stats = trade_stats(original_state["trades"])
    best_strategy = dict(strategy)
    best_stats = original_stats
    best_score = quality_score(original_stats)
    for target in targets:
        for hold in holds:
            candidate = dict(strategy)
            candidate["target_pct"] = target
            candidate["hold_days"] = hold
            candidate_state = v2.simulate_portfolio([candidate], [])
            candidate_stats = trade_stats(candidate_state["trades"])
            candidate_score = quality_score(candidate_stats)
            if (candidate_score, candidate_stats["pnl"]) > (best_score, best_stats["pnl"]):
                best_strategy = candidate
                best_stats = candidate_stats
                best_score = candidate_score
    best_strategy["v3_original_target_pct"] = strategy.get("target_pct")
    best_strategy["v3_original_hold_days"] = strategy.get("hold_days")
    best_strategy["v3_parameter_score"] = best_score
    best_strategy["v3_parameter_changed"] = (
        fnum(best_strategy.get("target_pct")) != fnum(strategy.get("target_pct"))
        or fnum(best_strategy.get("hold_days")) != fnum(strategy.get("hold_days"))
    )
    return best_strategy, best_stats


def choose_adaptive_size(stats: dict[str, Any], score: float) -> tuple[float, str]:
    size = 1.0
    reasons: list[str] = []
    if score < 55 or fnum(stats["avg_pct"]) < 1.1:
        size = min(size, 0.85)
        reasons.append("خفض محدود لجودة أقل من المطلوب")
    if fnum(stats["worst_pct"]) <= -14:
        size = min(size, 0.85)
        reasons.append("خفض محدود بسبب خسارة عميقة")
    if fnum(stats["month_concentration_pct"]) >= 65:
        size = min(size, 0.9)
        reasons.append("خفض محدود بسبب تركيز زمني")
    if not reasons:
        reasons.append("إبقاء الحجم مع تعديل الهدف/المدة عند الحاجة")
    return round(size, 2), "؛ ".join(reasons)


def build_v3_adaptive_strategies() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base_strategies, _ = v2.selected_portfolio_strategies()
    strategies: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    for strategy in base_strategies:
        tuned, stats = tune_strategy_parameters(strategy)
        score = quality_score(stats)
        size_multiplier, reason = choose_adaptive_size(stats, score)
        approved = fnum(stats["pnl"]) > 0 and fnum(stats["win_rate"]) >= 70 and fnum(stats["trades"]) >= 8
        row = {
            "ticker": tuned.get("ticker"),
            "strategy_id": tuned.get("strategy_id"),
            "timeframe": tuned.get("timeframe"),
            "entry_rule": tuned.get("entry_rule"),
            "original_target_pct": tuned.get("v3_original_target_pct"),
            "v3_target_pct": tuned.get("target_pct"),
            "original_hold_days": tuned.get("v3_original_hold_days"),
            "v3_hold_days": tuned.get("hold_days"),
            "parameter_changed": tuned.get("v3_parameter_changed"),
            "v2_size_multiplier": strategy.get("size_multiplier", 1.0),
            "v3_size_multiplier": size_multiplier,
            "quality_score": score,
            "approved": approved,
            "v3_reason": reason,
            **{f"quality_{key}": value for key, value in stats.items()},
        }
        quality_rows.append(row)
        if not approved:
            continue
        updated = dict(tuned)
        updated["selected_version"] = "v3_adaptive_quality"
        updated["version"] = "v3_adaptive_quality"
        updated["size_multiplier"] = size_multiplier
        updated["v3_quality_score"] = score
        updated["v3_reason"] = reason
        updated["v3_context_gate"] = "adaptive_no_signal_veto"
        strategies.append(updated)
    return strategies, quality_rows


def capped_stop_price(entry_price: float, technical_stop: float, timeframe: str) -> tuple[float, float | None]:
    return v2.capped_stop_price(entry_price, technical_stop, timeframe, None)


def simulate_portfolio_v3(strategies: list[dict[str, Any]], quality_gate: list[dict[str, Any]]) -> dict[str, Any]:
    tickers = {str(strategy["ticker"]) for strategy in strategies}
    all_bars = bars_by_ticker(tickers | set(MARKET_TICKERS))
    strategy_bars = {ticker: all_bars[ticker] for ticker in tickers}
    market_bars = {ticker: all_bars[ticker] for ticker in MARKET_TICKERS if ticker in all_bars}
    market_index = {ticker: index_by_date(bars) for ticker, bars in market_bars.items()}
    all_dates = sorted({bar.date for bars in strategy_bars.values() for bar in bars if bar.date >= CONFIG["start_date"]})
    index_maps = {ticker: index_by_date(bars) for ticker, bars in strategy_bars.items()}
    state: dict[str, Any] = {
        "cash": INITIAL_CAPITAL,
        "trades": [],
        "snapshots": [],
        "next_id": 1,
        "quality_gate": quality_gate,
        "skipped_signals": [],
    }
    open_trades: list[dict[str, Any]] = []
    for current_date in all_dates:
        for trade in list(open_trades):
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None:
                continue
            bar = strategy_bars[ticker][idx]
            v2.update_trailing_stop(trade, bar.high)
            if bar.low <= fnum(trade["stop_price"]):
                v2.close_trade(state, trade, current_date, fnum(trade["stop_price"]), "ضرب الوقف المتحرك/الفني", "TRAILING_WIN" if fnum(trade.get("highest_price")) > fnum(trade["entry_price"]) else "LOSS")
                open_trades.remove(trade)
                continue
            if bar.high >= fnum(trade["exit_price"]):
                v2.close_trade(state, trade, current_date, fnum(trade["exit_price"]), "تحقق هدف الاستراتيجية", "WIN")
                open_trades.remove(trade)
                continue
            entry_date = dt.date.fromisoformat(str(trade["entry_date"]))
            if (dt.date.fromisoformat(current_date) - entry_date).days >= int(trade["hold_days"]):
                v2.close_trade(state, trade, current_date, bar.close, "انتهاء مدة الاحتفاظ", "TIME")
                open_trades.remove(trade)

        for strategy in strategies:
            ticker = str(strategy["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or idx == 0:
                continue
            signal, signal_note = entry_signal_v3(strategy, strategy_bars[ticker], idx, market_bars, market_index)
            if not signal:
                if signal_note:
                    state["skipped_signals"].append({"date": current_date, "ticker": ticker, "strategy_id": strategy.get("strategy_id", ""), "reason": signal_note})
                continue
            duplicate = any(
                trade["status"] == "OPEN"
                and trade["ticker"] == ticker
                and trade.get("strategy_id") == strategy.get("strategy_id")
                for trade in open_trades
            )
            if duplicate:
                continue
            bar = strategy_bars[ticker][idx]
            available_cash = fnum(state["cash"])
            target_alloc = available_cash * POSITION_CAP_PCT * fnum(strategy.get("size_multiplier", 1.0), 1.0)
            avg_dollar_volume = v2.avg_dollar_volume(strategy_bars[ticker], idx)
            liquidity_cap = avg_dollar_volume * MAX_TRADE_ADV_PCT
            alloc = min(target_alloc, liquidity_cap, available_cash)
            shares = math.floor(alloc / bar.close) if bar.close > 0 else 0
            if shares <= 0:
                continue
            entry_price = bar.close
            if strategy.get("stop_model") == "v1_atr_support":
                technical_stop = v2.v1_stop_price(strategy, strategy_bars[ticker], idx)
            else:
                technical_stop = bar.close * (1 - fnum(strategy["initial_stop_pct"]) / 100)
            stop_price, stop_cap_pct = capped_stop_price(entry_price, technical_stop, str(strategy.get("timeframe", "")))
            target = bar.close * (1 + fnum(strategy["target_pct"]) / 100)
            trade = {
                "id": f"V3-{state['next_id']:04d}",
                "ticker": ticker,
                "strategy_id": strategy.get("strategy_id", ""),
                "behavior": strategy.get("behavior", ""),
                "entry_rule": strategy.get("entry_rule", ""),
                "timeframe": strategy.get("timeframe", ""),
                "selected_version": strategy.get("selected_version", ""),
                "v3_quality_score": strategy.get("v3_quality_score", ""),
                "v3_reason": strategy.get("v3_reason", ""),
                "v3_context_note": signal_note,
                "entry_date": current_date,
                "entry_price": round(entry_price, 4),
                "shares": shares,
                "capital": round(shares * entry_price, 2),
                "market_value": round(shares * entry_price, 2),
                "exit_price": round(target, 4),
                "initial_stop_price": round(stop_price, 4),
                "technical_initial_stop_price": round(technical_stop, 4),
                "stop_price": round(stop_price, 4),
                "stop_cap_pct": round(stop_cap_pct, 2) if stop_cap_pct is not None else "",
                "highest_price": round(entry_price, 4),
                "hold_days": int(fnum(strategy["hold_days"])),
                "status": "OPEN",
                "outcome": "OPEN",
                "close_date": "",
                "close_price": "",
                "close_reason": "",
                "realized_pnl": 0.0,
                "realized_pnl_pct": 0.0,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "latest_price": round(entry_price, 4),
                "avg_dollar_volume": round(avg_dollar_volume, 2),
                "liquidity_cap": round(liquidity_cap, 2),
            }
            state["next_id"] += 1
            state["cash"] = round(available_cash - shares * entry_price, 2)
            state["trades"].append(trade)
            open_trades.append(trade)

        for trade in open_trades:
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None:
                continue
            close = strategy_bars[ticker][idx].close
            trade["latest_price"] = round(close, 4)
            trade["market_value"] = round(int(trade["shares"]) * close, 2)
            trade["unrealized_pnl"] = round((close - fnum(trade["entry_price"])) * int(trade["shares"]), 2)
            trade["unrealized_pnl_pct"] = round((close / fnum(trade["entry_price"]) - 1) * 100, 2)
        state["snapshots"].append({"date": current_date, "cash": round(fnum(state["cash"]), 2), "value": round(v2.portfolio_value(state), 2), "open_trades": len(open_trades)})
    return state


def portfolio_summary(state: dict[str, Any], label: str) -> dict[str, Any]:
    trades = state["trades"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if fnum(trade.get("realized_pnl")) >= 0]
    losses = [trade for trade in closed if fnum(trade.get("realized_pnl")) < 0]
    value = v2.portfolio_value(state)
    snapshots = state.get("snapshots", [])
    end_date = snapshots[-1]["date"] if snapshots else ""
    elapsed = max((dt.date.fromisoformat(end_date) - START_DATE).days / 365.25, 1 / 365.25) if end_date else 1
    annual = ((value / INITIAL_CAPITAL) ** (1 / elapsed) - 1) * 100 if value > 0 else -100
    dd = v2.max_drawdown(snapshots)
    return {
        "version": label,
        "portfolio_value": round(value, 2),
        "pnl": round(value - INITIAL_CAPITAL, 2),
        "period_return_pct": round((value / INITIAL_CAPITAL - 1) * 100, 2),
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
        "max_drawdown_pct": round(fnum(dd.get("drawdown")), 2),
        "end_date": end_date,
    }


def comparison_rows(v2_state: dict[str, Any], v3_state: dict[str, Any], defensive_state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    v2_summary = portfolio_summary(v2_state, "V2")
    v3_summary = portfolio_summary(v3_state, "V3 Adaptive")
    delta = {
        "version": "Delta V3-V2",
        **{
            key: round(fnum(v3_summary.get(key)) - fnum(v2_summary.get(key)), 2)
            for key in v2_summary
            if key not in {"version", "end_date"}
        },
        "end_date": v3_summary["end_date"],
    }
    rows = [v2_summary, v3_summary]
    if defensive_state is not None:
        defensive_summary = portfolio_summary(defensive_state, "V3 Defensive")
        rows.append(defensive_summary)
    rows.append(delta)
    return rows


def equity_points_js(state: dict[str, Any]) -> str:
    points = [[row["date"], fnum(row["value"])] for row in state.get("snapshots", [])]
    return json.dumps(points, ensure_ascii=False)


def render_strategy_rows(rows: list[dict[str, Any]]) -> str:
    out = []
    for row in sorted(rows, key=lambda item: fnum(item.get("quality_score")), reverse=True):
        approved = str(row.get("approved")) == "True" or row.get("approved") is True
        out.append(
            f"""
            <tr>
              <td><strong class="ltr">{html.escape(str(row.get('ticker', '')))}</strong></td>
              <td>{html.escape(str(row.get('timeframe', '')))}</td>
              <td><span class="ltr">{html.escape(str(row.get('strategy_id', '')))}</span></td>
              <td class="num">{fnum(row.get('quality_score')):.2f}</td>
              <td class="num">{fnum(row.get('quality_win_rate')):.2f}%</td>
              <td class="num {tone(row.get('quality_avg_pct'))}">{fnum(row.get('quality_avg_pct')):.2f}%</td>
              <td class="num negative">{fnum(row.get('quality_worst_pct')):.2f}%</td>
              <td class="num">{fnum(row.get('v3_size_multiplier')):.2f}</td>
              <td>{'معتمدة' if approved else 'مستبعدة'}</td>
              <td>{html.escape(str(row.get('v3_reason', '')))}</td>
            </tr>
            """
        )
    return "\n".join(out)


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def render_dashboard(v2_state: dict[str, Any], v3_state: dict[str, Any], quality_rows: list[dict[str, Any]], defensive_state: dict[str, Any] | None = None) -> str:
    rows = comparison_rows(v2_state, v3_state, defensive_state)
    v2_row = rows[0]
    v3_row = rows[1]
    defensive_row = rows[2] if defensive_state is not None else None
    delta = rows[-1]
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>محفظة V3 التجريبية</title>
  <style>
    :root {{ --bg:#f4f7fa; --panel:#fff; --text:#061629; --muted:#61738a; --line:#d7e2ec; --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    main {{ max-width:1540px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:30px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    .sub,.note,small {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .btn {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; color:var(--blue); text-decoration:none; }}
    .btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .card,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .card span {{ display:block; color:var(--muted); }}
    .card strong {{ display:block; direction:ltr; text-align:right; font-size:30px; margin-top:7px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#24364d; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }}
    .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .positive {{ color:var(--green); font-weight:800; }}
    .negative {{ color:var(--red); font-weight:800; }}
    .warning {{ color:var(--amber); font-weight:800; }}
    .chart-wrap {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; margin:14px 0; }}
    canvas {{ width:100%; height:320px; }}
    @media (max-width:1000px) {{ header {{ display:block; }} .grid {{ grid-template-columns:1fr; }} .nav {{ margin-top:12px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>محفظة V3 التجريبية</h1>
      <div class="sub">V3 تختبر اختيارًا أكثر وعيًا بالجودة والسياق: بوابة سوقية، بوابة فنية للسهم، وحجم صفقة متغير حسب جودة الاستراتيجية.</div>
      <div class="note">هذه نسخة اختبار مستقلة ولا تغير V2.</div>
    </div>
    <nav class="nav">
      <a class="btn" href="paper_portfolio_v2_dashboard.html">V2 الرئيسي</a>
      <a class="btn" href="paper_portfolio_v2_analytics.html">تحليلات V2</a>
      <a class="btn primary" href="paper_portfolio_v3_dashboard.html">V3 التجريبية</a>
    </nav>
  </header>

  <section class="grid">
    <article class="card"><span>قيمة V3 Adaptive</span><strong class="{tone(v3_row['portfolio_value'])}">{money(v3_row['portfolio_value'])}</strong><small>V2 {money(v2_row['portfolio_value'])}</small></article>
    <article class="card"><span>فرق الربح</span><strong class="{tone(delta['pnl'])}">{money(delta['pnl'])}</strong><small>V3 - V2</small></article>
    <article class="card"><span>فرق العائد</span><strong class="{tone(delta['period_return_pct'])}">{pct(delta['period_return_pct'])}</strong><small>عائد V3 {pct(v3_row['period_return_pct'])}</small></article>
    <article class="card"><span>فرق عدد الصفقات</span><strong class="{tone(delta['trades'])}">{int(delta['trades'])}</strong><small>V3 {v3_row['trades']} / V2 {v2_row['trades']}</small></article>
    <article class="card"><span>نسبة الفوز V3</span><strong>{pct(v3_row['win_rate'])}</strong><small>الفرق {pct(delta['win_rate'])}</small></article>
    <article class="card"><span>أسوأ خسارة</span><strong class="negative">{pct(v3_row['worst_loss_pct'])}</strong><small>V2 {pct(v2_row['worst_loss_pct'])}</small></article>
    <article class="card"><span>السحب الأقصى</span><strong class="negative">{pct(v3_row['max_drawdown_pct'])}</strong><small>V2 {pct(v2_row['max_drawdown_pct'])}</small></article>
    <article class="card"><span>V3 Defensive</span><strong class="{tone(defensive_row['portfolio_value'] if defensive_row else 0)}">{money(defensive_row['portfolio_value'] if defensive_row else 0)}</strong><small>اختبار بوابات السياق الصارمة</small></article>
  </section>

  <section class="chart-wrap">
    <h2>منحنى قيمة المحفظة V2/V3</h2>
    <canvas id="equityChart" width="1300" height="340"></canvas>
  </section>

  <section class="panel">
    <h2>مقارنة مختصرة</h2>
    <table>
      <thead><tr><th>النسخة</th><th>قيمة المحفظة</th><th>الربح</th><th>عائد الفترة</th><th>سنوي</th><th>صفقات</th><th>رابحة/خاسرة</th><th>فوز</th><th>أسوأ خسارة</th><th>السحب</th></tr></thead>
      <tbody>
        {''.join(f"<tr><td>{row['version']}</td><td class='num'>{money(row['portfolio_value'])}</td><td class='num {tone(row['pnl'])}'>{money(row['pnl'])}</td><td class='num {tone(row['period_return_pct'])}'>{pct(row['period_return_pct'])}</td><td class='num {tone(row['annual_return_pct'])}'>{pct(row['annual_return_pct'])}</td><td class='num'>{row['trades']}</td><td class='num'>{row['wins']} / {row['losses']}</td><td class='num'>{pct(row['win_rate'])}</td><td class='num negative'>{pct(row['worst_loss_pct'])}</td><td class='num negative'>{pct(row['max_drawdown_pct'])}</td></tr>" for row in rows)}
      </tbody>
    </table>
  </section>

  <section class="panel" style="margin-top:14px;">
    <h2>تشخيص الاستراتيجيات في V3</h2>
    <table>
      <thead><tr><th>السهم</th><th>الإطار</th><th>الاستراتيجية</th><th>نقاط الجودة</th><th>فوز</th><th>متوسط</th><th>أسوأ</th><th>الحجم</th><th>الحالة</th><th>سبب القرار</th></tr></thead>
      <tbody>{render_strategy_rows(quality_rows)}</tbody>
    </table>
  </section>
</main>
<script>
const V2_POINTS = {equity_points_js(v2_state)};
const V3_POINTS = {equity_points_js(v3_state)};
const DEF_POINTS = {equity_points_js(defensive_state or {"snapshots": []})};
function drawChart() {{
  const canvas = document.getElementById('equityChart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const all = V2_POINTS.concat(V3_POINTS);
  const values = all.map(p => p[1]);
  const min = Math.min(...values), max = Math.max(...values);
  const pad = 42;
  function x(i, n) {{ return pad + i * (w - pad * 2) / Math.max(n - 1, 1); }}
  function y(value) {{ return h - pad - (value - min) * (h - pad * 2) / Math.max(max - min, 1); }}
  ctx.strokeStyle = '#d7e2ec'; ctx.lineWidth = 1;
  for (let i=0;i<5;i++) {{ const yy = pad + i*(h-pad*2)/4; ctx.beginPath(); ctx.moveTo(pad, yy); ctx.lineTo(w-pad, yy); ctx.stroke(); }}
  function line(points, color) {{
    ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.beginPath();
    points.forEach((p, i) => {{ const xx=x(i, points.length), yy=y(p[1]); if (i===0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy); }});
    ctx.stroke();
  }}
  line(V2_POINTS, '#8192a8');
  line(V3_POINTS, '#1d6597');
  if (DEF_POINTS.length) line(DEF_POINTS, '#a66b00');
  ctx.fillStyle = '#061629'; ctx.font = '16px Tahoma';
  ctx.fillText('V2', w - 100, y(V2_POINTS[V2_POINTS.length-1][1]) - 8);
  ctx.fillText('V3', w - 100, y(V3_POINTS[V3_POINTS.length-1][1]) + 18);
  if (DEF_POINTS.length) ctx.fillText('Defensive', w - 130, y(DEF_POINTS[DEF_POINTS.length-1][1]) + 18);
}}
drawChart();
</script>
</body>
</html>"""


def main() -> int:
    import paper_portfolio_v3_rebuild

    return paper_portfolio_v3_rebuild.main()


if __name__ == "__main__":
    raise SystemExit(main())
