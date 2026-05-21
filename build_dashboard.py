#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import html
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DIAGNOSIS = REPORTS / "stock_diagnosis.csv"
STRATEGIES = REPORTS / "designed_strategies.csv"
VERIFICATION = REPORTS / "strategy_verification.csv"
REFINEMENTS = REPORTS / "strategy_refinements.csv"
COMPARISON = REPORTS / "strategy_verification_comparison.csv"
SELECTED_STRATEGIES = REPORTS / "selected_strategies.csv"
SELECTED_VERIFICATION = REPORTS / "selected_strategy_verification.csv"
QUALITY_GATE = REPORTS / "portfolio_quality_gate_v2.csv"
DASHBOARD = REPORTS / "strategy_v2_dashboard.html"


BEHAVIOR_LABELS = {
    "breakout": "اختراق",
    "pullback_recovery": "ارتداد بعد هبوط",
    "trend_following": "تتبع ترند",
    "mixed_or_choppy": "مختلط / متذبذب",
    "v1_success_swing": "نجاح تاريخي - سوينق",
    "v1_success_monthly": "نجاح تاريخي - شهري",
}

TIMEFRAME_LABELS = {
    "swing": "سوينق",
    "monthly": "شهري",
    "short_term_daily_proxy": "قصير المدى",
}

ENTRY_LABELS = {
    "v1_breakout": "اختراق",
    "v1_rsi_recovery": "ارتداد RSI",
    "breakout": "اختراق",
    "rsi_recovery": "ارتداد RSI",
    "pullback_recovery": "ارتداد بعد هبوط",
    "trend_following": "تتبع ترند",
}

STOP_LABELS = {
    "v1_atr_support": "ATR والدعم",
    "atr_trailing": "ATR متحرك",
    "support_stop": "الدعم",
}

VERSION_LABELS = {
    "v2_from_v1_success": "مختارة من نجاح النسخة الأولى",
    "v1": "النسخة الأولى",
    "v2": "تصميم مخصص",
}


def read_rows() -> list[dict[str, str]]:
    with DIAGNOSIS.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_optional(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def num(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except ValueError:
        return 0.0


def fmt(value: object, suffix: str = "") -> str:
    try:
        return f'<span class="num">{float(value):,.2f}{suffix}</span>'
    except (TypeError, ValueError):
        return "-"


def plain_fmt(value: object, suffix: str = "") -> str:
    try:
        return f"{float(value):,.2f}{suffix}"
    except (TypeError, ValueError):
        return "-"


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def card_html(title: str, value: object, note: str = "") -> str:
    return f"""
    <article class="card">
      <span>{html.escape(title)}</span>
      <strong>{value}</strong>
      <small>{html.escape(note)}</small>
    </article>
    """


def rows_table(rows: list[dict[str, str]]) -> str:
    body = []
    for row in rows:
        behavior = row["behavior"]
        body.append(
            "<tr>"
            f"<td>{html.escape(row['ticker'])}</td>"
            f"<td>{html.escape(BEHAVIOR_LABELS.get(behavior, behavior))}</td>"
            f"<td>{fmt(row['trend_return_pct'], '%')}</td>"
            f"<td>{fmt(row['max_drawdown_pct'], '%')}</td>"
            f"<td>{fmt(row['avg_daily_range_pct'], '%')}</td>"
            f"<td>{html.escape(row['breakout_events'])}</td>"
            f"<td>{fmt(row['breakout_success_rate_pct'], '%')}</td>"
            f"<td>{html.escape(row['pullback_events'])}</td>"
            f"<td>{fmt(row['pullback_success_rate_pct'], '%')}</td>"
            f"<td>{html.escape(row['proposed_design'])}</td>"
            f"<td>{html.escape(row.get('entry_rule', '-'))}</td>"
            f"<td>{fmt(row.get('target_pct', ''), '%')}</td>"
            f"<td>{fmt(row.get('initial_stop_pct', ''), '%')}</td>"
            f"<td>{html.escape(str(row.get('trades', '-')))}</td>"
            f"<td>{fmt(row.get('win_rate', ''), '%')}</td>"
            f"<td>{fmt(row.get('total_return', ''), '%')}</td>"
            f"<td>{html.escape(str(row.get('designed_pass', '-')))}</td>"
            "</tr>"
        )
    return "\n".join(body)


def top_list(title: str, rows: list[dict[str, str]], key: str, suffix: str = "%") -> str:
    items = "".join(
        f"<li><strong>{html.escape(row['ticker'])}</strong><span>{fmt(row[key], suffix)}</span></li>"
        for row in rows[:8]
    )
    return f"""
    <section class="panel">
      <h2>{html.escape(title)}</h2>
      <ul class="ranked">{items}</ul>
    </section>
    """


def refinements_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<tr><td colspan='9'>لا توجد تصميمات فاشلة بحاجة لتعديل.</td></tr>"
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row['ticker'])}</td>"
            f"<td>{html.escape(BEHAVIOR_LABELS.get(row['behavior'], row['behavior']))}</td>"
            f"<td>{html.escape(row['failure_reason'])}</td>"
            f"<td>{html.escape(row['current_entry_rule'])}</td>"
            f"<td>{html.escape(row['proposed_entry_rule'])}</td>"
            f"<td>{fmt(row['proposed_target_pct'], '%')}</td>"
            f"<td>{fmt(row['proposed_stop_pct'], '%')}</td>"
            f"<td>{fmt(row['win_rate'], '%')}</td>"
            f"<td>{html.escape(row['proposed_change'])}</td>"
            "</tr>"
        )
    return "\n".join(body)


