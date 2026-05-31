#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import math
import urllib.parse
from pathlib import Path

import design_strategies


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SELECTED = REPORTS / "selected_strategies.csv"
SELECTED_VERIFICATION = REPORTS / "selected_strategy_verification.csv"
TRADES_CSV = REPORTS / "paper_trades_v2.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v2.csv"
QUALITY_GATE_CSV = REPORTS / "portfolio_quality_gate_v2.csv"
BENCHMARK_COMPARISON_CSV = REPORTS / "v1_vs_v2_nine_stock_comparison.csv"
STOP_SHADOW_SUMMARY_CSV = REPORTS / "stop_shadow_summary_v2.csv"
STOP_SHADOW_TRADES_CSV = REPORTS / "stop_shadow_trades_v2.csv"
STOP_SHADOW_COMPARISON_CSV = REPORTS / "stop_shadow_trade_comparison_v2.csv"
DASHBOARD = REPORTS / "paper_portfolio_v2_dashboard.html"
ANALYTICS_DASHBOARD = REPORTS / "paper_portfolio_v2_analytics.html"
V1_TRADES_CSV = Path(r"C:\Users\anasbinessa\Documents\New project\reports\paper_trades.csv")
FOCUSED_TICKERS = {"AMD", "ANET", "AVGO", "LRCX", "MRVL", "NVDA", "PANW", "SHOP", "TSLA"}
MARKET_BENCHMARKS = [
    ("QQQ", "ناسداك 100"),
    ("SPY", "S&P 500"),
    ("SOXX", "أشباه الموصلات"),
]

START_DATE = dt.date.fromisoformat(CONFIG["start_date"])
INITIAL_CAPITAL = float(CONFIG.get("initial_capital", 30000))
POSITION_CAP_PCT = float(CONFIG.get("position_cap_pct", 0.25))
LIQUIDITY_LOOKBACK_DAYS = int(CONFIG.get("liquidity_lookback_days", 20))
MAX_TRADE_ADV_PCT = float(CONFIG.get("max_trade_adv_pct", 0.01))
TRAILING_STOP_STEP_PCT = float(CONFIG.get("trailing_stop_step_pct", 1.0))
MIN_VERIFICATION_TRADES = int(CONFIG.get("min_verification_trades", 8))
MIN_VERIFICATION_WIN_RATE = float(CONFIG.get("min_verification_win_rate", 55.0))
MIN_VERIFICATION_AVG_RETURN = float(CONFIG.get("min_verification_avg_return", 0.0))
EXCLUDED_BEHAVIORS = set(CONFIG.get("excluded_portfolio_behaviors", ["mixed_or_choppy"]))
USE_PORTFOLIO_PROXY_GATE = bool(CONFIG.get("use_portfolio_proxy_gate", True))
MIN_PORTFOLIO_PROXY_PNL = float(CONFIG.get("min_portfolio_proxy_pnl", 0.0))
REQUIRE_V2_TO_BEAT_V1_BY_TICKER = bool(CONFIG.get("require_v2_to_beat_v1_by_ticker", True))
PORTFOLIO_UNIVERSE = str(CONFIG.get("portfolio_universe", "all"))
BENCHMARK_COMPARISON_MODE = bool(CONFIG.get("benchmark_comparison_mode", False))
MIN_ACCEPTABLE_ANNUAL_RETURN_PCT = float(CONFIG.get("min_acceptable_annual_return_pct", 70.0))
STOP_SHADOW_CAPS_PCT = {
    "swing": float(CONFIG.get("shadow_swing_stop_cap_pct", 6.0)),
    "monthly": float(CONFIG.get("shadow_monthly_stop_cap_pct", 10.0)),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, "") or default)
    except ValueError:
        return default


def to_bool(value: object) -> bool:
    return str(value).strip().lower() == "true"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_bars(ticker: str) -> list[design_strategies.Bar]:
    return design_strategies.read_bars(ticker)


def add_verification_metrics(strategy: dict[str, str], verification: dict[str, str]) -> dict[str, str]:
    enriched = dict(strategy)
    enriched.update(
        {
            "verification_trades": str(int(to_float(verification, "trades"))),
            "verification_win_rate": str(round(to_float(verification, "win_rate"), 2)),
            "verification_avg_return": str(round(to_float(verification, "avg_return"), 2)),
            "verification_total_return": str(round(to_float(verification, "total_return"), 2)),
        }
    )
    return enriched


def trade_stats(rows: list[dict[str, object]]) -> dict[str, object]:
    closed = [row for row in rows if row.get("status") == "CLOSED"]
    pnl = sum(float(row.get("realized_pnl") or 0) + float(row.get("unrealized_pnl") or 0) for row in rows)
    losses = [row for row in closed if float(row.get("realized_pnl") or 0) < 0]
    wins = [row for row in closed if float(row.get("realized_pnl") or 0) >= 0]
    return {
        "trades": len(rows),
        "pnl": round(pnl, 2),
        "wins": len(wins),
        "losses": len(losses),
    }


def trade_stats_by_ticker(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("ticker", "")), []).append(row)
    return {ticker: trade_stats(items) for ticker, items in grouped.items()}


