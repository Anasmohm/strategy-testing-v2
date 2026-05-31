#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
TRADES_CSV = REPORTS / "paper_trades_v2.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v2.csv"
SHADOW_CSV = REPORTS / "stop_shadow_summary_v2.csv"
OUT = REPORTS / "data_analyst_lab.html"
JSON_OUT = REPORTS / "data_analyst_lab.json"


KEY_COLUMNS = [
    "id",
    "ticker",
    "timeframe",
    "entry_date",
    "close_date",
    "status",
    "outcome",
    "capital",
    "realized_pnl",
    "realized_pnl_pct",
    "unrealized_pnl",
    "entry_rule",
    "strategy_id",
]


def fnum(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def normal_p_value(z_score: float) -> float:
    # Two-sided normal approximation. Good enough as a screening signal, not a formal statistical audit.
    return 2.0 * (1.0 - statistics.NormalDist().cdf(abs(z_score)))


def welch_test(a: list[float], b: list[float]) -> dict[str, float]:
    if len(a) < 2 or len(b) < 2:
        return {"delta": mean(a) - mean(b), "z": 0.0, "p": 1.0, "effect": 0.0}
    ma = mean(a)
    mb = mean(b)
    va = statistics.variance(a)
    vb = statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    z = (ma - mb) / se if se else 0.0
    pooled = math.sqrt((va + vb) / 2.0) if (va + vb) > 0 else 0.0
    effect = (ma - mb) / pooled if pooled else 0.0
    return {"delta": ma - mb, "z": z, "p": normal_p_value(z), "effect": effect}


def month_key(date_text: str) -> str:
    return date_text[:7] if date_text else "غير محدد"


def load_trades() -> list[dict[str, object]]:
    trades: list[dict[str, object]] = []
    for row in read_csv(TRADES_CSV):
        status = row.get("status", "")
        realized = fnum(row.get("realized_pnl"))
        unrealized = fnum(row.get("unrealized_pnl"))
        pnl = realized if status == "CLOSED" else unrealized
        pnl_pct = fnum(row.get("realized_pnl_pct"))
        if status != "CLOSED":
            entry = fnum(row.get("entry_price"))
            latest = fnum(row.get("latest_price"))
            pnl_pct = ((latest - entry) / entry * 100.0) if entry else 0.0
        trades.append(
            {
                **row,
                "status": status,
                "ticker": row.get("ticker", ""),
                "timeframe": row.get("timeframe", ""),
                "entry_rule": row.get("entry_rule", ""),
                "strategy_id": row.get("strategy_id", ""),
                "entry_month": month_key(row.get("entry_date", "")),
                "capital_num": fnum(row.get("capital")),
                "pnl_num": round(pnl, 2),
                "pnl_pct_num": round(pnl_pct, 2),
                "shares_num": inum(row.get("shares")),
            }
        )
    return trades


def load_equity() -> list[dict[str, object]]:
    return [{"date": row.get("date", ""), "value": fnum(row.get("value"))} for row in read_csv(EQUITY_CSV)]


def group_stats(trades: list[dict[str, object]], key: str) -> list[dict[str, object]]:
    buckets: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        buckets[str(trade.get(key) or "غير محدد")].append(trade)
    rows = []
    for name, items in buckets.items():
        closed = [t for t in items if t.get("status") == "CLOSED"]
        wins = [t for t in closed if fnum(t.get("pnl_num")) > 0]
        losses = [t for t in closed if fnum(t.get("pnl_num")) < 0]
        pnl = sum(fnum(t.get("pnl_num")) for t in items)
        cap = sum(fnum(t.get("capital_num")) for t in items)
        pcts = [fnum(t.get("pnl_pct_num")) for t in closed]
        rows.append(
            {
                "name": name,
                "trades": len(items),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
                "pnl": round(pnl, 2),
                "capital": round(cap, 2),
                "return_on_capital": round(pnl / cap * 100.0, 2) if cap else 0.0,
                "avg_pct": round(mean(pcts), 2),
                "median_pct": round(median(pcts), 2),
                "worst_pct": round(min(pcts), 2) if pcts else 0.0,
                "best_pct": round(max(pcts), 2) if pcts else 0.0,
            }
        )
    return sorted(rows, key=lambda row: fnum(row["pnl"]), reverse=True)


def data_profile(raw_rows: list[dict[str, str]], trades: list[dict[str, object]]) -> dict[str, object]:
    columns = list(raw_rows[0].keys()) if raw_rows else []
    ids = [row.get("id", "") for row in raw_rows]
    duplicate_ids = sum(count - 1 for count in Counter(ids).values() if count > 1)
    missing = []
    for col in KEY_COLUMNS:
        if col not in columns:
            missing.append({"column": col, "missing": len(raw_rows), "pct": 100.0})
            continue
        count = sum(1 for row in raw_rows if row.get(col, "") in ("", None))
        missing.append({"column": col, "missing": count, "pct": round(count / len(raw_rows) * 100.0, 2) if raw_rows else 0.0})
    pcts = [fnum(t.get("pnl_pct_num")) for t in trades if t.get("status") == "CLOSED"]
    q1 = quantile(pcts, 0.25)
    q3 = quantile(pcts, 0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    outliers = [v for v in pcts if v < low or v > high]
    dates = sorted([str(t.get("entry_date", "")) for t in trades if t.get("entry_date")])
    return {
        "rows": len(raw_rows),
        "columns": len(columns),
        "duplicate_ids": duplicate_ids,
        "missing": missing,
        "outlier_count": len(outliers),
        "outlier_low": round(low, 2),
        "outlier_high": round(high, 2),
        "start_date": dates[0] if dates else "",
        "end_date": dates[-1] if dates else "",
    }


def grade_by_p_value(p_value: float, effect: float) -> str:
    if p_value <= 0.05 and abs(effect) >= 0.35:
        return "ثقة عالية"
    if p_value <= 0.15 or abs(effect) >= 0.25:
        return "ثقة متوسطة"
    return "ثقة منخفضة"


def hypothesis_timeframe(closed: list[dict[str, object]], by_timeframe: list[dict[str, object]]) -> dict[str, object]:
    swing = [fnum(t.get("pnl_pct_num")) for t in closed if t.get("timeframe") == "swing"]
    monthly = [fnum(t.get("pnl_pct_num")) for t in closed if t.get("timeframe") == "monthly"]
    test = welch_test(swing, monthly)
    best = max(by_timeframe, key=lambda row: fnum(row["return_on_capital"])) if by_timeframe else {}
    return {
        "title": "هل السوينق أعلى كفاءة من الشهري؟",
        "grade": grade_by_p_value(test["p"], test["effect"]),
        "what": f"متوسط السوينق {mean(swing):.2f}% مقابل الشهري {mean(monthly):.2f}%. أفضل إطار بكفاءة رأس المال: {best.get('name', '-')}.",
        "so_what": "هذا يحدد هل توزيع الكاش بين الأطر مبني على فرق حقيقي أو مجرد انطباع من إجمالي الربح.",
        "now_what": "إذا بقي الفرق لصالح إطار معين في اختبارات قادمة، نختبر رفع وزنه تدريجيًا بدل التغيير المباشر.",
        "evidence": {
            "swing_count": len(swing),
            "monthly_count": len(monthly),
            "delta_pct": round(test["delta"], 2),
            "p_value": round(test["p"], 4),
            "effect_size": round(test["effect"], 2),
        },
    }


def hypothesis_concentration(by_ticker: list[dict[str, object]], total_pnl: float) -> dict[str, object]:
    positives = [row for row in by_ticker if fnum(row["pnl"]) > 0]
    top = positives[0] if positives else {}
    shares = [(fnum(row["pnl"]) / total_pnl) for row in positives if total_pnl]
    hhi = sum(share * share for share in shares) * 10000.0
    top_share = fnum(top.get("pnl")) / total_pnl * 100.0 if total_pnl else 0.0
    grade = "ثقة عالية" if top_share >= 25 or hhi >= 1800 else "ثقة متوسطة" if top_share >= 15 or hhi >= 1000 else "ثقة منخفضة"
    return {
        "title": "هل الربح مركز في سهم واحد؟",
        "grade": grade,
        "what": f"أكبر مساهم في الربح هو {top.get('name', '-')} بنسبة {top_share:.2f}% من إجمالي الربح. مؤشر التركيز HHI = {hhi:.0f}.",
        "so_what": "لو كان الربح مركزًا، فرفع وزن هذا السهم قد يحسن الأداء لكنه يزيد الاعتماد على مسار واحد.",
        "now_what": "استخدم هذا كتحذير عند رفع الوزن: نرفع فقط إذا ظل السهم قويًا بعد فحص الخسائر والسيولة.",
        "evidence": {
            "top_ticker": top.get("name", ""),
            "top_contribution_pct": round(top_share, 2),
            "hhi": round(hhi, 0),
        },
    }


def hypothesis_position_size(closed: list[dict[str, object]]) -> dict[str, object]:
    caps = [fnum(t.get("capital_num")) for t in closed]
    q25 = quantile(caps, 0.25)
    q75 = quantile(caps, 0.75)
    small = [fnum(t.get("pnl_pct_num")) for t in closed if fnum(t.get("capital_num")) <= q25]
    large = [fnum(t.get("pnl_pct_num")) for t in closed if fnum(t.get("capital_num")) >= q75]
    test = welch_test(large, small)
    large_loss_rate = sum(1 for v in large if v < 0) / len(large) * 100.0 if large else 0.0
    small_loss_rate = sum(1 for v in small if v < 0) / len(small) * 100.0 if small else 0.0
    return {
        "title": "هل حجم الصفقة الأكبر يرفع الخطر؟",
        "grade": grade_by_p_value(test["p"], test["effect"]),
        "what": f"متوسط الصفقات الكبيرة {mean(large):.2f}% مقابل الصغيرة {mean(small):.2f}%. خسارة الكبيرة {large_loss_rate:.1f}% مقابل الصغيرة {small_loss_rate:.1f}%.",
        "so_what": "هذا يختبر هل زيادة رأس المال أو حد الصفقة قد تضغط الجودة أو أن السوق يستوعب الحجم.",
        "now_what": "إذا الصفقات الكبيرة أقل جودة، نخلي حد الصفقة الأعلى مرنًا حسب السيولة وجودة السهم لا رقم ثابت.",
        "evidence": {
            "large_count": len(large),
            "small_count": len(small),
            "capital_q25": round(q25, 2),
            "capital_q75": round(q75, 2),
            "delta_pct": round(test["delta"], 2),
            "p_value": round(test["p"], 4),
            "effect_size": round(test["effect"], 2),
        },
    }


def hypothesis_stop_shadow(shadow_rows: list[dict[str, str]]) -> dict[str, object]:
    base = next((row for row in shadow_rows if row.get("scenario") == "baseline"), {})
    shadow = next((row for row in shadow_rows if row.get("scenario") == "shadow_tighter_stop"), {})
    diff = fnum(shadow.get("portfolio_value")) - fnum(base.get("portfolio_value"))
    loss_diff = inum(shadow.get("losses")) - inum(base.get("losses"))
    worst_improvement = fnum(shadow.get("worst_loss_pct")) - fnum(base.get("worst_loss_pct"))
    grade = "ثقة عالية" if diff < 0 and loss_diff > 0 else "ثقة متوسطة"
    return {
        "title": "هل تضييق الوقف يستحق الاعتماد؟",
        "grade": grade,
        "what": f"الوقف الأقرب خفض قيمة المحفظة بمقدار ${diff:,.2f}، وزاد الخسائر {loss_diff}، لكنه حسّن أسوأ خسارة {worst_improvement:.2f} نقطة.",
        "so_what": "التحسين في أسوأ خسارة لا يكفي إذا كان يقتل صفقات رابحة ويخفض قيمة المحفظة.",
        "now_what": "لا نعتمد تضييق الوقف كقاعدة عامة. نختبره فقط على الأسهم التي تملك أسوأ خسائر متكررة.",
        "evidence": {
            "value_delta": round(diff, 2),
            "loss_count_delta": loss_diff,
            "worst_loss_delta_points": round(worst_improvement, 2),
            "winners_turned_loss": inum(shadow.get("winners_turned_loss")),
        },
    }


def hypothesis_entry_rules(by_entry: list[dict[str, object]]) -> dict[str, object]:
    eligible = [row for row in by_entry if inum(row["closed"]) >= 10]
    if not eligible:
        eligible = by_entry
    best = max(eligible, key=lambda row: fnum(row["return_on_capital"])) if eligible else {}
    worst = min(eligible, key=lambda row: fnum(row["return_on_capital"])) if eligible else {}
    spread = fnum(best.get("return_on_capital")) - fnum(worst.get("return_on_capital"))
    grade = "ثقة عالية" if spread >= 2 else "ثقة متوسطة" if spread >= 1 else "ثقة منخفضة"
    return {
        "title": "هل قواعد الدخول متباينة بما يكفي؟",
        "grade": grade,
        "what": f"أفضل قاعدة {best.get('name', '-')} بعائد رأس مال {fnum(best.get('return_on_capital')):.2f}%، وأضعف قاعدة {worst.get('name', '-')} بعائد {fnum(worst.get('return_on_capital')):.2f}%.",
        "so_what": "إذا الفرق واضح، فليست كل الإشارات متساوية حتى لو كانت كلها داخل المحفظة.",
        "now_what": "نستخدم هذا لاحقًا في مختبر الاستراتيجيات: رفع وزن القاعدة الأقوى أو اختبار شروط إضافية للقاعدة الأضعف.",
        "evidence": {
            "best_rule": best.get("name", ""),
            "worst_rule": worst.get("name", ""),
            "spread_return_on_capital": round(spread, 2),
        },
    }


def hypothesis_months(by_month: list[dict[str, object]], total_pnl: float) -> dict[str, object]:
    top = by_month[0] if by_month else {}
    negative = [row for row in by_month if fnum(row["pnl"]) < 0]
    top_share = fnum(top.get("pnl")) / total_pnl * 100.0 if total_pnl else 0.0
    grade = "ثقة عالية" if top_share >= 20 or negative else "ثقة متوسطة"
    return {
        "title": "هل الأداء موسمي أو مستقر؟",
        "grade": grade,
        "what": f"أقوى شهر {top.get('name', '-')} ساهم بـ {top_share:.2f}% من الربح. عدد الأشهر السلبية: {len(negative)}.",
        "so_what": "إذا كان شهر واحد يقود جزءًا كبيرًا من الربح، لا نبالغ في قراءة الأداء السنوي بدون اختبار فترات أخرى.",
        "now_what": "نراقب الأشهر القائدة والضاغطة، ونستخدمها كمدخل لتفسير الأخبار لا كتعديل مباشر.",
        "evidence": {
            "top_month": top.get("name", ""),
            "top_month_contribution_pct": round(top_share, 2),
            "negative_month_count": len(negative),
        },
    }


def max_drawdown(equity: list[dict[str, object]]) -> float:
    peak = 0.0
    worst = 0.0
    for row in equity:
        value = fnum(row.get("value"))
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak * 100.0)
    return round(worst, 2)


def build_payload() -> dict[str, object]:
    raw_rows = read_csv(TRADES_CSV)
    trades = load_trades()
    equity = load_equity()
    shadow = read_csv(SHADOW_CSV)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    wins = [t for t in closed if fnum(t.get("pnl_num")) > 0]
    losses = [t for t in closed if fnum(t.get("pnl_num")) < 0]
    total_pnl = sum(fnum(t.get("pnl_num")) for t in trades)
    initial_value = fnum(equity[0]["value"]) if equity else 0.0
    final_value = fnum(equity[-1]["value"]) if equity else 0.0

    by_ticker = group_stats(trades, "ticker")
    by_timeframe = group_stats(trades, "timeframe")
    by_entry = group_stats(trades, "entry_rule")
    by_month = group_stats(trades, "entry_month")

    hypotheses = [
        hypothesis_timeframe(closed, by_timeframe),
        hypothesis_concentration(by_ticker, total_pnl),
        hypothesis_position_size(closed),
        hypothesis_stop_shadow(shadow),
        hypothesis_entry_rules(by_entry),
        hypothesis_months(by_month, total_pnl),
    ]
    profile = data_profile(raw_rows, trades)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "rows": len(trades),
            "closed": len(closed),
            "open": len(trades) - len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
            "total_pnl": round(total_pnl, 2),
            "initial_value": round(initial_value, 2),
            "final_value": round(final_value, 2),
            "return_pct": round((final_value - initial_value) / initial_value * 100.0, 2) if initial_value else 0.0,
            "max_drawdown_pct": max_drawdown(equity),
            "avg_win_pct": round(mean([fnum(t.get("pnl_pct_num")) for t in wins]), 2),
            "avg_loss_pct": round(mean([fnum(t.get("pnl_pct_num")) for t in losses]), 2),
        },
        "profile": profile,
        "hypotheses": hypotheses,
        "tables": {
            "ticker": by_ticker,
            "timeframe": by_timeframe,
            "entry_rule": by_entry,
            "month": by_month,
        },
    }


