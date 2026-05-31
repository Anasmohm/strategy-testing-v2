#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import html
from pathlib import Path
from typing import Any

import eodhd_official_data as eodhd
import paper_portfolio_v2 as v2
import paper_portfolio_v31 as v31
import test_profit_protection_v31 as lab


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
REPORT_HTML = REPORTS / "experimental_five_year_high_trailing_v31.html"
SUMMARY_CSV = REPORTS / "experimental_five_year_high_trailing_v31_summary.csv"
TRAINING_CSV = REPORTS / "experimental_five_year_high_trailing_v31_training.csv"
TICKER_CSV = REPORTS / "experimental_five_year_high_trailing_v31_by_ticker.csv"
TIMEFRAME_CSV = REPORTS / "experimental_five_year_high_trailing_v31_by_timeframe.csv"
COVERAGE_CSV = REPORTS / "experimental_five_year_high_trailing_v31_coverage.csv"

TRADING_START = "2021-01-01"
TRAINING_END = "2021-12-31"
OUT_OF_SAMPLE_START = "2022-01-01"
REQUIRED_DAILY_START = "2020-01-02"
STEPS = [0.5, 1.0, 1.5, 1.8, 2.0, 3.0, 4.0, 5.0]


def fnum(value: Any) -> float:
    return float(value or 0)


def key_for_step(step: float) -> str:
    return str(step).replace(".", "_")


def next_session_policy(step: float) -> lab.Policy:
    return lab.Policy(
        f"next_high_{key_for_step(step)}",
        f"أعلى اليوم ثم تفعيل الجلسة التالية: درجة {step:g} بالمئة",
        "step",
        step_pct=step,
        update_timing="daily_high_next_session",
    )


def current_policy() -> lab.Policy:
    return lab.Policy("current", "الحالي: رفع داخل الجلسة بدرجة 1 بالمئة", "step", step_pct=1.0)