def portfolio_quality_gate(
    strategies: list[dict[str, str]],
    proxy_stats_by_ticker: dict[str, dict[str, object]] | None = None,
    v1_stats_by_ticker: dict[str, dict[str, object]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    verification_by_ticker = {row["ticker"]: row for row in read_csv(SELECTED_VERIFICATION)}
    proxy_stats_by_ticker = proxy_stats_by_ticker or {}
    v1_stats_by_ticker = v1_stats_by_ticker or {}
    approved: list[dict[str, str]] = []
    decisions: list[dict[str, object]] = []
    for strategy in strategies:
        ticker = strategy["ticker"]
        verification = verification_by_ticker.get(ticker, {})
        trades = int(to_float(verification, "trades"))
        win_rate = to_float(verification, "win_rate")
        avg_return = to_float(verification, "avg_return")
        total_return = to_float(verification, "total_return")
        proxy_stats = proxy_stats_by_ticker.get(ticker, {})
        v1_stats = v1_stats_by_ticker.get(ticker, {})
        proxy_pnl = float(proxy_stats.get("pnl", 0) or 0)
        proxy_losses = int(proxy_stats.get("losses", 0) or 0)
        v1_pnl = float(v1_stats.get("pnl", 0) or 0)
        v1_losses = int(v1_stats.get("losses", 0) or 0)
        reasons = []
        if strategy.get("behavior") in EXCLUDED_BEHAVIORS:
            reasons.append("excluded_behavior")
        if not to_bool(verification.get("designed_pass")):
            reasons.append("verification_failed")
        if trades < MIN_VERIFICATION_TRADES:
            reasons.append("too_few_verification_trades")
        if win_rate < MIN_VERIFICATION_WIN_RATE:
            reasons.append("win_rate_below_gate")
        if avg_return <= MIN_VERIFICATION_AVG_RETURN:
            reasons.append("avg_return_below_gate")
        strict_approved = not reasons
        proxy_approved = USE_PORTFOLIO_PROXY_GATE and proxy_pnl > MIN_PORTFOLIO_PROXY_PNL
        benchmark_available = ticker in v1_stats_by_ticker
        benchmark_approved = proxy_pnl > v1_pnl and proxy_losses <= v1_losses
        if BENCHMARK_COMPARISON_MODE:
            approved_flag = True
            reason = "benchmark_comparison_included"
        elif REQUIRE_V2_TO_BEAT_V1_BY_TICKER and benchmark_available:
            approved_flag = benchmark_approved
            reason = "approved_beats_v1_ticker" if approved_flag else "rejected_v1_better_for_ticker"
        else:
            approved_flag = strict_approved or proxy_approved
            reason = "approved" if strict_approved else "approved_by_portfolio_proxy" if proxy_approved else "|".join(reasons)
        decision = {
            "ticker": ticker,
            "behavior": strategy.get("behavior", ""),
            "entry_rule": strategy.get("entry_rule", ""),
            "selected_version": strategy.get("selected_version", ""),
            "approved": approved_flag,
            "reason": reason,
            "verification_trades": trades,
            "verification_win_rate": round(win_rate, 2),
            "verification_avg_return": round(avg_return, 2),
            "verification_total_return": round(total_return, 2),
            "portfolio_proxy_pnl": round(proxy_pnl, 2),
            "portfolio_proxy_losses": proxy_losses,
            "v1_ticker_pnl": round(v1_pnl, 2) if benchmark_available else "",
            "v1_ticker_losses": v1_losses if benchmark_available else "",
        }
        decisions.append(decision)
        if approved_flag:
            approved.append(add_verification_metrics(strategy, verification))
    return approved, decisions


def avg_dollar_volume(bars: list[design_strategies.Bar], index: int) -> float:
    sample = bars[max(0, index - LIQUIDITY_LOOKBACK_DAYS + 1) : index + 1]
    if not sample:
        return 0.0
    return sum(bar.close * bar.volume for bar in sample) / len(sample)


def atr(bars: list[design_strategies.Bar], index: int, period: int = 14) -> float | None:
    if index <= 0:
        return None
    start = max(1, index - period + 1)
    ranges = []
    for cursor in range(start, index + 1):
        high_low = bars[cursor].high - bars[cursor].low
        high_close = abs(bars[cursor].high - bars[cursor - 1].close)
        low_close = abs(bars[cursor].low - bars[cursor - 1].close)
        ranges.append(max(high_low, high_close, low_close))
    return sum(ranges) / len(ranges) if ranges else None


def v1_stop_price(strategy: dict[str, str], bars: list[design_strategies.Bar], index: int) -> float:
    current_price = bars[index].close
    timeframe = strategy.get("timeframe", "swing")
    if timeframe == "monthly":
        atr_multiple = 3.0
        support_lookback = 21
    elif timeframe == "short_term_daily_proxy":
        atr_multiple = 1.5
        support_lookback = 5
    else:
        atr_multiple = 2.0
        support_lookback = 10
    latest_atr = atr(bars, index) or current_price * 0.03
    support_slice = bars[max(0, index - support_lookback + 1) : index + 1]
    recent_support = min(bar.low for bar in support_slice)
    atr_stop = current_price - latest_atr * atr_multiple
    stop_price = max(recent_support, atr_stop)
    return min(stop_price, current_price * 0.995)


def update_trailing_stop(trade: dict[str, object], high_price: float) -> None:
    entry = float(trade["entry_price"])
    highest = max(float(trade.get("highest_price", entry)), high_price)
    trade["highest_price"] = round(highest, 4)
    gain_pct = (highest / entry - 1) * 100
    if gain_pct < TRAILING_STOP_STEP_PCT:
        return
    locked_gain = math.floor(gain_pct / TRAILING_STOP_STEP_PCT) * TRAILING_STOP_STEP_PCT
    new_stop = entry * (1 + locked_gain / 100)
    trade["stop_price"] = round(max(float(trade["stop_price"]), new_stop), 4)


def close_trade(state: dict[str, object], trade: dict[str, object], date: str, price: float, reason: str, outcome: str) -> None:
    shares = int(trade["shares"])
    proceeds = shares * price
    pnl = proceeds - float(trade["capital"])
    trade["status"] = "CLOSED"
    trade["outcome"] = outcome
    trade["close_date"] = date
    trade["close_price"] = round(price, 4)
    trade["realized_pnl"] = round(pnl, 2)
    trade["realized_pnl_pct"] = round((price / float(trade["entry_price"]) - 1) * 100, 2)
    trade["close_reason"] = reason
    trade["market_value"] = 0.0
    trade["unrealized_pnl"] = 0.0
    state["cash"] = round(float(state["cash"]) + proceeds, 2)


def portfolio_value(state: dict[str, object]) -> float:
    open_value = sum(float(trade.get("market_value", 0) or 0) for trade in state["trades"] if trade["status"] == "OPEN")
    return round(float(state["cash"]) + open_value, 2)


def benchmark_v1() -> dict[str, object]:
    if not V1_TRADES_CSV.exists():
        return {}
    rows = read_csv(V1_TRADES_CSV)
    stats = trade_stats(rows)
    return {
        "trades": stats["trades"],
        "pnl": stats["pnl"],
        "value": round(INITIAL_CAPITAL + float(stats["pnl"]), 2),
        "wins": stats["wins"],
        "losses": stats["losses"],
    }


def benchmark_v1_by_ticker() -> dict[str, dict[str, object]]:
    if not V1_TRADES_CSV.exists():
        return {}
    return trade_stats_by_ticker(read_csv(V1_TRADES_CSV))


def benchmark_tickers() -> set[str]:
    return set(FOCUSED_TICKERS)


def comparison_rows(v2_trades: list[dict[str, object]]) -> list[dict[str, object]]:
    v1_stats = benchmark_v1_by_ticker()
    v2_stats = trade_stats_by_ticker(v2_trades)
    rows = []
    for ticker in sorted(set(v1_stats) | set(v2_stats)):
        v1 = v1_stats.get(ticker, {"pnl": 0, "losses": 0, "wins": 0, "trades": 0})
        v2 = v2_stats.get(ticker, {"pnl": 0, "losses": 0, "wins": 0, "trades": 0})
        rows.append(
            {
                "ticker": ticker,
                "v1_pnl": v1["pnl"],
                "v2_pnl": v2["pnl"],
                "pnl_delta": round(float(v2["pnl"]) - float(v1["pnl"]), 2),
                "v1_losses": v1["losses"],
                "v2_losses": v2["losses"],
                "loss_delta": int(v2["losses"]) - int(v1["losses"]),
                "v1_trades": v1["trades"],
                "v2_trades": v2["trades"],
                "winner": "V2" if float(v2["pnl"]) > float(v1["pnl"]) and int(v2["losses"]) <= int(v1["losses"]) else "V1",
            }
        )
    return rows


def capped_stop_price(entry_price: float, technical_stop: float, timeframe: str, stop_caps_pct: dict[str, float] | None) -> tuple[float, float | None]:
    if not stop_caps_pct:
        return technical_stop, None
    cap_pct = stop_caps_pct.get(timeframe)
    if not cap_pct:
        return technical_stop, None
    cap_stop = entry_price * (1 - cap_pct / 100)
    return max(technical_stop, cap_stop), cap_pct


def simulate_portfolio(
    strategies: list[dict[str, str]],
    quality_gate: list[dict[str, object]],
    stop_caps_pct: dict[str, float] | None = None,
) -> dict[str, object]:
    tickers = sorted({row["ticker"] for row in strategies})
    bars_by_ticker = {ticker: read_bars(ticker) for ticker in tickers}
    all_dates = sorted({bar.date for bars in bars_by_ticker.values() for bar in bars if bar.date >= CONFIG["start_date"]})
    index_by_ticker_date = {
        ticker: {bar.date: index for index, bar in enumerate(bars)}
        for ticker, bars in bars_by_ticker.items()
    }
    state: dict[str, object] = {
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "trades": [],
        "snapshots": [],
        "skipped": [],
        "quality_gate": quality_gate,
    }

    for date in all_dates:
        daily_bars = {}
        for ticker, bars in bars_by_ticker.items():
            idx = index_by_ticker_date[ticker].get(date)
            if idx is not None:
                daily_bars[ticker] = (idx, bars[idx])

        for trade in list(state["trades"]):
            if trade["status"] != "OPEN":
                continue
            item = daily_bars.get(str(trade["ticker"]))
            if item is None or date <= str(trade["entry_date"]):
                continue
            _idx, bar = item
            update_trailing_stop(trade, bar.high)
            stop = float(trade["stop_price"])
            target = float(trade["exit_price"])
            trade["held_sessions"] = int(trade.get("held_sessions", 0)) + 1
            if bar.low <= stop:
                outcome = "TRAILING_WIN" if stop >= float(trade["entry_price"]) else "LOSS"
                close_trade(state, trade, date, stop, "ضرب الوقف المتحرك/الفني", outcome)
                continue
            if bar.high >= target:
                close_trade(state, trade, date, target, "تحقق الهدف", "WIN")
                continue
            if int(trade["held_sessions"]) >= int(trade["hold_days"]):
                pnl_pct = (bar.close / float(trade["entry_price"]) - 1) * 100
                close_trade(state, trade, date, bar.close, "انتهت مدة الاحتفاظ", "TIMEOUT_WIN" if pnl_pct > 0 else "TIMEOUT_LOSS")
                continue
            market_value = int(trade["shares"]) * bar.close
            trade["latest_price"] = round(bar.close, 4)
            trade["market_value"] = round(market_value, 2)
            trade["unrealized_pnl"] = round(market_value - float(trade["capital"]), 2)

        for strategy in strategies:
            ticker = strategy["ticker"]
            item = daily_bars.get(ticker)
            if item is None:
                continue
            idx, bar = item
            if not design_strategies.entry_signal(strategy, bars_by_ticker[ticker], idx):
                continue
            existing = [
                trade
                for trade in state["trades"]
                if trade["status"] == "OPEN" and trade["ticker"] == ticker and trade["entry_rule"] == strategy["entry_rule"]
                and trade.get("strategy_id", "") == strategy.get("strategy_id", "")
            ]
            if existing:
                continue
            cash = float(state["cash"])
            target_alloc = cash * POSITION_CAP_PCT * float(strategy.get("size_multiplier", 1.0) or 1.0)
            adv = avg_dollar_volume(bars_by_ticker[ticker], idx)
            liquidity_cap = adv * MAX_TRADE_ADV_PCT if adv else target_alloc
            allocation = min(cash, target_alloc, liquidity_cap)
            shares = math.floor(allocation / bar.close)
            if shares < 1:
                state["skipped"].append({"date": date, "ticker": ticker, "reason": "cash_or_liquidity_below_one_share"})
                continue
            capital = shares * bar.close
            if strategy.get("stop_model") == "v1_atr_support":
                technical_stop = v1_stop_price(strategy, bars_by_ticker[ticker], idx)
            else:
                technical_stop = bar.close * (1 - float(strategy["initial_stop_pct"]) / 100)
            timeframe = strategy.get("timeframe", "")
            stop, stop_cap_pct = capped_stop_price(bar.close, technical_stop, timeframe, stop_caps_pct)
            target = bar.close * (1 + float(strategy["target_pct"]) / 100)
            trade = {
                "id": f"V2-{len(state['trades']) + 1:04d}",
                "ticker": ticker,
                "strategy_id": strategy.get("strategy_id", ""),
                "behavior": strategy["behavior"],
                "entry_rule": strategy["entry_rule"],
                "timeframe": timeframe,
                "selected_version": strategy.get("selected_version", ""),
                "verification_trades": strategy.get("verification_trades", ""),
                "verification_win_rate": strategy.get("verification_win_rate", ""),
                "verification_avg_return": strategy.get("verification_avg_return", ""),
                "verification_total_return": strategy.get("verification_total_return", ""),
                "status": "OPEN",
                "outcome": "",
                "entry_date": date,
                "entry_price": round(bar.close, 4),
                "shares": shares,
                "capital": round(capital, 2),
                "avg_dollar_volume": round(adv, 2),
                "liquidity_cap": round(liquidity_cap, 2),
                "technical_initial_stop_price": round(technical_stop, 4),
                "stop_cap_pct": round(stop_cap_pct, 2) if stop_cap_pct is not None else "",
                "initial_stop_price": round(stop, 4),
                "stop_price": round(stop, 4),
                "highest_price": round(bar.close, 4),
                "exit_price": round(target, 4),
                "hold_days": int(float(strategy["hold_days"])),
                "held_sessions": 0,
                "latest_price": round(bar.close, 4),
                "market_value": round(capital, 2),
                "unrealized_pnl": 0.0,
                "realized_pnl": "",
                "realized_pnl_pct": "",
                "close_date": "",
                "close_price": "",
                "close_reason": "",
            }
            state["trades"].append(trade)
            state["cash"] = round(cash - capital, 2)

        state["snapshots"].append({"date": date, "value": portfolio_value(state)})

    return state


def selected_portfolio_strategies() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    all_strategies = read_csv(SELECTED)
    if PORTFOLIO_UNIVERSE == "v1_benchmark_tickers":
        allowed = benchmark_tickers()
        all_strategies = [strategy for strategy in all_strategies if strategy["ticker"] in allowed]
    verification_by_ticker = {row["ticker"]: row for row in read_csv(SELECTED_VERIFICATION)}
    enriched_strategies = [
        add_verification_metrics(strategy, verification_by_ticker.get(strategy["ticker"], {}))
        for strategy in all_strategies
    ]
    proxy_stats_by_ticker: dict[str, dict[str, object]] = {}
    for strategy in enriched_strategies:
        proxy_state = simulate_portfolio([strategy], [])
        proxy_stats_by_ticker[strategy["ticker"]] = trade_stats(proxy_state["trades"])
    strategies, quality_gate = portfolio_quality_gate(
        all_strategies,
        proxy_stats_by_ticker=proxy_stats_by_ticker,
        v1_stats_by_ticker=benchmark_v1_by_ticker(),
    )
    return strategies, quality_gate


def build_portfolio() -> dict[str, object]:
    strategies, quality_gate = selected_portfolio_strategies()
    return simulate_portfolio(strategies, quality_gate)


def money(value: object) -> str:
    try:
        return f'<span class="num">${float(value):,.2f}</span>'
    except (TypeError, ValueError):
        return "-"


def pct_text(value: float) -> str:
    return f"{value * 100:.2f}%"


def trade_pnl(trade: dict[str, object]) -> float:
    if str(trade.get("status")) == "CLOSED":
        return float(trade.get("realized_pnl", 0) or 0)
    return float(trade.get("unrealized_pnl", 0) or 0)


def trade_pnl_pct(trade: dict[str, object]) -> float:
    if str(trade.get("status")) == "CLOSED" and trade.get("realized_pnl_pct") not in ("", None):
        return float(trade.get("realized_pnl_pct", 0) or 0)
    entry = float(trade.get("entry_price", 0) or 0)
    latest = float(trade.get("latest_price", 0) or 0)
    if not entry:
        return 0.0
    return (latest / entry - 1) * 100


def pct_cell(value: float) -> str:
    class_name = "positive" if value >= 0 else "negative"
    return f'<span class="{class_name} num">{value:.2f}%</span>'


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def ma(values: list[float], lookback: int) -> float | None:
    if len(values) < lookback:
        return None
    return mean(values[-lookback:])


def return_over_bars(values: list[float], sessions: int) -> float:
    if len(values) <= sessions or values[-sessions - 1] == 0:
        return 0.0
    return (values[-1] / values[-sessions - 1] - 1) * 100


def trend_label(close: float, ma50: float | None, ma200: float | None, ret20: float) -> str:
    if ma50 and ma200 and close >= ma50 >= ma200 and ret20 >= 0:
        return "صاعد"
    if ma50 and ma200 and close < ma50 < ma200 and ret20 < 0:
        return "هابط"
    if ma200 and close >= ma200 and ret20 >= 0:
        return "صاعد"
    if ma200 and close < ma200 and ret20 < 0:
        return "هابط"
    return "محايد"


def trend_class(label: str) -> str:
    return "positive" if label == "صاعد" else "negative" if label == "هابط" else ""


def market_metric(ticker: str, label: str | None = None) -> dict[str, object]:
    try:
        bars = read_bars(ticker)
    except FileNotFoundError:
        bars = []
    if len(bars) < 30:
        return {
            "ticker": ticker,
            "label": label or ticker,
            "trend": "لا توجد بيانات",
            "trend_class": "",
            "close": 0.0,
            "ma50": None,
            "ma200": None,
            "above50": False,
            "above200": False,
            "ret20": 0.0,
            "ret60": 0.0,
            "volume_ratio": 0.0,
            "volume_status": "-",
            "last_date": "-",
        }
    closes = [bar.close for bar in bars]
    volumes = [float(bar.volume) for bar in bars]
    close = closes[-1]
    ma50 = ma(closes, 50)
    ma200 = ma(closes, 200)
    ret20 = return_over_bars(closes, 20)
    ret60 = return_over_bars(closes, 60)
    avg_volume = mean(volumes[-21:-1]) if len(volumes) > 21 else mean(volumes[:-1])
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    trend = trend_label(close, ma50, ma200, ret20)
    volume_status = "مرتفع" if volume_ratio >= 1.2 else "منخفض" if volume_ratio <= 0.8 else "طبيعي"
    return {
        "ticker": ticker,
        "label": label or ticker,
        "trend": trend,
        "trend_class": trend_class(trend),
        "close": close,
        "ma50": ma50,
        "ma200": ma200,
        "above50": bool(ma50 and close >= ma50),
        "above200": bool(ma200 and close >= ma200),
        "ret20": ret20,
        "ret60": ret60,
        "volume_ratio": volume_ratio,
        "volume_status": volume_status,
        "last_date": bars[-1].date,
    }


def market_context() -> dict[str, object]:
    benchmarks = [market_metric(ticker, label) for ticker, label in MARKET_BENCHMARKS]
    tickers = sorted(FOCUSED_TICKERS)
    stocks = [market_metric(ticker) for ticker in tickers]
    valid_stocks = [item for item in stocks if item["trend"] != "لا توجد بيانات"]
    up = sum(1 for item in valid_stocks if item["trend"] == "صاعد")
    down = sum(1 for item in valid_stocks if item["trend"] == "هابط")
    neutral = len(valid_stocks) - up - down
    above50 = sum(1 for item in valid_stocks if item["above50"])
    above200 = sum(1 for item in valid_stocks if item["above200"])
    avg20 = mean([float(item["ret20"]) for item in valid_stocks])
    avg60 = mean([float(item["ret60"]) for item in valid_stocks])
    avg_volume_ratio = mean([float(item["volume_ratio"]) for item in valid_stocks])
    bench_up = sum(1 for item in benchmarks if item["trend"] == "صاعد")
    bench_down = sum(1 for item in benchmarks if item["trend"] == "هابط")
    if bench_up >= 2 and up >= max(5, len(valid_stocks) // 2 + 1):
        overall = "داعم"
    elif bench_down >= 2 or down >= max(5, len(valid_stocks) // 2 + 1):
        overall = "ضاغط"
    else:
        overall = "حذر / مختلط"
    best_stock = max(valid_stocks, key=lambda item: float(item["ret20"]), default=None)
    weakest_stock = min(valid_stocks, key=lambda item: float(item["ret20"]), default=None)
    return {
        "benchmarks": benchmarks,
        "stocks": stocks,
        "overall": overall,
        "overall_class": "positive" if overall == "داعم" else "negative" if overall == "ضاغط" else "",
        "up": up,
        "down": down,
        "neutral": neutral,
        "above50": above50,
        "above200": above200,
        "avg20": avg20,
        "avg60": avg60,
        "avg_volume_ratio": avg_volume_ratio,
        "best_stock": best_stock,
        "weakest_stock": weakest_stock,
        "last_date": max([str(item["last_date"]) for item in benchmarks + stocks], default="-"),
    }


def market_summary_cards(context: dict[str, object]) -> str:
    benchmarks = context["benchmarks"]
    qqq = next((item for item in benchmarks if item["ticker"] == "QQQ"), benchmarks[0] if benchmarks else None)
    spy = next((item for item in benchmarks if item["ticker"] == "SPY"), benchmarks[0] if benchmarks else None)
    soxx = next((item for item in benchmarks if item["ticker"] == "SOXX"), benchmarks[0] if benchmarks else None)

    def card(title: str, value: str, detail: str = "", class_name: str = "") -> str:
        return f"<article class='pulse-card'><span>{title}</span><strong class='{class_name}'>{value}</strong><small>{detail}</small></article>"

    cards = [
        card("حالة السوق", str(context["overall"]), f"آخر بيانات: {html.escape(str(context['last_date']))}", str(context["overall_class"])),
    ]
    for item in [qqq, spy, soxx]:
        if item:
            cards.append(
                card(
                    str(item["label"]),
                    str(item["trend"]),
                    f"20 يوم {float(item['ret20']):.2f}% | الحجم {float(item['volume_ratio']):.2f}x",
                    str(item["trend_class"]),
                )
            )
    cards.extend(
        [
            card("سلة الأسهم", f"{context['up']} من {len(context['stocks'])} صاعدة", f"هابطة {context['down']} | محايدة {context['neutral']}", "positive" if int(context["up"]) >= 5 else ""),
            card("قوة المتوسطات", f"{context['above200']} فوق 200 يوم", f"{context['above50']} فوق 50 يوم"),
            card("متوسط أداء السلة", f"{float(context['avg20']):.2f}%", f"60 يوم {float(context['avg60']):.2f}%", "positive" if float(context["avg20"]) >= 0 else "negative"),
        ]
    )
    return "".join(cards)


def market_rows(metrics: list[dict[str, object]]) -> str:
    rows = []
    for item in metrics:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item['ticker']))}</td>"
            f"<td>{html.escape(str(item['label']))}</td>"
            f"<td class='{html.escape(str(item['trend_class']))}'>{html.escape(str(item['trend']))}</td>"
            f"<td>{money(item['close'])}</td>"
            f"<td>{'نعم' if item['above50'] else 'لا'}</td>"
            f"<td>{'نعم' if item['above200'] else 'لا'}</td>"
            f"<td>{pct_cell(float(item['ret20']))}</td>"
            f"<td>{pct_cell(float(item['ret60']))}</td>"
            f"<td><span class='num'>{float(item['volume_ratio']):.2f}x</span> {html.escape(str(item['volume_status']))}</td>"
            f"<td>{html.escape(str(item['last_date']))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def analytics_group_stats(trades: list[dict[str, object]], key: str) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for trade in trades:
        groups.setdefault(str(trade.get(key, "") or "-"), []).append(trade)
    rows: list[dict[str, object]] = []
    for name, items in groups.items():
        closed = [item for item in items if item.get("status") == "CLOSED"]
        wins = [item for item in closed if float(item.get("realized_pnl", 0) or 0) >= 0]
        losses = [item for item in closed if float(item.get("realized_pnl", 0) or 0) < 0]
        total_pnl = sum(trade_pnl(item) for item in items)
        gross_win = sum(float(item.get("realized_pnl", 0) or 0) for item in wins)
        gross_loss = abs(sum(float(item.get("realized_pnl", 0) or 0) for item in losses))
        rows.append(
            {
                "name": name,
                "trades": len(items),
                "open": len(items) - len(closed),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(items), 2) if items else 0.0,
                "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
                "avg_capital": round(sum(float(item.get("capital", 0) or 0) for item in items) / len(items), 2)
                if items
                else 0.0,
            }
        )
    return sorted(rows, key=lambda row: float(row["total_pnl"]), reverse=True)


