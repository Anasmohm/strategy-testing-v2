#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

import paper_portfolio_v31 as v31
import test_profit_protection_v31 as lab


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SUMMARY_CSV = REPORTS / "experimental_close_trailing_v31_summary.csv"
REPORT_HTML = REPORTS / "experimental_close_trailing_v31.html"

POLICIES = [
    lab.Policy(
        "intraday_step_1",
        "الحالية: رفع الوقف داخل الجلسة بدرجة 1 بالمئة",
        "step",
        step_pct=1.0,
        update_timing="intraday",
    ),
    lab.Policy(
        "close_step_1",
        "رفع الوقف بعد إغلاق اليوم بدرجة 1 بالمئة",
        "step",
        step_pct=1.0,
        update_timing="daily_close",
    ),
    lab.Policy(
        "close_step_1_8",
        "رفع الوقف بعد إغلاق اليوم بدرجة 1.8 بالمئة",
        "step",
        step_pct=1.8,
        update_timing="daily_close",
    ),
]


def fnum(value: Any) -> float:
    return float(value or 0)


def write_csv(rows: list[dict[str, Any]]) -> None:
    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def render(rows: list[dict[str, Any]]) -> str:
    current = rows[0]
    best = max(rows, key=lambda row: fnum(row["portfolio_value"]))
    body = "".join(
        f"""<tr class="{"best" if row["key"] == best["key"] else ""}">
        <td>{html.escape(str(row["label"]))}</td>
        <td class="num">${fnum(row["portfolio_value"]):,.2f}</td>
        <td class="num {'positive' if fnum(row["period_return_pct"]) >= 0 else 'negative'}">{fnum(row["period_return_pct"]):,.2f}%</td>
        <td class="num {'positive' if fnum(row["delta_value"]) >= 0 else 'negative'}">${fnum(row["delta_value"]):,.2f}</td>
        <td class="num negative">{fnum(row["max_drawdown_pct"]):,.2f}%</td>
        <td class="num">{row["wins"]} / {row["losses"]}</td>
        <td class="num">{fnum(row["avg_win_pct"]):,.2f}%</td>
        <td class="num">{fnum(row["avg_loss_pct"]):,.2f}%</td>
        </tr>"""
        for row in rows
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>اختبار رفع الوقف عند الإغلاق</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f4f7fb;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1180px;margin:auto;padding:28px}} h1{{font-size:29px;margin:0 0 8px}} p{{color:#587289;line-height:1.9}}
.notice{{background:#fff5de;border:1px solid #e7bd62;padding:14px 18px;border-radius:8px;margin:20px 0}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}} .card,.panel{{background:#fff;border:1px solid #d5e1ec;border-radius:8px;padding:18px}}
.card span{{display:block;color:#62788d;margin-bottom:9px}} .card strong{{direction:ltr;unicode-bidi:isolate;display:block;font-size:28px}}
.num{{direction:ltr;unicode-bidi:isolate;text-align:left}} .positive{{color:#087852}} .negative{{color:#b53434}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:14px 10px;border-bottom:1px solid #e2eaf2;text-align:right}} th{{background:#eaf0f6;color:#23415d}}
tr.best{{background:#e9f7f1}} .logic{{line-height:2;margin-top:18px}} @media(max-width:820px){{.cards{{grid-template-columns:1fr}} .panel{{overflow-x:auto}} table{{min-width:900px}}}}
</style></head><body><main class="wrap">
<h1>اختبار رفع الوقف عند إغلاق اليوم</h1>
<p>الدخول والمؤشرات اليومية ثابتة، والهدف والوقف الأصلي ينفذان بخمس دقائق. المقارنة تغيّر فقط توقيت رفع الوقف المتحرك.</p>
<div class="notice">تجربة مستقلة غير معتمدة: لم يتم تعديل الداشبورد الرئيسي أو سياسة المحفظة الرسمية.</div>
<section class="cards">
<article class="card"><span>قيمة السياسة الحالية</span><strong>${fnum(current['portfolio_value']):,.2f}</strong><small>عائد الفترة <span class="num">{fnum(current['period_return_pct']):,.2f}%</span></small></article>
<article class="card"><span>أفضل نتيجة في المقارنة</span><strong class="positive">${fnum(best['portfolio_value']):,.2f}</strong><small>{html.escape(str(best['label']))}</small></article>
<article class="card"><span>الفرق عن الحالية</span><strong class="{'positive' if fnum(best['delta_value']) >= 0 else 'negative'}">${fnum(best['delta_value']):,.2f}</strong><small>السحب الأقصى <span class="num">{fnum(best['max_drawdown_pct']):,.2f}%</span></small></article>
</section>
<section class="panel"><table><thead><tr><th>سياسة رفع الوقف</th><th>قيمة المحفظة</th><th>عائد الفترة</th><th>الفرق عن الحالية</th><th>السحب الأقصى</th><th>رابحة / خاسرة</th><th>متوسط الرابحة</th><th>متوسط الخاسرة</th></tr></thead><tbody>{body}</tbody></table></section>
<section class="panel logic"><strong>قاعدة الاختبار</strong><p>في سياستي الإغلاق لا يُرفع الوقف بسبب أعلى سعر خلال اليوم. إذا انتهت الجلسة بإغلاق يحقق درجة الربح، يُرفع الوقف بعد الإغلاق فقط ويصبح قابلا للتنفيذ ابتداء من الجلسة التالية.</p></section>
</main></body></html>"""


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        state = lab.simulate(strategies, policy)
        summary = v31.portfolio_summary(state, policy.label)
        rows.append(
            {
                "key": policy.key,
                "label": policy.label,
                "portfolio_value": summary["portfolio_value"],
                "pnl": summary["pnl"],
                "period_return_pct": summary["period_return_pct"],
                "annual_return_pct": summary["annual_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "trades": summary["trades"],
                "wins": summary["wins"],
                "losses": summary["losses"],
                "win_rate": summary["win_rate"],
                "avg_win_pct": summary["avg_win_pct"],
                "avg_loss_pct": summary["avg_loss_pct"],
            }
        )
    baseline = fnum(rows[0]["portfolio_value"])
    for row in rows:
        row["delta_value"] = round(fnum(row["portfolio_value"]) - baseline, 2)
    write_csv(rows)
    REPORT_HTML.write_text(render(rows), encoding="utf-8", newline="\n")
    for row in rows:
        print(
            f"{row['label']}: value=${fnum(row['portfolio_value']):,.2f}; "
            f"return={fnum(row['period_return_pct']):,.2f}%; "
            f"drawdown={fnum(row['max_drawdown_pct']):,.2f}%; "
            f"wins/losses={row['wins']}/{row['losses']}"
        )
    print(f"Report: {REPORT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
