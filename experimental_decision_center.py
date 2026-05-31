#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
TRADES_CSV = REPORTS / "paper_trades_v2.csv"
EQUITY_CSV = REPORTS / "paper_equity_curve_v2.csv"
OUT = REPORTS / "paper_portfolio_v2_analytics.html"
LOCAL_PREVIEW_OUT = REPORTS / "experimental_decision_center.html"


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
                "id": row.get("id", ""),
                "ticker": row.get("ticker", ""),
                "timeframe": row.get("timeframe", ""),
                "behavior": row.get("behavior", ""),
                "entry_rule": row.get("entry_rule", ""),
                "strategy_id": row.get("strategy_id", ""),
                "status": status,
                "outcome": row.get("outcome", ""),
                "entry_date": row.get("entry_date", ""),
                "close_date": row.get("close_date", ""),
                "entry_month": month_key(row.get("entry_date", "")),
                "shares": inum(row.get("shares")),
                "capital": fnum(row.get("capital")),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "hold_days": inum(row.get("hold_days")),
                "liquidity_cap": fnum(row.get("liquidity_cap")),
                "avg_dollar_volume": fnum(row.get("avg_dollar_volume")),
            }
        )
    return trades


def load_equity() -> list[dict[str, object]]:
    rows = []
    for row in read_csv(EQUITY_CSV):
        rows.append({"date": row.get("date", ""), "value": fnum(row.get("value"))})
    return rows


def max_drawdown(equity: list[dict[str, object]]) -> float:
    peak = 0.0
    worst = 0.0
    for row in equity:
        value = fnum(row.get("value"))
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak * 100.0)
    return round(worst, 2)


def group_stats(trades: list[dict[str, object]], key: str) -> list[dict[str, object]]:
    buckets: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        buckets[str(trade.get(key) or "غير محدد")].append(trade)

    rows: list[dict[str, object]] = []
    for name, items in buckets.items():
        closed = [t for t in items if t["status"] == "CLOSED"]
        open_items = [t for t in items if t["status"] != "CLOSED"]
        wins = [t for t in closed if fnum(t["pnl"]) > 0]
        losses = [t for t in closed if fnum(t["pnl"]) < 0]
        pnl = sum(fnum(t["pnl"]) for t in items)
        capital = sum(fnum(t["capital"]) for t in items)
        avg_pct = sum(fnum(t["pnl_pct"]) for t in items) / len(items) if items else 0.0
        avg_loss_pct = sum(fnum(t["pnl_pct"]) for t in losses) / len(losses) if losses else 0.0
        avg_win_pct = sum(fnum(t["pnl_pct"]) for t in wins) / len(wins) if wins else 0.0
        worst_pct = min((fnum(t["pnl_pct"]) for t in items), default=0.0)
        win_rate = len(wins) / len(closed) * 100.0 if closed else 0.0
        pnl_pct_on_capital = pnl / capital * 100.0 if capital else 0.0
        rows.append(
            {
                "name": name,
                "trades": len(items),
                "closed": len(closed),
                "open": len(open_items),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 2),
                "pnl": round(pnl, 2),
                "open_pnl": round(sum(fnum(t["pnl"]) for t in open_items), 2),
                "pnl_pct_on_capital": round(pnl_pct_on_capital, 2),
                "avg_pnl": round(pnl / len(items), 2) if items else 0.0,
                "avg_pct": round(avg_pct, 2),
                "avg_win_pct": round(avg_win_pct, 2),
                "avg_loss_pct": round(avg_loss_pct, 2),
                "worst_pct": round(worst_pct, 2),
                "worst_pnl": round(min((fnum(t["pnl"]) for t in items), default=0.0), 2),
                "best_pnl": round(max((fnum(t["pnl"]) for t in items), default=0.0), 2),
            }
        )
    return sorted(rows, key=lambda item: fnum(item["pnl"]), reverse=True)