def analytics_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<tr><td colspan='9'>لا توجد بيانات كافية.</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['name']))}</td>"
        f"<td>{row['trades']}</td>"
        f"<td>{row['open']}</td>"
        f"<td>{row['closed']}</td>"
        f"<td>{row['wins']}</td>"
        f"<td>{row['losses']}</td>"
        f"<td><span class='num'>{float(row['win_rate']):.2f}%</span></td>"
        f"<td>{money(row['total_pnl'])}</td>"
        f"<td>{money(row['avg_pnl'])}</td>"
        "</tr>"
        for row in rows
    )


def monthly_trade_stats(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for trade in trades:
        groups.setdefault(str(trade.get("entry_date", ""))[:7], []).append(trade)
    rows: list[dict[str, object]] = []
    for month, items in groups.items():
        closed = [item for item in items if item.get("status") == "CLOSED"]
        wins = [item for item in closed if float(item.get("realized_pnl", 0) or 0) >= 0]
        losses = [item for item in closed if float(item.get("realized_pnl", 0) or 0) < 0]
        ticker_pnl: dict[str, float] = {}
        for item in items:
            ticker = str(item.get("ticker", ""))
            ticker_pnl[ticker] = ticker_pnl.get(ticker, 0.0) + trade_pnl(item)
        leaders = ", ".join(name for name, _ in sorted(ticker_pnl.items(), key=lambda pair: pair[1], reverse=True)[:3])
        rows.append(
            {
                "month": month,
                "trades": len(items),
                "wins": len(wins),
                "losses": len(losses),
                "total_pnl": round(sum(trade_pnl(item) for item in items), 2),
                "leaders": leaders,
            }
        )
    return sorted(rows, key=lambda row: float(row["total_pnl"]), reverse=True)


def monthly_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<tr><td colspan='6'>لا توجد بيانات شهرية كافية.</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['month']))}</td>"
        f"<td>{row['trades']}</td>"
        f"<td>{row['wins']}</td>"
        f"<td>{row['losses']}</td>"
        f"<td>{money(row['total_pnl'])}</td>"
        f"<td>{html.escape(str(row['leaders']))}</td>"
        "</tr>"
        for row in rows
    )


def period_returns(snapshots: list[dict[str, object]], period: str) -> list[dict[str, object]]:
    if not snapshots:
        return []
    groups: dict[str, list[dict[str, object]]] = {}
    for item in snapshots:
        date = str(item["date"])
        key = date[:4] if period == "year" else date[:7]
        groups.setdefault(key, []).append(item)
    ordered = []
    previous_close = INITIAL_CAPITAL
    for key in sorted(groups):
        items = groups[key]
        opening = previous_close
        closing = float(items[-1]["value"])
        pnl = closing - opening
        ret = (closing / opening - 1) * 100 if opening else 0.0
        ordered.append({"period": key, "opening": opening, "closing": closing, "pnl": pnl, "return": ret})
        previous_close = closing
    return ordered


def period_return_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<tr><td colspan='5'>لا توجد بيانات كافية.</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['period']))}</td>"
        f"<td>{money(row['opening'])}</td>"
        f"<td>{money(row['closing'])}</td>"
        f"<td>{money(row['pnl'])}</td>"
        f"<td><span class='num'>{float(row['return']):.2f}%</span></td>"
        "</tr>"
        for row in rows
    )


def max_drawdown(snapshots: list[dict[str, object]]) -> dict[str, object]:
    peak_value = 0.0
    peak_date = ""
    worst = {"drawdown": 0.0, "peak_date": "", "trough_date": "", "peak": 0.0, "trough": 0.0}
    for item in snapshots:
        value = float(item["value"])
        if value > peak_value:
            peak_value = value
            peak_date = str(item["date"])
        if peak_value:
            drawdown = (value / peak_value - 1) * 100
            if drawdown < float(worst["drawdown"]):
                worst = {
                    "drawdown": drawdown,
                    "peak_date": peak_date,
                    "trough_date": str(item["date"]),
                    "peak": peak_value,
                    "trough": value,
                }
    return worst


def closed_losses(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        trade
        for trade in trades
        if trade.get("status") == "CLOSED" and float(trade.get("realized_pnl", 0) or 0) < 0
    ]


def closed_wins(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        trade
        for trade in trades
        if trade.get("status") == "CLOSED" and float(trade.get("realized_pnl", 0) or 0) >= 0
    ]


def avg_realized_pct(trades: list[dict[str, object]]) -> float:
    if not trades:
        return 0.0
    return sum(float(trade.get("realized_pnl_pct", 0) or 0) for trade in trades) / len(trades)


def worst_realized_pct(trades: list[dict[str, object]]) -> float:
    return min((float(trade.get("realized_pnl_pct", 0) or 0) for trade in trades), default=0.0)


def shadow_signature(trade: dict[str, object]) -> str:
    return "|".join(
        [
            str(trade.get("ticker", "")),
            str(trade.get("strategy_id", "")),
            str(trade.get("entry_date", "")),
            f"{float(trade.get('entry_price', 0) or 0):.4f}",
        ]
    )


