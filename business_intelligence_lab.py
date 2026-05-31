#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
TRADES_CSV = REPORTS / "paper_trades_v2.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v2.csv"
V1_V2_CSV = REPORTS / "v1_vs_v2_nine_stock_comparison.csv"
FINANCIAL_JSON = REPORTS / "financial_diagnostics_lab.json"
OUT = REPORTS / "business_intelligence_lab.html"

TARGET_ANNUAL_RETURN = 70.0


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: Any, default: int = 0) -> int:
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


def load_financial_payload() -> dict[str, Any]:
    if not FINANCIAL_JSON.exists():
        return {}
    return json.loads(FINANCIAL_JSON.read_text(encoding="utf-8"))


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def cls(value: Any) -> str:
    return "pos" if fnum(value) >= 0 else "neg"


def parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def trade_pnl(trade: dict[str, str]) -> float:
    if trade.get("status") == "OPEN":
        return fnum(trade.get("unrealized_pnl"))
    return fnum(trade.get("realized_pnl"))


def trade_pct(trade: dict[str, str]) -> float:
    if trade.get("status") == "OPEN":
        return fnum(trade.get("unrealized_pnl_pct"))
    return fnum(trade.get("realized_pnl_pct"))


def equity_stats(equity: list[dict[str, str]]) -> dict[str, Any]:
    points = [
        {"date": row.get("date", ""), "value": fnum(row.get("value"))}
        for row in equity
        if row.get("date")
    ]
    if not points:
        return {
            "initial": 0.0,
            "current": 0.0,
            "period_return_pct": 0.0,
            "target_value": 0.0,
            "target_return_pct": 0.0,
            "target_gap": 0.0,
            "max_drawdown_pct": 0.0,
            "start_date": "",
            "end_date": "",
            "years": 0.0,
        }
    initial = points[0]["value"]
    current = points[-1]["value"]
    start_date = parse_date(points[0]["date"])
    end_date = parse_date(points[-1]["date"])
    years = max((end_date - start_date).days / 365.25, 1 / 365.25)
    period_return_pct = ((current / initial) - 1) * 100 if initial else 0.0
    target_value = initial * ((1 + TARGET_ANNUAL_RETURN / 100) ** years)
    target_return_pct = ((target_value / initial) - 1) * 100 if initial else 0.0
    peak = points[0]["value"]
    max_drawdown = 0.0
    for point in points:
        peak = max(peak, point["value"])
        if peak > 0:
            max_drawdown = min(max_drawdown, (point["value"] / peak - 1) * 100)
    return {
        "initial": initial,
        "current": current,
        "period_return_pct": period_return_pct,
        "target_value": target_value,
        "target_return_pct": target_return_pct,
        "target_gap": current - target_value,
        "max_drawdown_pct": max_drawdown,
        "start_date": points[0]["date"],
        "end_date": points[-1]["date"],
        "years": years,
        "points": points,
    }


def group_stats(trades: list[dict[str, str]], key: str, total_pnl: float) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for trade in trades:
        name = trade.get(key, "") or "-"
        buckets[name].append(trade)
    rows: list[dict[str, Any]] = []
    for name, items in buckets.items():
        closed = [trade for trade in items if trade.get("status") == "CLOSED"]
        open_items = [trade for trade in items if trade.get("status") == "OPEN"]
        wins = [trade for trade in closed if fnum(trade.get("realized_pnl")) >= 0]
        losses = [trade for trade in closed if fnum(trade.get("realized_pnl")) < 0]
        pnl = sum(trade_pnl(trade) for trade in items)
        avg_pct = sum(trade_pct(trade) for trade in items) / len(items) if items else 0.0
        worst_pct = min((trade_pct(trade) for trade in items), default=0.0)
        contribution_pct = (pnl / total_pnl * 100) if total_pnl else 0.0
        win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
        rows.append(
            {
                "name": name,
                "trades": len(items),
                "closed": len(closed),
                "open": len(open_items),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": win_rate,
                "pnl": pnl,
                "avg_pct": avg_pct,
                "worst_pct": worst_pct,
                "contribution_pct": contribution_pct,
            }
        )
    return sorted(rows, key=lambda row: row["pnl"], reverse=True)


