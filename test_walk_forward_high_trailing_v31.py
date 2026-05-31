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
SUMMARY_CSV = REPORTS / "experimental_walk_forward_high_trailing_v31_summary.csv"
TRAINING_CSV = REPORTS / "experimental_walk_forward_high_trailing_v31_training.csv"
TIMEFRAME_CSV = REPORTS / "experimental_walk_forward_high_trailing_v31_by_timeframe.csv"
TICKER_CSV = REPORTS / "experimental_walk_forward_high_trailing_v31_by_ticker.csv"
MONTH_CSV = REPORTS / "experimental_walk_forward_high_trailing_v31_by_month.csv"
REPORT_HTML = REPORTS / "experimental_walk_forward_high_trailing_v31.html"

TRAINING_START = "2024-01-01"
TRAINING_END = "2024-12-31"
TEST_2025_START = "2025-01-01"
TEST_2025_END = "2025-12-31"
TEST_2026_START = "2026-01-01"

STEP_VALUES = [0.5, 1.0, 1.5, 1.8, 2.0, 3.0, 4.0, 5.0]


def fnum(value: Any) -> float:
    return float(value or 0)


def step_key(step: float) -> str:
    return str(step).replace(".", "_")


def high_policy(step: float) -> lab.Policy:
    return lab.Policy(
        f"next_high_{step_key(step)}pct",
        f"أعلى اليوم ثم تفعيل الجلسة التالية: درجة {step:g} بالمئة",
        "step",
        step_pct=step,
        update_timing="daily_high_next_session",
    )


def latest_market_date(strategies: list[dict[str, Any]]) -> str:
    tickers = sorted({str(row["ticker"]) for row in strategies})
    latest_dates = [eodhd.read_daily_bars(ticker)[-1].date for ticker in tickers]
    return min(latest_dates)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summary_row(
    key: str,
    label: str,
    state: dict[str, Any],
    period: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    trades = state["trades"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if v2.trade_pnl(trade) >= 0]
    losses = [trade for trade in closed if v2.trade_pnl(trade) < 0]
    value = v2.portfolio_value(state)
    elapsed = max((dt.date.fromisoformat(end_date) - dt.date.fromisoformat(start_date)).days / 365.25, 1 / 365.25)
    annual_return = ((value / v2.INITIAL_CAPITAL) ** (1 / elapsed) - 1) * 100 if value > 0 else -100
    drawdown = v2.max_drawdown(state["snapshots"])
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "key": key,
        "label": label,
        "portfolio_value": round(value, 2),
        "pnl": round(value - v2.INITIAL_CAPITAL, 2),
        "period_return_pct": round((value / v2.INITIAL_CAPITAL - 1) * 100, 2),
        "annual_return_pct": round(annual_return, 2),
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


def grouped_trade_stats(
    current: dict[str, Any],
    candidate: dict[str, Any],
    period: str,
    field: str,
) -> list[dict[str, Any]]:
    groups = sorted(
        {str(trade.get(field, "")) for trade in current["trades"]}
        | {str(trade.get(field, "")) for trade in candidate["trades"]}
    )
    rows: list[dict[str, Any]] = []
    for group in groups:
        current_trades = [trade for trade in current["trades"] if str(trade.get(field, "")) == group]
        candidate_trades = [trade for trade in candidate["trades"] if str(trade.get(field, "")) == group]
        candidate_closed = [trade for trade in candidate_trades if trade.get("status") == "CLOSED"]
        wins = [trade for trade in candidate_closed if v2.trade_pnl(trade) >= 0]
        losses = [trade for trade in candidate_closed if v2.trade_pnl(trade) < 0]
        current_pnl = round(sum(v2.trade_pnl(trade) for trade in current_trades), 2)
        candidate_pnl = round(sum(v2.trade_pnl(trade) for trade in candidate_trades), 2)
        rows.append(
            {
                "period": period,
                "group": group or "غير محدد",
                "current_pnl": current_pnl,
                "candidate_pnl": candidate_pnl,
                "delta_pnl": round(candidate_pnl - current_pnl, 2),
                "candidate_trades": len(candidate_trades),
                "candidate_wins": len(wins),
                "candidate_losses": len(losses),
            }
        )
    return sorted(rows, key=lambda row: (row["period"], -fnum(row["delta_pnl"])))


def monthly_value_changes(state: dict[str, Any]) -> dict[str, float]:
    by_month: dict[str, list[dict[str, Any]]] = {}
    for snap in state["snapshots"]:
        by_month.setdefault(str(snap["date"])[:7], []).append(snap)
    prior_value = v2.INITIAL_CAPITAL
    changes: dict[str, float] = {}
    for month in sorted(by_month):
        close = fnum(by_month[month][-1]["value"])
        changes[month] = round(close - prior_value, 2)
        prior_value = close
    return changes


def month_comparison(current: dict[str, Any], candidate: dict[str, Any], period: str) -> list[dict[str, Any]]:
    current_months = monthly_value_changes(current)
    candidate_months = monthly_value_changes(candidate)
    return [
        {
            "period": period,
            "month": month,
            "current_change": current_months.get(month, 0.0),
            "candidate_change": candidate_months.get(month, 0.0),
            "delta_change": round(candidate_months.get(month, 0.0) - current_months.get(month, 0.0), 2),
        }
        for month in sorted(set(current_months) | set(candidate_months))
    ]


def money(value: Any) -> str:
    return f'<span class="num">${fnum(value):,.2f}</span>'


def pct(value: Any) -> str:
    return f'<span class="num">{fnum(value):,.2f}%</span>'


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def summary_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"""<tr class="{"chosen" if row["key"] == "selected" else ""}">
        <td>{html.escape(str(row["label"]))}</td><td>{money(row["portfolio_value"])}</td>
        <td class="{tone(row["period_return_pct"])}">{pct(row["period_return_pct"])}</td>
        <td class="negative">{pct(row["max_drawdown_pct"])}</td>
        <td>{row["trades"]}</td><td>{row["wins"]} / {row["losses"]}</td><td>{pct(row["win_rate"])}</td>
        </tr>"""
        for row in rows
    )
    return f"""<table><thead><tr><th>السياسة</th><th>قيمة المحفظة</th><th>عائد الفترة</th><th>السحب الأقصى</th><th>الصفقات</th><th>رابحة / خاسرة</th><th>نسبة الفوز</th></tr></thead><tbody>{body}</tbody></table>"""


