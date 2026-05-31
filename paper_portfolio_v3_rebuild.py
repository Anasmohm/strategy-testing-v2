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

FOCUSED_TICKERS = sorted(v2.FOCUSED_TICKERS)
START_DATE = dt.date.fromisoformat(CONFIG["start_date"])
INITIAL_CAPITAL = float(CONFIG.get("initial_capital", 10000.0))
POSITION_CAP_PCT = float(CONFIG.get("position_cap_pct", 0.4))
MAX_TRADE_ADV_PCT = float(CONFIG.get("max_trade_adv_pct", 0.01))
MIN_ACCEPTABLE_ANNUAL_RETURN_PCT = float(CONFIG.get("min_acceptable_annual_return_pct", 70.0))
BAR_FEATURE_CACHE: dict[int, dict[str, Any]] = {}

TRADES_CSV = REPORTS / "paper_trades_v3.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v3.csv"
STRATEGIES_CSV = REPORTS / "selected_strategies_v3.csv"
CANDIDATES_CSV = REPORTS / "strategy_candidates_v3_rebuild.csv"
CANDIDATES_BY_TICKER_DIR = REPORTS / "strategy_candidates_v3_by_ticker"
QUALITY_CSV = REPORTS / "strategy_quality_v3.csv"
COMPARISON_CSV = REPORTS / "v2_vs_v3_portfolio_comparison.csv"
DASHBOARD = REPORTS / "paper_portfolio_v3_dashboard.html"


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def moving_average(values: list[float], index: int, lookback: int) -> float | None:
    if index + 1 < lookback:
        return None
    return mean(values[index - lookback + 1 : index + 1])


