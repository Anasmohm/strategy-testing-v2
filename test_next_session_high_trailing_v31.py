#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

import paper_portfolio_v2 as v2
import paper_portfolio_v31 as v31
import test_profit_protection_v31 as lab


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SUMMARY_CSV = REPORTS / "experimental_next_session_high_trailing_v31_summary.csv"
TIMEFRAME_CSV = REPORTS / "experimental_next_session_high_trailing_v31_by_timeframe.csv"
TICKER_CSV = REPORTS / "experimental_next_session_high_trailing_v31_by_ticker.csv"
REPORT_HTML = REPORTS / "experimental_next_session_high_trailing_v31.html"
OLD_DAILY_SUMMARY = REPORTS / "experimental_eodhd_5m_v31_summary.csv"


POLICIES = [
    lab.Policy("current_1pct", "الحالي: رفع داخل الجلسة بدرجة 1 بالمئة", "step", step_pct=1.0),
    lab.Policy("intraday_1_8pct", "أفضل اختبار سابق: رفع داخل الجلسة بدرجة 1.8 بالمئة", "step", step_pct=1.8),
    lab.Policy("next_high_0_5pct", "أعلى اليوم ثم الجلسة التالية: درجة 0.5 بالمئة", "step", step_pct=0.5, update_timing="daily_high_next_session"),
    lab.Policy("next_high_1pct", "قاعدة النسخة القديمة الواقعية: أعلى اليوم ثم الجلسة التالية بدرجة 1 بالمئة", "step", step_pct=1.0, update_timing="daily_high_next_session"),
    lab.Policy("next_high_1_5pct", "أعلى اليوم ثم الجلسة التالية: درجة 1.5 بالمئة", "step", step_pct=1.5, update_timing="daily_high_next_session"),
    lab.Policy("next_high_1_8pct", "أعلى اليوم ثم الجلسة التالية: درجة 1.8 بالمئة", "step", step_pct=1.8, update_timing="daily_high_next_session"),
    lab.Policy("next_high_2pct", "أعلى اليوم ثم الجلسة التالية: درجة 2 بالمئة", "step", step_pct=2.0, update_timing="daily_high_next_session"),
    lab.Policy("next_high_3pct", "أعلى اليوم ثم الجلسة التالية: درجة 3 بالمئة", "step", step_pct=3.0, update_timing="daily_high_next_session"),
    lab.Policy("next_high_4pct", "أعلى اليوم ثم الجلسة التالية: درجة 4 بالمئة", "step", step_pct=4.0, update_timing="daily_high_next_session"),
    lab.Policy("next_high_5pct", "أعلى اليوم ثم الجلسة التالية: درجة 5 بالمئة", "step", step_pct=5.0, update_timing="daily_high_next_session"),
]