def stop_shadow_summary(base_state: dict[str, object], shadow_state: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    base_trades = list(base_state["trades"])
    shadow_trades = list(shadow_state["trades"])
    base_losses = closed_losses(base_trades)
    shadow_losses = closed_losses(shadow_trades)
    base_wins = closed_wins(base_trades)
    shadow_wins = closed_wins(shadow_trades)
    base_by_sig = {shadow_signature(trade): trade for trade in base_trades}
    shadow_by_sig = {shadow_signature(trade): trade for trade in shadow_trades}
    comparisons: list[dict[str, object]] = []
    winners_turned_loss = 0
    winners_reduced = 0
    losses_improved = 0
    for signature, base in base_by_sig.items():
        shadow = shadow_by_sig.get(signature)
        if not shadow:
            continue
        base_pnl = trade_pnl(base)
        shadow_pnl = trade_pnl(shadow)
        base_pct = trade_pnl_pct(base)
        shadow_pct = trade_pnl_pct(shadow)
        base_was_win = base.get("status") == "CLOSED" and base_pnl > 0
        shadow_closed_earlier = (
            bool(shadow.get("close_date"))
            and bool(base.get("close_date"))
            and str(shadow.get("close_date")) < str(base.get("close_date"))
        )
        if base_was_win and shadow_pnl < 0:
            winners_turned_loss += 1
        if base_was_win and shadow_pnl < base_pnl and shadow_closed_earlier:
            winners_reduced += 1
        if base_pnl < 0 and shadow_pnl > base_pnl:
            losses_improved += 1
        if base_pnl != shadow_pnl or base.get("close_date") != shadow.get("close_date"):
            comparisons.append(
                {
                    "ticker": base.get("ticker", ""),
                    "strategy_id": base.get("strategy_id", ""),
                    "timeframe": base.get("timeframe", ""),
                    "entry_date": base.get("entry_date", ""),
                    "base_close_date": base.get("close_date", ""),
                    "shadow_close_date": shadow.get("close_date", ""),
                    "base_pnl": round(base_pnl, 2),
                    "shadow_pnl": round(shadow_pnl, 2),
                    "pnl_delta": round(shadow_pnl - base_pnl, 2),
                    "base_pnl_pct": round(base_pct, 2),
                    "shadow_pnl_pct": round(shadow_pct, 2),
                    "base_outcome": base.get("outcome", ""),
                    "shadow_outcome": shadow.get("outcome", ""),
                }
            )
    summary = [
        {
            "scenario": "baseline",
            "swing_stop_cap_pct": "",
            "monthly_stop_cap_pct": "",
            "portfolio_value": portfolio_value(base_state),
            "pnl": round(portfolio_value(base_state) - INITIAL_CAPITAL, 2),
            "closed_trades": len([trade for trade in base_trades if trade.get("status") == "CLOSED"]),
            "wins": len(base_wins),
            "losses": len(base_losses),
            "avg_loss_pct": round(avg_realized_pct(base_losses), 2),
            "worst_loss_pct": round(worst_realized_pct(base_losses), 2),
            "max_drawdown_pct": round(float(max_drawdown(base_state["snapshots"])["drawdown"]), 2),
            "winners_turned_loss": "",
            "winners_reduced_by_early_stop": "",
            "losses_improved": "",
        },
        {
            "scenario": "shadow_tighter_stop",
            "swing_stop_cap_pct": STOP_SHADOW_CAPS_PCT["swing"],
            "monthly_stop_cap_pct": STOP_SHADOW_CAPS_PCT["monthly"],
            "portfolio_value": portfolio_value(shadow_state),
            "pnl": round(portfolio_value(shadow_state) - INITIAL_CAPITAL, 2),
            "closed_trades": len([trade for trade in shadow_trades if trade.get("status") == "CLOSED"]),
            "wins": len(shadow_wins),
            "losses": len(shadow_losses),
            "avg_loss_pct": round(avg_realized_pct(shadow_losses), 2),
            "worst_loss_pct": round(worst_realized_pct(shadow_losses), 2),
            "max_drawdown_pct": round(float(max_drawdown(shadow_state["snapshots"])["drawdown"]), 2),
            "winners_turned_loss": winners_turned_loss,
            "winners_reduced_by_early_stop": winners_reduced,
            "losses_improved": losses_improved,
        },
    ]
    return summary, sorted(comparisons, key=lambda row: float(row["pnl_delta"]))


def news_search_url(ticker: str, month: str, tone: str) -> str:
    query = urllib.parse.quote(f"{ticker} stock news {month} {tone} earnings AI semiconductors market")
    return f"https://www.google.com/search?tbm=nws&q={query}"


def news_blocks(title: str, tickers: list[str], months: list[str], tone: str) -> str:
    if not tickers or not months:
        return ""
    cards = []
    for ticker in tickers[:5]:
        links = " ".join(
            f"<a class='pill' target='_blank' href='{news_search_url(ticker, month, tone)}'>أخبار {html.escape(month)}</a>"
            for month in months[:4]
        )
        cards.append(
            f"<article class='news-card'><h3>{html.escape(ticker)}</h3>"
            f"<div class='search-pills'>{links}</div>"
            "<p>روابط بحث أخبار جاهزة لنفس شهر الربح/الخسارة. استخدمها لتفسير الحركة، وليست جزءا من حساب المحاكاة.</p>"
            "</article>"
        )
    return f"<h2>{title}</h2><section class='news-grid'>{''.join(cards)}</section>"


def render_analytics_dashboard(state: dict[str, object]) -> str:
    trades = list(state["trades"])
    snapshots = list(state["snapshots"])
    by_ticker = analytics_group_stats(trades, "ticker")
    by_behavior = analytics_group_stats(trades, "behavior")
    by_entry = analytics_group_stats(trades, "entry_rule")
    by_version = analytics_group_stats(trades, "selected_version")
    month_stats = monthly_trade_stats(trades)
    year_returns = period_returns(snapshots, "year")
    month_returns = period_returns(snapshots, "month")
    market = market_context()
    dd = max_drawdown(snapshots)
    total_value = portfolio_value(state)
    total_pnl = total_value - INITIAL_CAPITAL
    total_return = (total_value / INITIAL_CAPITAL - 1) * 100 if INITIAL_CAPITAL else 0.0
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if float(trade.get("realized_pnl", 0) or 0) >= 0]
    losses = [trade for trade in closed if float(trade.get("realized_pnl", 0) or 0) < 0]
    gross_win = sum(float(trade.get("realized_pnl", 0) or 0) for trade in wins)
    gross_loss = abs(sum(float(trade.get("realized_pnl", 0) or 0) for trade in losses))
    profit_factor = gross_win / gross_loss if gross_loss else 0.0
    liquidity_limited = [
        trade
        for trade in trades
        if float(trade.get("liquidity_cap", 0) or 0) > 0
        and float(trade.get("capital", 0) or 0) >= float(trade.get("liquidity_cap", 0) or 0) * 0.995
    ]
    avg_liquidity_use = (
        sum(float(trade.get("capital", 0) or 0) / float(trade.get("liquidity_cap", 1) or 1) for trade in trades)
        / len(trades)
        * 100
        if trades
        else 0.0
    )
    best_ticker = by_ticker[0]["name"] if by_ticker else "-"
    best_behavior = by_behavior[0]["name"] if by_behavior else "-"
    best_entry = by_entry[0]["name"] if by_entry else "-"
    best_month = month_stats[0]["month"] if month_stats else "-"
    worst_month = sorted(month_stats, key=lambda row: float(row["total_pnl"]))[0]["month"] if month_stats else "-"
    loss_trades = [trade for trade in closed if float(trade.get("realized_pnl", 0) or 0) < 0]
    loss_by_ticker: dict[str, float] = {}
    for trade in loss_trades:
        ticker = str(trade.get("ticker", ""))
        loss_by_ticker[ticker] = loss_by_ticker.get(ticker, 0.0) + abs(float(trade.get("realized_pnl", 0) or 0))
    winning_tickers = [str(row["name"]) for row in by_ticker if float(row["total_pnl"]) > 0]
    losing_tickers = [ticker for ticker, _ in sorted(loss_by_ticker.items(), key=lambda pair: pair[1], reverse=True)]
    best_months = [str(row["month"]) for row in month_stats if float(row["total_pnl"]) > 0]
    worst_months = [str(row["entry_date"])[:7] for row in loss_trades]
    worst_months = list(dict.fromkeys(worst_months))
    suggestions = []
    if by_behavior:
        leader = by_behavior[0]
        suggestions.append(
            f"الأقوى حاليا حسب السلوك هو {leader['name']} بربح {float(leader['total_pnl']):,.2f} دولار ونسبة فوز {float(leader['win_rate']):.2f}%."
        )
    if avg_liquidity_use < 25 and not liquidity_limited:
        suggestions.append("السيولة لا تبدو عائقا بالحجم الحالي؛ يمكن اختبار رفع حد الصفقة تدريجيا بشرط مراقبة السحب الأقصى.")
    elif liquidity_limited:
        suggestions.append("بعض الصفقات وصلت حد السيولة، لذلك رفع رأس المال قد لا يتحول كله إلى صفقات فعلية بنفس الكفاءة.")
    if dd["drawdown"] < -15:
        suggestions.append("السحب الأقصى مرتفع نسبيا؛ قبل زيادة حجم الصفقة راقب أشهر الهبوط والصفقات المتزامنة.")
    if not suggestions:
        suggestions.append("لا توجد إشارة خطر بارزة من التحليلات الحالية، لكن القرار النهائي يبقى بعد اختبار إعدادات مختلفة.")
    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    best_stock = market.get("best_stock") or {}
    weakest_stock = market.get("weakest_stock") or {}
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>تحليلات محفظة V2</title>
  <style>
    :root {{ --bg:#f5f7f9; --panel:#fff; --ink:#17212b; --muted:#65717d; --line:#d9e1e8; --blue:#1d5f8f; --green:#176b4d; --red:#a33a3a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:"Segoe UI", Tahoma, Arial, sans-serif; }}
    main {{ max-width:1260px; margin:0 auto; padding:28px; }}
    header {{ display:flex; justify-content:space-between; align-items:end; gap:16px; margin-bottom:18px; }}
    h1 {{ margin:0 0 4px; font-size:28px; }}
    h2 {{ margin:26px 0 12px; font-size:18px; }}
    .sub {{ color:var(--muted); font-size:14px; }}
    .header-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .back {{ border:1px solid var(--line); background:#eef3f7; color:var(--blue); border-radius:8px; padding:9px 12px; text-decoration:none; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; margin:14px 0; }}
    .card, table, .notes, .news-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
    .card {{ padding:14px; }}
    .card span {{ display:block; color:var(--muted); font-size:13px; }}
    .card strong {{ display:block; margin-top:4px; font-size:22px; }}
    .card small {{ display:block; margin-top:4px; color:var(--muted); font-size:12px; }}
    .positive {{ color:var(--green); }}
    .negative {{ color:var(--red); }}
    .notes {{ padding:14px 18px; margin:14px 0; }}
    .notes li {{ margin:7px 0; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; overflow:hidden; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px 12px; text-align:right; font-size:13px; vertical-align:top; }}
    th {{ background:#eaf0f5; color:#33404b; }}
    tr:last-child td {{ border-bottom:0; }}
    .num {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .grid-two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:14px; align-items:start; }}
    .news-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:10px; }}
    .news-card {{ padding:14px; }}
    .news-card h3 {{ margin:0 0 8px; font-size:20px; }}
    .news-card p {{ margin:10px 0 0; color:var(--muted); font-size:13px; }}
    .search-pills {{ display:flex; flex-wrap:wrap; gap:6px; }}
    .pill {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:5px 9px; background:#eef3f7; color:var(--blue); text-decoration:none; font-size:12px; }}
    @media (max-width:850px) {{ main {{ padding:18px; }} header {{ display:block; }} table {{ display:block; overflow-x:auto; white-space:nowrap; }} .grid-two {{ display:block; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>تحليلات محفظة V2</h1>
        <div class="sub">صفحة مشتقة من صفقات ومنحنى محفظة V2. آخر تحديث: {updated}</div>
      </div>
      <a class="back" href="paper_portfolio_v2_dashboard.html">العودة للداشبورد</a>
    </header>
    <section class="cards">
      <article class="card"><span>قيمة المحفظة</span><strong>{money(total_value)}</strong></article>
      <article class="card"><span>عائد الفترة الكلي</span><strong class="{'positive' if total_return >= 0 else 'negative'}"><span class="num">{total_return:.2f}%</span></strong></article>
      <article class="card"><span>الربح / الخسارة</span><strong class="{'positive' if total_pnl >= 0 else 'negative'}">{money(total_pnl)}</strong></article>
      <article class="card"><span>معامل الربح</span><strong><span class="num">{profit_factor:.2f}</span></strong></article>
      <article class="card"><span>السحب الأقصى</span><strong class="negative"><span class="num">{float(dd['drawdown']):.2f}%</span></strong></article>
      <article class="card"><span>أفضل سهم</span><strong>{html.escape(str(best_ticker))}</strong></article>
      <article class="card"><span>أفضل سلوك</span><strong>{html.escape(str(best_behavior))}</strong></article>
      <article class="card"><span>أفضل قاعدة دخول</span><strong>{html.escape(str(best_entry))}</strong></article>
      <article class="card"><span>أفضل شهر صفقات</span><strong>{html.escape(str(best_month))}</strong></article>
      <article class="card"><span>أسوأ شهر صفقات</span><strong>{html.escape(str(worst_month))}</strong></article>
    </section>
    <h2>حالة السوق وسلة الأسهم</h2>
    <section class="cards">
      <article class="card"><span>حالة السوق</span><strong class="{market['overall_class']}">{market['overall']}</strong></article>
      <article class="card"><span>الأسهم الصاعدة من السلة</span><strong>{market['up']} / {len(market['stocks'])}</strong></article>
      <article class="card"><span>فوق متوسط 200 يوم</span><strong>{market['above200']} / {len(market['stocks'])}</strong></article>
      <article class="card"><span>متوسط عائد السلة 20 يوم</span><strong class="{'positive' if float(market['avg20']) >= 0 else 'negative'}"><span class="num">{float(market['avg20']):.2f}%</span></strong></article>
      <article class="card"><span>أقوى سهم 20 يوم</span><strong>{html.escape(str(best_stock.get('ticker', '-')))}</strong><small>{float(best_stock.get('ret20', 0) or 0):.2f}%</small></article>
      <article class="card"><span>أضعف سهم 20 يوم</span><strong>{html.escape(str(weakest_stock.get('ticker', '-')))}</strong><small>{float(weakest_stock.get('ret20', 0) or 0):.2f}%</small></article>
    </section>
    <div class="grid-two">
      <section>
        <h2>المؤشرات المرجعية</h2>
        <table><thead><tr><th>الرمز</th><th>الاسم</th><th>الاتجاه</th><th>آخر سعر</th><th>فوق 50</th><th>فوق 200</th><th>20 يوم</th><th>60 يوم</th><th>الحجم</th><th>آخر بيانات</th></tr></thead><tbody>{market_rows(market['benchmarks'])}</tbody></table>
      </section>
      <section>
        <h2>سلة الأسهم التسعة</h2>
        <table><thead><tr><th>الرمز</th><th>الاسم</th><th>الاتجاه</th><th>آخر سعر</th><th>فوق 50</th><th>فوق 200</th><th>20 يوم</th><th>60 يوم</th><th>الحجم</th><th>آخر بيانات</th></tr></thead><tbody>{market_rows(market['stocks'])}</tbody></table>
      </section>
    </div>
    <section class="notes">
      <strong>قراءة تنفيذية</strong>
      <ul>{"".join(f"<li>{html.escape(item)}</li>" for item in suggestions)}</ul>
    </section>
    <section class="cards">
      <article class="card"><span>متوسط استخدام حد السيولة</span><strong><span class="num">{avg_liquidity_use:.2f}%</span></strong></article>
      <article class="card"><span>صفقات حدتها السيولة</span><strong>{len(liquidity_limited)}</strong></article>
      <article class="card"><span>قمة السحب</span><strong>{html.escape(str(dd['peak_date']))}</strong></article>
      <article class="card"><span>قاع السحب</span><strong>{html.escape(str(dd['trough_date']))}</strong></article>
    </section>
    <div class="grid-two">
      <section>
        <h2>عائد السنوات من منحنى المحفظة</h2>
        <table><thead><tr><th>الفترة</th><th>رصيد الافتتاح</th><th>رصيد الإغلاق</th><th>الربح</th><th>العائد</th></tr></thead><tbody>{period_return_rows(year_returns)}</tbody></table>
      </section>
      <section>
        <h2>أفضل الأشهر من منحنى المحفظة</h2>
        <table><thead><tr><th>الفترة</th><th>رصيد الافتتاح</th><th>رصيد الإغلاق</th><th>الربح</th><th>العائد</th></tr></thead><tbody>{period_return_rows(sorted(month_returns, key=lambda row: float(row['pnl']), reverse=True)[:12])}</tbody></table>
      </section>
    </div>
    <h2>الأسهم الأعلى ربحية</h2>
    <table><thead><tr><th>السهم</th><th>الصفقات</th><th>مفتوحة</th><th>مغلقة</th><th>رابحة</th><th>خاسرة</th><th>نسبة الفوز</th><th>الربح</th><th>متوسط الصفقة</th></tr></thead><tbody>{analytics_rows(by_ticker)}</tbody></table>
    <h2>السلوكيات / الأطر الأكثر تميزا</h2>
    <table><thead><tr><th>السلوك</th><th>الصفقات</th><th>مفتوحة</th><th>مغلقة</th><th>رابحة</th><th>خاسرة</th><th>نسبة الفوز</th><th>الربح</th><th>متوسط الصفقة</th></tr></thead><tbody>{analytics_rows(by_behavior)}</tbody></table>
    <h2>قواعد الدخول الأكثر تميزا</h2>
    <table><thead><tr><th>قاعدة الدخول</th><th>الصفقات</th><th>مفتوحة</th><th>مغلقة</th><th>رابحة</th><th>خاسرة</th><th>نسبة الفوز</th><th>الربح</th><th>متوسط الصفقة</th></tr></thead><tbody>{analytics_rows(by_entry)}</tbody></table>
    <h2>أداء النسخ</h2>
    <table><thead><tr><th>النسخة</th><th>الصفقات</th><th>مفتوحة</th><th>مغلقة</th><th>رابحة</th><th>خاسرة</th><th>نسبة الفوز</th><th>الربح</th><th>متوسط الصفقة</th></tr></thead><tbody>{analytics_rows(by_version)}</tbody></table>
    <h2>أعلى الأشهر ربحية حسب الصفقات</h2>
    <table><thead><tr><th>الشهر</th><th>الصفقات</th><th>رابحة</th><th>خاسرة</th><th>الربح</th><th>أبرز الأسهم</th></tr></thead><tbody>{monthly_rows(month_stats)}</tbody></table>
    {news_blocks("روابط أخبار مرتبطة بالأسهم الرابحة", winning_tickers, best_months, "profit rally breakout")}
    {news_blocks("روابط أخبار مرتبطة بالأسهم الخاسرة", losing_tickers, worst_months, "loss drop selloff")}
  </main>
</body>
</html>"""


def stop_shadow_rows(rows: list[dict[str, object]], positive: bool) -> str:
    selected = [row for row in rows if (float(row.get("pnl_delta", 0) or 0) > 0) == positive]
    selected = sorted(selected, key=lambda row: float(row.get("pnl_delta", 0) or 0), reverse=positive)[:6]
    if not selected:
        return "<tr><td colspan='6'>لا توجد صفقات في هذا التصنيف.</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('ticker', '')))}</td>"
        f"<td>{html.escape(str(row.get('entry_date', '')))}</td>"
        f"<td>{money(row.get('base_pnl'))}</td>"
        f"<td>{money(row.get('shadow_pnl'))}</td>"
        f"<td><strong class=\"{'positive' if float(row.get('pnl_delta', 0) or 0) >= 0 else 'negative'}\">{money(row.get('pnl_delta'))}</strong></td>"
        f"<td>{html.escape(str(row.get('base_outcome', '')))} / {html.escape(str(row.get('shadow_outcome', '')))}</td>"
        "</tr>"
        for row in selected
    )


def stop_shadow_section(summary_rows: list[dict[str, object]], comparison_rows: list[dict[str, object]]) -> str:
    if len(summary_rows) < 2:
        return ""
    base, shadow = summary_rows[0], summary_rows[1]
    value_delta = float(shadow["portfolio_value"]) - float(base["portfolio_value"])
    pnl_delta = float(shadow["pnl"]) - float(base["pnl"])
    loss_delta = int(shadow["losses"]) - int(base["losses"])
    avg_loss_delta = float(shadow["avg_loss_pct"]) - float(base["avg_loss_pct"])
    dd_delta = float(shadow["max_drawdown_pct"]) - float(base["max_drawdown_pct"])
    value_class = "positive" if value_delta >= 0 else "negative"
    loss_class = "positive" if loss_delta <= 0 else "negative"
    avg_loss_class = "positive" if avg_loss_delta >= 0 else "negative"
    dd_class = "positive" if dd_delta >= 0 else "negative"
    return f"""
    <section class="shadow-test">
      <div class="section-title">
        <h2>اختبار ظل للوقف الأقرب</h2>
        <span>لا يغير المحفظة الأساسية: سوينق {STOP_SHADOW_CAPS_PCT['swing']:.0f}%، شهري {STOP_SHADOW_CAPS_PCT['monthly']:.0f}%</span>
      </div>
      <div class="shadow-grid">
        <article class="shadow-card"><span>فرق قيمة المحفظة</span><strong class="{value_class}">{money(value_delta)}</strong><small>النسخة الحالية {money(base['portfolio_value'])} / الاختبار {money(shadow['portfolio_value'])}</small></article>
        <article class="shadow-card"><span>فرق الربح</span><strong class="{value_class}">{money(pnl_delta)}</strong><small>يقيس أثر الوقف الأقرب على الربحية</small></article>
        <article class="shadow-card"><span>فرق عدد الخسائر</span><strong class="{loss_class}"><span class="num">{loss_delta:+d}</span></strong><small>الحالي {base['losses']} / الاختبار {shadow['losses']}</small></article>
        <article class="shadow-card"><span>متوسط الخسارة</span><strong class="{avg_loss_class}"><span class="num">{float(shadow['avg_loss_pct']):.2f}%</span></strong><small>الحالي {float(base['avg_loss_pct']):.2f}%</small></article>
        <article class="shadow-card"><span>أسوأ خسارة</span><strong class="negative"><span class="num">{float(shadow['worst_loss_pct']):.2f}%</span></strong><small>الحالي {float(base['worst_loss_pct']):.2f}%</small></article>
        <article class="shadow-card"><span>السحب الأقصى</span><strong class="{dd_class}"><span class="num">{float(shadow['max_drawdown_pct']):.2f}%</span></strong><small>الحالي {float(base['max_drawdown_pct']):.2f}%</small></article>
        <article class="shadow-card"><span>رابحات تحولت لخسارة</span><strong class="negative"><span class="num">{shadow['winners_turned_loss']}</span></strong><small>تحذير من الوقف الضيق</small></article>
        <article class="shadow-card"><span>خسائر تحسنت</span><strong class="positive"><span class="num">{shadow['losses_improved']}</span></strong><small>صفقات قل ضررها بالوقف الأقرب</small></article>
      </div>
      <div class="shadow-tables">
        <section>
          <h3>أكثر صفقات تضررت</h3>
          <table class="compact-table"><thead><tr><th>السهم</th><th>الدخول</th><th>الحالي</th><th>الوقف الأقرب</th><th>الفرق</th><th>النتيجة</th></tr></thead><tbody>{stop_shadow_rows(comparison_rows, positive=False)}</tbody></table>
        </section>
        <section>
          <h3>أكثر خسائر تحسنت</h3>
          <table class="compact-table"><thead><tr><th>السهم</th><th>الدخول</th><th>الحالي</th><th>الوقف الأقرب</th><th>الفرق</th><th>النتيجة</th></tr></thead><tbody>{stop_shadow_rows(comparison_rows, positive=True)}</tbody></table>
        </section>
      </div>
    </section>
    """


def render_dashboard(state: dict[str, object]) -> str:
    trades = state["trades"]
    benchmark = benchmark_v1()
    quality_gate = state.get("quality_gate", [])
    approved_count = sum(1 for row in quality_gate if row.get("approved"))
    rejected_count = len(quality_gate) - approved_count
    v1_better_count = sum(1 for row in quality_gate if row.get("reason") == "rejected_v1_better_for_ticker")
    open_trades = [trade for trade in trades if trade["status"] == "OPEN"]
    closed = [trade for trade in trades if trade["status"] == "CLOSED"]
    wins = [trade for trade in closed if float(trade.get("realized_pnl", 0) or 0) >= 0]
    losses = [trade for trade in closed if float(trade.get("realized_pnl", 0) or 0) < 0]
    realized = sum(float(trade.get("realized_pnl", 0) or 0) for trade in closed)
    unrealized = sum(float(trade.get("unrealized_pnl", 0) or 0) for trade in open_trades)
    value = portfolio_value(state)
    pnl = value - INITIAL_CAPITAL
    first_date = START_DATE
    last_date = max((dt.date.fromisoformat(str(item["date"])) for item in state["snapshots"]), default=START_DATE)
    elapsed_years = max((last_date - first_date).days / 365.25, 1 / 365.25)
    annual_return_pct = ((value / INITIAL_CAPITAL) ** (1 / elapsed_years) - 1) * 100 if value > 0 else -100
    period_return_pct = ((value / INITIAL_CAPITAL) - 1) * 100 if INITIAL_CAPITAL > 0 else -100
    benchmark_gap = pnl - float(benchmark.get("pnl", 0) or 0)
    loss_gap = len(losses) - int(benchmark.get("losses", 0) or 0)
    settings_json = json.dumps(
        {
            "initial_capital": INITIAL_CAPITAL,
            "position_cap_pct": POSITION_CAP_PCT,
            "trailing_stop_step_pct": TRAILING_STOP_STEP_PCT,
            "liquidity_lookback_days": LIQUIDITY_LOOKBACK_DAYS,
            "max_trade_adv_pct": MAX_TRADE_ADV_PCT,
            "min_acceptable_annual_return_pct": MIN_ACCEPTABLE_ANNUAL_RETURN_PCT,
            "portfolio_universe": PORTFOLIO_UNIVERSE,
        },
        ensure_ascii=False,
    )
    market = market_context()
    market_cards = market_summary_cards(market)
    tickers = sorted({str(trade["ticker"]) for trade in trades})
    ticker_filters = "\n".join(f'<button data-filter="{html.escape(ticker)}">{html.escape(ticker)}</button>' for ticker in tickers)
    ticker_chips = "".join(f'<span class="chip">{html.escape(ticker)}</span>' for ticker in tickers)
    years = sorted({str(trade["entry_date"])[:4] for trade in trades})
    months = sorted({str(trade["entry_date"])[5:7] for trade in trades})
    year_options = "".join(f'<option value="{html.escape(year)}">{html.escape(year)}</option>' for year in years)
    month_options = "".join(f'<option value="{html.escape(month)}">{html.escape(month)}</option>' for month in months)
    dd = max_drawdown(state["snapshots"])
    gross_win = sum(float(trade.get("realized_pnl", 0) or 0) for trade in wins)
    gross_loss = abs(sum(float(trade.get("realized_pnl", 0) or 0) for trade in losses))
    profit_factor = gross_win / gross_loss if gross_loss else 0.0
    win_rate = len(wins) / len(closed) * 100 if closed else 0.0
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    avg_win_pct = (
        sum(float(trade.get("realized_pnl", 0) or 0) / float(trade.get("capital", 1) or 1) * 100 for trade in wins)
        / len(wins)
        if wins
        else 0.0
    )
    avg_loss_pct = (
        sum(float(trade.get("realized_pnl", 0) or 0) / float(trade.get("capital", 1) or 1) * 100 for trade in losses)
        / len(losses)
        if losses
        else 0.0
    )
    largest_loss = min((float(trade.get("realized_pnl", 0) or 0) for trade in losses), default=0.0)
    avg_liquidity_use = (
        sum(float(trade.get("capital", 0) or 0) / float(trade.get("liquidity_cap", 1) or 1) for trade in trades)
        / len(trades)
        * 100
        if trades
        else 0.0
    )
    largest_open_value = max((float(trade.get("market_value", 0) or 0) for trade in open_trades), default=0.0)
    concentration_pct = largest_open_value / value * 100 if value else 0.0
    updated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    last_data_date = last_date.isoformat()
    year_return_table = period_return_rows(period_returns(state["snapshots"], "year"))
    month_return_table = period_return_rows(
        sorted(period_returns(state["snapshots"], "month"), key=lambda row: float(row["pnl"]), reverse=True)[:6]
    )
    shadow_html = stop_shadow_section(
        list(state.get("stop_shadow_summary", [])),
        list(state.get("stop_shadow_comparison", [])),
    )
    open_cards = "\n".join(
        f"""
        <article class="position-card">
          <div class="position-head"><strong>{html.escape(str(trade['ticker']))}</strong><span>{html.escape(str(trade.get('behavior', '')))}</span></div>
          <div class="position-grid">
            <span>الدخول <b>{money(trade.get('entry_price'))}</b></span>
            <span>الحالي <b>{money(trade.get('latest_price'))}</b></span>
            <span>الوقف <b>{money(trade.get('stop_price'))}</b></span>
            <span>التخارج <b>{money(trade.get('exit_price'))}</b></span>
            <span>القيمة <b>{money(trade.get('market_value'))}</b></span>
            <span>الأسهم <b class="num">{html.escape(str(trade.get('shares', '')))}</b></span>
          </div>
          <div class="position-pnl {'positive' if float(trade.get('unrealized_pnl', 0) or 0) >= 0 else 'negative'}">
            {money(trade.get('unrealized_pnl', 0))}
            <span class="position-pnl-pct">{pct_cell(trade_pnl_pct(trade))}</span>
          </div>
        </article>
        """
        for trade in sorted(open_trades, key=lambda item: float(item.get("market_value", 0) or 0), reverse=True)[:8]
    ) or '<article class="position-card empty">لا توجد صفقات مفتوحة حاليا.</article>'
    rows = "\n".join(
        f"<tr data-ticker=\"{html.escape(str(trade['ticker']))}\" data-status=\"{html.escape(str(trade['status']))}\" data-outcome=\"{html.escape(str(trade.get('outcome', '')))}\" data-year=\"{html.escape(str(trade['entry_date'])[:4])}\" data-month=\"{html.escape(str(trade['entry_date'])[5:7])}\" data-pnl=\"{float(trade.get('realized_pnl') if trade['status'] == 'CLOSED' else trade.get('unrealized_pnl') or 0):.2f}\" data-pnl-pct=\"{trade_pnl_pct(trade):.4f}\" data-capital=\"{float(trade.get('capital', 0) or 0):.2f}\" data-market-value=\"{float(trade.get('market_value', 0) or 0):.2f}\" data-liquidity-cap=\"{float(trade.get('liquidity_cap', 0) or 0):.2f}\" data-pnl-kind=\"{'loss' if float(trade.get('realized_pnl') if trade['status'] == 'CLOSED' else trade.get('unrealized_pnl') or 0) < 0 else 'win'}\" data-behavior=\"{html.escape(str(trade['behavior']))}\" data-version=\"{html.escape(str(trade.get('selected_version', '')))}\">"
        f"<td>{html.escape(str(trade['id']))}</td>"
        f"<td>{html.escape(str(trade['ticker']))}</td>"
        f"<td>{html.escape(str(trade['behavior']))}</td>"
        f"<td>{html.escape(str(trade['entry_rule']))}</td>"
        f"<td>{html.escape(str(trade.get('selected_version', '')))}</td>"
        f"<td>{html.escape(str(trade.get('verification_win_rate', '')))}%</td>"
        f"<td>{html.escape(str(trade.get('verification_total_return', '')))}%</td>"
        f"<td>{html.escape(str(trade['status']))}</td>"
        f"<td>{html.escape(str(trade.get('outcome', '')))}</td>"
        f"<td>{html.escape(str(trade['entry_date']))}</td>"
        f"<td>{html.escape(str(trade.get('close_date') or '-'))}</td>"
        f"<td>{money(trade['entry_price'])}</td>"
        f"<td>{money(trade['capital'])}</td>"
        f"<td>{html.escape(str(trade['shares']))}</td>"
        f"<td>{money(trade.get('liquidity_cap', ''))}</td>"
        f"<td>{money(trade.get('initial_stop_price', ''))}</td>"
        f"<td>{money(trade['stop_price'])}</td>"
        f"<td>{money(trade.get('highest_price', ''))}</td>"
        f"<td>{money(trade['exit_price'])}</td>"
        f"<td>{money(trade.get('latest_price', ''))}</td>"
        f"<td>{money(trade.get('market_value', 0))}</td>"
        f"<td>{money(trade.get('realized_pnl') if trade['status'] == 'CLOSED' else trade.get('unrealized_pnl'))}</td>"
        f"<td>{pct_cell(trade_pnl_pct(trade))}</td>"
        "</tr>"
        for trade in sorted(trades, key=lambda item: item["id"], reverse=True)
    )
    chart_data = json.dumps(state["snapshots"], ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>محفظة النسخة الثانية</title>
  <style>
    :root {{ --bg:#f5f7f9; --panel:#fff; --ink:#17212b; --muted:#65717d; --line:#d9e1e8; --blue:#1d5f8f; --green:#176b4d; --red:#a33a3a; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:"Segoe UI", Tahoma, Arial, sans-serif; }}
    main {{ max-width:1320px; margin:0 auto; padding:24px; }}
    header {{ display:flex; justify-content:space-between; align-items:end; gap:16px; margin-bottom:16px; }}
    h1 {{ margin:0 0 4px; font-size:28px; }}
    h2 {{ margin:26px 0 12px; font-size:18px; }}
    .sub {{ color:var(--muted); font-size:14px; }}
    .last-update {{ color:var(--muted); font-size:12px; margin-top:5px; }}
    .last-update strong {{ color:var(--ink); font-weight:600; }}
    .header-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .section-title {{ display:flex; align-items:end; justify-content:space-between; gap:12px; margin:24px 0 10px; }}
    .section-title h2 {{ margin:0; }}
    .section-title span {{ color:var(--muted); font-size:13px; }}
    .market-pulse {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; margin:14px 0; }}
    .market-pulse .section-title {{ margin:0 0 10px; }}
    .pulse-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:10px; }}
    .pulse-card {{ border:1px solid var(--line); background:#fbfcfd; border-radius:7px; padding:11px; }}
    .pulse-card span {{ display:block; color:var(--muted); font-size:12px; }}
    .pulse-card strong {{ display:block; margin-top:4px; font-size:18px; }}
    .pulse-card small {{ display:block; margin-top:5px; color:var(--muted); font-size:11px; }}
    .stats {{ display:grid; grid-template-columns:repeat(6,minmax(145px,1fr)); gap:10px; margin:14px 0; }}
    .stat, .chart, table, .settings, .panel, .position-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
    .stat {{ padding:14px; min-height:92px; }}
    .stat.primary {{ background:#f8fbfd; border-color:#c9d9e6; }}
    .stats .stat {{ display:none; }}
    .stats .stat:nth-child(4), .stats .stat:nth-child(5), .stats .stat:nth-child(6), .stats .stat:nth-child(1), .stats .stat:nth-child(10), .stats .stat:nth-child(11) {{ display:block; }}
    .stats .stat:nth-child(4) {{ order:1; }}
    .stats .stat:nth-child(5) {{ order:2; }}
    .stats .stat:nth-child(6) {{ order:3; }}
    .stats .stat:nth-child(1) {{ order:4; }}
    .stats .stat:nth-child(10) {{ order:5; }}
    .stats .stat:nth-child(11) {{ order:6; }}
    .stat span {{ display:block; color:var(--muted); font-size:13px; }}
    .stat strong {{ display:block; margin-top:4px; font-size:24px; }}
    .stat small {{ display:block; color:var(--muted); margin-top:6px; font-size:12px; }}
    .positive {{ color:var(--green); }}
    .negative {{ color:var(--red); }}
    .dashboard-grid {{ display:grid; grid-template-columns:minmax(0,2fr) minmax(300px,0.9fr); gap:14px; align-items:start; }}
    .panel {{ padding:14px; }}
    .panel h3 {{ margin:0 0 10px; font-size:16px; }}
    .risk-grid {{ display:grid; grid-template-columns:repeat(2,minmax(120px,1fr)); gap:10px; }}
    .risk-card {{ border:1px solid var(--line); background:#fbfcfd; border-radius:7px; padding:11px; }}
    .risk-card span {{ display:block; color:var(--muted); font-size:12px; }}
    .risk-card strong {{ display:block; margin-top:4px; font-size:20px; }}
    .mini-tables {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:14px 0; }}
    .toolbar {{ display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:10px; }}
    .tabs button, .filters button, .link-btn, .save-btn, .refresh-btn {{ border:1px solid var(--line); background:#eef3f7; color:var(--blue); padding:8px 11px; border-radius:7px; cursor:pointer; text-decoration:none; font:inherit; }}
    .tabs button.active, .filters button.active {{ background:var(--blue); color:white; border-color:var(--blue); }}
    .filters {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 10px; }}
    .chart {{ padding:14px; margin-bottom:0; }}
    svg {{ width:100%; height:310px; display:block; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; overflow:hidden; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px; text-align:right; font-size:13px; vertical-align:top; }}
    th {{ background:#eaf0f5; }}
    .num {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .table-wrap {{ overflow:auto; max-height:650px; }}
    .compact-table th, .compact-table td {{ font-size:12px; padding:8px 9px; }}
    .open-positions {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:10px; }}
    .position-card {{ padding:13px; }}
    .position-card.empty {{ color:var(--muted); }}
    .position-head {{ display:flex; justify-content:space-between; gap:8px; align-items:center; margin-bottom:10px; }}
    .position-head strong {{ font-size:20px; }}
    .position-head span {{ color:var(--muted); font-size:12px; }}
    .position-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .position-grid span {{ border:1px solid var(--line); border-radius:6px; padding:7px; color:var(--muted); font-size:12px; }}
    .position-grid b {{ display:block; color:var(--ink); margin-top:3px; font-size:13px; }}
    .position-pnl {{ margin-top:10px; font-weight:700; font-size:18px; display:flex; justify-content:flex-end; align-items:baseline; gap:8px; flex-wrap:wrap; }}
    .position-pnl-pct {{ font-size:13px; font-weight:700; }}
    .settings {{ padding:14px; margin:16px 0; }}
    details.settings summary {{ cursor:pointer; color:var(--blue); font-weight:700; }}
    .settings form {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; align-items:end; }}
    .settings label {{ color:var(--muted); font-size:13px; }}
    .settings input {{ width:100%; margin-top:4px; border:1px solid var(--line); border-radius:6px; padding:8px; font:inherit; }}
    .settings-actions {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .settings-note {{ margin-top:8px; color:var(--muted); font-size:13px; }}
    .universe {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
    .chip {{ border:1px solid var(--line); background:#f7fafc; border-radius:999px; padding:4px 9px; font-size:12px; color:var(--muted); }}
    .quick {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:16px 0; }}
    .quick button {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; text-align:right; cursor:pointer; font:inherit; }}
    .quick button.active {{ border-color:var(--blue); box-shadow:inset 0 0 0 1px var(--blue); }}
    .quick button span {{ display:block; color:var(--muted); font-size:13px; }}
    .quick button strong {{ display:block; margin-top:3px; font-size:22px; }}
    .table-tools {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0; }}
    .quick + .table-tools {{ display:none; }}
    .table-tools input, .table-tools select {{ border:1px solid var(--line); border-radius:7px; padding:8px; font:inherit; background:white; }}
    @media (max-width: 980px) {{
      main {{ padding:16px; }}
      header {{ display:block; }}
      .header-actions {{ margin-top:12px; }}
      .stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
      .dashboard-grid, .mini-tables {{ display:block; }}
      .panel, .chart {{ margin-bottom:12px; }}
      .table-wrap {{ max-height:none; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>محفظة ورقية V2</h1>
        <div class="sub">تستخدم فقط الاستراتيجيات التي اجتازت بوابة الجودة بعد التشخيص. البداية: {CONFIG['start_date']}</div>
        <div class="last-update">آخر تاريخ بيانات السوق: <strong>{last_data_date}</strong> | آخر تحديث للملف: <strong>{updated_at}</strong></div>
      </div>
      <div class="header-actions">
        <a class="link-btn" href="paper_portfolio_v2_analytics.html">التحليلات</a>
        <a class="link-btn" href="business_intelligence_lab.html">ذكاء الأعمال</a>
        <a class="link-btn" href="strategy_v2_dashboard.html">داشبورد التشخيص</a>
      </div>
    </header>
    <section class="market-pulse">
      <div class="section-title"><h2>نبض السوق</h2><span>ملخص سريع للمؤشرات وسلة الأسهم</span></div>
      <div class="pulse-grid">{market_cards}</div>
    </section>
    <section class="settings">
      <div class="settings-note">الأسهم التسعة: {ticker_chips}</div>
      <form id="settingsForm">
        <label>رأس المال
          <input id="initialCapital" type="number" min="1000" step="1000" value="{INITIAL_CAPITAL:.0f}">
        </label>
        <label>حد الصفقة من الكاش %
          <input id="positionCap" type="number" min="1" max="100" step="1" value="{POSITION_CAP_PCT * 100:.0f}">
        </label>
        <label>نسبة السيولة من ADV %
          <input id="liquidityPct" type="number" min="0.01" max="10" step="0.01" value="{MAX_TRADE_ADV_PCT * 100:.2f}">
        </label>
        <label>أيام حساب السيولة
          <input id="liquidityLookback" type="number" min="5" max="100" step="1" value="{LIQUIDITY_LOOKBACK_DAYS}">
        </label>
        <label>خطوة رفع الوقف %
          <input id="trailingStep" type="number" min="0.5" max="10" step="0.5" value="{TRAILING_STOP_STEP_PCT:.1f}">
        </label>
        <label>أقل عائد سنوي مقبول %
          <input id="minAnnualReturn" type="number" min="1" max="500" step="1" value="{MIN_ACCEPTABLE_ANNUAL_RETURN_PCT:.0f}">
        </label>
        <div class="settings-actions">
          <button class="save-btn" type="submit">حفظ وإعادة بناء</button>
          <button class="refresh-btn" type="button" id="refreshDataBtn">تحديث</button>
        </div>
      </form>
      <div class="settings-note" id="settingsStatus">الكون الاستثماري مقفل على الأسهم التسعة، وتعديل القيم يعيد بناء المحفظة بنفس الأسهم فقط.</div>
    </section>
    <section class="table-tools">
      <input id="tradeSearch" type="search" placeholder="بحث: سهم، رقم صفقة، حالة">
      <select id="yearFilter"><option value="all">كل السنوات</option>{year_options}</select>
      <select id="monthFilter"><option value="all">كل الشهور</option>{month_options}</select>
      <button type="button" class="refresh-btn" id="clearTradeFilters">مسح الفلاتر</button>
    </section>
    <section class="stats">
      <article class="stat"><span>رأس المال</span><strong>{money(INITIAL_CAPITAL)}</strong></article>
      <article class="stat"><span>حد الصفقة</span><strong>{POSITION_CAP_PCT * 100:.0f}%</strong></article>
      <article class="stat"><span>حد السيولة</span><strong>{MAX_TRADE_ADV_PCT * 100:.2f}%</strong></article>
      <article class="stat"><span>قيمة المحفظة</span><strong>{money(value)}</strong></article>
      <article class="stat"><span>الربح / الخسارة</span><strong class="{'positive' if value >= INITIAL_CAPITAL else 'negative'}">{money(pnl)}</strong></article>
      <article class="stat"><span>عائد الفترة</span><strong class="{'positive' if period_return_pct >= 0 else 'negative'}">{period_return_pct:.2f}%</strong></article>
      <article class="stat"><span>الحد الأدنى المقبول</span><strong>{MIN_ACCEPTABLE_ANNUAL_RETURN_PCT:.0f}%</strong></article>
      <article class="stat"><span>ربح محقق</span><strong class="{'positive' if realized >= 0 else 'negative'}">{money(realized)}</strong></article>
      <article class="stat"><span>غير محقق</span><strong class="{'positive' if unrealized >= 0 else 'negative'}">{money(unrealized)}</strong></article>
      <article class="stat"><span>صفقات مفتوحة</span><strong>{len(open_trades)}</strong></article>
      <article class="stat"><span>صفقات مغلقة</span><strong>{len(closed)}</strong></article>
      <article class="stat"><span>رابحة</span><strong class="positive">{len(wins)}</strong></article>
      <article class="stat"><span>خاسرة</span><strong class="negative">{len(losses)}</strong></article>
      <article class="stat"><span>استراتيجيات معتمدة</span><strong>{approved_count}</strong></article>
      <article class="stat"><span>استراتيجيات مستبعدة</span><strong>{rejected_count}</strong></article>
      <article class="stat"><span>النسخة الأولى أفضل فيها</span><strong>{v1_better_count}</strong></article>
      <article class="stat"><span>فرق الربح عن النسخة الأولى</span><strong class="{'positive' if benchmark_gap >= 0 else 'negative'}">{money(benchmark_gap) if benchmark else '-'}</strong></article>
      <article class="stat"><span>فرق الخسائر عن النسخة الأولى</span><strong class="{'positive' if loss_gap <= 0 else 'negative'}">{loss_gap if benchmark else '-'}</strong></article>
    </section>
    {shadow_html}
    <section class="chart">
      <div class="toolbar">
        <strong>قيمة المحفظة</strong>
        <div class="tabs">
          <button class="active" data-mode="daily">يومي</button>
          <button data-mode="weekly">أسبوعي</button>
          <button data-mode="monthly">شهري</button>
        </div>
      </div>
      <svg id="chart"></svg>
    </section>
    <h2>بيانات الصفقات</h2>
    <section class="quick">
      <button type="button" data-quick="OPEN"><span>الصفقات المفتوحة</span><strong>{len(open_trades)}</strong></button>
      <button type="button" data-quick="CLOSED"><span>الصفقات المغلقة</span><strong>{len(closed)}</strong></button>
      <button type="button" data-quick="win"><span>الصفقات الرابحة</span><strong>{len(wins)}</strong></button>
      <button type="button" data-quick="loss"><span>الصفقات الخاسرة</span><strong>{len(losses)}</strong></button>
    </section>
    <section class="table-tools">
      <input id="tradeSearch" type="search" placeholder="بحث: سهم، رقم صفقة، حالة">
      <select id="yearFilter"><option value="all">كل السنوات</option>{year_options}</select>
      <select id="monthFilter"><option value="all">كل الشهور</option>{month_options}</select>
      <button type="button" class="refresh-btn" id="clearTradeFilters">مسح الفلاتر</button>
    </section>
    <div class="filters">
      {ticker_filters}
      <button class="active" data-filter="all">الكل</button>
      <button data-filter="breakout">اختراق</button>
      <button data-filter="pullback_recovery">ارتداد</button>
      <button data-filter="trend_following">ترند</button>
      <button data-filter="mixed_or_choppy">مختلط</button>
      <button data-filter="v2_refined">v2 محسّن</button>
      <button data-filter="v1_original">v1 أصلي</button>
    </div>
    <section class="table-wrap">
      <table>
        <thead><tr><th>رقم</th><th>السهم</th><th>السلوك</th><th>قاعدة الدخول</th><th>النسخة</th><th>نسبة النجاح</th><th>عائد التحقق</th><th>الحالة</th><th>النتيجة</th><th>الدخول</th><th>الخروج</th><th>سعر الدخول</th><th>قيمة الصفقة</th><th>الأسهم</th><th>حد السيولة</th><th>وقف ابتدائي</th><th>الوقف</th><th>أعلى سعر</th><th>الهدف</th><th>آخر سعر</th><th>القيمة الحالية</th><th>ربح/خسارة</th><th>ربح/خسارة %</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
  </main>
  <script>
    const data = {chart_data};
    const settings = {settings_json};
    const localApi = 'http://127.0.0.1:8766';
    const localControlAvailable = location.protocol === 'file:' || location.hostname === '127.0.0.1' || location.hostname === 'localhost';
    const svg = document.getElementById('chart');
    const tabButtons = [...document.querySelectorAll('.tabs button')];
    const filterButtons = [...document.querySelectorAll('.filters button')];
    const tradeSearch = document.getElementById('tradeSearch');
    const yearFilter = document.getElementById('yearFilter');
    const monthFilter = document.getElementById('monthFilter');
    let activeFilter = 'all';
    let quickFilter = 'all';
    let currentChartMode = 'daily';
    const moneyFmt = new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD' }});
    function reshapeDashboard() {{
      const main = document.querySelector('main');
      const chartSection = document.querySelector('.chart');
      const settingsSection = document.querySelector('section.settings');
      if (settingsSection) {{
        const settingsDetails = document.createElement('details');
        settingsDetails.className = 'settings';
        const summary = document.createElement('summary');
        summary.textContent = 'إعدادات المحفظة وإعادة البناء';
        settingsDetails.appendChild(summary);
        while (settingsSection.firstChild) settingsDetails.appendChild(settingsSection.firstChild);
        settingsSection.replaceWith(settingsDetails);
      }}
      const riskPanel = document.createElement('aside');
      riskPanel.className = 'panel';
      riskPanel.innerHTML = `
        <h3>مؤشرات المخاطر</h3>
        <div class="risk-grid">
          <div class="risk-card"><span>معامل الربح</span><strong class="num">{profit_factor:.2f}</strong></div>
          <div class="risk-card"><span>نسبة الفوز</span><strong class="num">{win_rate:.2f}%</strong></div>
          <div class="risk-card"><span>السحب الأقصى</span><strong class="negative num">{float(dd['drawdown']):.2f}%</strong></div>
          <div class="risk-card"><span>أكبر خسارة</span><strong class="negative">{money(largest_loss)}</strong></div>
          <div class="risk-card"><span>متوسط الرابحة</span><strong>{money(avg_win)}</strong></div>
          <div class="risk-card"><span>متوسط الخاسرة</span><strong>{money(avg_loss)}</strong></div>
          <div class="risk-card"><span>متوسط ربح الصفقة %</span><strong class="positive num">{avg_win_pct:.2f}%</strong></div>
          <div class="risk-card"><span>متوسط خسارة الصفقة %</span><strong class="negative num">{avg_loss_pct:.2f}%</strong></div>
          <div class="risk-card"><span>أكبر تركّز مفتوح</span><strong class="num">{concentration_pct:.2f}%</strong></div>
          <div class="risk-card"><span>استخدام السيولة</span><strong class="num">{avg_liquidity_use:.2f}%</strong></div>
        </div>`;
      if (chartSection && !document.querySelector('.dashboard-grid')) {{
        const dashboardGrid = document.createElement('section');
        dashboardGrid.className = 'dashboard-grid';
        chartSection.before(dashboardGrid);
        dashboardGrid.appendChild(chartSection);
        dashboardGrid.appendChild(riskPanel);
        const miniTables = document.createElement('section');
        miniTables.className = 'mini-tables';
        miniTables.innerHTML = `
          <div class="panel">
            <div class="section-title"><h2>عائد السنوات</h2><span>منحنى المحفظة</span></div>
            <table class="compact-table"><thead><tr><th>الفترة</th><th>الافتتاح</th><th>الإغلاق</th><th>الربح</th><th>العائد</th></tr></thead><tbody>{year_return_table}</tbody></table>
          </div>
          <div class="panel">
            <div class="section-title"><h2>أفضل الأشهر</h2><span>حسب ربح المحفظة</span></div>
            <table class="compact-table"><thead><tr><th>الفترة</th><th>الافتتاح</th><th>الإغلاق</th><th>الربح</th><th>العائد</th></tr></thead><tbody>{month_return_table}</tbody></table>
          </div>`;
        dashboardGrid.after(miniTables);
        const openTitle = document.createElement('div');
        openTitle.className = 'section-title';
        openTitle.innerHTML = '<h2>الصفقات المفتوحة</h2><span>الأهم للمتابعة اليومية</span>';
        const openSection = document.createElement('section');
        openSection.className = 'open-positions';
        openSection.innerHTML = `{open_cards}`;
        miniTables.after(openTitle, openSection);
        const settingsDetails = document.querySelector('details.settings');
        if (settingsDetails) openSection.after(settingsDetails);
      }}
      const tradeHeading = [...document.querySelectorAll('h2')].find(item => item.nextElementSibling && item.nextElementSibling.classList.contains('quick'));
      if (tradeHeading) tradeHeading.textContent = 'سجل الصفقات الكامل';
      const firstStats = document.querySelectorAll('.stats .stat');
      if (firstStats[3]) firstStats[3].classList.add('primary');
      if (firstStats[4]) firstStats[4].classList.add('primary');
      if (firstStats[5]) firstStats[5].classList.add('primary');
    }}
    function setSignedClass(element, value) {{
      element.classList.toggle('positive', value >= 0);
      element.classList.toggle('negative', value < 0);
    }}
    function riskCards() {{
      return [...document.querySelectorAll('.risk-card strong')];
    }}
    function setRiskCard(index, value, formatter, signed=false) {{
      const cards = riskCards();
      const item = cards[index];
      if (!item) return;
      item.textContent = formatter(value);
      if (signed) setSignedClass(item, value);
    }}
    function maxDrawdownForRows(rows, opening) {{
      let peak = opening;
      let worst = 0;
      for (const item of rows) {{
        const value = Number(item.value);
        peak = Math.max(peak, value);
        if (peak > 0) worst = Math.min(worst, (value / peak - 1) * 100);
      }}
      return worst;
    }}
    function filteredChartRows() {{
      const year = yearFilter.value;
      const month = monthFilter.value;
      return data.filter(item => (year === 'all' || item.date.slice(0, 4) === year) && (month === 'all' || item.date.slice(5, 7) === month));
    }}
    function selectedPeriodContext() {{
      const rows = filteredChartRows();
      if (!rows.length) {{
        const fallback = data.length ? Number(data[data.length - 1].value) : settings.initial_capital;
        return {{ rows, opening: fallback, closing: fallback, startDate: null, endDate: null }};
      }}
      const firstDate = rows[0].date;
      const previousRows = data.filter(item => item.date < firstDate);
      const opening = previousRows.length ? Number(previousRows[previousRows.length - 1].value) : settings.initial_capital;
      const closing = Number(rows[rows.length - 1].value);
      return {{
        rows,
        opening,
        closing,
        startDate: new Date(firstDate + 'T00:00:00'),
        endDate: new Date(rows[rows.length - 1].date + 'T00:00:00')
      }};
    }}
    function updateDashboardStats(visibleRows) {{
      const stats = document.querySelectorAll('.stats .stat strong');
      const realized = visibleRows.filter(row => row.dataset.status === 'CLOSED').reduce((sum, row) => sum + Number(row.dataset.pnl || 0), 0);
      const unrealized = visibleRows.filter(row => row.dataset.status === 'OPEN').reduce((sum, row) => sum + Number(row.dataset.pnl || 0), 0);
      const openCount = visibleRows.filter(row => row.dataset.status === 'OPEN').length;
      const closedRows = visibleRows.filter(row => row.dataset.status === 'CLOSED');
      const winRows = closedRows.filter(row => Number(row.dataset.pnl || 0) >= 0);
      const lossRows = closedRows.filter(row => Number(row.dataset.pnl || 0) < 0);
      const wins = winRows.length;
      const losses = lossRows.length;
      const filteredTradePnl = visibleRows.reduce((sum, row) => sum + Number(row.dataset.pnl || 0), 0);
      const period = selectedPeriodContext();
      const hasTradeScopeFilter = (tradeSearch.value || '').trim() || activeFilter !== 'all' || quickFilter !== 'all';
      const value = hasTradeScopeFilter ? period.opening + filteredTradePnl : period.closing;
      const pnl = value - period.opening;
      const periodReturn = value > 0 && period.opening > 0 ? ((value / period.opening) - 1) * 100 : -100;
      if (stats[0]) stats[0].textContent = moneyFmt.format(period.opening);
      if (stats[3]) stats[3].textContent = moneyFmt.format(value);
      if (stats[4]) {{ stats[4].textContent = moneyFmt.format(pnl); setSignedClass(stats[4], pnl); }}
      if (stats[5]) {{ stats[5].textContent = `${{periodReturn.toFixed(2)}}%`; setSignedClass(stats[5], periodReturn); }}
      if (stats[7]) {{ stats[7].textContent = moneyFmt.format(realized); setSignedClass(stats[7], realized); }}
      if (stats[8]) {{ stats[8].textContent = moneyFmt.format(unrealized); setSignedClass(stats[8], unrealized); }}
      if (stats[9]) stats[9].textContent = openCount;
      if (stats[10]) stats[10].textContent = closedRows.length;
      if (stats[11]) stats[11].textContent = wins;
      if (stats[12]) stats[12].textContent = losses;
      const grossWin = winRows.reduce((sum, row) => sum + Number(row.dataset.pnl || 0), 0);
      const grossLoss = Math.abs(lossRows.reduce((sum, row) => sum + Number(row.dataset.pnl || 0), 0));
      const profitFactorPeriod = grossLoss ? grossWin / grossLoss : (grossWin ? Infinity : 0);
      const winRatePeriod = closedRows.length ? wins / closedRows.length * 100 : 0;
      const drawdownPeriod = maxDrawdownForRows(period.rows, period.opening);
      const largestLossPeriod = lossRows.reduce((min, row) => Math.min(min, Number(row.dataset.pnl || 0)), 0);
      const avgWinPeriod = wins ? grossWin / wins : 0;
      const avgLossPeriod = losses ? grossLoss / losses : 0;
      const avgWinPctPeriod = wins ? winRows.reduce((sum, row) => sum + Number(row.dataset.pnlPct || 0), 0) / wins : 0;
      const avgLossPctPeriod = losses ? lossRows.reduce((sum, row) => sum + Number(row.dataset.pnlPct || 0), 0) / losses : 0;
      const openRows = visibleRows.filter(row => row.dataset.status === 'OPEN');
      const largestOpen = openRows.reduce((max, row) => Math.max(max, Number(row.dataset.marketValue || 0)), 0);
      const concentrationPeriod = value ? largestOpen / value * 100 : 0;
      const avgLiquidityPeriod = visibleRows.length
        ? visibleRows.reduce((sum, row) => {{
            const cap = Number(row.dataset.capital || 0);
            const liquidity = Number(row.dataset.liquidityCap || 0);
            return sum + (liquidity ? cap / liquidity * 100 : 0);
          }}, 0) / visibleRows.length
        : 0;
      setRiskCard(0, profitFactorPeriod, value => Number.isFinite(value) ? value.toFixed(2) : '∞');
      setRiskCard(1, winRatePeriod, value => `${{value.toFixed(2)}}%`);
      setRiskCard(2, drawdownPeriod, value => `${{value.toFixed(2)}}%`, true);
      setRiskCard(3, largestLossPeriod, value => moneyFmt.format(value), true);
      setRiskCard(4, avgWinPeriod, value => moneyFmt.format(value), true);
      setRiskCard(5, avgLossPeriod, value => moneyFmt.format(value));
      setRiskCard(6, avgWinPctPeriod, value => `${{value.toFixed(2)}}%`, true);
      setRiskCard(7, avgLossPctPeriod, value => `${{value.toFixed(2)}}%`, true);
      setRiskCard(8, concentrationPeriod, value => `${{value.toFixed(2)}}%`);
      setRiskCard(9, avgLiquidityPeriod, value => `${{value.toFixed(2)}}%`);
    }}
    function aggregate(mode) {{
      const map = new Map();
      for (const item of data) {{
        let key = item.date;
        if (mode === 'weekly') {{
          const d = new Date(item.date + 'T00:00:00');
          const first = new Date(d.getFullYear(), 0, 1);
          const week = Math.ceil((((d - first) / 86400000) + first.getDay() + 1) / 7);
          key = `${{d.getFullYear()}}-W${{String(week).padStart(2, '0')}}`;
        }}
        if (mode === 'monthly') key = item.date.slice(0, 7);
        map.set(key, {{ date: key, value: Number(item.value) }});
      }}
      return [...map.values()];
    }}
    function draw(mode) {{
      let rows = aggregate(mode);
      const selectedYear = yearFilter ? yearFilter.value : 'all';
      const selectedMonth = monthFilter ? monthFilter.value : 'all';
      rows = rows.filter(item => (selectedYear === 'all' || item.date.slice(0, 4) === selectedYear) && (selectedMonth === 'all' || item.date.slice(5, 7) === selectedMonth));
      if (!rows.length) {{
        svg.innerHTML = '<text x="500" y="155" text-anchor="middle" fill="#65717d">لا توجد بيانات لهذه الفترة</text>';
        return;
      }}
      const width = 1000, height = 310, left = 92, right = 118, top = 28, bottom = 62;
      svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
      const values = rows.map(d => Number(d.value));
      const period = selectedPeriodContext();
      const openingBalance = period.opening;
      const rawMin = Math.min(...values, openingBalance);
      const rawMax = Math.max(...values, openingBalance);
      const pad = Math.max(500, (rawMax - rawMin) * 0.12);
      const min = Math.max(0, rawMin - pad);
      const max = rawMax + pad;
      const x = i => left + i * (width - left - right) / Math.max(rows.length - 1, 1);
      const y = v => height - bottom - ((v - min) / Math.max(max - min, 1)) * (height - top - bottom);
      const points = rows.map((d, i) => `${{x(i)}},${{y(Number(d.value))}}`).join(' ');
      const monthNames = ['ينا','فبر','مار','أبر','مايو','يون','يول','أغس','سبت','أكت','نوف','ديس'];
      const tickIndexes = [];
      if (mode === 'daily') {{
        const seen = new Set();
        rows.forEach((d, i) => {{ const key = d.date.slice(0, 7); if (!seen.has(key)) {{ seen.add(key); tickIndexes.push(i); }} }});
      }} else if (mode === 'weekly') {{
        rows.forEach((d, i) => {{ if (i === 0 || i === rows.length - 1 || i % 4 === 0) tickIndexes.push(i); }});
      }} else {{
        rows.forEach((d, i) => tickIndexes.push(i));
      }}
      const ticks = tickIndexes.map(i => {{
        const d = rows[i];
        const label = mode === 'weekly' ? d.date.replace('-', ' ') : `${{monthNames[Number(d.date.slice(5,7))-1] || d.date}} ${{d.date.slice(2,4)}}`;
        return `<line x1="${{x(i)}}" y1="${{top}}" x2="${{x(i)}}" y2="${{height-bottom}}" stroke="#f0f3f6"/><text x="${{x(i)}}" y="${{height-18}}" text-anchor="middle" fill="#65717d" font-size="12">${{label}}</text>`;
      }}).join('');
      const gridVals = [min, min + (max-min)*0.25, min + (max-min)*0.5, min + (max-min)*0.75, max];
      const grid = gridVals.map(v => `<line x1="${{left}}" y1="${{y(v)}}" x2="${{width-right}}" y2="${{y(v)}}" stroke="#edf1f5"/><text x="${{left-10}}" y="${{y(v)+4}}" text-anchor="end" fill="#65717d" font-size="12">$${{v.toFixed(0)}}</text>`).join('');
      const baseY = y(openingBalance);
      svg.innerHTML = `${{grid}}${{ticks}}<line x1="${{left}}" y1="${{height-bottom}}" x2="${{width-right}}" y2="${{height-bottom}}" stroke="#d9e1e8"/><line x1="${{left}}" y1="${{top}}" x2="${{left}}" y2="${{height-bottom}}" stroke="#d9e1e8"/><line x1="${{left}}" y1="${{baseY}}" x2="${{width-right}}" y2="${{baseY}}" stroke="#a8b3bd" stroke-dasharray="6 5"/><polyline points="${{points}}" fill="none" stroke="#1d5f8f" stroke-width="3"/><circle cx="${{x(rows.length-1)}}" cy="${{y(values[values.length-1])}}" r="5" fill="#176b4d"/><text x="${{left}}" y="18" fill="#17212b">$${{values[0].toFixed(0)}} · ${{rows[0].date}}</text><text x="${{width-18}}" y="18" text-anchor="end" fill="#17212b">$${{values[values.length-1].toFixed(0)}} · ${{rows[rows.length-1].date}}</text>`;
    }}
    reshapeDashboard();
    tabButtons.forEach(button => button.addEventListener('click', () => {{ tabButtons.forEach(item => item.classList.remove('active')); button.classList.add('active'); currentChartMode = button.dataset.mode; draw(currentChartMode); }}));
    function applyTradeFilters() {{
      const search = (tradeSearch.value || '').trim().toLowerCase();
      const year = yearFilter.value;
      const month = monthFilter.value;
      const visibleRows = [];
      document.querySelectorAll('tbody tr[data-ticker]').forEach(row => {{
        const text = row.innerText.toLowerCase();
        const baseOk = activeFilter === 'all' || row.dataset.ticker === activeFilter || row.dataset.behavior === activeFilter || row.dataset.version === activeFilter;
        let quickOk = quickFilter === 'all' || row.dataset.status === quickFilter;
        if (quickFilter === 'loss') quickOk = row.dataset.status === 'CLOSED' && row.dataset.pnlKind === 'loss';
        if (quickFilter === 'win') quickOk = row.dataset.status === 'CLOSED' && row.dataset.pnlKind === 'win';
        const yearOk = year === 'all' || row.dataset.year === year;
        const monthOk = month === 'all' || row.dataset.month === month;
        const searchOk = !search || text.includes(search);
        const visible = baseOk && quickOk && yearOk && monthOk && searchOk;
        row.style.display = visible ? '' : 'none';
        if (visible) visibleRows.push(row);
      }});
      updateDashboardStats(visibleRows);
      draw(currentChartMode);
    }}
    filterButtons.forEach(button => button.addEventListener('click', () => {{
      filterButtons.forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      activeFilter = button.dataset.filter;
      applyTradeFilters();
    }}));
    document.querySelectorAll('.quick button[data-quick]').forEach(button => button.addEventListener('click', () => {{
      document.querySelectorAll('.quick button[data-quick]').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      quickFilter = button.dataset.quick;
      applyTradeFilters();
    }}));
    tradeSearch.addEventListener('input', applyTradeFilters);
    yearFilter.addEventListener('change', applyTradeFilters);
    monthFilter.addEventListener('change', applyTradeFilters);
    document.getElementById('clearTradeFilters').addEventListener('click', () => {{
      activeFilter = 'all';
      quickFilter = 'all';
      tradeSearch.value = '';
      yearFilter.value = 'all';
      monthFilter.value = 'all';
      filterButtons.forEach(item => item.classList.toggle('active', item.dataset.filter === 'all'));
      document.querySelectorAll('.quick button[data-quick]').forEach(item => item.classList.remove('active'));
      applyTradeFilters();
    }});
    document.getElementById('settingsForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const status = document.getElementById('settingsStatus');
      if (!localControlAvailable) {{
        status.textContent = 'التعديل اليدوي يعمل من النسخة المحلية فقط. الرابط المنشور للعرض ويتحدث تلقائيا كل ساعة من جهاز مصدر البيانات.';
        return;
      }}
      status.textContent = 'جاري الحفظ وإعادة بناء المحفظة...';
      const payload = {{
        initial_capital: Number(document.getElementById('initialCapital').value),
        position_cap_pct: Number(document.getElementById('positionCap').value) / 100,
        max_trade_adv_pct: Number(document.getElementById('liquidityPct').value) / 100,
        liquidity_lookback_days: Number(document.getElementById('liquidityLookback').value),
        trailing_stop_step_pct: Number(document.getElementById('trailingStep').value),
        min_acceptable_annual_return_pct: Number(document.getElementById('minAnnualReturn').value),
        portfolio_universe: settings.portfolio_universe
      }};
      try {{
        const response = await fetch(`${{localApi}}/settings`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }});
        if (!response.ok) throw new Error('save failed');
        status.textContent = 'تم الحفظ والتحديث والنشر. جاري إعادة تحميل الصفحة بالنتائج الجديدة...';
        window.setTimeout(() => window.location.reload(), 700);
      }} catch (error) {{
        status.textContent = 'خادم إعدادات V2 غير شغال على هذا الجهاز. شغل settings_server_v2.py ثم أعد المحاولة من النسخة المحلية.';
      }}
    }});
    document.getElementById('refreshDataBtn').addEventListener('click', async () => {{
      const status = document.getElementById('settingsStatus');
      if (!localControlAvailable) {{
        status.textContent = 'زر التحديث اليدوي يعمل من النسخة المحلية فقط. الرابط المنشور للعرض، أما التحديث التلقائي فيعمل كل ساعة من جهاز مصدر البيانات.';
        return;
      }}
      status.textContent = 'جاري سحب بيانات السوق وإعادة بناء الداشبورد والنشر...';
      try {{
        const response = await fetch(`${{localApi}}/refresh`, {{ method: 'POST' }});
        if (!response.ok) throw new Error('refresh failed');
        status.textContent = 'تم سحب البيانات وإعادة البناء والنشر. جاري إعادة تحميل الصفحة بالنتائج الجديدة...';
        window.setTimeout(() => window.location.reload(), 700);
      }} catch (error) {{
        status.textContent = 'خادم تحديث V2 غير شغال على هذا الجهاز. شغل settings_server_v2.py ثم أعد المحاولة من النسخة المحلية.';
      }}
    }});
    applyTradeFilters();
  </script>
</body>
</html>"""


def main() -> int:
    strategies, quality_gate = selected_portfolio_strategies()
    state = simulate_portfolio(strategies, quality_gate)
    write_csv(TRADES_CSV, state["trades"])
    write_csv(EQUITY_CSV, state["snapshots"])
    write_csv(QUALITY_GATE_CSV, state["quality_gate"])
    write_csv(BENCHMARK_COMPARISON_CSV, comparison_rows(state["trades"]))
    from financial_diagnostics_lab import main as build_financial_diagnostics
    from dashboard_financial_overlay_preview import (
        apply_analytics_financial_overlay,
        apply_dashboard_financial_overlay,
        load_payload as load_financial_payload,
    )
    from business_intelligence_overlay_preview import (
        apply_analytics_bi_overlay,
        apply_dashboard_bi_overlay,
    )

    build_financial_diagnostics()
    from business_intelligence_lab import build_payload as build_business_intelligence_payload
    from business_intelligence_lab import main as build_business_intelligence

    build_business_intelligence()
    financial_payload = load_financial_payload()
    business_payload = build_business_intelligence_payload()
    dashboard_html = apply_dashboard_financial_overlay(render_dashboard(state), financial_payload)
    dashboard_html = apply_dashboard_bi_overlay(dashboard_html, business_payload)
    DASHBOARD.write_text(dashboard_html, encoding="utf-8")
    ANALYTICS_DASHBOARD.write_text(render_analytics_dashboard(state), encoding="utf-8")
    from experimental_decision_center import main as build_decision_analytics

    build_decision_analytics()
    analytics_html = ANALYTICS_DASHBOARD.read_text(encoding="utf-8")
    analytics_html = apply_analytics_financial_overlay(analytics_html, financial_payload)
    analytics_html = apply_analytics_bi_overlay(analytics_html, business_payload)
    ANALYTICS_DASHBOARD.write_text(analytics_html, encoding="utf-8")
    print(f"Portfolio value: {portfolio_value(state):.2f}")
    print(f"Trades: {len(state['trades'])}")
    print(f"Approved strategies: {sum(1 for row in state['quality_gate'] if row.get('approved'))}")
    print(f"Rejected strategies: {sum(1 for row in state['quality_gate'] if not row.get('approved'))}")
    print(f"Dashboard: {DASHBOARD}")
    print(f"Analytics: {ANALYTICS_DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
