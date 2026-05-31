#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import math
from pathlib import Path
from typing import Any

import paper_portfolio_v2 as v2
import paper_portfolio_v3_rebuild as v3
import paper_portfolio_v31 as v31


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
INTRADAY_ROOT = ROOT / "data" / "eodhd_private" / "historical_5m_rth_adjusted"
SUMMARY_CSV = REPORTS / "experimental_eodhd_5m_v31_summary.csv"
TICKER_CSV = REPORTS / "experimental_eodhd_5m_v31_by_ticker.csv"
TRADES_CSV = REPORTS / "experimental_eodhd_5m_v31_trades.csv"
EQUITY_CSV = REPORTS / "experimental_eodhd_5m_v31_equity_curve.csv"
CONSERVATIVE_TRADES_CSV = REPORTS / "experimental_eodhd_5m_next_bar_trades.csv"
CONSERVATIVE_EQUITY_CSV = REPORTS / "experimental_eodhd_5m_next_bar_equity_curve.csv"
REPORT_HTML = REPORTS / "experimental_eodhd_5m_v31_comparison.html"


def fnum(value: Any, default: float = 0.0) -> float:
    return v31.fnum(value, default)


def read_intraday(ticker: str) -> dict[str, list[dict[str, Any]]]:
    path = INTRADAY_ROOT / f"{ticker}_5m_rth_adjusted.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing experimental 5m data for {ticker}: {path}")
    grouped: dict[str, list[dict[str, Any]]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(row["date"], []).append(
                {
                    "datetime_utc": row["datetime_utc"],
                    "time_et": row["time_et"],
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
    return grouped


def simulate_with_5m_exits(
    strategies: list[dict[str, Any]], trailing_activation: str = "same_bar"
) -> tuple[dict[str, Any], dict[str, int]]:
    if trailing_activation not in {"same_bar", "next_bar"}:
        raise ValueError("trailing_activation must be same_bar or next_bar")
    tickers = sorted({str(strategy["ticker"]) for strategy in strategies})
    daily = {ticker: v2.read_bars(ticker) for ticker in tickers}
    index_maps = {ticker: {bar.date: idx for idx, bar in enumerate(bars)} for ticker, bars in daily.items()}
    intraday = {ticker: read_intraday(ticker) for ticker in tickers}
    market_cache = v3.build_market_cache()
    all_dates = sorted({bar.date for bars in daily.values() for bar in bars if bar.date >= v31.CONFIG["start_date"]})
    state: dict[str, Any] = {
        "initial_capital": v2.INITIAL_CAPITAL,
        "cash": v2.INITIAL_CAPITAL,
        "trades": [],
        "snapshots": [],
        "skipped": [],
        "quality_gate": [],
        "next_id": 1,
    }
    diagnostics = {
        "intraday_exit_trades": 0,
        "fallback_daily_sessions": 0,
        "same_5m_stop_target_ambiguities": 0,
        "same_5m_raised_stop_ambiguities": 0,
    }
    open_trades: list[dict[str, Any]] = []

    for current_date in all_dates:
        for trade in list(open_trades):
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or current_date <= str(trade["entry_date"]):
                continue
            day_bar = daily[ticker][idx]
            bars_5m = intraday[ticker].get(current_date, [])
            trade["held_sessions"] = int(trade.get("held_sessions", 0)) + 1
            if not bars_5m:
                diagnostics["fallback_daily_sessions"] += 1
                bars_5m = [
                    {
                        "datetime_utc": f"{current_date} daily",
                        "time_et": "daily",
                        "high": day_bar.high,
                        "low": day_bar.low,
                        "close": day_bar.close,
                    }
                ]
            closed_in_session = False
            for bar in bars_5m:
                prior_stop = fnum(trade["stop_price"])
                target = fnum(trade["exit_price"])
                if trailing_activation == "same_bar":
                    v2.update_trailing_stop(trade, fnum(bar["high"]))
                stop = fnum(trade["stop_price"])
                stop_hit = fnum(bar["low"]) <= stop
                target_hit = fnum(bar["high"]) >= target
                if stop_hit and target_hit:
                    diagnostics["same_5m_stop_target_ambiguities"] += 1
                if stop > prior_stop and stop_hit:
                    diagnostics["same_5m_raised_stop_ambiguities"] += 1
                if stop_hit:
                    outcome = "TRAILING_WIN" if stop >= fnum(trade["entry_price"]) else "LOSS"
                    v2.close_trade(state, trade, current_date, stop, "5m trailing/technical stop", outcome)
                    trade["close_time_et"] = str(bar["time_et"])
                    diagnostics["intraday_exit_trades"] += 1
                    open_trades.remove(trade)
                    closed_in_session = True
                    break
                if target_hit:
                    v2.close_trade(state, trade, current_date, target, "5m strategy target", "WIN")
                    trade["close_time_et"] = str(bar["time_et"])
                    diagnostics["intraday_exit_trades"] += 1
                    open_trades.remove(trade)
                    closed_in_session = True
                    break
                if trailing_activation == "next_bar":
                    v2.update_trailing_stop(trade, fnum(bar["high"]))
                    raised_stop = fnum(trade["stop_price"])
                    if raised_stop > prior_stop and fnum(bar["low"]) <= raised_stop:
                        diagnostics["same_5m_raised_stop_ambiguities"] += 1
            if closed_in_session:
                continue
            if int(trade["held_sessions"]) >= int(trade["hold_days"]):
                pnl_pct = (day_bar.close / fnum(trade["entry_price"]) - 1) * 100
                outcome = "TIMEOUT_WIN" if pnl_pct > 0 else "TIMEOUT_LOSS"
                v2.close_trade(state, trade, current_date, day_bar.close, "holding period ended", outcome)
                trade["close_time_et"] = "16:00"
                open_trades.remove(trade)

        for strategy in strategies:
            ticker = str(strategy["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or idx == 0:
                continue
            bars = daily[ticker]
            if not v31.hybrid_entry_signal(strategy, bars, idx, market_cache):
                continue
            duplicate = any(
                trade["status"] == "OPEN"
                and trade["ticker"] == ticker
                and trade.get("strategy_id") == strategy.get("strategy_id")
                for trade in open_trades
            )
            if duplicate:
                continue
            day_bar = bars[idx]
            cash = fnum(state["cash"])
            target_alloc = cash * v2.POSITION_CAP_PCT * min(fnum(strategy.get("size_multiplier"), 1.0), 1.0)
            adv = v2.avg_dollar_volume(bars, idx)
            liquidity_cap = adv * v2.MAX_TRADE_ADV_PCT if adv else target_alloc
            allocation = min(cash, target_alloc, liquidity_cap)
            shares = math.floor(allocation / day_bar.close) if day_bar.close > 0 else 0
            if shares <= 0:
                state["skipped"].append({"date": current_date, "ticker": ticker, "reason": "cash_or_liquidity_below_one_share"})
                continue
            entry = day_bar.close
            technical_stop = v31.stop_price(strategy, bars, idx)
            target = entry * (1 + fnum(strategy["target_pct"]) / 100)
            capital = shares * entry
            trade = {
                "id": f"E5M-{state['next_id']:04d}",
                "ticker": ticker,
                "strategy_source": strategy.get("strategy_source", ""),
                "strategy_id": strategy.get("strategy_id", ""),
                "behavior": strategy.get("behavior", ""),
                "entry_rule": strategy.get("entry_rule", ""),
                "timeframe": strategy.get("timeframe", ""),
                "selected_version": strategy.get("selected_version", ""),
                "status": "OPEN",
                "outcome": "OPEN",
                "entry_date": current_date,
                "entry_price": round(entry, 4),
                "shares": shares,
                "capital": round(capital, 2),
                "avg_dollar_volume": round(adv, 2),
                "liquidity_cap": round(liquidity_cap, 2),
                "technical_initial_stop_price": round(technical_stop, 4),
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

        for trade in open_trades:
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None:
                continue
            close = daily[ticker][idx].close
            market_value = int(trade["shares"]) * close
            trade["latest_price"] = round(close, 4)
            trade["market_value"] = round(market_value, 2)
            trade["unrealized_pnl"] = round(market_value - fnum(trade["capital"]), 2)
            trade["unrealized_pnl_pct"] = round((close / fnum(trade["entry_price"]) - 1) * 100, 2)
        state["snapshots"].append(
            {
                "date": current_date,
                "value": v2.portfolio_value(state),
                "cash": round(fnum(state["cash"]), 2),
                "open_trades": len(open_trades),
            }
        )
    return state, diagnostics


def by_ticker(state: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    results: dict[str, dict[str, float | int]] = {}
    for trade in state["trades"]:
        ticker = str(trade["ticker"])
        row = results.setdefault(ticker, {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
        pnl = v2.trade_pnl(trade)
        row["pnl"] = fnum(row["pnl"]) + pnl
        row["trades"] = int(row["trades"]) + 1
        if trade.get("status") == "CLOSED":
            if pnl >= 0:
                row["wins"] = int(row["wins"]) + 1
            else:
                row["losses"] = int(row["losses"]) + 1
    return results


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def ltr(value: str) -> str:
    return f"<span class='ltr'>{value}</span>"


def comparison_html(
    current: dict[str, Any],
    intraday: dict[str, Any],
    conservative: dict[str, Any],
    diagnostics: dict[str, int],
    conservative_diagnostics: dict[str, int],
    ticker_rows: list[dict[str, Any]],
) -> str:
    delta_value = fnum(intraday["portfolio_value"]) - fnum(current["portfolio_value"])
    delta_return = fnum(intraday["period_return_pct"]) - fnum(current["period_return_pct"])
    conservative_delta_value = fnum(conservative["portfolio_value"]) - fnum(current["portfolio_value"])
    rows = "".join(
        "<tr>"
        f"<td dir='ltr'>{html.escape(str(row['ticker']))}</td>"
        f"<td>{ltr(money(row['daily_pnl']))}</td><td>{ltr(money(row['five_min_pnl']))}</td>"
        f"<td class='{'pos' if fnum(row['pnl_delta']) >= 0 else 'neg'}'>{ltr(money(row['pnl_delta']))}</td>"
        f"<td>{ltr(money(row['conservative_pnl']))}</td>"
        f"<td class='{'pos' if fnum(row['conservative_delta']) >= 0 else 'neg'}'>{ltr(money(row['conservative_delta']))}</td>"
        f"<td>{ltr(f"{row['daily_trades']} / {row['five_min_trades']} / {row['conservative_trades']}")}</td>"
        f"<td>{ltr(f"{row['daily_losses']} / {row['five_min_losses']} / {row['conservative_losses']}")}</td>"
        "</tr>"
        for row in ticker_rows
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>مقارنة بيانات خمس دقائق - V3.1</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f4f7fb;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1250px;margin:auto;padding:28px}} h1{{font-size:29px;margin:0 0 8px}} .sub{{color:#607890;margin-bottom:22px}}
.banner{{background:#fff5de;border:1px solid #e7bd62;padding:14px 18px;border-radius:8px;margin-bottom:22px;line-height:1.8}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}} .card,.panel{{background:#fff;border:1px solid #d6e1ec;border-radius:8px;padding:18px}}
.card span{{display:block;color:#637b91;font-size:13px;margin-bottom:8px}} .card strong{{font-size:26px;direction:ltr;display:block}} .pos{{color:#087852}} .neg{{color:#b53434}}
.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}
table{{width:100%;border-collapse:collapse;background:#fff}} th,td{{padding:12px 10px;border-bottom:1px solid #e3eaf1;text-align:right}} th{{background:#eaf0f6;color:#23415d}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px}} .panel h2{{font-size:18px;margin:0 0 12px}}
.facts{{line-height:2;margin:0;padding:0 18px}} @media(max-width:850px){{.cards,.grid2{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap">
<h1>مقارنة المحفظة المعتمدة مع تنفيذ خمس دقائق</h1>
<p class="sub">تجربة مستقلة: الاستراتيجيات وإشارات الدخول والسيولة نفسها، والاختلاف فقط في فحص الوقف والهدف على بيانات EODHD بدقة خمس دقائق.</p>
<div class="banner">هذه النتيجة لا تستبدل الداشبورد المعتمد. بقي غموض محدود إذا تحقق الوقف والهدف داخل شمعة خمس دقائق نفسها.</div>
<section class="cards">
<article class="card"><span>قيمة النسخة اليومية</span><strong>{money(current['portfolio_value'])}</strong></article>
<article class="card"><span>خمس دقائق - نفس افتراض الوقف</span><strong class="{'pos' if delta_value >= 0 else 'neg'}">{money(intraday['portfolio_value'])}</strong></article>
<article class="card"><span>خمس دقائق - رفع الوقف من الشمعة التالية</span><strong class="{'pos' if conservative_delta_value >= 0 else 'neg'}">{money(conservative['portfolio_value'])}</strong></article>
<article class="card"><span>فرق العائد - نفس الافتراض</span><strong class="{'pos' if delta_return >= 0 else 'neg'}">{pct(delta_return)}</strong></article>
</section>
<section class="grid2">
<article class="panel"><h2>ملخص المقارنة</h2><table><tbody>
<tr><th>المعيار</th><th>اليومي المعتمد</th><th>5m نفس الافتراض</th><th>5m تحفظي</th></tr>
<tr><td>عائد الفترة</td><td>{ltr(pct(current['period_return_pct']))}</td><td>{ltr(pct(intraday['period_return_pct']))}</td><td>{ltr(pct(conservative['period_return_pct']))}</td></tr>
<tr><td>السحب الأقصى</td><td>{ltr(pct(current['max_drawdown_pct']))}</td><td>{ltr(pct(intraday['max_drawdown_pct']))}</td><td>{ltr(pct(conservative['max_drawdown_pct']))}</td></tr>
<tr><td>عدد الصفقات</td><td>{current['trades']}</td><td>{intraday['trades']}</td><td>{conservative['trades']}</td></tr>
<tr><td>الرابحة / الخاسرة</td><td>{ltr(f"{current['wins']} / {current['losses']}")}</td><td>{ltr(f"{intraday['wins']} / {intraday['losses']}")}</td><td>{ltr(f"{conservative['wins']} / {conservative['losses']}")}</td></tr>
<tr><td>نسبة الفوز</td><td>{ltr(pct(current['win_rate']))}</td><td>{ltr(pct(intraday['win_rate']))}</td><td>{ltr(pct(conservative['win_rate']))}</td></tr>
</tbody></table></article>
<article class="panel"><h2>جودة التنفيذ داخل اليوم</h2><ul class="facts">
<li>صفقات أغلقت باستخدام مسار خمس دقائق: {diagnostics['intraday_exit_trades']}</li>
<li>جلسات احتاجت رجوعًا لليومي: {diagnostics['fallback_daily_sessions']}</li>
<li>شموع خمس دقائق جمعت الوقف والهدف معًا: {diagnostics['same_5m_stop_target_ambiguities']}</li>
<li>شموع رفع فيها الوقف ثم ضرب داخل الشمعة نفسها: {diagnostics['same_5m_raised_stop_ambiguities']}</li>
<li>في المسار التحفظي، حالات غموض رفع الوقف التي تأجل تنفيذها: {conservative_diagnostics['same_5m_raised_stop_ambiguities']}</li>
</ul></article>
</section>
<section class="panel"><h2>الأثر حسب السهم</h2><table><thead><tr><th>السهم</th><th>ربح اليومي</th><th>ربح 5m</th><th>فرق 5m</th><th>ربح 5m التحفظي</th><th>فرق التحفظي</th><th>الصفقات يومي / 5m / تحفظي</th><th>الخاسرة يومي / 5m / تحفظي</th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    current_state = v31.simulate_hybrid_portfolio(strategies)
    intraday_state, diagnostics = simulate_with_5m_exits(strategies)
    conservative_state, conservative_diagnostics = simulate_with_5m_exits(strategies, trailing_activation="next_bar")
    current = v31.portfolio_summary(current_state, "V3.1 daily approved")
    intraday = v31.portfolio_summary(intraday_state, "V3.1 EODHD 5m same-bar trailing")
    conservative = v31.portfolio_summary(conservative_state, "V3.1 EODHD 5m next-bar trailing")
    summaries = [current, intraday, conservative]
    write_csv(SUMMARY_CSV, summaries)
    write_csv(TRADES_CSV, intraday_state["trades"])
    write_csv(EQUITY_CSV, intraday_state["snapshots"])
    write_csv(CONSERVATIVE_TRADES_CSV, conservative_state["trades"])
    write_csv(CONSERVATIVE_EQUITY_CSV, conservative_state["snapshots"])
    daily_tickers = by_ticker(current_state)
    five_tickers = by_ticker(intraday_state)
    conservative_tickers = by_ticker(conservative_state)
    ticker_rows: list[dict[str, Any]] = []
    for ticker in sorted(set(daily_tickers) | set(five_tickers) | set(conservative_tickers)):
        daily_row = daily_tickers.get(ticker, {})
        five_row = five_tickers.get(ticker, {})
        conservative_row = conservative_tickers.get(ticker, {})
        ticker_rows.append(
            {
                "ticker": ticker,
                "daily_pnl": round(fnum(daily_row.get("pnl")), 2),
                "five_min_pnl": round(fnum(five_row.get("pnl")), 2),
                "pnl_delta": round(fnum(five_row.get("pnl")) - fnum(daily_row.get("pnl")), 2),
                "conservative_pnl": round(fnum(conservative_row.get("pnl")), 2),
                "conservative_delta": round(fnum(conservative_row.get("pnl")) - fnum(daily_row.get("pnl")), 2),
                "daily_trades": int(daily_row.get("trades", 0)),
                "five_min_trades": int(five_row.get("trades", 0)),
                "conservative_trades": int(conservative_row.get("trades", 0)),
                "daily_losses": int(daily_row.get("losses", 0)),
                "five_min_losses": int(five_row.get("losses", 0)),
                "conservative_losses": int(conservative_row.get("losses", 0)),
            }
        )
    write_csv(TICKER_CSV, ticker_rows)
    REPORT_HTML.write_text(
        comparison_html(current, intraday, conservative, diagnostics, conservative_diagnostics, ticker_rows),
        encoding="utf-8",
    )
    result = {
        "current": current,
        "eodhd_5m": intraday,
        "eodhd_5m_conservative": conservative,
        "delta_value": round(fnum(intraday["portfolio_value"]) - fnum(current["portfolio_value"]), 2),
        "delta_return_points": round(fnum(intraday["period_return_pct"]) - fnum(current["period_return_pct"]), 2),
        "diagnostics": diagnostics,
        "conservative_diagnostics": conservative_diagnostics,
        "report": str(REPORT_HTML),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