def comparison_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<tr><td colspan='8'>لا توجد مقارنة بعد.</td></tr>"
    body = []
    for row in sorted(rows, key=lambda item: num(item, "return_delta"), reverse=True):
        body.append(
            "<tr>"
            f"<td>{html.escape(row['ticker'])}</td>"
            f"<td>{html.escape(row.get('selected_version', ''))}</td>"
            f"<td>{html.escape(row['old_pass'])}</td>"
            f"<td>{html.escape(row['new_pass'])}</td>"
            f"<td>{fmt(row['old_total_return'], '%')}</td>"
            f"<td>{fmt(row['new_total_return'], '%')}</td>"
            f"<td>{fmt(row['return_delta'], '%')}</td>"
            f"<td>{fmt(row['win_rate_delta'], '%')}</td>"
            "</tr>"
        )
    return "\n".join(body)


def selected_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row.get("ticker", ""), row.get("behavior", ""), row.get("entry_rule", ""))


def selected_strategy_title(row: dict[str, str]) -> str:
    entry = ENTRY_LABELS.get(row.get("entry_rule", ""), row.get("entry_rule", "-"))
    timeframe = TIMEFRAME_LABELS.get(row.get("timeframe", ""), row.get("timeframe", "-"))
    return f"{entry} - {timeframe}"


def detail_chip(text: object, ltr: bool = False) -> str:
    css_class = "detail-chip ltr" if ltr else "detail-chip"
    return f'<span class="{css_class}">{html.escape(str(text))}</span>'