def rolling_average(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for idx, value in enumerate(values):
        total += value
        if idx >= lookback:
            total -= values[idx - lookback]
        if idx + 1 >= lookback:
            out.append(total / lookback)
        else:
            out.append(None)
    return out


def bar_features(bars: list[design_strategies.Bar]) -> dict[str, Any]:
    key = id(bars)
    cached = BAR_FEATURE_CACHE.get(key)
    if cached is not None:
        return cached
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    cached = {
        "closes": closes,
        "avg_volume_20": rolling_average(volumes, 20),
        "ma_20": rolling_average(closes, 20),
        "ma_50": rolling_average(closes, 50),
        "ma_100": rolling_average(closes, 100),
        "ma_200": rolling_average(closes, 200),
    }
    for period in (7, 10, 14, 21):
        cached[f"rsi_{period}"] = design_strategies.rsi(closes, period)
    BAR_FEATURE_CACHE[key] = cached
    return cached


def return_pct(values: list[float], index: int, sessions: int) -> float:
    if index - sessions < 0 or values[index - sessions] == 0:
        return 0.0
    return (values[index] / values[index - sessions] - 1) * 100


def avg_volume(bars: list[design_strategies.Bar], index: int, lookback: int = 20) -> float:
    if lookback == 20:
        averages = bar_features(bars)["avg_volume_20"]
        if 0 <= index < len(averages) and averages[index] is not None:
            return float(averages[index])
    sample = bars[max(0, index - lookback + 1) : index + 1]
    return mean([bar.volume for bar in sample])


def rsi_value(values: list[float], index: int, period: int) -> float | None:
    series = design_strategies.rsi(values, period)
    if index < 0 or index >= len(series):
        return None
    return series[index]


def support_stop(strategy: dict[str, Any], bars: list[design_strategies.Bar], index: int) -> float:
    if strategy.get("stop_model") == "atr_support":
        return v2.v1_stop_price(strategy, bars, index)
    stop_pct = fnum(strategy.get("initial_stop_pct"), 6.0)
    return bars[index].close * (1 - stop_pct / 100)


def trend_state(bars: list[design_strategies.Bar], index: int) -> dict[str, float | str]:
    features = bar_features(bars)
    closes = features["closes"]
    close = closes[index]
    ma20 = features["ma_20"][index]
    ma50 = features["ma_50"][index]
    ma200 = features["ma_200"][index]
    ret20 = return_pct(closes, index, 20)
    if ma50 and ma200 and close > ma50 > ma200:
        label = "uptrend"
    elif ma50 and close > ma50 and ret20 > 0:
        label = "recovery"
    elif ma50 and close < ma50:
        label = "weak"
    else:
        label = "mixed"
    return {
        "label": label,
        "ret20": ret20,
        "extension20": (close / ma20 - 1) * 100 if ma20 else 0.0,
        "extension50": (close / ma50 - 1) * 100 if ma50 else 0.0,
        "rsi14": features["rsi_14"][index] or 0.0,
    }


def market_filter_ok(strategy: dict[str, Any], date: str, market_cache: dict[str, Any]) -> bool:
    mode = strategy.get("market_filter", "none")
    if mode == "none":
        return True
    passed = 0
    checked = 0
    for ticker in ("SPY", "QQQ", "SOXX"):
        bars = market_cache.get(ticker, [])
        index = market_cache.get(f"{ticker}_index", {}).get(date)
        if index is None or index < 200:
            continue
        features = bar_features(bars)
        closes = features["closes"]
        ma50 = features["ma_50"][index]
        ma200 = features["ma_200"][index]
        ret20 = return_pct(closes, index, 20)
        checked += 1
        if ma50 and ma200 and closes[index] > ma50 and (ma50 > ma200 or ret20 > -4):
            passed += 1
    return checked == 0 or passed >= 2


def entry_signal(strategy: dict[str, Any], bars: list[design_strategies.Bar], index: int, market_cache: dict[str, Any]) -> bool:
    if index < 220:
        return False
    if not market_filter_ok(strategy, bars[index].date, market_cache):
        return False
    features = bar_features(bars)
    closes = features["closes"]
    close = bars[index].close
    rule = str(strategy["entry_rule"])
    lookback = int(fnum(strategy.get("lookback"), 20))
    volume_filter = fnum(strategy.get("volume_filter"), 1.0)
    average_volume = avg_volume(bars, index - 1)
    if average_volume and bars[index].volume < average_volume * volume_filter:
        return False

    if rule == "raw_breakout":
        prior_high = max(bar.high for bar in bars[index - lookback : index])
        state = trend_state(bars, index)
        return close > prior_high and fnum(state["extension20"]) <= fnum(strategy.get("max_extension20"), 100)

    if rule == "raw_rsi_recovery":
        period = int(fnum(strategy.get("rsi_period"), lookback))
        threshold = fnum(strategy.get("rsi_cross_above"), 35)
        values = features.get(f"rsi_{period}") or design_strategies.rsi(closes, period)
        return (
            values[index - 1] is not None
            and values[index] is not None
            and values[index - 1] < threshold
            and values[index] >= threshold
        )

    if rule == "raw_pullback_reversal":
        drop_pct = fnum(strategy.get("drop_pct"), 5)
        drop = return_pct(closes, index - 1, lookback)
        ma200 = features["ma_200"][index]
        return drop <= -drop_pct and close > bars[index - 1].close and close > bars[index].open and (not ma200 or close > ma200 * 0.88)

    if rule == "raw_trend_resume":
        pullback = return_pct(closes, index - 1, lookback)
        ma50 = features["ma_50"][index]
        ma100 = features["ma_100"][index]
        return bool(ma50 and ma100 and close > ma50 > ma100 and pullback <= -fnum(strategy.get("drop_pct"), 2) and close > bars[index - 1].close)

    if rule == "raw_ma_reclaim":
        ma_period = int(fnum(strategy.get("ma_period"), lookback))
        ma_series = features.get(f"ma_{ma_period}")
        ma_now = ma_series[index] if ma_series else moving_average(closes, index, ma_period)
        ma_prev = ma_series[index - 1] if ma_series and index > 0 else moving_average(closes, index - 1, ma_period)
        if ma_now is None or ma_prev is None:
            return False
        state = trend_state(bars, index)
        return closes[index - 1] < ma_prev and close > ma_now and fnum(state["ret20"]) > -15

    return False


def candidate_universe(ticker: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    configs = {
        "swing": {"targets": [4, 5, 6, 7], "holds": [5, 8, 10, 13]},
        "monthly": {"targets": [6, 8, 10, 12], "holds": [10, 14, 21, 25]},
    }
    for timeframe, cfg in configs.items():
        for market_filter in ["none", "soft_market"]:
            for lookback in [20, 35, 55, 100]:
                for target in cfg["targets"]:
                    for hold in cfg["holds"]:
                        for max_ext in [25, 40, 100]:
                            candidates.append(
                                {
                                    "ticker": ticker,
                                    "timeframe": timeframe,
                                    "entry_rule": "raw_breakout",
                                    "strategy_id": f"{ticker}_{timeframe}_raw_breakout_{lookback}_{target}_{hold}_{max_ext}_{market_filter}",
                                    "behavior": f"raw_breakout_{timeframe}",
                                    "lookback": lookback,
                                    "target_pct": target,
                                    "hold_days": hold,
                                    "initial_stop_pct": 99,
                                    "stop_model": "atr_support",
                                    "volume_filter": 1.0,
                                    "max_extension20": max_ext,
                                    "market_filter": market_filter,
                                }
                            )
            for period in [7, 10, 14, 21]:
                for threshold in [30, 35, 40, 45]:
                    for target in cfg["targets"]:
                        for hold in cfg["holds"]:
                            candidates.append(
                                {
                                    "ticker": ticker,
                                    "timeframe": timeframe,
                                    "entry_rule": "raw_rsi_recovery",
                                    "strategy_id": f"{ticker}_{timeframe}_raw_rsi_{period}_{threshold}_{target}_{hold}_{market_filter}",
                                    "behavior": f"raw_rsi_recovery_{timeframe}",
                                    "lookback": period,
                                    "rsi_period": period,
                                    "rsi_cross_above": threshold,
                                    "target_pct": target,
                                    "hold_days": hold,
                                    "initial_stop_pct": 99,
                                    "stop_model": "atr_support",
                                    "volume_filter": 1.0,
                                    "market_filter": market_filter,
                                }
                            )
            for lookback in [3, 5, 8]:
                for drop in [3, 5, 7, 10]:
                    for target in cfg["targets"]:
                        for hold in cfg["holds"]:
                            candidates.append(
                                {
                                    "ticker": ticker,
                                    "timeframe": timeframe,
                                    "entry_rule": "raw_pullback_reversal",
                                    "strategy_id": f"{ticker}_{timeframe}_raw_pullback_{lookback}_{drop}_{target}_{hold}_{market_filter}",
                                    "behavior": f"raw_pullback_{timeframe}",
                                    "lookback": lookback,
                                    "drop_pct": drop,
                                    "target_pct": target,
                                    "hold_days": hold,
                                    "initial_stop_pct": 99,
                                    "stop_model": "atr_support",
                                    "volume_filter": 0.75,
                                    "market_filter": market_filter,
                                }
                            )
            for lookback in [3, 5, 8]:
                for drop in [1.5, 3, 5]:
                    for target in cfg["targets"]:
                        for hold in cfg["holds"]:
                            candidates.append(
                                {
                                    "ticker": ticker,
                                    "timeframe": timeframe,
                                    "entry_rule": "raw_trend_resume",
                                    "strategy_id": f"{ticker}_{timeframe}_raw_trend_{lookback}_{drop}_{target}_{hold}_{market_filter}",
                                    "behavior": f"raw_trend_resume_{timeframe}",
                                    "lookback": lookback,
                                    "drop_pct": drop,
                                    "target_pct": target,
                                    "hold_days": hold,
                                    "initial_stop_pct": 99,
                                    "stop_model": "atr_support",
                                    "volume_filter": 0.8,
                                    "market_filter": market_filter,
                                }
                            )
            for ma_period in [20, 50, 100]:
                for target in cfg["targets"]:
                    for hold in cfg["holds"]:
                        candidates.append(
                            {
                                "ticker": ticker,
                                "timeframe": timeframe,
                                "entry_rule": "raw_ma_reclaim",
                                "strategy_id": f"{ticker}_{timeframe}_raw_ma_{ma_period}_{target}_{hold}_{market_filter}",
                                "behavior": f"raw_ma_reclaim_{timeframe}",
                                "lookback": ma_period,
                                "ma_period": ma_period,
                                "target_pct": target,
                                "hold_days": hold,
                                "initial_stop_pct": 99,
                                "stop_model": "atr_support",
                                "volume_filter": 0.8,
                                "market_filter": market_filter,
                            }
                        )
    return candidates


def max_drawdown_from_returns(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        worst = min(worst, (equity / peak - 1) * 100)
    return worst


def backtest_candidate(strategy: dict[str, Any], bars: list[design_strategies.Bar], market_cache: dict[str, Any]) -> dict[str, Any]:
    returns: list[float] = []
    outcomes: list[str] = []
    months: dict[str, float] = {}
    i = 0
    while i < len(bars) - 2:
        if dt.date.fromisoformat(bars[i].date) < START_DATE or not entry_signal(strategy, bars, i, market_cache):
            i += 1
            continue
        entry = bars[i].close
        stop = support_stop(strategy, bars, i)
        target = entry * (1 + fnum(strategy["target_pct"]) / 100)
        hold_days = int(fnum(strategy["hold_days"]))
        exit_price = bars[min(i + hold_days, len(bars) - 1)].close
        outcome = "TIME"
        highest = entry
        dynamic_stop = stop
        for offset in range(1, min(hold_days, len(bars) - i - 1) + 1):
            bar = bars[i + offset]
            highest = max(highest, bar.high)
            gain_pct = (highest / entry - 1) * 100
            if gain_pct >= v2.TRAILING_STOP_STEP_PCT:
                locked = math.floor(gain_pct / v2.TRAILING_STOP_STEP_PCT) * v2.TRAILING_STOP_STEP_PCT
                dynamic_stop = max(dynamic_stop, entry * (1 + locked / 100))
            if bar.low <= dynamic_stop:
                exit_price = dynamic_stop
                outcome = "TRAILING_WIN" if highest > entry else "LOSS"
                break
            if bar.high >= target:
                exit_price = target
                outcome = "WIN"
                break
        ret = (exit_price / entry - 1) * 100
        returns.append(ret)
        outcomes.append(outcome if ret >= 0 else "LOSS")
        month = bars[i].date[:7]
        months[month] = months.get(month, 0.0) + ret
        i += max(1, hold_days)
    wins = [value for value in returns if value >= 0]
    losses = [value for value in returns if value < 0]
    total_return = (math.prod(1 + value / 100 for value in returns) - 1) * 100 if returns else 0.0
    month_concentration = max(months.values(), default=0.0) / sum(v for v in months.values() if v > 0) * 100 if sum(v for v in months.values() if v > 0) > 0 else 0.0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) else (sum(wins) if wins else 0.0)
    return {
        **strategy,
        "trades": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else 0.0,
        "avg_return": mean(returns),
        "median_return": median(returns),
        "total_return": total_return,
        "avg_win": mean(wins),
        "avg_loss": mean(losses),
        "worst_return": min(returns, default=0.0),
        "max_drawdown": max_drawdown_from_returns(returns),
        "profit_factor": profit_factor,
        "month_concentration": month_concentration,
    }


def candidate_score(row: dict[str, Any]) -> float:
    score = 0.0
    score += fnum(row["win_rate"]) * 0.42
    score += fnum(row["avg_return"]) * 9.5
    score += min(fnum(row["total_return"]) * 0.14, 38)
    score += min(fnum(row["profit_factor"]) * 2.0, 14)
    score += min(math.sqrt(max(fnum(row["trades"]), 0)) * 2.5, 12)
    score += fnum(row["worst_return"]) * 1.25
    score += fnum(row["max_drawdown"]) * 1.15
    score -= max(fnum(row["month_concentration"]) - 45, 0) * 0.2
    if fnum(row["trades"]) < 8:
        score -= 25
    return round(score, 2)


def candidate_passes(row: dict[str, Any]) -> bool:
    min_trades = 8
    min_avg = 0.9 if row.get("timeframe") == "swing" else 1.1
    return (
        fnum(row["trades"]) >= min_trades
        and fnum(row["win_rate"]) >= 58
        and fnum(row["avg_return"]) >= min_avg
        and fnum(row["total_return"]) > 12
        and fnum(row["worst_return"]) > -18
    )


def build_market_cache() -> dict[str, Any]:
    cache: dict[str, Any] = {}
    for ticker in ("SPY", "QQQ", "SOXX"):
        bars = v2.read_bars(ticker)
        cache[ticker] = bars
        cache[f"{ticker}_index"] = {bar.date: idx for idx, bar in enumerate(bars)}
    return cache


def select_rebuild_strategies() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_cache = build_market_cache()
    selected: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    CANDIDATES_BY_TICKER_DIR.mkdir(parents=True, exist_ok=True)
    for ticker in FOCUSED_TICKERS:
        bars = v2.read_bars(ticker)
        evaluated = []
        universe = candidate_universe(ticker)
        print(f"Testing {ticker}: {len(universe)} candidates")
        for candidate in universe:
            row = backtest_candidate(candidate, bars, market_cache)
            row["quality_score"] = candidate_score(row)
            row["passes_quality"] = candidate_passes(row)
            evaluated.append(row)
            candidate_rows.append(row)
        for timeframe in ("swing", "monthly"):
            pool = [row for row in evaluated if row["timeframe"] == timeframe and row["passes_quality"]]
            if not pool:
                pool = [row for row in evaluated if row["timeframe"] == timeframe and fnum(row["trades"]) >= 6 and fnum(row["total_return"]) > 0]
            if not pool:
                continue
            best = max(pool, key=lambda row: (fnum(row["quality_score"]), fnum(row["total_return"])))
            strategy = {key: best[key] for key in best if key not in {
                "trades", "wins", "losses", "win_rate", "avg_return", "median_return", "total_return",
                "avg_win", "avg_loss", "worst_return", "max_drawdown", "profit_factor", "month_concentration",
                "quality_score", "passes_quality",
            }}
            strategy["selected_version"] = "v3_raw_rebuild"
            strategy["version"] = "v3_raw_rebuild"
            strategy["size_multiplier"] = size_multiplier_for(best)
            strategy["v3_quality_score"] = best["quality_score"]
            strategy["v3_reason"] = reason_for(best)
            selected.append(strategy)
        write_csv(CANDIDATES_BY_TICKER_DIR / f"{ticker}_candidates.csv", evaluated)
    return selected, candidate_rows


def size_multiplier_for(row: dict[str, Any]) -> float:
    size = 1.0
    if fnum(row["quality_score"]) < 70:
        size = min(size, 0.85)
    if fnum(row["worst_return"]) <= -12:
        size = min(size, 0.85)
    if fnum(row["month_concentration"]) >= 60:
        size = min(size, 0.85)
    return round(min(size, 1.0), 2)


def reason_for(row: dict[str, Any]) -> str:
    reasons = [
        f"نقاط الجودة {fnum(row['quality_score']):.2f}",
        f"فوز {fnum(row['win_rate']):.2f}%",
        f"متوسط {fnum(row['avg_return']):.2f}%",
        f"أسوأ {fnum(row['worst_return']):.2f}%",
    ]
    if fnum(row["month_concentration"]) >= 60:
        reasons.append("خفض حجم بسبب تركيز الربح")
    if fnum(row["worst_return"]) <= -12:
        reasons.append("خفض حجم بسبب خسارة عميقة")
    return "؛ ".join(reasons)


def simulate_rebuild_portfolio(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    tickers = {str(strategy["ticker"]) for strategy in strategies}
    bars_by_ticker = {ticker: v2.read_bars(ticker) for ticker in tickers}
    index_maps = {ticker: {bar.date: idx for idx, bar in enumerate(bars)} for ticker, bars in bars_by_ticker.items()}
    market_cache = build_market_cache()
    all_dates = sorted({bar.date for bars in bars_by_ticker.values() for bar in bars if bar.date >= CONFIG["start_date"]})
    state: dict[str, Any] = {"cash": INITIAL_CAPITAL, "trades": [], "snapshots": [], "next_id": 1, "quality_gate": []}
    open_trades: list[dict[str, Any]] = []
    for current_date in all_dates:
        for trade in list(open_trades):
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or current_date <= str(trade["entry_date"]):
                continue
            bar = bars_by_ticker[ticker][idx]
            v2.update_trailing_stop(trade, bar.high)
            trade["held_sessions"] = int(trade.get("held_sessions", 0)) + 1
            if bar.low <= fnum(trade["stop_price"]):
                v2.close_trade(state, trade, current_date, fnum(trade["stop_price"]), "ضرب الوقف المتحرك/الفني", "TRAILING_WIN" if fnum(trade.get("highest_price")) > fnum(trade["entry_price"]) else "LOSS")
                open_trades.remove(trade)
                continue
            if bar.high >= fnum(trade["exit_price"]):
                v2.close_trade(state, trade, current_date, fnum(trade["exit_price"]), "تحقق هدف الاستراتيجية", "WIN")
                open_trades.remove(trade)
                continue
            if int(trade["held_sessions"]) >= int(trade["hold_days"]):
                v2.close_trade(state, trade, current_date, bar.close, "انتهاء مدة الاحتفاظ", "TIME")
                open_trades.remove(trade)
        for strategy in strategies:
            ticker = str(strategy["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or idx == 0 or not entry_signal(strategy, bars_by_ticker[ticker], idx, market_cache):
                continue
            duplicate = any(trade["status"] == "OPEN" and trade["ticker"] == ticker and trade.get("strategy_id") == strategy.get("strategy_id") for trade in open_trades)
            if duplicate:
                continue
            bar = bars_by_ticker[ticker][idx]
            available_cash = fnum(state["cash"])
            target_alloc = available_cash * POSITION_CAP_PCT * fnum(strategy.get("size_multiplier"), 1.0)
            average_dollar_volume = v2.avg_dollar_volume(bars_by_ticker[ticker], idx)
            liquidity_cap = average_dollar_volume * MAX_TRADE_ADV_PCT
            alloc = min(target_alloc, liquidity_cap, available_cash)
            shares = math.floor(alloc / bar.close) if bar.close > 0 else 0
            if shares <= 0:
                continue
            entry_price = bar.close
            stop_price = support_stop(strategy, bars_by_ticker[ticker], idx)
            target = entry_price * (1 + fnum(strategy["target_pct"]) / 100)
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
                "entry_date": current_date,
                "entry_price": round(entry_price, 4),
                "shares": shares,
                "capital": round(shares * entry_price, 2),
                "market_value": round(shares * entry_price, 2),
                "exit_price": round(target, 4),
                "initial_stop_price": round(stop_price, 4),
                "technical_initial_stop_price": round(stop_price, 4),
                "stop_price": round(stop_price, 4),
                "stop_cap_pct": "",
                "highest_price": round(entry_price, 4),
                "hold_days": int(fnum(strategy["hold_days"])),
                "held_sessions": 0,
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
                "avg_dollar_volume": round(average_dollar_volume, 2),
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
            close = bars_by_ticker[ticker][idx].close
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


def comparison_rows(v2_state: dict[str, Any], v3_state: dict[str, Any]) -> list[dict[str, Any]]:
    v2_summary = portfolio_summary(v2_state, "V2")
    v3_summary = portfolio_summary(v3_state, "V3 Raw Rebuild")
    delta = {
        "version": "Delta V3-V2",
        **{key: round(fnum(v3_summary.get(key)) - fnum(v2_summary.get(key)), 2) for key in v2_summary if key not in {"version", "end_date"}},
        "end_date": v3_summary["end_date"],
    }
    return [v2_summary, v3_summary, delta]


def equity_points_js(state: dict[str, Any]) -> str:
    return json.dumps([[row["date"], fnum(row["value"])] for row in state.get("snapshots", [])], ensure_ascii=False)


def render_strategy_rows(strategies: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> str:
    by_id = {row["strategy_id"]: row for row in candidate_rows}
    out: list[str] = []
    for strategy in sorted(strategies, key=lambda item: (str(item["ticker"]), str(item["timeframe"]))):
        row = by_id.get(strategy["strategy_id"], {})
        out.append(
            f"""
            <tr>
              <td><strong class="ltr">{html.escape(str(strategy.get('ticker', '')))}</strong></td>
              <td>{html.escape(str(strategy.get('timeframe', '')))}</td>
              <td><span class="ltr">{html.escape(str(strategy.get('entry_rule', '')))}</span></td>
              <td><span class="ltr">{html.escape(str(strategy.get('strategy_id', '')))}</span></td>
              <td class="num">{fnum(row.get('quality_score')):.2f}</td>
              <td class="num">{fnum(row.get('trades')):.0f}</td>
              <td class="num">{fnum(row.get('win_rate')):.2f}%</td>
              <td class="num {tone(row.get('avg_return'))}">{fnum(row.get('avg_return')):.2f}%</td>
              <td class="num negative">{fnum(row.get('worst_return')):.2f}%</td>
              <td class="num">{fnum(strategy.get('size_multiplier'), 1.0):.2f}</td>
              <td>{html.escape(str(strategy.get('v3_reason', '')))}</td>
            </tr>
            """
        )
    return "\n".join(out)


def render_dashboard(v2_state: dict[str, Any], v3_state: dict[str, Any], strategies: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> str:
    rows = comparison_rows(v2_state, v3_state)
    v2_row, v3_row, delta = rows
    top_candidates = sorted(candidate_rows, key=lambda row: fnum(row.get("quality_score")), reverse=True)[:8]
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>محفظة V3 من التشخيص الخام</title>
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
      <h1>محفظة V3 من التشخيص الخام</h1>
      <div class="sub">هذه النسخة تعيد قراءة الأسهم التسعة وتولد الاستراتيجيات من البيانات الخام، ثم تختار الأفضل بجودة الربح والمخاطر.</div>
      <div class="note">شكل الداشبورد محفوظ، والفرق في عقل بناء الاستراتيجية.</div>
    </div>
    <nav class="nav">
      <a class="btn" href="paper_portfolio_v2_dashboard.html">V2 الرئيسي</a>
      <a class="btn" href="paper_portfolio_v2_analytics.html">تحليلات V2</a>
      <a class="btn primary" href="paper_portfolio_v3_dashboard.html">V3 الخام</a>
    </nav>
  </header>

  <section class="grid">
    <article class="card"><span>قيمة V3</span><strong class="{tone(v3_row['portfolio_value'])}">{money(v3_row['portfolio_value'])}</strong><small>V2 {money(v2_row['portfolio_value'])}</small></article>
    <article class="card"><span>فرق الربح</span><strong class="{tone(delta['pnl'])}">{money(delta['pnl'])}</strong><small>V3 - V2</small></article>
    <article class="card"><span>فرق العائد</span><strong class="{tone(delta['period_return_pct'])}">{pct(delta['period_return_pct'])}</strong><small>عائد V3 {pct(v3_row['period_return_pct'])}</small></article>
    <article class="card"><span>عدد الصفقات</span><strong>{int(v3_row['trades'])}</strong><small>V2 {int(v2_row['trades'])}</small></article>
    <article class="card"><span>نسبة الفوز</span><strong>{pct(v3_row['win_rate'])}</strong><small>V2 {pct(v2_row['win_rate'])}</small></article>
    <article class="card"><span>أسوأ خسارة</span><strong class="negative">{pct(v3_row['worst_loss_pct'])}</strong><small>V2 {pct(v2_row['worst_loss_pct'])}</small></article>
    <article class="card"><span>السحب الأقصى</span><strong class="negative">{pct(v3_row['max_drawdown_pct'])}</strong><small>V2 {pct(v2_row['max_drawdown_pct'])}</small></article>
    <article class="card"><span>هدف 70% سنوي</span><strong class="{tone(v3_row['annual_return_pct'] - MIN_ACCEPTABLE_ANNUAL_RETURN_PCT)}">{pct(v3_row['annual_return_pct'])}</strong><small>الحد الأدنى {pct(MIN_ACCEPTABLE_ANNUAL_RETURN_PCT)}</small></article>
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
    <h2>الاستراتيجيات المختارة من التشخيص الخام</h2>
    <table>
      <thead><tr><th>السهم</th><th>الإطار</th><th>نوع الدخول</th><th>الاستراتيجية</th><th>الجودة</th><th>صفقات الاختبار</th><th>فوز</th><th>متوسط</th><th>أسوأ</th><th>الحجم</th><th>سبب الاختيار</th></tr></thead>
      <tbody>{render_strategy_rows(strategies, candidate_rows)}</tbody>
    </table>
  </section>

  <section class="panel" style="margin-top:14px;">
    <h2>أعلى المرشحين قبل الاختيار</h2>
    <table>
      <thead><tr><th>السهم</th><th>الإطار</th><th>القاعدة</th><th>الجودة</th><th>صفقات</th><th>فوز</th><th>متوسط</th><th>إجمالي</th></tr></thead>
      <tbody>
      {''.join(f"<tr><td><strong class='ltr'>{html.escape(str(row['ticker']))}</strong></td><td>{row['timeframe']}</td><td><span class='ltr'>{row['entry_rule']}</span></td><td class='num'>{fnum(row['quality_score']):.2f}</td><td class='num'>{fnum(row['trades']):.0f}</td><td class='num'>{pct(row['win_rate'])}</td><td class='num {tone(row['avg_return'])}'>{pct(row['avg_return'])}</td><td class='num {tone(row['total_return'])}'>{pct(row['total_return'])}</td></tr>" for row in top_candidates)}
      </tbody>
    </table>
  </section>
</main>
<script>
const V2_POINTS = {equity_points_js(v2_state)};
const V3_POINTS = {equity_points_js(v3_state)};
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
  ctx.fillStyle = '#061629'; ctx.font = '16px Tahoma';
  ctx.fillText('V2', w - 100, y(V2_POINTS[V2_POINTS.length-1][1]) - 8);
  ctx.fillText('V3 Raw', w - 120, y(V3_POINTS[V3_POINTS.length-1][1]) + 18);
}}
drawChart();
</script>
</body>
</html>"""


def main() -> int:
    strategies, candidate_rows = select_rebuild_strategies()
    v3_state = simulate_rebuild_portfolio(strategies)
    v2_strategies, v2_quality = v2.selected_portfolio_strategies()
    v2_state = v2.simulate_portfolio(v2_strategies, v2_quality)
    selected_ids = {strategy["strategy_id"] for strategy in strategies}
    quality_rows = [{**row, "selected": row["strategy_id"] in selected_ids} for row in candidate_rows if row["strategy_id"] in selected_ids]
    write_csv(STRATEGIES_CSV, strategies)
    write_csv(CANDIDATES_CSV, candidate_rows)
    write_csv(QUALITY_CSV, quality_rows)
    write_csv(TRADES_CSV, v3_state["trades"])
    write_csv(EQUITY_CSV, v3_state["snapshots"])
    write_csv(COMPARISON_CSV, comparison_rows(v2_state, v3_state))
    DASHBOARD.write_text(render_dashboard(v2_state, v3_state, strategies, candidate_rows), encoding="utf-8", newline="\n")
    print(f"V3 raw strategies: {len(strategies)}")
    print(f"V3 raw value: {v2.portfolio_value(v3_state):.2f}")
    print(f"Candidates: {len(candidate_rows)}")
    print(f"Dashboard: {DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