def action_for(row: dict[str, object]) -> tuple[str, str]:
    trades = inum(row.get("closed"))
    pnl = fnum(row.get("pnl"))
    win_rate = fnum(row.get("win_rate"))
    avg_pct = fnum(row.get("avg_pct"))
    avg_loss_pct = fnum(row.get("avg_loss_pct"))
    worst_pct = fnum(row.get("worst_pct"))
    if trades < 5:
        return "مراقبة", "العينة قليلة؛ لا نرفع الوزن قبل تراكم صفقات أكثر."
    if pnl > 0 and win_rate >= 70 and avg_pct > 0 and avg_loss_pct > -7:
        return "مرشح زيادة", "ربح موجب، فوز مرتفع، ومتوسط الخسارة تحت السيطرة."
    if pnl > 0 and win_rate >= 55 and worst_pct > -12:
        return "إبقاء", "الأداء إيجابي لكن لا يكفي وحده لزيادة الوزن."
    if pnl < 0 or avg_pct < 0 or worst_pct <= -12:
        return "خفض/مراجعة", "الخسارة أو أسوأ صفقة تحتاج فحص قبل ضخ كاش إضافي."
    return "مراقبة", "النتيجة غير حاسمة."


def add_actions(rows: list[dict[str, object]], total_pnl: float) -> list[dict[str, object]]:
    enriched = []
    for row in rows:
        action, reason = action_for(row)
        copied = dict(row)
        copied["action"] = action
        copied["reason"] = reason
        copied["contribution_pct"] = round(fnum(row["pnl"]) / total_pnl * 100.0, 2) if total_pnl else 0.0
        quality = fnum(row["pnl_pct_on_capital"]) + fnum(row["win_rate"]) / 10.0 + fnum(row["avg_pct"]) - abs(min(fnum(row["avg_loss_pct"]), 0.0))
        copied["quality_score"] = round(quality, 2)
        enriched.append(copied)
    return enriched


def news_search_url(ticker: str, month: str, tone: str) -> str:
    query = urllib.parse.quote(f"{ticker} stock news {month} {tone} earnings guidance market")
    return f"https://www.google.com/search?tbm=nws&q={query}"