def grouped_table(rows: list[dict[str, Any]], heading: str, name: str) -> str:
    body = "".join(
        f"""<tr><td>{html.escape(str(row[name]))}</td><td>{money(row["current_pnl"])}</td>
        <td class="{tone(row["candidate_pnl"])}">{money(row["candidate_pnl"])}</td>
        <td class="{tone(row["delta_pnl"])}">{money(row["delta_pnl"])}</td>
        <td>{row["candidate_trades"]}</td><td>{row["candidate_wins"]} / {row["candidate_losses"]}</td></tr>"""
        for row in rows
    )
    return f"""<section class="panel"><h2>{heading}</h2><table><thead><tr><th>التصنيف</th><th>ربح الحالي</th><th>ربح المرشح</th><th>الفرق</th><th>صفقات المرشح</th><th>رابحة / خاسرة</th></tr></thead><tbody>{body}</tbody></table></section>"""


def render(
    selected_step: float,
    training_rows: list[dict[str, Any]],
    testing_by_period: dict[str, list[dict[str, Any]]],
    timeframe_rows: list[dict[str, Any]],
    ticker_rows: list[dict[str, Any]],
    month_rows: list[dict[str, Any]],
    latest_date: str,
) -> str:
    candidate_2025 = next(row for row in testing_by_period["2025"] if row["key"] == "selected")
    current_2025 = next(row for row in testing_by_period["2025"] if row["key"] == "current")
    candidate_2026 = next(row for row in testing_by_period["2026"] if row["key"] == "selected")
    current_2026 = next(row for row in testing_by_period["2026"] if row["key"] == "current")
    profit_pass = (
        fnum(candidate_2025["portfolio_value"]) > fnum(current_2025["portfolio_value"])
        and fnum(candidate_2026["portfolio_value"]) > fnum(current_2026["portfolio_value"])
    )
    risk_pass = (
        fnum(candidate_2025["max_drawdown_pct"]) >= fnum(current_2025["max_drawdown_pct"])
        and fnum(candidate_2026["max_drawdown_pct"]) >= fnum(current_2026["max_drawdown_pct"])
    )
    month_body = "".join(
        f"""<tr><td>{row["period"]}</td><td><span class="num">{row["month"]}</span></td>
        <td>{money(row["current_change"])}</td><td class="{tone(row["candidate_change"])}">{money(row["candidate_change"])}</td>
        <td class="{tone(row["delta_change"])}">{money(row["delta_change"])}</td></tr>"""
        for row in sorted(month_rows, key=lambda row: fnum(row["delta_change"]), reverse=True)
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>التحقق الزمني لوقف أعلى اليوم</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f5f7fa;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1440px;margin:auto;padding:28px}} h1{{font-size:30px;margin:0 0 8px}} h2{{font-size:21px;margin:0 0 15px}}
p{{color:#566f85;line-height:1.9}} .notice{{background:#fff5df;border:1px solid #dfb251;border-radius:8px;padding:14px 18px;margin:18px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}} .card,.panel{{background:#fff;border:1px solid #d5e1eb;border-radius:8px;padding:18px;margin:14px 0}}
.card label{{display:block;color:#627b91;margin-bottom:9px}} .card strong{{font-size:27px;display:block}} .card small{{color:#60778b;line-height:1.8}}
.num{{direction:ltr;unicode-bidi:isolate;display:inline-block}} .positive{{color:#087852}} .negative{{color:#af3737}}
table{{width:100%;border-collapse:collapse;min-width:820px}} .panel{{overflow:auto}}
th,td{{padding:12px 10px;border-bottom:1px solid #e1eaf2;text-align:right}} th{{background:#eaf0f6;color:#29465e;white-space:nowrap}}
tr.chosen{{background:#eaf7f1}} .decision{{border-right:4px solid #1771a8}}
.bad{{color:#af3737}} .good{{color:#087852}} @media(max-width:980px){{.cards{{grid-template-columns:1fr 1fr}}}} @media(max-width:560px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap">
<h1>التحقق الزمني لقاعدة وقف أعلى اليوم</h1>
<p>اختارت بيانات عام <span class="num">2024</span> الدرجة دون رؤية المستقبل، ثم طبقت الدرجة نفسها على عام <span class="num">2025</span> وعلى عام <span class="num">2026</span> حتى آخر جلسة متاحة: <span class="num">{latest_date}</span>.</p>
<div class="notice">تجربة مستقلة فقط. لم تتغير المحفظة الرسمية أو صفحاتها. كل فترة تبدأ برأس مال مستقل قدره <span class="num">$10,000</span> حتى نقيس قابلية القاعدة للتكرار دون أثر تراكم أرباح فترة سابقة.</div>
<section class="cards">
<article class="card"><label>درجة الوقف المختارة من التدريب</label><strong><span class="num">{selected_step:g}%</span></strong><small>أعلى اليوم ثم التفعيل من الجلسة التالية</small></article>
<article class="card"><label>اختبار عام 2025</label><strong class="{tone(candidate_2025["period_return_pct"])}">{pct(candidate_2025["period_return_pct"])}</strong><small>الحالي {pct(current_2025["period_return_pct"])}</small></article>
<article class="card"><label>اختبار عام 2026</label><strong class="{tone(candidate_2026["period_return_pct"])}">{pct(candidate_2026["period_return_pct"])}</strong><small>الحالي {pct(current_2026["period_return_pct"])}</small></article>
<article class="card"><label>فحص الاتساق الأولي</label><strong class="{"good" if profit_pass and risk_pass else "bad"}">{"اجتاز" if profit_pass and risk_pass else "يحتاج مراجعة"}</strong><small>العائد: {"متفوق في الفترتين" if profit_pass else "غير متفوق في الفترتين"} | المخاطر: {"لم تسؤ" if risk_pass else "ارتفع السحب"}</small></article>
</section>
<section class="panel"><h2>مرحلة الاختيار: عام 2024 فقط</h2>{summary_table(training_rows)}</section>
<section class="panel"><h2>اختبار مستقل: عام 2025</h2>{summary_table(testing_by_period["2025"])}</section>
<section class="panel"><h2>اختبار مستقل: عام 2026 حتى {latest_date}</h2>{summary_table(testing_by_period["2026"])}</section>
<section class="panel decision"><h2>قراءة القرار</h2>
<p>نجاح التدريب وحده لا يعتمد السياسة. النجاح الأولي يتطلب تفوق الدرجة المختارة مسبقًا على السياسة الحالية في فترتي الاختبار مع مراقبة السحب الأقصى. إذا اجتازت ذلك، تصبح مرشحة لاختبار نهائي أو اعتماد واع لاختبار حي، لا وعدًا بعائد مستقبلي.</p></section>
{grouped_table(timeframe_rows, "الفرق عن الحالي حسب إطار التداول في فترتي الاختبار", "group")}
{grouped_table(ticker_rows, "الفرق عن الحالي حسب السهم في فترتي الاختبار", "group")}
<section class="panel"><h2>الفرق الشهري في فترتي الاختبار</h2><table><thead><tr><th>الفترة</th><th>الشهر</th><th>تغير الحالي</th><th>تغير المرشح</th><th>فرق المرشح</th></tr></thead><tbody>{month_body}</tbody></table></section>
</main></body></html>"""


def combine_group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = str(row["group"])
        target = merged.setdefault(
            group,
            {"group": group, "current_pnl": 0.0, "candidate_pnl": 0.0, "delta_pnl": 0.0, "candidate_trades": 0, "candidate_wins": 0, "candidate_losses": 0},
        )
        for key in ("current_pnl", "candidate_pnl", "delta_pnl"):
            target[key] = round(fnum(target[key]) + fnum(row[key]), 2)
        for key in ("candidate_trades", "candidate_wins", "candidate_losses"):
            target[key] += int(row[key])
    return sorted(merged.values(), key=lambda row: fnum(row["delta_pnl"]), reverse=True)


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    latest_date = latest_market_date(strategies)
    policies = [high_policy(step) for step in STEP_VALUES]
    training_states: dict[str, dict[str, Any]] = {}
    training_rows: list[dict[str, Any]] = []
    for policy in policies:
        state = lab.simulate(strategies, policy, TRAINING_START, TRAINING_END)
        training_states[policy.key] = state
        training_rows.append(summary_row(policy.key, policy.label, state, "2024 - تدريب", TRAINING_START, TRAINING_END))
    selected_training = max(training_rows, key=lambda row: fnum(row["portfolio_value"]))
    selected_step = next(policy.step_pct for policy in policies if policy.key == selected_training["key"])
    selected_policy = high_policy(selected_step)

    comparison_policies = [
        ("current", lab.Policy("current", "الحالي: رفع داخل الجلسة بدرجة 1 بالمئة", "step", step_pct=1.0)),
        ("intraday_1_8", lab.Policy("intraday_1_8", "أفضل مقارنة سابقة: رفع داخل الجلسة بدرجة 1.8 بالمئة", "step", step_pct=1.8)),
        ("selected", selected_policy),
    ]
    if selected_step != 0.5:
        comparison_policies.append(("full_history_0_5", high_policy(0.5)))

    ranges = {
        "2025": (TEST_2025_START, TEST_2025_END),
        "2026": (TEST_2026_START, latest_date),
    }
    states: dict[tuple[str, str], dict[str, Any]] = {}
    testing_by_period: dict[str, list[dict[str, Any]]] = {}
    for period, (start_date, end_date) in ranges.items():
        rows: list[dict[str, Any]] = []
        for output_key, policy in comparison_policies:
            state = lab.simulate(strategies, policy, start_date, end_date)
            states[(period, output_key)] = state
            label = policy.label
            if output_key == "selected":
                label = f"المختارة من 2024: أعلى اليوم ثم الجلسة التالية بدرجة {selected_step:g} بالمئة"
            elif output_key == "full_history_0_5":
                label = "مرجع بعد رؤية كامل التاريخ: أعلى اليوم ثم الجلسة التالية بدرجة 0.5 بالمئة"
            rows.append(summary_row(output_key, label, state, period, start_date, end_date))
        current = next(row for row in rows if row["key"] == "current")
        for row in rows:
            row["delta_value"] = round(fnum(row["portfolio_value"]) - fnum(current["portfolio_value"]), 2)
        testing_by_period[period] = rows

    all_summaries = list(training_rows) + testing_by_period["2025"] + testing_by_period["2026"]
    write_csv(TRAINING_CSV, training_rows)
    write_csv(SUMMARY_CSV, all_summaries)

    timeframe_all: list[dict[str, Any]] = []
    ticker_all: list[dict[str, Any]] = []
    month_rows: list[dict[str, Any]] = []
    for period in ranges:
        current_state = states[(period, "current")]
        selected_state = states[(period, "selected")]
        timeframe_all.extend(grouped_trade_stats(current_state, selected_state, period, "timeframe"))
        ticker_all.extend(grouped_trade_stats(current_state, selected_state, period, "ticker"))
        month_rows.extend(month_comparison(current_state, selected_state, period))
    timeframe_rows = combine_group_rows(timeframe_all)
    ticker_rows = combine_group_rows(ticker_all)
    write_csv(TIMEFRAME_CSV, timeframe_rows)
    write_csv(TICKER_CSV, ticker_rows)
    write_csv(MONTH_CSV, month_rows)
    REPORT_HTML.write_text(
        render(selected_step, training_rows, testing_by_period, timeframe_rows, ticker_rows, month_rows, latest_date),
        encoding="utf-8",
        newline="\n",
    )

    print(f"Selected from training: {selected_step:g}%")
    for period in ("2025", "2026"):
        for row in testing_by_period[period]:
            print(
                f"{period} | {row['key']}: value=${fnum(row['portfolio_value']):,.2f}; "
                f"return={fnum(row['period_return_pct']):,.2f}%; "
                f"drawdown={fnum(row['max_drawdown_pct']):,.2f}%; "
                f"wins/losses={row['wins']}/{row['losses']}"
            )
    print(f"Report: {REPORT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