def month_key(trade: dict[str, str]) -> str:
    return str(trade.get("entry_date", ""))[:7] or "-"


def add_month(trades: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched = []
    for trade in trades:
        row = dict(trade)
        row["entry_month"] = month_key(row)
        enriched.append(row)
    return enriched


def v1_v2_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    v1_pnl = sum(fnum(row.get("v1_pnl")) for row in rows)
    v2_pnl = sum(fnum(row.get("v2_pnl")) for row in rows)
    better_v2 = [row for row in rows if fnum(row.get("pnl_delta")) > 0]
    worse_v2 = [row for row in rows if fnum(row.get("pnl_delta")) < 0]
    worst = sorted(worse_v2, key=lambda row: fnum(row.get("pnl_delta")))[:3]
    best = sorted(better_v2, key=lambda row: fnum(row.get("pnl_delta")), reverse=True)[:3]
    return {
        "v1_pnl": v1_pnl,
        "v2_pnl": v2_pnl,
        "delta": v2_pnl - v1_pnl,
        "better_count": len(better_v2),
        "worse_count": len(worse_v2),
        "best": best,
        "worst": worst,
    }


def portfolio_quality(trades: list[dict[str, str]], equity: dict[str, Any], financial: dict[str, Any]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    open_trades = [trade for trade in trades if trade.get("status") == "OPEN"]
    wins = [trade for trade in closed if fnum(trade.get("realized_pnl")) >= 0]
    losses = [trade for trade in closed if fnum(trade.get("realized_pnl")) < 0]
    avg_win = sum(fnum(trade.get("realized_pnl_pct")) for trade in wins) / len(wins) if wins else 0.0
    avg_loss = sum(fnum(trade.get("realized_pnl_pct")) for trade in losses) / len(losses) if losses else 0.0
    open_value = sum(fnum(trade.get("market_value")) for trade in open_trades)
    open_pnl = sum(fnum(trade.get("unrealized_pnl")) for trade in open_trades)
    high_risk_open = [
        trade for trade in financial.get("open_trades", []) if str(trade.get("latest_risk", "")) == "مرتفع"
    ]
    total_pnl = equity["current"] - equity["initial"]
    by_ticker = group_stats(trades, "ticker", total_pnl)
    positive = [row for row in by_ticker if row["pnl"] > 0]
    top3_contribution = sum(row["pnl"] for row in positive[:3]) / total_pnl * 100 if total_pnl else 0.0
    return {
        "closed": len(closed),
        "open": len(open_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "payoff_ratio": abs(avg_win / avg_loss) if avg_loss else 0.0,
        "open_value": open_value,
        "open_pnl": open_pnl,
        "open_exposure_pct": open_value / equity["current"] * 100 if equity["current"] else 0.0,
        "high_risk_open": len(high_risk_open),
        "top3_contribution_pct": top3_contribution,
        "top_ticker": by_ticker[0] if by_ticker else {},
    }


def decision_items(equity: dict[str, Any], quality: dict[str, Any], v1v2: dict[str, Any], financial: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    target_gap_pct = equity["period_return_pct"] - equity["target_return_pct"]
    items.append(
        {
            "title": "الهدف السنوي",
            "value": "متجاوز" if target_gap_pct >= 0 else "أقل من الهدف",
            "tone": "pos" if target_gap_pct >= 0 else "neg",
            "body": f"عائد الفترة أعلى من هدف 70% سنويًا بفارق {pct(target_gap_pct)}.",
        }
    )
    concentration = quality["top3_contribution_pct"]
    items.append(
        {
            "title": "تركيز الربح",
            "value": pct(concentration),
            "tone": "warn" if concentration > 65 else "pos",
            "body": "الربح مركز في أعلى 3 أسهم؛ زيادة الوزن تحتاج مراقبة حتى لا يصبح القرار معتمدًا على سهم واحد.",
        }
    )
    items.append(
        {
            "title": "الصفقات المفتوحة",
            "value": f"{quality['high_risk_open']} عالية الخطر",
            "tone": "warn" if quality["high_risk_open"] else "pos",
            "body": f"الربح غير المحقق الحالي {money(quality['open_pnl'])}، والانكشاف المفتوح {pct(quality['open_exposure_pct'])}.",
        }
    )
    items.append(
        {
            "title": "اختيار النسخة",
            "value": money(v1v2["delta"]),
            "tone": "pos" if v1v2["delta"] >= 0 else "neg",
            "body": f"مقارنة التسعة أسهم: V2 أفضل في {v1v2['better_count']} وأضعف في {v1v2['worse_count']} أسهم.",
        }
    )
    market = financial.get("market", [])
    weak_market = [row for row in market if "ضغط" in str(row.get("score_label", "")) or "هابط" in str(row.get("trend", ""))]
    items.append(
        {
            "title": "نبض السوق",
            "value": "داعم" if not weak_market else "مختلط",
            "tone": "pos" if not weak_market else "warn",
            "body": "مؤشرات السوق الحالية داعمة لاستمرار المتابعة، لكنها لا تعفي من إدارة الانكشاف المفتوح.",
        }
    )
    return items


def bar_width(value: float, max_abs: float) -> str:
    if max_abs <= 0:
        return "0%"
    return f"{min(abs(value) / max_abs * 100, 100):.1f}%"


def render_metric(label: str, value: str, note: str, tone: str = "") -> str:
    return f"""
      <article class="metric">
        <span>{label}</span>
        <strong class="{tone}">{value}</strong>
        <small>{note}</small>
      </article>
    """


def render_decision_cards(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"""
        <article class="decision-card {item['tone']}">
          <span>{item['title']}</span>
          <strong>{item['value']}</strong>
          <p>{item['body']}</p>
        </article>
        """
        for item in items
    )


def render_driver_rows(rows: list[dict[str, Any]]) -> str:
    max_abs = max((abs(row["pnl"]) for row in rows), default=1)
    return "\n".join(
        f"""
        <tr>
          <td><strong class="ltr">{row['name']}</strong></td>
          <td class="num">{row['trades']}</td>
          <td class="num">{row['closed']}</td>
          <td class="num">{pct(row['win_rate'])}</td>
          <td class="num {cls(row['pnl'])}">{money(row['pnl'])}</td>
          <td class="num {cls(row['avg_pct'])}">{pct(row['avg_pct'])}</td>
          <td class="num neg">{pct(row['worst_pct'])}</td>
          <td>
            <div class="bar-track"><div class="bar {'negbar' if row['pnl'] < 0 else ''}" style="width:{bar_width(row['pnl'], max_abs)}"></div></div>
          </td>
        </tr>
        """
        for row in rows
    )


def render_bridge(equity: dict[str, Any]) -> str:
    values = [
        ("رأس المال", equity["initial"], "base"),
        ("قيمة الهدف", equity["target_value"], "target"),
        ("الفائض عن الهدف", equity["target_gap"], "gap"),
        ("القيمة الحالية", equity["current"], "current"),
    ]
    max_value = max(abs(v) for _, v, _ in values) or 1
    return "\n".join(
        f"""
        <div class="bridge-row">
          <span>{label}</span>
          <div class="bar-track"><div class="bar {'negbar' if value < 0 else ''}" style="width:{bar_width(value, max_value)}"></div></div>
          <strong class="num {cls(value)}">{money(value)}</strong>
        </div>
        """
        for label, value, _ in values
    )


def render_open_risk(financial: dict[str, Any]) -> str:
    rows = financial.get("open_trades", [])
    if not rows:
        return "<tr><td colspan='6'>لا توجد صفقات مفتوحة.</td></tr>"
    return "\n".join(
        f"""
        <tr>
          <td><strong class="ltr">{row.get('ticker')}</strong></td>
          <td>{row.get('behavior')}</td>
          <td class="num {cls(row.get('pnl_pct'))}">{pct(row.get('pnl_pct'))}</td>
          <td>{row.get('latest_trend')}</td>
          <td class="{'neg' if row.get('latest_risk') == 'مرتفع' else 'pos'}">{row.get('latest_risk')}</td>
          <td class="num">{row.get('latest_score')}</td>
        </tr>
        """
        for row in rows
    )


def render_definitions() -> str:
    rows = [
        ("عائد الفترة", "قيمة المحفظة الحالية ÷ رأس المال - 1", "قياس العائد الفعلي بدون تضخيم سنوي"),
        ("فائض الهدف", "قيمة المحفظة الحالية - قيمة هدف 70% سنويًا", "هل الأداء يتجاوز الحد الأدنى المقبول"),
        ("تركيز الربح", "ربح أعلى 3 أسهم ÷ ربح المحفظة", "اختبار الاعتماد الزائد على عدد قليل من الأسهم"),
        ("الانكشاف المفتوح", "قيمة الصفقات المفتوحة ÷ قيمة المحفظة", "حجم الخطر الحي مقارنة بالمحفظة"),
        ("جودة الربح", "متوسط الرابح ÷ متوسط الخاسر", "هل الأرباح تغطي طبيعة الخسائر"),
    ]
    return "\n".join(
        f"<tr><td>{name}</td><td>{formula}</td><td>{use}</td></tr>"
        for name, formula, use in rows
    )


def build_payload() -> dict[str, Any]:
    trades = add_month(read_csv(TRADES_CSV))
    equity_rows = read_csv(EQUITY_CSV)
    equity = equity_stats(equity_rows)
    financial = load_financial_payload()
    total_pnl = equity["current"] - equity["initial"]
    quality = portfolio_quality(trades, equity, financial)
    v1v2 = v1_v2_summary(read_csv(V1_V2_CSV))
    dimensions = {
        "ticker": group_stats(trades, "ticker", total_pnl),
        "timeframe": group_stats(trades, "timeframe", total_pnl),
        "behavior": group_stats(trades, "behavior", total_pnl),
        "entry_month": group_stats(trades, "entry_month", total_pnl),
    }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "equity": equity,
        "quality": quality,
        "v1v2": v1v2,
        "financial": financial,
        "dimensions": dimensions,
        "decisions": decision_items(equity, quality, v1v2, financial),
    }


def render(payload: dict[str, Any]) -> str:
    equity = payload["equity"]
    quality = payload["quality"]
    v1v2 = payload["v1v2"]
    dimensions_json = json.dumps(payload["dimensions"], ensure_ascii=False)
    top_ticker = quality.get("top_ticker", {})
    metrics = "\n".join(
        [
            render_metric("قيمة المحفظة", money(equity["current"]), f"حتى {equity['end_date']}", "pos"),
            render_metric("عائد الفترة", pct(equity["period_return_pct"]), f"من {equity['start_date']}", "pos"),
            render_metric("فائض الهدف", money(equity["target_gap"]), f"هدف الفترة {pct(equity['target_return_pct'])}", cls(equity["target_gap"])),
            render_metric("السحب الأقصى", pct(equity["max_drawdown_pct"]), "أكبر تراجع من قمة تاريخية", "neg"),
            render_metric("جودة الربح", f"{quality['payoff_ratio']:.2f}", f"متوسط رابحة {pct(quality['avg_win_pct'])} / خاسرة {pct(quality['avg_loss_pct'])}", "pos"),
            render_metric("تركيز أعلى 3", pct(quality["top3_contribution_pct"]), f"أكبر مصدر {top_ticker.get('name', '-')}", "warn" if quality["top3_contribution_pct"] > 65 else "pos"),
            render_metric("الانكشاف المفتوح", pct(quality["open_exposure_pct"]), f"ربح/خسارة مفتوحة {money(quality['open_pnl'])}", "warn" if quality["high_risk_open"] else "pos"),
            render_metric("فرق V2 عن V1", money(v1v2["delta"]), f"أفضل في {v1v2['better_count']} / أضعف في {v1v2['worse_count']}", cls(v1v2["delta"])),
        ]
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مختبر ذكاء الأعمال</title>
  <style>
    :root {{
      --bg:#f4f7fa; --panel:#fff; --text:#061629; --muted:#61738a; --line:#d7e2ec;
      --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    .wrap {{ max-width:1540px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:32px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:17px; }}
    a {{ color:var(--blue); text-decoration:none; }}
    .sub,.note,small {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .btn,select,input {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; font:inherit; color:var(--text); }}
    .btn.primary,.tabs button.active {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .badge {{ display:inline-flex; border:1px solid #f0c572; background:#fff8e7; color:#7b5200; border-radius:999px; padding:4px 10px; margin-top:8px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .two {{ display:grid; grid-template-columns:1.1fr .9fr; gap:14px; margin-top:14px; }}
    .panel,.metric,.decision-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .metric span,.decision-card span {{ color:var(--muted); display:block; }}
    .metric strong {{ display:block; direction:ltr; text-align:right; font-size:31px; margin-top:8px; }}
    .decision-card strong {{ display:block; font-size:25px; margin:7px 0; }}
    .decision-card p {{ margin:0; color:var(--muted); }}
    .decision-card.pos {{ border-color:#b8dccf; }}
    .decision-card.warn {{ border-color:#f0c572; background:#fffdf8; }}
    .decision-card.neg {{ border-color:#e3a6a6; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#24364d; }}
    tbody tr:hover {{ background:#f8fbfd; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }}
    .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .pos {{ color:var(--green); font-weight:800; }}
    .neg {{ color:var(--red); font-weight:800; }}
    .warn {{ color:var(--amber); font-weight:800; }}
    .bar-track {{ height:12px; background:#eef3f7; border-radius:999px; overflow:hidden; min-width:120px; direction:ltr; }}
    .bar {{ height:100%; border-radius:999px; background:var(--blue); }}
    .bar.negbar {{ background:var(--red); }}
    .bridge-row {{ display:grid; grid-template-columns:130px 1fr 150px; gap:12px; align-items:center; margin:10px 0; }}
    .table-wrap {{ overflow:auto; }}
    @media (max-width:1050px) {{
      header {{ display:block; }}
      .grid,.two {{ grid-template-columns:1fr; }}
      .nav {{ margin-top:12px; }}
      .bridge-row {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <header>
      <div>
        <h1>مختبر ذكاء الأعمال</h1>
        <div class="sub">قراءة تنفيذية للمحفظة: الهدف، الانحراف، محركات الربح، تركيز المخاطر، والقرار التالي.</div>
        <div class="badge">آخر توليد: {payload['generated_at']}</div>
      </div>
      <nav class="nav">
        <a class="btn" href="paper_portfolio_v2_dashboard.html">المحفظة</a>
        <a class="btn" href="paper_portfolio_v2_analytics.html">التحليلات</a>
        <a class="btn" href="strategy_v2_dashboard.html">التشخيص</a>
        <a class="btn primary" href="business_intelligence_lab.html">ذكاء الأعمال</a>
      </nav>
    </header>

    <section class="grid">{metrics}</section>

    <section style="margin-top:14px;">
      <h2>مركز القرار التنفيذي</h2>
      <div class="grid">{render_decision_cards(payload['decisions'])}</div>
    </section>

    <section class="two">
      <div class="panel">
        <h2>جسر الهدف إلى النتيجة</h2>
        {render_bridge(equity)}
      </div>
      <div class="panel table-wrap">
        <h2>الصفقات المفتوحة تحت القرار</h2>
        <table>
          <thead><tr><th>السهم</th><th>الاستراتيجية</th><th>ربح/خسارة</th><th>الترند</th><th>الخطر</th><th>النتيجة</th></tr></thead>
          <tbody>{render_open_risk(payload['financial'])}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" style="margin-top:14px;">
      <h2>محركات الربح والخسارة</h2>
      <div class="tabs">
        <button class="btn active" data-dim="ticker">السهم</button>
        <button class="btn" data-dim="timeframe">الإطار</button>
        <button class="btn" data-dim="behavior">السلوك</button>
        <button class="btn" data-dim="entry_month">الشهر</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>البعد</th><th>صفقات</th><th>مغلقة</th><th>فوز</th><th>الربح</th><th>متوسط %</th><th>أسوأ %</th><th>الأثر</th></tr></thead>
          <tbody id="driverRows">{render_driver_rows(payload['dimensions']['ticker'])}</tbody>
        </table>
      </div>
    </section>

    <section class="two">
      <div class="panel table-wrap">
        <h2>تعريفات المقاييس</h2>
        <table><thead><tr><th>المقياس</th><th>طريقة الحساب</th><th>استخدامه في القرار</th></tr></thead><tbody>{render_definitions()}</tbody></table>
      </div>
      <div class="panel table-wrap">
        <h2>مقارنة V2 مع V1 على التسعة أسهم</h2>
        <table>
          <thead><tr><th>الجانب</th><th>القيمة</th><th>القراءة</th></tr></thead>
          <tbody>
            <tr><td>ربح V1</td><td class="num">{money(v1v2['v1_pnl'])}</td><td>المرجع السابق</td></tr>
            <tr><td>ربح V2</td><td class="num">{money(v1v2['v2_pnl'])}</td><td>النسخة الحالية</td></tr>
            <tr><td>الفرق</td><td class="num {cls(v1v2['delta'])}">{money(v1v2['delta'])}</td><td>فرق اختيار الاستراتيجية على نفس الأسهم</td></tr>
            <tr><td>أفضل أسهم V2</td><td colspan="2">{", ".join(row.get('ticker', '') for row in v1v2['best']) or "-"}</td></tr>
            <tr><td>أضعف أسهم V2</td><td colspan="2">{", ".join(row.get('ticker', '') for row in v1v2['worst']) or "-"}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const BI_DIMENSIONS = {dimensions_json};
    function money(value) {{
      return '$' + Number(value || 0).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
    }}
    function pct(value) {{
      return Number(value || 0).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}}) + '%';
    }}
    function tone(value) {{
      return Number(value || 0) >= 0 ? 'pos' : 'neg';
    }}
    function maxAbs(rows) {{
      return Math.max(1, ...rows.map(row => Math.abs(Number(row.pnl || 0))));
    }}
    function renderRows(dim) {{
      const rows = BI_DIMENSIONS[dim] || [];
      const max = maxAbs(rows);
      document.getElementById('driverRows').innerHTML = rows.map(row => {{
        const width = Math.min(Math.abs(Number(row.pnl || 0)) / max * 100, 100).toFixed(1) + '%';
        return `<tr>
          <td><strong class="ltr">${{row.name}}</strong></td>
          <td class="num">${{row.trades}}</td>
          <td class="num">${{row.closed}}</td>
          <td class="num">${{pct(row.win_rate)}}</td>
          <td class="num ${{tone(row.pnl)}}">${{money(row.pnl)}}</td>
          <td class="num ${{tone(row.avg_pct)}}">${{pct(row.avg_pct)}}</td>
          <td class="num neg">${{pct(row.worst_pct)}}</td>
          <td><div class="bar-track"><div class="bar ${{Number(row.pnl || 0) < 0 ? 'negbar' : ''}}" style="width:${{width}}"></div></div></td>
        </tr>`;
      }}).join('');
    }}
    document.querySelectorAll('.tabs button').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('.tabs button').forEach(item => item.classList.toggle('active', item === button));
        renderRows(button.dataset.dim);
      }});
    }});
  </script>
</body>
</html>"""


def main() -> int:
    payload = build_payload()
    OUT.write_text(render(payload), encoding="utf-8", newline="\n")
    print(f"Business intelligence lab: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