def build_news_candidates(grouped: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    tickers = grouped.get("ticker", [])
    months = grouped.get("entry_month", [])
    top_tickers = [row for row in tickers if fnum(row.get("pnl")) > 0][:5]
    weak_tickers = sorted(
        [row for row in tickers if fnum(row.get("pnl")) < 0 or fnum(row.get("worst_pct")) <= -10],
        key=lambda row: fnum(row.get("pnl")),
    )[:5]
    top_months = [row for row in months if fnum(row.get("pnl")) > 0][:4]
    weak_months = [row for row in months if fnum(row.get("pnl")) < 0][:4]

    cards: list[dict[str, object]] = []
    for tone, title, ticker_rows, month_rows in [
        ("profit catalyst", "أخبار داعمة للأسهم الرابحة", top_tickers, top_months),
        ("selloff loss risk", "أخبار ضاغطة للأسهم الخاسرة", weak_tickers, weak_months),
    ]:
        for ticker_row in ticker_rows:
            ticker = str(ticker_row.get("name", ""))
            links = [
                {
                    "label": str(month_row.get("name", "")),
                    "url": news_search_url(ticker, str(month_row.get("name", "")), tone),
                }
                for month_row in month_rows
            ]
            cards.append(
                {
                    "section": title,
                    "ticker": ticker,
                    "pnl": fnum(ticker_row.get("pnl")),
                    "contribution_pct": fnum(ticker_row.get("contribution_pct")),
                    "worst_pct": fnum(ticker_row.get("worst_pct")),
                    "links": links,
                }
            )
    return cards


def month_decisions(months: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for row in months:
        label = "طبيعي"
        if fnum(row["pnl"]) > 0 and fnum(row["contribution_pct"]) >= 15:
            label = "شهر قائد"
        if fnum(row["pnl"]) < 0:
            label = "شهر ضغط"
        rows.append({**row, "action": label})
    return rows


def portfolio_summary(trades: list[dict[str, object]], equity: list[dict[str, object]]) -> dict[str, object]:
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = [t for t in closed if fnum(t["pnl"]) > 0]
    losses = [t for t in closed if fnum(t["pnl"]) < 0]
    start_value = fnum(equity[0]["value"]) if equity else 0.0
    end_value = fnum(equity[-1]["value"]) if equity else start_value
    total_pnl = sum(fnum(t["pnl"]) for t in trades)
    open_pnl = sum(fnum(t["pnl"]) for t in trades if t["status"] != "CLOSED")
    return {
        "start_value": round(start_value, 2),
        "end_value": round(end_value, 2),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round((end_value - start_value) / start_value * 100.0, 2) if start_value else 0.0,
        "max_drawdown_pct": max_drawdown(equity),
        "closed": len(closed),
        "open": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
        "open_pnl": round(open_pnl, 2),
        "avg_win_pct": round(sum(fnum(t["pnl_pct"]) for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(sum(fnum(t["pnl_pct"]) for t in losses) / len(losses), 2) if losses else 0.0,
        "latest_equity_date": equity[-1]["date"] if equity else "",
    }


def build_decision_notes(by_ticker: list[dict[str, object]], by_timeframe: list[dict[str, object]], months: list[dict[str, object]]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    if by_ticker:
        top = max(by_ticker, key=lambda row: fnum(row["pnl"]))
        notes.append(
            {
                "title": "أكبر مصدر ربح",
                "value": f"{top['name']} ({top['contribution_pct']:.2f}%)",
                "body": "هذا لا يعني زيادة الوزن مباشرة؛ يعني أن قرارنا يحتاج فحص تركيز الربح قبل الاعتماد عليه.",
                "filterKey": "ticker",
                "filterValue": str(top["name"]),
            }
        )
    risky = [r for r in by_ticker if fnum(r["worst_pct"]) <= -12 or fnum(r["avg_loss_pct"]) <= -8]
    if risky:
        worst = min(risky, key=lambda row: fnum(row["worst_pct"]))
        notes.append(
            {
                "title": "أكثر سهم يحتاج ضبط مخاطرة",
                "value": f"{worst['name']} ({worst['worst_pct']:.2f}%)",
                "body": "نستخدمه كنقطة بداية لاختبار وقف أو حجم صفقة أقل، وليس كتعديل مباشر.",
                "filterKey": "ticker",
                "filterValue": str(worst["name"]),
            }
        )
    if by_timeframe:
        best_tf = max(by_timeframe, key=lambda row: fnum(row["pnl_pct_on_capital"]))
        notes.append(
            {
                "title": "الإطار الأقوى كفاءة",
                "value": f"{best_tf['name']} ({best_tf['pnl_pct_on_capital']:.2f}%)",
                "body": "هذه قراءة كفاءة على رأس المال المستخدم، وهي أقرب لسؤال توزيع الكاش.",
                "filterKey": "timeframe",
                "filterValue": str(best_tf["name"]),
            }
        )
    if months:
        best_month = max(months, key=lambda row: fnum(row["pnl"]))
        notes.append(
            {
                "title": "أقوى شهر",
                "value": f"{best_month['name']} ({best_month['contribution_pct']:.2f}%)",
                "body": "لو كان شهر واحد يقود الربح، نحتاج نتأكد أن الاستراتيجية ليست معتمدة على موجة سوق مؤقتة.",
                "filterKey": "entry_month",
                "filterValue": str(best_month["name"]),
            }
        )
    return notes


def file_timestamp() -> str:
    if not TRADES_CSV.exists():
        return "غير متاح"
    return datetime.fromtimestamp(TRADES_CSV.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def render() -> str:
    trades = load_trades()
    equity = load_equity()
    summary = portfolio_summary(trades, equity)
    total_pnl = fnum(summary["total_pnl"])

    grouped = {
        "ticker": add_actions(group_stats(trades, "ticker"), total_pnl),
        "timeframe": add_actions(group_stats(trades, "timeframe"), total_pnl),
        "behavior": add_actions(group_stats(trades, "behavior"), total_pnl),
        "entry_rule": add_actions(group_stats(trades, "entry_rule"), total_pnl),
        "entry_month": [],
    }
    grouped["entry_month"] = month_decisions(add_actions(group_stats(trades, "entry_month"), total_pnl))
    notes = build_decision_notes(grouped["ticker"], grouped["timeframe"], grouped["entry_month"])
    news = build_news_candidates(grouped)
    payload = {
        "trades": trades,
        "grouped": grouped,
        "summary": summary,
        "notes": notes,
        "news": news,
        "fileTimestamp": file_timestamp(),
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مركز القرار والتحليلات</title>
  <style>
    :root {{
      --bg:#f4f7fa; --panel:#fff; --text:#061629; --muted:#61738a; --line:#d7e2ec;
      --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    .wrap {{ max-width:1540px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:28px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    a {{ color:var(--blue); text-decoration:none; }}
    .sub,.note {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .btn,select,input {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; font:inherit; color:var(--text); }}
    .btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .badge {{ display:inline-flex; border:1px solid #f0c572; background:#fff8e7; color:#7b5200; border-radius:999px; padding:4px 10px; margin-top:7px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .panel,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .metric .label {{ color:var(--muted); }}
    .metric .value {{ direction:ltr; text-align:right; font-size:30px; font-weight:800; margin-top:6px; }}
    .decision {{ cursor:pointer; min-height:150px; }}
    .decision:hover {{ border-color:var(--blue); }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }}
    .tabs button.active {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .controls {{ display:grid; grid-template-columns:1.3fr 1fr 1fr auto; gap:10px; align-items:end; margin:12px 0; }}
    .chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:14px 0; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#24364d; }}
    tbody tr:hover {{ background:#f8fbfd; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }}
    .pos {{ color:var(--green); font-weight:700; }}
    .neg {{ color:var(--red); font-weight:700; }}
    .warn {{ color:var(--amber); font-weight:700; }}
    .chip {{ display:inline-flex; border:1px solid var(--line); background:#f8fbfd; border-radius:999px; padding:2px 8px; margin:2px; }}
    .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .bar-row {{ display:grid; grid-template-columns:130px 1fr 115px; gap:10px; align-items:center; margin:8px 0; }}
    .bar-track {{ height:12px; background:#eef3f7; border-radius:999px; overflow:hidden; direction:ltr; }}
    .bar {{ height:100%; border-radius:999px; background:var(--blue); }}
    .bar.negbar {{ background:var(--red); }}
    .scatter {{ width:100%; height:270px; border:1px solid var(--line); border-radius:8px; background:linear-gradient(#fff,#fbfdff); }}
    .news-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .news-card h3 {{ margin:0 0 8px; }}
    .news-links {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .news-links a {{ border:1px solid var(--line); border-radius:999px; padding:5px 10px; background:#f8fbfd; }}
    @media (max-width:1000px) {{
      header {{ display:block; }}
      .grid,.chart-grid,.news-grid {{ grid-template-columns:1fr; }}
      .controls {{ grid-template-columns:1fr; }}
      .nav {{ margin-top:12px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>مركز القرار والتحليلات</h1>
        <div class="sub">صفحة التحليلات الرسمية: تربط أداء المحفظة، المخاطر، الاستراتيجيات، والأخبار الداعمة للقرار.</div>
        <div class="badge">آخر تحديث لملف الصفقات: <span id="fileTimestamp"></span></div>
      </div>
      <nav class="nav">
        <a class="btn" href="paper_portfolio_v2_dashboard.html">المحفظة</a>
        <a class="btn primary" href="paper_portfolio_v2_analytics.html">التحليلات</a>
        <a class="btn" href="business_intelligence_lab.html">ذكاء الأعمال</a>
        <a class="btn" href="strategy_v2_dashboard.html">التشخيص</a>
      </nav>
    </header>

    <section class="grid" id="summaryCards"></section>

    <section style="margin-top:14px;">
      <h2>قراءات قابلة للتحويل إلى قرار</h2>
      <div class="grid" id="decisionNotes"></div>
    </section>

    <section class="panel" style="margin-top:14px;">
      <h2>لوحة الاستكشاف والوزن</h2>
      <div class="tabs">
        <button class="btn primary active" data-group="ticker">السهم</button>
        <button class="btn" data-group="timeframe">الإطار</button>
        <button class="btn" data-group="entry_month">الشهر</button>
        <button class="btn" data-group="entry_rule">قاعدة الدخول</button>
        <button class="btn" data-group="behavior">السلوك</button>
      </div>
      <div class="controls">
        <label>بحث
          <input id="search" placeholder="سهم، شهر، استراتيجية، نتيجة">
        </label>
        <label>ترتيب
          <select id="sortBy">
            <option value="quality_score">جودة القراءة</option>
            <option value="pnl">الربح بالدولار</option>
            <option value="pnl_pct_on_capital">العائد على رأس المال</option>
            <option value="win_rate">نسبة الفوز</option>
            <option value="worst_pct">أسوأ نسبة خسارة</option>
          </select>
        </label>
        <label>أقل صفقات مغلقة
          <input id="minClosed" type="number" min="0" value="0">
        </label>
        <button class="btn" id="reset">مسح الفلتر</button>
      </div>
      <div id="activeFilter" class="note"></div>
      <div class="chart-grid">
        <div class="card">
          <h2>المساهمة في الربح</h2>
          <div id="barChart"></div>
        </div>
        <div class="card">
          <h2>الكفاءة مقابل المخاطرة</h2>
          <svg id="scatter" class="scatter" viewBox="0 0 620 270"></svg>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>البند</th>
            <th>قراءة القرار</th>
            <th>الصفقات</th>
            <th>رابحة / خاسرة</th>
            <th>نسبة الفوز</th>
            <th>الربح</th>
            <th>مساهمة الربح</th>
            <th>عائد رأس المال</th>
            <th>متوسط ربح/خسارة %</th>
            <th>أسوأ صفقة %</th>
            <th>السبب</th>
          </tr>
        </thead>
        <tbody id="groupRows"></tbody>
      </table>
    </section>

    <section class="panel" style="margin-top:14px;">
      <h2>الأخبار وروابط تفسير الحركة</h2>
      <div class="note">روابط بحث جاهزة للأسهم والأشهر التي قادت الربح أو الضغط. هذه الروابط تفسيرية ولا تدخل في حساب المحاكاة.</div>
      <div class="news-grid" id="newsGrid"></div>
    </section>

    <section class="panel" style="margin-top:14px;">
      <h2>الصفقات خلف القراءة</h2>
      <table>
        <thead>
          <tr>
            <th>رقم</th>
            <th>السهم</th>
            <th>الإطار</th>
            <th>الدخول</th>
            <th>الخروج</th>
            <th>الحالة</th>
            <th>النتيجة</th>
            <th>القيمة</th>
            <th>ربح/خسارة</th>
            <th>النسبة</th>
          </tr>
        </thead>
        <tbody id="tradeRows"></tbody>
      </table>
    </section>
  </div>
  <script id="payload" type="application/json">{data_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const state = {{ group: 'ticker', filterKey: '', filterValue: '' }};
    const money = (n) => '$' + Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    const pct = (n) => Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + '%';
    const cls = (n) => Number(n || 0) < 0 ? 'neg' : 'pos';
    document.getElementById('fileTimestamp').textContent = payload.fileTimestamp;

    function card(label, value, detail, tone='') {{
      return `<article class="card metric"><div class="label">${{label}}</div><div class="value ${{tone}}">${{value}}</div><div class="note">${{detail}}</div></article>`;
    }}

    function renderSummary() {{
      const s = payload.summary;
      document.getElementById('summaryCards').innerHTML = [
        card('قيمة المحفظة', money(s.end_value), 'حتى ' + s.latest_equity_date),
        card('عائد الفترة', pct(s.return_pct), 'من رأس المال الابتدائي', cls(s.return_pct)),
        card('نسبة الفوز', pct(s.win_rate), `${{s.wins}} رابحة / ${{s.losses}} خاسرة`),
        card('السحب الأقصى', pct(s.max_drawdown_pct), 'أكبر هبوط من قمة تاريخية', 'neg'),
        card('متوسط الصفقة الرابحة', pct(s.avg_win_pct), 'متوسط نسبة الربح في الصفقات الرابحة', 'pos'),
        card('متوسط الصفقة الخاسرة', pct(s.avg_loss_pct), 'متوسط نسبة الخسارة في الصفقات الخاسرة', 'neg'),
        card('الصفقات المفتوحة', String(s.open), money(s.open_pnl) + ' غير محقق', cls(s.open_pnl)),
        card('الصفقات المغلقة', String(s.closed), 'إجمالي الصفقات التي انتهت')
      ].join('');
    }}

    function renderNotes() {{
      document.getElementById('decisionNotes').innerHTML = payload.notes.map((n) => `
        <article class="card decision" data-key="${{n.filterKey}}" data-value="${{n.filterValue}}">
          <div class="label">${{n.title}}</div>
          <div class="value">${{n.value}}</div>
          <div class="note">${{n.body}}</div>
        </article>
      `).join('');
      document.querySelectorAll('.decision').forEach((el) => {{
        el.addEventListener('click', () => {{
          state.filterKey = el.dataset.key;
          state.filterValue = el.dataset.value;
          const matchingGroup = ['ticker','timeframe','entry_month','entry_rule','behavior'].includes(state.filterKey) ? state.filterKey : state.group;
          state.group = matchingGroup;
          document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.group === state.group));
          renderAll();
        }});
      }});
    }}

    function renderNews() {{
      const grid = document.getElementById('newsGrid');
      const items = payload.news || [];
      if (!items.length) {{
        grid.innerHTML = '<div class="note">لا توجد روابط أخبار كافية لهذه القراءة.</div>';
        return;
      }}
      grid.innerHTML = items.map((item) => `
        <article class="card news-card">
          <div class="label">${{item.section}}</div>
          <h3><span class="ltr">${{item.ticker}}</span></h3>
          <div class="note">
            الربح: <span class="${{cls(item.pnl)}} num">${{money(item.pnl)}}</span>
            <span class="chip">مساهمة ${{pct(item.contribution_pct)}}</span>
            <span class="chip">أسوأ ${{pct(item.worst_pct)}}</span>
          </div>
          <div class="news-links">
            ${{(item.links || []).map(link => `<a target="_blank" rel="noopener" href="${{link.url}}">أخبار ${{link.label}}</a>`).join('')}}
          </div>
        </article>
      `).join('');
    }}

    function filteredTrades() {{
      const search = document.getElementById('search').value.trim().toLowerCase();
      return payload.trades.filter(t => {{
        if (state.filterKey && String(t[state.filterKey] || '') !== state.filterValue) return false;
        if (!search) return true;
        return [t.id,t.ticker,t.timeframe,t.entry_month,t.entry_rule,t.behavior,t.strategy_id,t.status,t.outcome]
          .some(x => String(x || '').toLowerCase().includes(search));
      }});
    }}

    function rowsForGroup(trades) {{
      const base = payload.grouped[state.group] || [];
      const names = new Set(trades.map(t => String(t[state.group] || 'غير محدد')));
      const search = document.getElementById('search').value.trim().toLowerCase();
      const minClosed = Number(document.getElementById('minClosed').value || 0);
      let rows = base.filter(r => names.has(String(r.name)) && Number(r.closed || 0) >= minClosed);
      if (search) rows = rows.filter(r => String(r.name).toLowerCase().includes(search) || String(r.action || '').toLowerCase().includes(search));
      const sortBy = document.getElementById('sortBy').value;
      rows.sort((a,b) => Number(b[sortBy] || 0) - Number(a[sortBy] || 0));
      return rows;
    }}

    function actionClass(action) {{
      if (String(action).includes('زيادة')) return 'pos';
      if (String(action).includes('خفض') || String(action).includes('ضغط')) return 'neg';
      return 'warn';
    }}

    function renderRows(rows) {{
      document.getElementById('groupRows').innerHTML = rows.map(r => `
        <tr>
          <td><strong class="${{state.group === 'entry_rule' || state.group === 'behavior' ? 'ltr' : ''}}">${{r.name}}</strong></td>
          <td class="${{actionClass(r.action)}}">${{r.action || '-'}}</td>
          <td class="num">${{r.trades}} <span class="chip">مغلقة ${{r.closed}}</span></td>
          <td class="num">${{r.wins}} / ${{r.losses}}</td>
          <td class="num">${{pct(r.win_rate)}}</td>
          <td class="num ${{cls(r.pnl)}}">${{money(r.pnl)}}</td>
          <td class="num ${{cls(r.contribution_pct)}}">${{pct(r.contribution_pct)}}</td>
          <td class="num ${{cls(r.pnl_pct_on_capital)}}">${{pct(r.pnl_pct_on_capital)}}</td>
          <td class="num"><span class="pos">${{pct(r.avg_win_pct)}}</span> / <span class="neg">${{pct(r.avg_loss_pct)}}</span></td>
          <td class="num neg">${{pct(r.worst_pct)}}</td>
          <td>${{r.reason || ''}}</td>
        </tr>
      `).join('');
    }}

    function renderBars(rows) {{
      const top = rows.slice(0, 10);
      const maxAbs = Math.max(...top.map(r => Math.abs(Number(r.pnl || 0))), 1);
      document.getElementById('barChart').innerHTML = top.map(r => {{
        const w = Math.max(2, Math.abs(Number(r.pnl || 0)) / maxAbs * 100);
        return `<div class="bar-row"><div>${{r.name}}</div><div class="bar-track"><div class="bar ${{Number(r.pnl) < 0 ? 'negbar' : ''}}" style="width:${{w}}%"></div></div><div class="num ${{cls(r.pnl)}}">${{money(r.pnl)}}</div></div>`;
      }}).join('');
    }}

    function renderScatter(rows) {{
      const svg = document.getElementById('scatter');
      const maxX = Math.max(...rows.map(r => Number(r.pnl_pct_on_capital || 0)), 1);
      const minX = Math.min(...rows.map(r => Number(r.pnl_pct_on_capital || 0)), 0);
      const minY = Math.min(...rows.map(r => Number(r.worst_pct || 0)), -1);
      const maxY = Math.max(...rows.map(r => Number(r.win_rate || 0)), 100);
      const x = v => 50 + ((Number(v) - minX) / Math.max(maxX - minX, 1)) * 520;
      const y = v => 225 - ((Number(v) - minY) / Math.max(maxY - minY, 1)) * 180;
      svg.innerHTML = `
        <line x1="50" y1="225" x2="575" y2="225" stroke="#d8e2ec"/>
        <line x1="50" y1="30" x2="50" y2="225" stroke="#d8e2ec"/>
        <text x="55" y="22" fill="#61738a" font-size="12">نسبة الفوز / أسوأ خسارة</text>
        <text x="410" y="255" fill="#61738a" font-size="12">عائد رأس المال</text>
        ${{rows.slice(0, 45).map(r => `<circle cx="${{x(r.pnl_pct_on_capital)}}" cy="${{y(r.win_rate + r.worst_pct)}}" r="${{Math.max(5, Math.min(14, Number(r.trades || 1) / 8))}}" fill="${{Number(r.pnl) >= 0 ? '#14745f' : '#a8373d'}}"><title>${{r.name}} | ${{pct(r.pnl_pct_on_capital)}} | فوز ${{pct(r.win_rate)}} | أسوأ ${{pct(r.worst_pct)}}</title></circle>`).join('')}}
      `;
    }}

    function renderTrades(trades) {{
      const rows = trades.slice().sort((a,b) => Number(b.pnl || 0) - Number(a.pnl || 0)).slice(0, 70);
      document.getElementById('tradeRows').innerHTML = rows.map(t => `
        <tr>
          <td>${{t.id}}</td><td><strong>${{t.ticker}}</strong></td><td>${{t.timeframe}}</td>
          <td>${{t.entry_date}}</td><td>${{t.close_date || '-'}}</td><td>${{t.status}}</td><td>${{t.outcome}}</td>
          <td class="num">${{money(t.capital)}}</td><td class="num ${{cls(t.pnl)}}">${{money(t.pnl)}}</td><td class="num ${{cls(t.pnl_pct)}}">${{pct(t.pnl_pct)}}</td>
        </tr>
      `).join('');
    }}

    function renderAll() {{
      const trades = filteredTrades();
      const rows = rowsForGroup(trades);
      document.getElementById('activeFilter').textContent = state.filterKey ? `فلتر نشط: ${{state.filterKey}} = ${{state.filterValue}}` : '';
      renderRows(rows);
      renderBars(rows);
      renderScatter(rows);
      renderTrades(trades);
    }}

    document.querySelectorAll('.tabs button').forEach(btn => {{
      btn.addEventListener('click', () => {{
        state.group = btn.dataset.group;
        state.filterKey = '';
        state.filterValue = '';
        document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b === btn));
        renderAll();
      }});
    }});
    ['search','sortBy','minClosed'].forEach(id => {{
      document.getElementById(id).addEventListener('input', renderAll);
      document.getElementById(id).addEventListener('change', renderAll);
    }});
    document.getElementById('reset').addEventListener('click', () => {{
      state.filterKey = '';
      state.filterValue = '';
      document.getElementById('search').value = '';
      document.getElementById('sortBy').value = 'quality_score';
      document.getElementById('minClosed').value = '0';
      renderAll();
    }});

    renderSummary();
    renderNotes();
    renderNews();
    renderAll();
  </script>
</body>
</html>
"""


def main() -> int:
    if not TRADES_CSV.exists():
        raise FileNotFoundError(f"Missing trades file: {TRADES_CSV}")
    html_text = render()
    OUT.write_text(html_text, encoding="utf-8", newline="\n")
    LOCAL_PREVIEW_OUT.write_text(html_text, encoding="utf-8", newline="\n")
    print(f"Decision analytics: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