def parse_params(params: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in (params or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def entry_details_html(row: dict[str, str]) -> str:
    parts: list[str] = []
    params = parse_params(row.get("v1_params") or "")
    if params.get("lookback"):
        parts.append(detail_chip(f"فترة الاختراق: {params['lookback']}"))
    if params.get("period"):
        parts.append(detail_chip(f"فترة RSI: {params['period']}"))
    if params.get("cross_above"):
        parts.append(detail_chip(f"عبور RSI فوق {params['cross_above']}"))
    lookback = row.get("lookback") or ""
    if lookback and not (params.get("lookback") or params.get("period")):
        parts.append(detail_chip(f"فترة النظر: {lookback}"))
    volume_filter = row.get("volume_filter") or ""
    if volume_filter and num(row, "volume_filter") > 1:
        parts.append(detail_chip(f"حجم أعلى من المتوسط: {plain_fmt(volume_filter)}x"))
    if not parts:
        parts.append(detail_chip("شرط دخول مخصص للسهم"))
    return f'<div class="detail-parts">{"".join(parts)}</div>'


def exit_details_html(row: dict[str, str]) -> str:
    target = plain_fmt(row.get("target_pct"), "%")
    stop_pct = num(row, "initial_stop_pct")
    hold_days = row.get("hold_days") or "-"
    stop_model = STOP_LABELS.get(row.get("stop_model", ""), row.get("stop_model", "-"))
    parts = [
        detail_chip(f"الهدف: {target}"),
        detail_chip(f"المدة: {hold_days} يوم"),
    ]
    if 0 < stop_pct < 50:
        parts.append(detail_chip(f"وقف أولي: {plain_fmt(stop_pct, '%')}"))
    parts.append(detail_chip(f"الوقف: {stop_model}"))
    return f'<div class="detail-parts">{"".join(parts)}</div>'


def selected_reason(row: dict[str, str], diagnosis: dict[str, str] | None) -> str:
    if not diagnosis:
        return "اختيرت لأنها الأفضل ضمن اختبار السهم نفسه، وليست منقولة من سهم آخر."
    breakout = plain_fmt(diagnosis.get("breakout_success_rate_pct"), "%")
    pullback = plain_fmt(diagnosis.get("pullback_success_rate_pct"), "%")
    trend = plain_fmt(diagnosis.get("trend_return_pct"), "%")
    entry_rule = row.get("entry_rule", "")
    if "breakout" in entry_rule:
        edge = f"نجاح الاختراق التاريخي {breakout}"
    elif "rsi" in entry_rule:
        edge = f"استجابة الارتداد التاريخية {pullback}"
    else:
        edge = f"عائد الفترة {trend}"
    return f"مخصصة للسهم نفسه بناء على نتائج النسخة الأولى. نقطة القوة: {edge}. عائد السهم في فترة التشخيص {trend}."


def portfolio_effect_html(value: object) -> str:
    amount = num({"value": str(value)}, "value")
    css_class = "money positive" if amount >= 0 else "money negative"
    sign = "+" if amount > 0 else ""
    return f'<span class="{css_class}">{sign}${amount:,.2f}</span>'


def strategy_note(gate: dict[str, str], fallback: dict[str, str] | None) -> str:
    source = gate if gate else (fallback or {})
    win_rate = num(source, "verification_win_rate") or num(source, "win_rate")
    avg_return = num(source, "verification_avg_return") or num(source, "avg_return")
    total_return = num(source, "verification_total_return") or num(source, "total_return")
    if avg_return < 0 or total_return < 0:
        return "تحتاج مراجعة: التحقق منفردا ضعيف رغم أثرها في المحفظة."
    if win_rate < 50:
        return "تحتاج مراقبة: نسبة الفوز أقل من 50%."
    if win_rate >= 60 and avg_return > 0:
        return "جيدة: الفوز والعائد المتوسط داعمان."
    return "مقبولة: تحتاج مقارنة دورية مع البدائل."


def verification_details(gate: dict[str, str], fallback: dict[str, str] | None) -> str:
    source = gate if gate else (fallback or {})
    trades = source.get("verification_trades") or source.get("trades") or "-"
    win_rate = source.get("verification_win_rate") or source.get("win_rate") or ""
    avg_return = source.get("verification_avg_return") or source.get("avg_return") or ""
    total_return = source.get("verification_total_return") or source.get("total_return") or ""
    return (
        f"صفقات {html.escape(str(trades))}، "
        f"فوز {fmt(win_rate, '%')}، "
        f"متوسط {fmt(avg_return, '%')}، "
        f"إجمالي {fmt(total_return, '%')}"
    )


def selected_strategies_table(
    selected_rows: list[dict[str, str]],
    diagnosis_by_ticker: dict[str, dict[str, str]],
    gate_by_key: dict[tuple[str, str, str], dict[str, str]],
    verification_by_ticker: dict[str, dict[str, str]],
) -> str:
    if not selected_rows:
        return "<tr><td colspan='9'>لا توجد استراتيجيات معتمدة بعد.</td></tr>"
    order = {"swing": 0, "monthly": 1}
    body = []
    for row in sorted(selected_rows, key=lambda item: (item.get("ticker", ""), order.get(item.get("timeframe", ""), 9))):
        ticker = row.get("ticker", "")
        gate = gate_by_key.get(selected_key(row), {})
        diagnosis = diagnosis_by_ticker.get(ticker)
        portfolio_pnl = gate.get("portfolio_proxy_pnl") or ""
        strategy = selected_strategy_title(row)
        note = strategy_note(gate, verification_by_ticker.get(ticker))
        body.append(
            "<tr>"
            f"<td><strong>{html.escape(ticker)}</strong></td>"
            f"<td><span class='pill'>{html.escape(TIMEFRAME_LABELS.get(row.get('timeframe', ''), row.get('timeframe', '-')))}</span></td>"
            f"<td>{html.escape(strategy)}</td>"
            f"<td>{entry_details_html(row)}</td>"
            f"<td>{exit_details_html(row)}</td>"
            f"<td>{html.escape(selected_reason(row, diagnosis))}</td>"
            f"<td>{verification_details(gate, verification_by_ticker.get(ticker))}</td>"
            f"<td>{portfolio_effect_html(portfolio_pnl)}</td>"
            f"<td>{html.escape(note)}</td>"
            "</tr>"
        )
    return "\n".join(body)


def selected_strategies_section(rows: list[dict[str, str]]) -> str:
    selected_rows = read_optional(SELECTED_STRATEGIES)
    quality_rows = read_optional(QUALITY_GATE)
    selected_verification = read_optional(SELECTED_VERIFICATION)
    diagnosis_by_ticker = {row["ticker"]: row for row in rows}
    gate_by_key = {selected_key(row): row for row in quality_rows}
    verification_by_ticker = {row["ticker"]: row for row in selected_verification}
    unique_tickers = len({row.get("ticker", "") for row in selected_rows})
    needs_review = sum(
        1
        for row in selected_rows
        if strategy_note(gate_by_key.get(selected_key(row), {}), verification_by_ticker.get(row.get("ticker", ""))).startswith("تحتاج")
    )
    win_rates = [num(row, "verification_win_rate") for row in quality_rows if row.get("verification_win_rate")]
    avg_returns = [num(row, "verification_avg_return") for row in quality_rows if row.get("verification_avg_return")]
    cards = "".join(
        [
            card_html("الاستراتيجيات المستخدمة", len(selected_rows), "المعتمدة داخل المحفظة"),
            card_html("الأسهم المغطاة", unique_tickers, "الأسهم التسعة الحالية"),
            card_html("سوينق", sum(1 for row in selected_rows if row.get("timeframe") == "swing"), "استراتيجيات قصيرة/متوسطة"),
            card_html("شهري", sum(1 for row in selected_rows if row.get("timeframe") == "monthly"), "استراتيجيات أطول"),
            card_html("تحتاج مراجعة", needs_review, "ضعف تحقق أو فوز منخفض"),
            card_html("متوسط فوز التحقق", f"{mean(win_rates):.2f}%", f"متوسط العائد {mean(avg_returns):.2f}%"),
        ]
    )
    table = selected_strategies_table(selected_rows, diagnosis_by_ticker, gate_by_key, verification_by_ticker)
    return f"""
    <section class="panel" style="margin-top: 14px;">
      <h2>الاستراتيجيات المستخدمة</h2>
      <div class="sub" style="margin-bottom: 10px;">هذا القسم يركز على القرار العملي: ما الاستراتيجية، متى تدخل، كيف تخرج، وهل أداؤها منفردا أو داخل المحفظة يستحق المتابعة.</div>
      <section class="cards compact">{cards}</section>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>السهم</th><th>الإطار</th><th>الاستراتيجية</th><th>شروط الدخول</th>
              <th>إدارة الخروج</th><th>سبب الاستخدام</th><th>نتائج التحقق</th><th>أثر المحفظة</th><th>ملاحظة</th>
            </tr>
          </thead>
          <tbody>{table}</tbody>
        </table>
      </div>
    </section>
    """


def build_html(rows: list[dict[str, str]]) -> str:
    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = Counter(row["behavior"] for row in rows)
    best_breakout = sorted(rows, key=lambda row: num(row, "breakout_success_rate_pct"), reverse=True)
    best_pullback = sorted(rows, key=lambda row: num(row, "pullback_success_rate_pct"), reverse=True)
    best_trend = sorted(rows, key=lambda row: num(row, "trend_return_pct"), reverse=True)
    highest_risk = sorted(rows, key=lambda row: num(row, "max_drawdown_pct"))
    passed = sum(1 for row in rows if str(row.get("designed_pass", "")).lower() == "true")
    refinements = read_optional(REFINEMENTS)
    comparison = read_optional(COMPARISON)
    selected_section = selected_strategies_section(rows)

    cards = "".join(
        [
            card_html("عدد الأسهم", len(rows), "بعد التشخيص الأولي"),
            card_html("اختراق", counts.get("breakout", 0), "أسهم تميل لاختراق القمم"),
            card_html("ارتداد", counts.get("pullback_recovery", 0), "أسهم تتحسن بعد الهبوط"),
            card_html("ترند", counts.get("trend_following", 0), "أسهم تميل للاتجاه"),
            card_html("مختلط", counts.get("mixed_or_choppy", 0), "تحتاج حذر أو شروط إضافية"),
            card_html("تصاميم نجحت", passed, "تحقق أولي للاستراتيجيات المصممة"),
        ]
    )

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>اختبار الاستراتيجيات - النسخة الثانية</title>
  <style>
    :root {{
      --bg: #f5f7f9;
      --panel: #fff;
      --ink: #17212b;
      --muted: #65717d;
      --line: #d9e1e8;
      --blue: #1d5f8f;
      --green: #176b4d;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", Tahoma, Arial, sans-serif; }}
    main {{ max-width: 1260px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 4px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .sub {{ color: var(--muted); font-size: 14px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .card, .panel, table {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    .card {{ padding: 14px; }}
    .card span {{ display: block; color: var(--muted); font-size: 13px; }}
    .card strong {{ display: block; margin-top: 4px; font-size: 24px; }}
    .card small {{ display: block; margin-top: 5px; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin: 14px 0; }}
    .panel {{ padding: 14px; }}
    .ranked {{ list-style: none; padding: 0; margin: 0; }}
    .ranked li {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding: 8px 0; }}
    .ranked li:last-child {{ border-bottom: 0; }}
    .compact {{ margin: 0 0 12px; }}
    .pill, .status {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px; font-size: 12px; border: 1px solid var(--line); background: #f3f7fa; }}
    .detail-parts {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: flex-start; }}
    .detail-chip {{ display: inline-flex; align-items: center; min-height: 26px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 8px; background: #f8fafc; direction: rtl; unicode-bidi: isolate; white-space: nowrap; }}
    .ltr {{ direction: ltr; unicode-bidi: isolate; }}
    .money {{ direction: ltr; unicode-bidi: isolate; display: inline-block; font-weight: 700; }}
    .money.positive {{ color: var(--green); }}
    .money.negative {{ color: #a23b3b; }}
    .status.ok {{ color: #0f6b4a; border-color: #b9decf; background: #ecf8f2; }}
    .status.warn {{ color: #8a5a00; border-color: #ead6a6; background: #fff8e6; }}
    small {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px; text-align: right; font-size: 13px; vertical-align: top; }}
    th {{ background: #eaf0f5; color: #33404b; position: sticky; top: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    .num {{ direction: ltr; unicode-bidi: isolate; display: inline-block; }}
    .table-wrap {{ max-height: 620px; overflow: auto; border-radius: 8px; }}
    @media (max-width: 850px) {{
      main {{ padding: 18px; }}
      header {{ display: block; }}
      .table-wrap {{ overflow-x: auto; }}
      table {{ min-width: 1000px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>اختبار الاستراتيجيات - النسخة الثانية</h1>
        <div class="sub">تشخيص سلوك الأسهم أولًا، ثم تصميم استراتيجية مخصصة لكل سهم. آخر تحديث: {updated}</div>
      </div>
      <div class="sub">هذه ليست نسخة الصفقات بعد؛ هذه واجهة التشخيص والتصميم الأولي.</div>
    </header>
    <section class="cards">{cards}</section>
    <section class="grid">
      {top_list("أفضل أسهم للاختراق", best_breakout, "breakout_success_rate_pct")}
      {top_list("أفضل أسهم للارتداد", best_pullback, "pullback_success_rate_pct")}
      {top_list("أقوى ترند", best_trend, "trend_return_pct")}
      {top_list("أعلى مخاطر/سحب", highest_risk, "max_drawdown_pct")}
    </section>
    {selected_section}
    <section class="panel">
      <h2>تشخيص كل سهم والاستراتيجية المقترحة</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>السهم</th><th>السلوك</th><th>عائد الفترة</th><th>أقصى سحب</th><th>مدى يومي</th>
              <th>اختراقات</th><th>نجاح الاختراق</th><th>هبوط/ارتداد</th><th>نجاح الارتداد</th><th>تصميم الاستراتيجية</th>
              <th>قاعدة الدخول</th><th>الهدف</th><th>الوقف</th><th>صفقات التحقق</th><th>فوز التحقق</th><th>عائد التحقق</th><th>نجح؟</th>
            </tr>
          </thead>
          <tbody>{rows_table(rows)}</tbody>
        </table>
      </div>
    </section>
    <section class="panel" style="margin-top: 14px;">
      <h2>تحسين التصميمات التي فشلت</h2>
      <div class="sub" style="margin-bottom: 10px;">هذا الجدول لا يطارد أفضل رقم، بل يشرح لماذا فشل التصميم الأولي وما التعديل المنطقي المقترح.</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>السهم</th><th>السلوك</th><th>سبب الفشل</th><th>الدخول الحالي</th><th>الدخول المقترح</th>
              <th>هدف مقترح</th><th>وقف مقترح</th><th>فوز سابق</th><th>التعديل المقترح</th>
            </tr>
          </thead>
          <tbody>{refinements_table(refinements)}</tbody>
        </table>
      </div>
    </section>
    <section class="panel" style="margin-top: 14px;">
      <h2>مقارنة التصميم الأولي مع التصميم المحسن</h2>
      <div class="sub" style="margin-bottom: 10px;">نختار v2 فقط إذا حسّن العائد، وإلا نحتفظ بتصميم v1.</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>السهم</th><th>النسخة المختارة</th><th>نجاح v1</th><th>نجاح v2</th>
              <th>عائد v1</th><th>عائد v2</th><th>فرق العائد</th><th>فرق الفوز</th>
            </tr>
          </thead>
          <tbody>{comparison_table(comparison)}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    rows = read_rows()
    strategies = {row["ticker"]: row for row in read_optional(STRATEGIES)}
    verification = {row["ticker"]: row for row in read_optional(VERIFICATION)}
    for row in rows:
        row.update(strategies.get(row["ticker"], {}))
        row.update(verification.get(row["ticker"], {}))
    DASHBOARD.write_text(build_html(rows), encoding="utf-8")
    print(f"Dashboard written: {DASHBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
