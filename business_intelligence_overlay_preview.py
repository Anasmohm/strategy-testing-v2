#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from business_intelligence_lab import build_payload


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DASHBOARD_SRC = REPORTS / "paper_portfolio_v2_dashboard.html"
ANALYTICS_SRC = REPORTS / "paper_portfolio_v2_analytics.html"
DASHBOARD_OUT = REPORTS / "paper_portfolio_v2_dashboard_bi_preview.html"
ANALYTICS_OUT = REPORTS / "paper_portfolio_v2_analytics_bi_preview.html"


def fnum(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def tone(value: Any) -> str:
    return "positive" if fnum(value) >= 0 else "negative"


def bi_css() -> str:
    return """
    .bi-preview-note { border:1px solid #f0c572; background:#fff8e7; color:#725000; border-radius:8px; padding:10px 12px; margin:12px 0; }
    .bi-panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; margin:16px 0; }
    .bi-panel h2 { margin:0 0 10px; }
    .bi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
    .bi-card { border:1px solid var(--line); background:#fbfcfd; border-radius:8px; padding:12px; }
    .bi-card span { display:block; color:var(--muted); font-size:12px; }
    .bi-card strong { display:block; margin-top:5px; font-size:22px; }
    .bi-card small { display:block; margin-top:5px; color:var(--muted); font-size:12px; }
    .bi-two { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }
    .bi-row { display:grid; grid-template-columns:130px 1fr 145px; gap:10px; align-items:center; margin:9px 0; }
    .bi-bar-track { height:10px; background:#eef3f7; border-radius:999px; overflow:hidden; direction:ltr; }
    .bi-bar { height:100%; background:var(--blue); border-radius:999px; }
    .bi-bar.negative { background:var(--red); }
    .bi-mini-table { width:100%; border-collapse:collapse; }
    .bi-mini-table th,.bi-mini-table td { padding:8px 9px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }
    .bi-mini-table th { background:var(--soft); color:#24364d; }
    .bi-panel .positive { color:var(--green); font-weight:800; }
    .bi-panel .negative { color:var(--red); font-weight:800; }
    @media (max-width:1050px) { .bi-grid,.bi-two { grid-template-columns:1fr; } .bi-row { grid-template-columns:1fr; } }
    """


def inject_css(source: str) -> str:
    return source.replace("</style>", bi_css() + "\n  </style>", 1)


def insert_before(source: str, marker: str, block: str) -> str:
    if marker not in source:
        raise RuntimeError(f"Marker not found: {marker}")
    return source.replace(marker, block + "\n" + marker, 1)


def bar_width(value: Any, max_abs: float) -> str:
    if max_abs <= 0:
        return "0%"
    return f"{min(abs(fnum(value)) / max_abs * 100, 100):.1f}%"


def decision_text(payload: dict[str, Any]) -> tuple[str, str, str]:
    quality = payload["quality"]
    equity = payload["equity"]
    if quality["high_risk_open"]:
        return ("قرار المتابعة", "تقليل زيادة الوزن", f"{quality['high_risk_open']} صفقة مفتوحة عالية الخطر، لا نزيد الانكشاف قبل تحسن قراءتها.")
    if equity["target_gap"] > 0:
        return ("قرار المتابعة", "الأداء متقدم", "المحفظة فوق هدف الفترة، الأفضل مراقبة التركيز بدل مطاردة صفقة جديدة.")
    return ("قرار المتابعة", "تحتاج تحسين", "العائد دون الهدف، نراجع محركات الخسارة قبل رفع الكاش.")


def metric_cards(payload: dict[str, Any]) -> str:
    equity = payload["equity"]
    quality = payload["quality"]
    title, value, note = decision_text(payload)
    cards = [
        ("فائض الهدف", money(equity["target_gap"]), f"هدف الفترة {pct(equity['target_return_pct'])}", tone(equity["target_gap"])),
        ("تركيز أعلى 3", pct(quality["top3_contribution_pct"]), "يقيس اعتماد الربح على قلة من الأسهم", "negative" if quality["top3_contribution_pct"] > 65 else "positive"),
        ("الانكشاف المفتوح", pct(quality["open_exposure_pct"]), f"ربح/خسارة مفتوحة {money(quality['open_pnl'])}", "negative" if quality["high_risk_open"] else "positive"),
        (title, value, note, "positive" if not quality["high_risk_open"] else "negative"),
    ]
    return "\n".join(
        f"""
        <article class="bi-card">
          <span>{esc(label)}</span>
          <strong class="{cls}">{esc(value)}</strong>
          <small>{esc(note)}</small>
        </article>
        """
        for label, value, note, cls in cards
    )


def bridge_rows(payload: dict[str, Any]) -> str:
    equity = payload["equity"]
    values = [
        ("رأس المال", equity["initial"]),
        ("هدف الفترة", equity["target_value"]),
        ("فائض/عجز الهدف", equity["target_gap"]),
        ("القيمة الحالية", equity["current"]),
    ]
    max_abs = max(abs(v) for _, v in values) or 1
    return "\n".join(
        f"""
        <div class="bi-row">
          <span>{esc(label)}</span>
          <div class="bi-bar-track"><div class="bi-bar {tone(value)}" style="width:{bar_width(value, max_abs)}"></div></div>
          <strong class="num {tone(value)}">{money(value)}</strong>
        </div>
        """
        for label, value in values
    )


def driver_rows(rows: list[dict[str, Any]], limit: int = 6) -> str:
    rows = rows[:limit]
    if not rows:
        return "<tr><td colspan='5'>لا توجد بيانات.</td></tr>"
    return "\n".join(
        f"""
        <tr>
          <td><strong class="ltr">{esc(row.get("name"))}</strong></td>
          <td class="num">{esc(row.get("trades"))}</td>
          <td class="num">{pct(row.get("win_rate"))}</td>
          <td class="num {tone(row.get("pnl"))}">{money(row.get("pnl"))}</td>
          <td class="num {tone(row.get("avg_pct"))}">{pct(row.get("avg_pct"))}</td>
        </tr>
        """
        for row in rows
    )


def worst_driver_rows(rows: list[dict[str, Any]], limit: int = 5) -> str:
    selected = sorted(rows, key=lambda row: fnum(row.get("pnl")))[:limit]
    return driver_rows(selected, limit)


def dashboard_block(payload: dict[str, Any], *, preview: bool = True) -> str:
    note = (
        '<div class="bi-preview-note">معاينة تجريبية: هذه خلاصة ذكاء الأعمال داخل الداشبورد الرئيسي. لا تغير نتائج المحفظة ولا الصفقات.</div>'
        if preview
        else ""
    )
    return f"""
    <section class="bi-panel">
      {note}
      <div class="section-title">
        <h2>ذكاء الأعمال</h2>
        <span>قراءة تنفيذية مختصرة قبل الدخول في تفاصيل الشارت والصفقات.</span>
      </div>
      <div class="bi-grid">{metric_cards(payload)}</div>
    </section>
    """


def analytics_block(payload: dict[str, Any], *, preview: bool = True) -> str:
    ticker_rows = payload["dimensions"]["ticker"]
    timeframe_rows = payload["dimensions"]["timeframe"]
    note = (
        '<div class="bi-preview-note">معاينة تجريبية: هذا دمج جزئي لذكاء الأعمال داخل صفحة التحليلات. الصفحة المستقلة تبقى للمراجعة الكاملة.</div>'
        if preview
        else ""
    )
    return f"""
    <section class="panel bi-panel" style="margin-top:14px;">
      {note}
      <h2>ذكاء الأعمال داخل التحليلات</h2>
      <div class="bi-grid">{metric_cards(payload)}</div>
      <div class="bi-two">
        <div>
          <h3>جسر الهدف إلى النتيجة</h3>
          {bridge_rows(payload)}
        </div>
        <div>
          <h3>أفضل محركات الربح</h3>
          <table class="bi-mini-table">
            <thead><tr><th>السهم</th><th>صفقات</th><th>فوز</th><th>الربح</th><th>متوسط</th></tr></thead>
            <tbody>{driver_rows(ticker_rows, 5)}</tbody>
          </table>
        </div>
        <div>
          <h3>أضعف محركات الربح</h3>
          <table class="bi-mini-table">
            <thead><tr><th>السهم</th><th>صفقات</th><th>فوز</th><th>الربح</th><th>متوسط</th></tr></thead>
            <tbody>{worst_driver_rows(ticker_rows, 5)}</tbody>
          </table>
        </div>
        <div>
          <h3>الإطار الأكثر تأثيرًا</h3>
          <table class="bi-mini-table">
            <thead><tr><th>الإطار</th><th>صفقات</th><th>فوز</th><th>الربح</th><th>متوسط</th></tr></thead>
            <tbody>{driver_rows(timeframe_rows, 4)}</tbody>
          </table>
        </div>
      </div>
    </section>
    """


def apply_dashboard_bi_overlay(source: str, payload: dict[str, Any], *, preview: bool = False) -> str:
    source = inject_css(source)
    return insert_before(source, '<section class="chart">', dashboard_block(payload, preview=preview))


def apply_analytics_bi_overlay(source: str, payload: dict[str, Any], *, preview: bool = False) -> str:
    source = inject_css(source)
    return insert_before(source, '<section style="margin-top:14px;">\n      <h2>', analytics_block(payload, preview=preview))


def build_dashboard_preview(payload: dict[str, Any]) -> str:
    source = DASHBOARD_SRC.read_text(encoding="utf-8")
    source = source.replace(
        '<a class="link-btn" href="business_intelligence_lab.html">ذكاء الأعمال</a>',
        '<a class="link-btn" href="business_intelligence_lab.html">ذكاء الأعمال الكامل</a>'
        '<a class="link-btn" href="paper_portfolio_v2_dashboard_bi_preview.html">معاينة BI</a>',
        1,
    )
    return apply_dashboard_bi_overlay(source, payload, preview=True)


def build_analytics_preview(payload: dict[str, Any]) -> str:
    source = ANALYTICS_SRC.read_text(encoding="utf-8")
    source = source.replace(
        '<a class="btn" href="business_intelligence_lab.html">ذكاء الأعمال</a>',
        '<a class="btn" href="business_intelligence_lab.html">ذكاء الأعمال الكامل</a>'
        '<a class="btn primary" href="paper_portfolio_v2_analytics_bi_preview.html">معاينة BI</a>',
        1,
    )
    return apply_analytics_bi_overlay(source, payload, preview=True)


def main() -> int:
    payload = build_payload()
    DASHBOARD_OUT.write_text(build_dashboard_preview(payload), encoding="utf-8", newline="\n")
    ANALYTICS_OUT.write_text(build_analytics_preview(payload), encoding="utf-8", newline="\n")
    print(f"Dashboard BI preview: {DASHBOARD_OUT}")
    print(f"Analytics BI preview: {ANALYTICS_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