def fnum(value: Any) -> float:
    return float(value or 0)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def result_row(policy: lab.Policy, state: dict[str, Any]) -> dict[str, Any]:
    summary = v31.portfolio_summary(state, policy.label)
    return {
        "key": policy.key,
        "label": policy.label,
        "basis": "قابل للتنفيذ ببيانات خمس دقائق",
        "portfolio_value": summary["portfolio_value"],
        "pnl": summary["pnl"],
        "period_return_pct": summary["period_return_pct"],
        "annual_return_pct": summary["annual_return_pct"],
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "trades": summary["trades"],
        "closed": summary["closed"],
        "open": summary["open"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "win_rate": summary["win_rate"],
        "avg_win_pct": summary["avg_win_pct"],
        "avg_loss_pct": summary["avg_loss_pct"],
    }


def old_daily_reference() -> dict[str, Any]:
    with OLD_DAILY_SUMMARY.open(newline="", encoding="utf-8-sig") as handle:
        saved = next(row for row in csv.DictReader(handle) if row["version"] == "V3.1 daily approved")
    return {
        "key": "old_daily_reference",
        "label": "النسخة اليومية القديمة: مرجع للمقارنة فقط",
        "basis": "غير معتمد للتنفيذ: ترتيب الحركة داخل اليوم غير معلوم",
        "portfolio_value": fnum(saved["portfolio_value"]),
        "pnl": fnum(saved["pnl"]),
        "period_return_pct": fnum(saved["period_return_pct"]),
        "annual_return_pct": fnum(saved["annual_return_pct"]),
        "max_drawdown_pct": fnum(saved["max_drawdown_pct"]),
        "trades": int(saved["trades"]),
        "closed": int(saved["closed"]),
        "open": int(saved["open"]),
        "wins": int(saved["wins"]),
        "losses": int(saved["losses"]),
        "win_rate": fnum(saved["win_rate"]),
        "avg_win_pct": fnum(saved["avg_win_pct"]),
        "avg_loss_pct": fnum(saved["avg_loss_pct"]),
    }


def grouped_trade_stats(
    current: dict[str, Any],
    candidate: dict[str, Any],
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
        current_closed = [trade for trade in current_trades if trade.get("status") == "CLOSED"]
        candidate_closed = [trade for trade in candidate_trades if trade.get("status") == "CLOSED"]
        current_pnl = round(sum(v2.trade_pnl(trade) for trade in current_trades), 2)
        candidate_pnl = round(sum(v2.trade_pnl(trade) for trade in candidate_trades), 2)
        wins = [trade for trade in candidate_closed if v2.trade_pnl(trade) >= 0]
        losses = [trade for trade in candidate_closed if v2.trade_pnl(trade) < 0]
        rows.append(
            {
                "group": group or "غير محدد",
                "current_pnl": current_pnl,
                "candidate_pnl": candidate_pnl,
                "delta_pnl": round(candidate_pnl - current_pnl, 2),
                "candidate_trades": len(candidate_trades),
                "candidate_wins": len(wins),
                "candidate_losses": len(losses),
                "candidate_win_rate": round(len(wins) / len(candidate_closed) * 100, 2) if candidate_closed else 0.0,
            }
        )
    return sorted(rows, key=lambda row: fnum(row["delta_pnl"]), reverse=True)


def num(value: Any, suffix: str = "") -> str:
    return f'<span class="num">{fnum(value):,.2f}{suffix}</span>'


def money(value: Any) -> str:
    return f'<span class="num">${fnum(value):,.2f}</span>'


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def render_group_table(rows: list[dict[str, Any]], heading: str) -> str:
    body = "".join(
        f"""<tr>
        <td>{html.escape(str(row["group"]))}</td>
        <td>{money(row["current_pnl"])}</td>
        <td class="{tone(row["candidate_pnl"])}">{money(row["candidate_pnl"])}</td>
        <td class="{tone(row["delta_pnl"])}">{money(row["delta_pnl"])}</td>
        <td>{row["candidate_trades"]}</td>
        <td>{row["candidate_wins"]} / {row["candidate_losses"]}</td>
        <td>{num(row["candidate_win_rate"], "%")}</td>
        </tr>"""
        for row in rows
    )
    return f"""<section class="panel"><h2>{heading}</h2><table>
    <thead><tr><th>التصنيف</th><th>ربح الحالي</th><th>ربح المرشح</th><th>الفرق</th><th>صفقات المرشح</th><th>رابحة / خاسرة</th><th>نسبة الفوز</th></tr></thead>
    <tbody>{body}</tbody></table></section>"""


def render(
    rows: list[dict[str, Any]],
    timeframe_rows: list[dict[str, Any]],
    ticker_rows: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> str:
    current = next(row for row in rows if row["key"] == "current_1pct")
    executable = [row for row in rows if row["key"] != "old_daily_reference"]
    best_executable = max(executable, key=lambda row: fnum(row["portfolio_value"]))
    body = "".join(
        f"""<tr class="{"candidate" if row["key"] == candidate["key"] else ""} {"reference" if row["key"] == "old_daily_reference" else ""}">
        <td><strong>{html.escape(str(row["label"]))}</strong><small>{html.escape(str(row["basis"]))}</small></td>
        <td>{money(row["portfolio_value"])}</td>
        <td class="{tone(row["period_return_pct"])}">{num(row["period_return_pct"], "%")}</td>
        <td class="{tone(row["delta_value"])}">{money(row["delta_value"])}</td>
        <td class="negative">{num(row["max_drawdown_pct"], "%")}</td>
        <td>{row["trades"]}</td>
        <td>{row["wins"]} / {row["losses"]}</td>
        <td>{num(row["win_rate"], "%")}</td>
        <td>{num(row["avg_win_pct"], "%")}</td>
        <td>{num(row["avg_loss_pct"], "%")}</td>
        </tr>"""
        for row in rows
    )
    verdict = (
        "أفضل قاعدة مؤجلة تجاوزت الوضع الحالي في العائد التاريخي، لكنها تحتاج تحققًا زمنيًا قبل الاعتماد."
        if fnum(candidate["portfolio_value"]) > fnum(current["portfolio_value"])
        else "قاعدة أعلى اليوم المؤجلة لم تتجاوز الوضع الحالي في هذا الاختبار، فلا يوجد سبب لاعتمادها الآن."
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>اختبار وقف أعلى اليوم التنفيذي</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f5f7fa;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1440px;margin:auto;padding:28px}} h1{{font-size:30px;margin:0 0 10px}} h2{{font-size:21px;margin:0 0 16px}}
p{{color:#536d83;line-height:1.9;margin:7px 0}} .notice{{background:#fff5de;border:1px solid #dfb34d;border-radius:8px;padding:14px 18px;margin:19px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}} .card,.panel{{background:#fff;border:1px solid #d5e0eb;border-radius:8px;padding:18px}}
.card label{{display:block;color:#60798f;margin-bottom:10px}} .card strong{{display:block;font-size:27px}} .card small{{line-height:1.8;color:#60798f}}
.num{{direction:ltr;unicode-bidi:isolate;display:inline-block}} .positive{{color:#087952}} .negative{{color:#ae3737}}
.panel{{margin:15px 0;overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:920px}}
th,td{{padding:12px 10px;border-bottom:1px solid #e2eaf2;text-align:right;vertical-align:top}} th{{background:#eaf0f6;color:#29465e;white-space:nowrap}}
td small{{display:block;color:#667d92;font-size:12px;line-height:1.6;margin-top:4px}} tr.candidate{{background:#ebf7f1}} tr.reference{{background:#fff5de}}
.decision{{border-right:4px solid #1771a8}} @media(max-width:950px){{.cards{{grid-template-columns:1fr 1fr}}}} @media(max-width:560px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap">
<h1>اختبار وقف أعلى اليوم بصيغة قابلة للتنفيذ</h1>
<p>الإشارات اليومية، الأسهم التسعة، رأس المال، والسيولة ثابتة. الهدف والوقف الأصلي ينفذان خلال الجلسة ببيانات خمس دقائق. المتغير الوحيد هو توقيت رفع الوقف المتحرك.</p>
<div class="notice">هذه تجربة منفصلة ولم تغير المحفظة الرسمية أو الداشبورد المنشور. صف النسخة اليومية القديمة معروض كمرجع تفسير فقط لأنه لا يثبت ترتيب الحركة داخل اليوم.</div>
<section class="cards">
<article class="card"><label>الوضع الحالي</label><strong>{money(current["portfolio_value"])}</strong><small>عائد الفترة {num(current["period_return_pct"], "%")}</small></article>
<article class="card"><label>أفضل قاعدة أعلى اليوم المؤجلة</label><strong class="{tone(candidate["delta_value"])}">{money(candidate["portfolio_value"])}</strong><small>{html.escape(str(candidate["label"]))}</small></article>
<article class="card"><label>فرق المرشح عن الحالي</label><strong class="{tone(candidate["delta_value"])}">{money(candidate["delta_value"])}</strong><small>السحب الأقصى {num(candidate["max_drawdown_pct"], "%")}</small></article>
<article class="card"><label>أفضل سياسة تنفيذية في الجدول</label><strong>{money(best_executable["portfolio_value"])}</strong><small>{html.escape(str(best_executable["label"]))}</small></article>
</section>
<section class="panel"><h2>المقارنة العامة</h2><table><thead><tr><th>السياسة</th><th>قيمة المحفظة</th><th>عائد الفترة</th><th>الفرق عن الحالي</th><th>السحب الأقصى</th><th>الصفقات</th><th>رابحة / خاسرة</th><th>نسبة الفوز</th><th>متوسط الرابحة</th><th>متوسط الخاسرة</th></tr></thead><tbody>{body}</tbody></table></section>
<section class="panel decision"><h2>قراءة القرار</h2><p>{verdict}</p><p>المرشح الملون بالأخضر هو أفضل نسخة من قاعدة أعلى اليوم المؤجلة فقط، وليس قرار اعتماد. المقارنة مع المرجع الأصفر لا تكفي للاعتماد لأنه يمثل المحاكاة اليومية القديمة غير التنفيذية.</p></section>
{render_group_table(timeframe_rows, "أثر أفضل مرشح حسب إطار التداول")}
{render_group_table(ticker_rows, "أثر أفضل مرشح حسب السهم")}
</main></body></html>"""


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    states: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        state = lab.simulate(strategies, policy)
        states[policy.key] = state
        rows.append(result_row(policy, state))
    rows.append(old_daily_reference())
    current = next(row for row in rows if row["key"] == "current_1pct")
    for row in rows:
        row["delta_value"] = round(fnum(row["portfolio_value"]) - fnum(current["portfolio_value"]), 2)
        row["delta_return_pct"] = round(fnum(row["period_return_pct"]) - fnum(current["period_return_pct"]), 2)
    high_candidates = [row for row in rows if row["key"].startswith("next_high_")]
    candidate = max(high_candidates, key=lambda row: fnum(row["portfolio_value"]))
    timeframe_rows = grouped_trade_stats(states["current_1pct"], states[candidate["key"]], "timeframe")
    ticker_rows = grouped_trade_stats(states["current_1pct"], states[candidate["key"]], "ticker")
    write_csv(SUMMARY_CSV, rows)
    write_csv(TIMEFRAME_CSV, timeframe_rows)
    write_csv(TICKER_CSV, ticker_rows)
    REPORT_HTML.write_text(render(rows, timeframe_rows, ticker_rows, candidate), encoding="utf-8", newline="\n")
    for row in sorted(rows, key=lambda value: fnum(value["portfolio_value"]), reverse=True):
        print(
            f"{row['key']}: value=${fnum(row['portfolio_value']):,.2f}; "
            f"return={fnum(row['period_return_pct']):,.2f}%; "
            f"drawdown={fnum(row['max_drawdown_pct']):,.2f}%; "
            f"wins/losses={row['wins']}/{row['losses']}"
        )
    print(f"Candidate: {candidate['key']}")
    print(f"Report: {REPORT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