def former_best_policy() -> lab.Policy:
    return lab.Policy("intraday_1_8", "المقارنة السابقة: رفع داخل الجلسة بدرجة 1.8 بالمئة", "step", step_pct=1.8)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def data_coverage(strategies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    tickers = sorted({str(strategy["ticker"]) for strategy in strategies} | {"SPY", "QQQ", "SOXX"})
    session_sets: dict[str, set[str]] = {}
    rows: list[dict[str, Any]] = []
    latest_dates: list[str] = []
    for ticker in tickers:
        daily = eodhd.read_daily_bars(ticker)
        sessions = eodhd.intraday_by_date(ticker)
        execution_dates = {date_value for date_value in sessions if date_value >= TRADING_START}
        session_sets[ticker] = execution_dates
        latest_dates.append(max(execution_dates))
        bad_sessions = [
            date_value
            for date_value, bars in sessions.items()
            if date_value >= TRADING_START
            and len(bars) < 70
            and dt.date.fromisoformat(date_value) not in eodhd.provider.EARLY_CLOSE_DATES
        ]
        rows.append(
            {
                "symbol": ticker,
                "daily_first_date": daily[0].date,
                "execution_first_date": min(execution_dates),
                "execution_last_date": max(execution_dates),
                "execution_sessions": len(execution_dates),
                "unexpected_partial_sessions": len(bad_sessions),
            }
        )
        if daily[0].date > REQUIRED_DAILY_START:
            raise RuntimeError(f"Daily indicator warmup is insufficient for {ticker}: {daily[0].date}.")
        if min(execution_dates) > "2021-01-04" or bad_sessions:
            raise RuntimeError(f"Five-minute execution coverage is incomplete for {ticker}.")
    reference_dates = session_sets["SPY"]
    mismatched = [ticker for ticker, dates in session_sets.items() if dates != reference_dates]
    if mismatched:
        raise RuntimeError(f"Execution trading dates do not match SPY for: {', '.join(mismatched)}.")
    return rows, min(latest_dates)


def result(
    key: str,
    label: str,
    state: dict[str, Any],
    period: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    trades = state["trades"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if v2.trade_pnl(trade) >= 0]
    losses = [trade for trade in closed if v2.trade_pnl(trade) < 0]
    value = v2.portfolio_value(state)
    drawdown = v2.max_drawdown(state["snapshots"])
    years = max((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days / 365.25, 1 / 365.25)
    return {
        "period": period,
        "start_date": start,
        "end_date": end,
        "key": key,
        "label": label,
        "portfolio_value": round(value, 2),
        "pnl": round(value - v2.INITIAL_CAPITAL, 2),
        "period_return_pct": round((value / v2.INITIAL_CAPITAL - 1) * 100, 2),
        "annual_return_pct": round(((value / v2.INITIAL_CAPITAL) ** (1 / years) - 1) * 100, 2),
        "max_drawdown_pct": round(fnum(drawdown.get("drawdown")), 2),
        "trades": len(trades),
        "closed": len(closed),
        "open": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "avg_win_pct": round(sum(v2.trade_pnl_pct(trade) for trade in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(sum(v2.trade_pnl_pct(trade) for trade in losses) / len(losses), 2) if losses else 0.0,
    }


def grouped_stats(current: dict[str, Any], candidate: dict[str, Any], field: str) -> list[dict[str, Any]]:
    groups = sorted(
        {str(trade.get(field, "")) for trade in current["trades"]}
        | {str(trade.get(field, "")) for trade in candidate["trades"]}
    )
    rows: list[dict[str, Any]] = []
    for group in groups:
        old = [trade for trade in current["trades"] if str(trade.get(field, "")) == group]
        new = [trade for trade in candidate["trades"] if str(trade.get(field, "")) == group]
        closed = [trade for trade in new if trade.get("status") == "CLOSED"]
        wins = [trade for trade in closed if v2.trade_pnl(trade) >= 0]
        losses = [trade for trade in closed if v2.trade_pnl(trade) < 0]
        old_pnl = round(sum(v2.trade_pnl(trade) for trade in old), 2)
        new_pnl = round(sum(v2.trade_pnl(trade) for trade in new), 2)
        rows.append(
            {
                "group": group or "غير محدد",
                "current_pnl": old_pnl,
                "candidate_pnl": new_pnl,
                "delta_pnl": round(new_pnl - old_pnl, 2),
                "candidate_trades": len(new),
                "candidate_wins": len(wins),
                "candidate_losses": len(losses),
            }
        )
    return sorted(rows, key=lambda row: fnum(row["delta_pnl"]), reverse=True)


def money(value: Any) -> str:
    return f'<span class="num">${fnum(value):,.2f}</span>'


def pct(value: Any) -> str:
    return f'<span class="num">{fnum(value):,.2f}%</span>'


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def rows_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"""<tr class="{"selected" if row["key"] == "selected" else ""}">
        <td>{html.escape(str(row["label"]))}</td><td>{money(row["portfolio_value"])}</td>
        <td class="{tone(row["period_return_pct"])}">{pct(row["period_return_pct"])}</td>
        <td>{pct(row["annual_return_pct"])}</td><td class="negative">{pct(row["max_drawdown_pct"])}</td>
        <td>{row["trades"]}</td><td>{row["wins"]} / {row["losses"]}</td><td>{pct(row["win_rate"])}</td></tr>"""
        for row in rows
    )
    return f"""<table><thead><tr><th>السياسة</th><th>قيمة المحفظة</th><th>عائد الفترة</th><th>العائد السنوي المركب</th><th>السحب الأقصى</th><th>الصفقات</th><th>رابحة / خاسرة</th><th>نسبة الفوز</th></tr></thead><tbody>{body}</tbody></table>"""


def group_table(rows: list[dict[str, Any]], title: str) -> str:
    body = "".join(
        f"""<tr><td>{html.escape(str(row["group"]))}</td><td>{money(row["current_pnl"])}</td>
        <td class="{tone(row["candidate_pnl"])}">{money(row["candidate_pnl"])}</td>
        <td class="{tone(row["delta_pnl"])}">{money(row["delta_pnl"])}</td>
        <td>{row["candidate_trades"]}</td><td>{row["candidate_wins"]} / {row["candidate_losses"]}</td></tr>"""
        for row in rows
    )
    return f"""<section class="panel"><h2>{title}</h2><table><thead><tr><th>التصنيف</th><th>ربح الحالي</th><th>ربح المرشح</th><th>الفرق</th><th>الصفقات</th><th>رابحة / خاسرة</th></tr></thead><tbody>{body}</tbody></table></section>"""


def render(
    step: float,
    latest: str,
    coverage: list[dict[str, Any]],
    training: list[dict[str, Any]],
    annual: dict[str, list[dict[str, Any]]],
    cumulative: list[dict[str, Any]],
    out_of_sample: list[dict[str, Any]],
    ticker_rows: list[dict[str, Any]],
    timeframe_rows: list[dict[str, Any]],
) -> str:
    selected_full = next(row for row in cumulative if row["key"] == "selected")
    current_full = next(row for row in cumulative if row["key"] == "current")
    selected_oos = next(row for row in out_of_sample if row["key"] == "selected")
    current_oos = next(row for row in out_of_sample if row["key"] == "current")
    annual_wins = sum(
        next(row for row in rows if row["key"] == "selected")["portfolio_value"]
        > next(row for row in rows if row["key"] == "current")["portfolio_value"]
        for rows in annual.values()
    )
    coverage_body = "".join(
        f"<tr><td>{row['symbol']}</td><td><span class='num'>{row['daily_first_date']}</span></td><td><span class='num'>{row['execution_first_date']}</span></td><td>{row['execution_sessions']}</td><td>{row['unexpected_partial_sessions']}</td></tr>"
        for row in coverage
    )
    annual_sections = "".join(
        f"<section class='panel'><h2>اختبار مستقل: عام {year}</h2>{rows_table(rows)}</section>"
        for year, rows in annual.items()
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>اختبار خمس سنوات لوقف أعلى اليوم</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7fa;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1450px;margin:auto;padding:28px}}h1{{font-size:30px;margin:0 0 8px}}h2{{font-size:21px;margin:0 0 14px}}p{{color:#586f84;line-height:1.9}}
.notice{{background:#fff5df;border:1px solid #dfb251;border-radius:8px;padding:14px 18px;margin:18px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}.card,.panel{{background:#fff;border:1px solid #d6e1ea;border-radius:8px;padding:18px;margin:14px 0;overflow:auto}}
.card label{{display:block;color:#647c90;margin-bottom:9px}}.card strong{{display:block;font-size:27px}}.card small{{color:#61788d;line-height:1.8}}
.num{{direction:ltr;unicode-bidi:isolate;display:inline-block}}.positive{{color:#087852}}.negative{{color:#ad3737}}
table{{width:100%;border-collapse:collapse;min-width:850px}}th,td{{padding:12px 10px;border-bottom:1px solid #e2eaf2;text-align:right;vertical-align:top}}th{{background:#eaf0f6;color:#29465e;white-space:nowrap}}
tr.selected{{background:#eaf7f1}}.decision{{border-right:4px solid #1771a8}}@media(max-width:970px){{.cards{{grid-template-columns:1fr 1fr}}}}@media(max-width:560px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap">
<h1>اختبار خمس سنوات لقاعدة وقف أعلى اليوم</h1>
<p>بداية المحاكاة الممتدة: <span class="num">2021-01-01</span>. بيانات المؤشرات مهيأة من عام <span class="num">2020</span>، وتنفيذ الوقف والهدف يستخدم خمس دقائق ابتداء من أول جلسة تداول في <span class="num">2021</span> وحتى <span class="num">{latest}</span>.</p>
<div class="notice">هذه نسخة اختبار ولم تغير المحفظة الرسمية بعد. اختيار الدرجة تم من عام <span class="num">2021</span> فقط، ثم اختبرت دون تعديل في السنوات اللاحقة.</div>
<div class="notice">تنبيه منهجي: هذا الاختبار يقيس سياسة الخروج على استراتيجيات <span class="num">V3.1</span> الحالية بعد تثبيتها. لا يعد اختبارا نهائيا لبناء الاستراتيجيات نفسها، لأنها صممت في مرحلة لاحقة وتحتاج إعادة تصميم زمنية منفصلة إذا أردنا اعتماد محفظة تبدأ فعليا من عام <span class="num">2021</span>.</div>
<section class="cards">
<article class="card"><label>الدرجة المختارة من 2021</label><strong><span class="num">{step:g}%</span></strong><small>أعلى اليوم ثم التفعيل في الجلسة التالية</small></article>
<article class="card"><label>المحاكاة الوصفية 2021 - 2026</label><strong class="positive">{pct(selected_full["period_return_pct"])}</strong><small>الحالي {pct(current_full["period_return_pct"])}</small></article>
<article class="card"><label>اختبار خارج الاختيار 2022 - 2026</label><strong class="positive">{pct(selected_oos["period_return_pct"])}</strong><small>الحالي {pct(current_oos["period_return_pct"])}</small></article>
<article class="card"><label>سنوات تفوق المرشح بعد التدريب</label><strong><span class="num">{annual_wins} / {len(annual)}</span></strong><small>مقارنة بالسياسة الحالية سنويًا</small></article>
</section>
<section class="panel decision"><h2>قراءة القرار</h2><p>المحاكاة الكاملة من <span class="num">2021</span> مفيدة لقياس شكل المحفظة لو طبقت القاعدة طوال المدة، لكنها تشمل سنة الاختيار. المقياس الأصدق للاعتماد هو الاختبار التراكمي من <span class="num">2022</span> فصاعدًا والنتائج السنوية المنفصلة.</p></section>
<section class="panel"><h2>تغطية البيانات</h2><table><thead><tr><th>الرمز</th><th>بداية المؤشرات اليومية</th><th>بداية تنفيذ خمس دقائق</th><th>جلسات التنفيذ</th><th>جلسات ناقصة غير متوقعة</th></tr></thead><tbody>{coverage_body}</tbody></table></section>
<section class="panel"><h2>اختيار الدرجة: عام 2021 فقط</h2>{rows_table(training)}</section>
<section class="panel"><h2>محفظة تراكمية وصفية: من 2021 حتى {latest}</h2>{rows_table(cumulative)}</section>
<section class="panel"><h2>اختبار تراكمي خارج الاختيار: من 2022 حتى {latest}</h2>{rows_table(out_of_sample)}</section>
{annual_sections}
{group_table(timeframe_rows, "تفصيل الاختبار التراكمي خارج الاختيار حسب الإطار")}
{group_table(ticker_rows, "تفصيل الاختبار التراكمي خارج الاختيار حسب السهم")}
</main></body></html>"""


def compare_states(
    strategies: list[dict[str, Any]],
    selected: lab.Policy,
    period: str,
    start: str,
    end: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    policies = [("current", current_policy()), ("intraday_1_8", former_best_policy()), ("selected", selected)]
    states: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for key, policy in policies:
        state = lab.simulate(strategies, policy, start, end)
        states[key] = state
        label = policy.label if key != "selected" else f"المختارة من 2021: أعلى اليوم ثم الجلسة التالية بدرجة {selected.step_pct:g} بالمئة"
        rows.append(result(key, label, state, period, start, end))
    return rows, states


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    coverage, latest = data_coverage(strategies)
    write_csv(COVERAGE_CSV, coverage)
    training: list[dict[str, Any]] = []
    for step in STEPS:
        policy = next_session_policy(step)
        state = lab.simulate(strategies, policy, TRADING_START, TRAINING_END)
        training.append(result(policy.key, policy.label, state, "2021 - اختيار", TRADING_START, TRAINING_END))
    selected_training = max(training, key=lambda row: fnum(row["portfolio_value"]))
    selected_step = next(step for step in STEPS if selected_training["key"] == next_session_policy(step).key)
    selected = next_session_policy(selected_step)
    write_csv(TRAINING_CSV, training)

    cumulative, _ = compare_states(strategies, selected, "2021-2026 وصفي", TRADING_START, latest)
    out_of_sample, oos_states = compare_states(strategies, selected, "2022-2026 خارج الاختيار", OUT_OF_SAMPLE_START, latest)
    annual: dict[str, list[dict[str, Any]]] = {}
    for year in ("2022", "2023", "2024", "2025"):
        annual[year], _ = compare_states(strategies, selected, year, f"{year}-01-01", f"{year}-12-31")
    annual["2026"], _ = compare_states(strategies, selected, "2026", "2026-01-01", latest)
    all_rows = training + cumulative + out_of_sample + [row for rows in annual.values() for row in rows]
    write_csv(SUMMARY_CSV, all_rows)

    timeframe_rows = grouped_stats(oos_states["current"], oos_states["selected"], "timeframe")
    ticker_rows = grouped_stats(oos_states["current"], oos_states["selected"], "ticker")
    write_csv(TIMEFRAME_CSV, timeframe_rows)
    write_csv(TICKER_CSV, ticker_rows)
    REPORT_HTML.write_text(
        render(selected_step, latest, coverage, training, annual, cumulative, out_of_sample, ticker_rows, timeframe_rows),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Selected from 2021: {selected_step:g}%")
    for row in cumulative:
        print(f"Full {row['key']}: value=${fnum(row['portfolio_value']):,.2f}; return={fnum(row['period_return_pct']):,.2f}%; drawdown={fnum(row['max_drawdown_pct']):,.2f}%")
    for row in out_of_sample:
        print(f"OOS {row['key']}: value=${fnum(row['portfolio_value']):,.2f}; return={fnum(row['period_return_pct']):,.2f}%; drawdown={fnum(row['max_drawdown_pct']):,.2f}%")
    print(f"Report: {REPORT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