def js_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def render(payload: dict[str, object]) -> str:
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مختبر محلل البيانات</title>
  <style>
    :root {{
      --bg:#f4f7fa; --panel:#fff; --text:#071827; --muted:#60758b; --line:#d7e2ec;
      --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    .wrap {{ max-width:1520px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:28px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:18px; }}
    a {{ color:var(--blue); text-decoration:none; }}
    .sub,.note {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .btn,select,input {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; font:inherit; color:var(--text); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .panel,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .metric .label {{ color:var(--muted); }}
    .metric .value {{ direction:ltr; text-align:right; font-size:30px; font-weight:800; margin-top:6px; }}
    .hypothesis {{ display:grid; grid-template-columns:220px 1fr; gap:12px; border-top:1px solid var(--line); padding:14px 0; }}
    .hypothesis:first-child {{ border-top:0; }}
    .grade {{ display:inline-flex; border-radius:999px; padding:4px 10px; font-weight:700; border:1px solid var(--line); background:#f8fbfd; }}
    .grade.high {{ color:var(--green); border-color:#b7decf; background:#edf8f4; }}
    .grade.mid {{ color:var(--amber); border-color:#f0d394; background:#fff8e7; }}
    .grade.low {{ color:var(--muted); }}
    .qa {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:10px; }}
    .qa div {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fbfdff; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#24364d; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }}
    .pos {{ color:var(--green); font-weight:700; }}
    .neg {{ color:var(--red); font-weight:700; }}
    .warn {{ color:var(--amber); font-weight:700; }}
    .bar-row {{ display:grid; grid-template-columns:130px 1fr 110px; gap:10px; align-items:center; margin:8px 0; }}
    .bar-track {{ height:12px; background:#eef3f7; border-radius:999px; overflow:hidden; direction:ltr; }}
    .bar {{ height:100%; border-radius:999px; background:var(--blue); }}
    .bar.negbar {{ background:var(--red); }}
    .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    @media (max-width:1000px) {{
      header {{ display:block; }}
      .grid,.two,.qa,.hypothesis {{ grid-template-columns:1fr; }}
      .nav {{ margin-top:12px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>مختبر محلل البيانات</h1>
        <div class="sub">تجربة مهارة Data Analyst: تحويل نتائج المحفظة إلى فرضيات قابلة للاختبار قبل أي تعديل.</div>
        <div class="note">آخر توليد: <span id="generatedAt"></span></div>
      </div>
      <nav class="nav">
        <a class="btn" href="paper_portfolio_v2_dashboard.html">المحفظة</a>
        <a class="btn" href="paper_portfolio_v2_analytics.html">مركز القرار</a>
      </nav>
    </header>

    <section class="grid" id="summaryCards"></section>

    <section class="panel" style="margin-top:14px;">
      <h2>الفرضيات المختبرة</h2>
      <div id="hypotheses"></div>
    </section>

    <section class="two" style="margin-top:14px;">
      <div class="panel">
        <h2>فحص جودة البيانات</h2>
        <div id="profile"></div>
      </div>
      <div class="panel">
        <h2>تركيز الربح حسب السهم</h2>
        <div id="tickerBars"></div>
      </div>
    </section>

    <section class="panel" style="margin-top:14px;">
      <h2>أفضل وأسوأ القراءات</h2>
      <div style="overflow:auto;">
        <table>
          <thead>
            <tr>
              <th>الفئة</th>
              <th>البند</th>
              <th>الصفقات</th>
              <th>الفوز</th>
              <th>الربح</th>
              <th>عائد رأس المال</th>
              <th>متوسط %</th>
              <th>أسوأ %</th>
            </tr>
          </thead>
          <tbody id="rankRows"></tbody>
        </table>
      </div>
    </section>
  </div>
  <script id="payload" type="application/json">{js_payload(payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const money = (n) => '$' + Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    const pct = (n) => Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + '%';
    const cls = (n) => Number(n || 0) < 0 ? 'neg' : 'pos';
    document.getElementById('generatedAt').textContent = payload.generated_at;

    function card(label, value, detail, tone='') {{
      return `<article class="card metric"><div class="label">${{label}}</div><div class="value ${{tone}}">${{value}}</div><div class="note">${{detail}}</div></article>`;
    }}

    function renderSummary() {{
      const s = payload.summary;
      document.getElementById('summaryCards').innerHTML = [
        card('قيمة المحفظة', money(s.final_value), 'من ' + money(s.initial_value)),
        card('عائد الفترة', pct(s.return_pct), 'قراءة المحفظة الحالية', cls(s.return_pct)),
        card('نسبة الفوز', pct(s.win_rate), `${{s.wins}} رابحة / ${{s.losses}} خاسرة`),
        card('السحب الأقصى', pct(s.max_drawdown_pct), 'أكبر هبوط من قمة', 'neg'),
      ].join('');
    }}

    function gradeClass(text) {{
      if (text.includes('عالية')) return 'high';
      if (text.includes('متوسطة')) return 'mid';
      return 'low';
    }}

    function renderHypotheses() {{
      document.getElementById('hypotheses').innerHTML = payload.hypotheses.map((h) => `
        <article class="hypothesis">
          <div>
            <h3>${{h.title}}</h3>
            <span class="grade ${{gradeClass(h.grade)}}">${{h.grade}}</span>
          </div>
          <div>
            <div class="qa">
              <div><strong>ماذا وجدنا؟</strong><br>${{h.what}}</div>
              <div><strong>لماذا يهم؟</strong><br>${{h.so_what}}</div>
              <div><strong>وش نسوي؟</strong><br>${{h.now_what}}</div>
            </div>
            <div class="note" style="margin-top:8px;">الأدلة: <span class="ltr">${{JSON.stringify(h.evidence)}}</span></div>
          </div>
        </article>
      `).join('');
    }}

    function renderProfile() {{
      const p = payload.profile;
      const missingRows = p.missing
        .filter(r => Number(r.missing) > 0)
        .map(r => `<tr><td>${{r.column}}</td><td class="num">${{r.missing}}</td><td class="num">${{pct(r.pct)}}</td></tr>`)
        .join('') || '<tr><td colspan="3">لا توجد فراغات مؤثرة في الأعمدة الأساسية.</td></tr>';
      document.getElementById('profile').innerHTML = `
        <div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr)); margin-bottom:10px;">
          <div class="card"><div class="label">الصفوف</div><div class="value num">${{p.rows}}</div></div>
          <div class="card"><div class="label">الأعمدة</div><div class="value num">${{p.columns}}</div></div>
          <div class="card"><div class="label">مكرر ID</div><div class="value num">${{p.duplicate_ids}}</div></div>
          <div class="card"><div class="label">قيم شاذة</div><div class="value num">${{p.outlier_count}}</div></div>
        </div>
        <div class="note">الفترة: ${{p.start_date}} إلى ${{p.end_date}}. نطاق الشذوذ التقريبي: ${{pct(p.outlier_low)}} إلى ${{pct(p.outlier_high)}}.</div>
        <table style="margin-top:10px;"><thead><tr><th>العمود</th><th>الفراغات</th><th>النسبة</th></tr></thead><tbody>${{missingRows}}</tbody></table>
      `;
    }}

    function renderTickerBars() {{
      const rows = payload.tables.ticker.slice(0, 9);
      const maxAbs = Math.max(...rows.map(r => Math.abs(Number(r.pnl || 0))), 1);
      document.getElementById('tickerBars').innerHTML = rows.map((r) => {{
        const w = Math.max(2, Math.abs(Number(r.pnl || 0)) / maxAbs * 100);
        return `<div class="bar-row"><div><strong>${{r.name}}</strong></div><div class="bar-track"><div class="bar ${{Number(r.pnl) < 0 ? 'negbar' : ''}}" style="width:${{w}}%"></div></div><div class="num ${{cls(r.pnl)}}">${{money(r.pnl)}}</div></div>`;
      }}).join('');
    }}

    function renderRanks() {{
      const blocks = [
        ['السهم', payload.tables.ticker],
        ['الإطار', payload.tables.timeframe],
        ['قاعدة الدخول', payload.tables.entry_rule],
        ['الشهر', payload.tables.month],
      ];
      const rows = [];
      blocks.forEach(([label, items]) => {{
        items.slice(0, 5).forEach((r) => rows.push([label, r]));
      }});
      document.getElementById('rankRows').innerHTML = rows.map(([label, r]) => `
        <tr>
          <td>${{label}}</td>
          <td><strong class="ltr">${{r.name}}</strong></td>
          <td class="num">${{r.closed}}</td>
          <td class="num">${{pct(r.win_rate)}}</td>
          <td class="num ${{cls(r.pnl)}}">${{money(r.pnl)}}</td>
          <td class="num ${{cls(r.return_on_capital)}}">${{pct(r.return_on_capital)}}</td>
          <td class="num ${{cls(r.avg_pct)}}">${{pct(r.avg_pct)}}</td>
          <td class="num neg">${{pct(r.worst_pct)}}</td>
        </tr>
      `).join('');
    }}

    renderSummary();
    renderHypotheses();
    renderProfile();
    renderTickerBars();
    renderRanks();
  </script>
</body>
</html>
"""


def main() -> int:
    payload = build_payload()
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    OUT.write_text(render(payload), encoding="utf-8", newline="\n")
    print(f"Data analyst lab: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
