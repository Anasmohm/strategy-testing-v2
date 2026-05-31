#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
FINANCIAL_JSON = REPORTS / "financial_diagnostics_lab.json"
DASHBOARD_SRC = REPORTS / "paper_portfolio_v2_dashboard.html"
ANALYTICS_SRC = REPORTS / "paper_portfolio_v2_analytics.html"
DASHBOARD_OUT = REPORTS / "paper_portfolio_v2_dashboard_financial_preview.html"
ANALYTICS_OUT = REPORTS / "paper_portfolio_v2_analytics_financial_preview.html"


def fnum(value: Any) -> float:
    try:
        if value is None or value == "":
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


def tone_class(value: Any) -> str:
    text = str(value)
    if text in {"داعم", "داعم قوي", "صاعد", "صاعد قوي", "أقوى من السوق", "منخفض"}:
        return "positive"
    if text in {"ضغط", "هابط", "مرتفع", "تشبع شراء", "متأخر عن السوق", "ضغط سوقي"}:
        return "negative"
    if fnum(value) < 0:
        return "negative"
    return "positive"


def load_payload() -> dict[str, Any]:
    with FINANCIAL_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dashboard_css() -> str:
    return """
    .fd-preview-note { border:1px solid #f0c572; background:#fff8e7; color:#725000; border-radius:8px; padding:10px 12px; margin:12px 0; }
    .fd-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
    .fd-card { border:1px solid var(--line); background:#fbfcfd; border-radius:8px; padding:12px; }
    .fd-card span { display:block; color:var(--muted); margin-bottom:6px; }
    .fd-card strong { font-size:24px; }
    .fd-market-note { margin-top:10px; border-top:1px solid var(--line); padding-top:9px; color:var(--muted); }
    .fd-market-note strong { color:var(--text); }
    .fd-market-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:10px; }
    .fd-market-card { border:1px solid var(--line); background:#fbfcfd; border-radius:8px; padding:10px; }
    .fd-market-card span { color:var(--muted); display:block; }
    .fd-meta { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:10px; }
    .fd-chip { display:inline-flex; border:1px solid var(--line); border-radius:999px; padding:2px 8px; margin:2px; background:#f8fbfd; color:var(--muted); }
    .fd-action { border-top:1px solid var(--line); margin-top:10px; padding-top:10px; color:var(--muted); }
    .position-card.fd-watch { border-color:#f0c572; box-shadow:0 0 0 1px rgba(240,197,114,.35) inset; }
    .position-card.fd-danger { border-color:#e3a6a6; box-shadow:0 0 0 1px rgba(168,55,61,.2) inset; }
    .fd-diagnostic { border-top:1px solid var(--line); margin-top:10px; padding-top:10px; }
    .fd-diagnostic-title { display:flex; justify-content:space-between; gap:8px; align-items:center; color:var(--muted); margin-bottom:6px; }
    .fd-diagnostic-title strong { color:var(--text); }
    .fd-diagnostic-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .fd-trade-row-note { display:block; margin-top:4px; color:var(--muted); font-size:12px; }
    @media (max-width:1050px) { .fd-grid,.fd-market-grid { grid-template-columns:1fr; } }
    """


def analytics_css() -> str:
    return """
    .fd-preview-note { border:1px solid #f0c572; background:#fff8e7; color:#725000; border-radius:8px; padding:10px 12px; margin:12px 0; }
    .fd-two { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .fd-table-wrap { overflow:auto; }
    .fd-chip { display:inline-flex; border:1px solid var(--line); border-radius:999px; padding:2px 8px; margin:2px; background:#f8fbfd; color:var(--muted); }
    @media (max-width:1050px) { .fd-two { grid-template-columns:1fr; } }
    """


def open_trade_action(trade: dict[str, Any]) -> str:
    pnl_pct = fnum(trade.get("pnl_pct"))
    risk = str(trade.get("latest_risk"))
    score = fnum(trade.get("latest_score"))
    trend = str(trade.get("latest_trend"))
    if pnl_pct < -3 and risk == "مرتفع" and score < 65:
        return "تنبيه متابعة قوي: خسارة مفتوحة مع خطر مرتفع ونتيجة فنية ضعيفة نسبيًا."
    if pnl_pct < -3 and risk == "مرتفع" and "صاعد" in trend:
        return "متابعة قريبة: الخسارة قائمة والخطر مرتفع، لكن الترند ما زال داعمًا؛ لا نزيد الحجم."
    if risk == "مرتفع":
        return "خطر مرتفع: مناسب كتنبيه حجم ومراقبة، وليس سبب خروج وحده."
    return "لا يوجد تنبيه فني حاد حاليًا."


def render_market_pulse_overlay(payload: dict[str, Any]) -> str:
    open_trades = payload["open_trades"]
    high_risk = [trade for trade in open_trades if trade.get("latest_risk") == "مرتفع"]
    weak = [trade for trade in open_trades if fnum(trade.get("latest_score")) < 60]
    worst = min(open_trades, key=lambda trade: fnum(trade.get("pnl_pct")), default={})
    open_pnl = sum(fnum(trade.get("pnl")) for trade in open_trades)
    market = payload.get("market", [])
    strongest = max(market, key=lambda row: fnum(row.get("technical_score")), default={})
    weakest = min(market, key=lambda row: fnum(row.get("technical_score")), default={})
    cards = [
        ("صفقات مفتوحة بخطر مرتفع", str(len(high_risk)), "تحتاج متابعة حجم ومخاطر", "negative" if high_risk else "positive"),
        ("نتيجة فنية ضعيفة", str(len(weak)), "أقل من 60 في المختبر", "negative" if weak else "positive"),
        ("أسوأ مفتوحة", f"{esc(worst.get('ticker', '-'))} {pct(worst.get('pnl_pct'))}", "حسب الربح/الخسارة الحالية", "negative"),
        ("ربح/خسارة المفتوحة", money(open_pnl), "محقق لاحقًا حسب حركة السوق", tone_class(open_pnl)),
    ]
    card_html = "\n".join(
        f"""<article class="fd-card"><span>{esc(label)}</span><strong class="{tone}">{value}</strong><small>{esc(note)}</small></article>"""
        for label, value, note, tone in cards
    )
    market_html = "\n".join(
        f"""
        <article class="fd-market-card">
          <span>{esc(row.get("ticker"))}</span>
          <strong class="{tone_class(row.get("score_label"))}">{esc(row.get("trend"))}</strong>
          <div class="fd-chip">20 يوم {pct(row.get("ret20"))}</div>
          <div class="fd-chip">Vol {pct(row.get("vol20_ann"))}</div>
        </article>
        """
        for row in market
    )
    return f"""
    <div class="fd-preview-note">معاينة: تم دمج قراءة التشخيص الفني في نبض السوق والصفقات المفتوحة. اختبار الظل للوقف الأقرب محذوف من هذه المعاينة لأنه لم يثبت فائدة.</div>
    <div class="fd-market-note">
      <strong>قراءة التشخيص:</strong>
      أقوى مؤشر حاليًا <span class="ltr">{esc(strongest.get("ticker", "-"))}</span> ({esc(strongest.get("score_label", "-"))})،
      وأضعف قراءة <span class="ltr">{esc(weakest.get("ticker", "-"))}</span> ({esc(weakest.get("score_label", "-"))}).
    </div>
    <div class="fd-market-grid">{market_html}</div>
      <div class="fd-grid">{card_html}</div>
    """


def dashboard_runtime_script(payload: dict[str, Any]) -> str:
    open_map = {str(trade.get("id")): trade for trade in payload.get("open_trades", [])}
    return f"""
    <script>
      window.FINANCIAL_OPEN_DIAGNOSTICS = {json.dumps(open_map, ensure_ascii=False)};
      function fdToneClass(value) {{
        const text = String(value || '');
        if (['صاعد قوي','صاعد','داعم قوي','داعم','منخفض'].includes(text)) return 'positive';
        if (['هابط','ضغط','مرتفع','تشبع شراء'].includes(text)) return 'negative';
        return 'positive';
      }}
      function fdMoney(value) {{
        return '$' + Number(value || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
      }}
      function fdPct(value) {{
        return Number(value || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + '%';
      }}
      function fdAction(trade) {{
        const pnlPct = Number(trade.pnl_pct || 0);
        const risk = String(trade.latest_risk || '');
        const score = Number(trade.latest_score || 0);
        const trend = String(trade.latest_trend || '');
        if (pnlPct < -3 && risk === 'مرتفع' && score < 65) return 'تنبيه متابعة قوي: خسارة مفتوحة مع خطر مرتفع ونتيجة فنية ضعيفة نسبيًا.';
        if (pnlPct < -3 && risk === 'مرتفع' && trend.includes('صاعد')) return 'متابعة قريبة: الخسارة قائمة والخطر مرتفع، لكن الترند ما زال داعمًا؛ لا نزيد الحجم.';
        if (risk === 'مرتفع') return 'خطر مرتفع: مناسب كتنبيه حجم ومراقبة، وليس سبب خروج وحده.';
        return 'لا يوجد تنبيه فني حاد حاليًا.';
      }}
      function fdApplyDiagnostics() {{
        const map = window.FINANCIAL_OPEN_DIAGNOSTICS || {{}};
        document.querySelectorAll('.position-card').forEach(card => {{
          const ticker = card.querySelector('.position-head strong')?.textContent?.trim();
          const behavior = card.querySelector('.position-head span')?.textContent?.trim();
          const match = Object.values(map).find(item => item.ticker === ticker && item.behavior === behavior && !card.dataset.fdUsed);
          if (!match) return;
          card.dataset.fdUsed = '1';
          card.classList.add(Number(match.latest_score || 0) < 65 ? 'fd-danger' : 'fd-watch');
          card.insertAdjacentHTML('beforeend', `
            <div class="fd-diagnostic">
              <div class="fd-diagnostic-title"><strong>تشخيص فني</strong><span class="${{fdToneClass(match.latest_risk)}}">${{match.latest_risk}}</span></div>
              <div class="fd-diagnostic-grid">
                <span class="fd-chip">الترند: ${{match.latest_trend}}</span>
                <span class="fd-chip">النتيجة: ${{match.latest_score}}</span>
                <span class="fd-chip">الخسارة: ${{fdPct(match.pnl_pct)}}</span>
                <span class="fd-chip">الدخول: ${{match.entry_date}}</span>
              </div>
              <div class="fd-action">${{fdAction(match)}}</div>
            </div>
          `);
        }});
        document.querySelectorAll('tbody tr[data-status="OPEN"]').forEach(row => {{
          const id = row.children[0]?.textContent?.trim();
          const match = map[id];
          if (!match || row.dataset.fdRowUsed) return;
          row.dataset.fdRowUsed = '1';
          row.children[1]?.insertAdjacentHTML('beforeend', `<span class="fd-trade-row-note">تشخيص: ${{match.latest_trend}} | خطر ${{match.latest_risk}} | نتيجة ${{match.latest_score}}</span>`);
        }});
      }}
      window.addEventListener('load', () => setTimeout(fdApplyDiagnostics, 100));
    </script>
    """


def render_market_rows(payload: dict[str, Any]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td><strong class="ltr">{esc(row["ticker"])}</strong></td>
          <td>{esc(row["trend"])}</td>
          <td class="num {tone_class(row["ret20"])}">{pct(row["ret20"])}</td>
          <td class="num">{pct(row["vol20_ann"])}</td>
          <td class="num {tone_class(row["sharpe63"])}">{esc(row["sharpe63"])}</td>
          <td class="num negative">{pct(row["var60_95"])}</td>
          <td class="{tone_class(row["score_label"])}">{esc(row["score_label"])}</td>
        </tr>
        """
        for row in payload["market"]
    )


def render_context_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td><strong>{esc(row["name"])}</strong></td>
          <td class="num">{esc(row["closed"])}</td>
          <td class="num">{pct(row["win_rate"])}</td>
          <td class="num {tone_class(row["avg_pct"])}">{pct(row["avg_pct"])}</td>
          <td class="num negative">{pct(row["worst_pct"])}</td>
        </tr>
        """
        for row in rows
    )


def render_finding_rows(payload: dict[str, Any]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td>{esc(row["dimension"])}</td>
          <td><strong>{esc(row["name"])}</strong></td>
          <td>{esc(row["tone"])}</td>
          <td class="num">{esc(row["closed"])}</td>
          <td class="num">{esc(row["win_rate"])}</td>
          <td class="num">{esc(row["avg_pct"])}</td>
          <td>{esc(row["action"])}</td>
        </tr>
        """
        for row in payload["findings"][:12]
    )


def render_analytics_overlay(payload: dict[str, Any]) -> str:
    groups = payload["groups"]
    return f"""
    <section class="panel" style="margin-top:14px;">
      <h2>التشخيص الفني والمخاطر</h2>
      <div class="fd-preview-note">هذه معاينة لما سينتقل من Financial Analysis Agent إلى صفحة التحليلات: تفسير السياقات، وليس تنبيه يومي مختصر.</div>
      <div class="fd-two">
        <div class="fd-table-wrap">
          <h3>قراءة السوق</h3>
          <table><thead><tr><th>المؤشر</th><th>الترند</th><th>20 يوم</th><th>Vol</th><th>Sharpe</th><th>VaR</th><th>النتيجة</th></tr></thead><tbody>{render_market_rows(payload)}</tbody></table>
        </div>
        <div class="fd-table-wrap">
          <h3>أهم الاستنتاجات</h3>
          <table><thead><tr><th>البعد</th><th>السياق</th><th>التقييم</th><th>صفقات</th><th>فوز</th><th>متوسط</th><th>إجراء</th></tr></thead><tbody>{render_finding_rows(payload)}</tbody></table>
        </div>
      </div>
      <div class="fd-two" style="margin-top:12px;">
        <div class="fd-table-wrap">
          <h3>الترند وقت الدخول</h3>
          <table><thead><tr><th>السياق</th><th>مغلقة</th><th>الفوز</th><th>متوسط %</th><th>أسوأ %</th></tr></thead><tbody>{render_context_rows(groups["entry_trend"])}</tbody></table>
        </div>
        <div class="fd-table-wrap">
          <h3>RSI وقت الدخول</h3>
          <table><thead><tr><th>السياق</th><th>مغلقة</th><th>الفوز</th><th>متوسط %</th><th>أسوأ %</th></tr></thead><tbody>{render_context_rows(groups["entry_rsi_zone"])}</tbody></table>
        </div>
        <div class="fd-table-wrap">
          <h3>التذبذب وقت الدخول</h3>
          <table><thead><tr><th>السياق</th><th>مغلقة</th><th>الفوز</th><th>متوسط %</th><th>أسوأ %</th></tr></thead><tbody>{render_context_rows(groups["entry_volatility"])}</tbody></table>
        </div>
        <div class="fd-table-wrap">
          <h3>مكان السعر وقت الدخول</h3>
          <table><thead><tr><th>السياق</th><th>مغلقة</th><th>الفوز</th><th>متوسط %</th><th>أسوأ %</th></tr></thead><tbody>{render_context_rows(groups["entry_location"])}</tbody></table>
        </div>
      </div>
      <div class="note" style="margin-top:10px;">للتفاصيل الكاملة افتح: <a href="financial_diagnostics_lab.html">مختبر التشخيص المالي والفني</a></div>
    </section>
    """


def inject_css(source: str, css: str) -> str:
    return source.replace("</style>", css + "\n  </style>", 1)


def inject_before(source: str, marker: str, block: str) -> str:
    if marker not in source:
        raise RuntimeError(f"Marker not found: {marker}")
    return source.replace(marker, block + "\n" + marker, 1)


def remove_shadow_test(source: str) -> str:
    start = source.find('<section class="shadow-test">')
    if start < 0:
        return source
    end = source.find('<section class="chart">', start)
    if end < 0:
        return source
    return source[:start] + source[end:]


def inject_after_market_pulse(source: str, block: str) -> str:
    marker = "</section>\n    <section class=\"settings\">"
    if marker not in source:
        raise RuntimeError("Market pulse insertion marker not found")
    return source.replace(marker, "</section>\n" + block + "\n    <section class=\"settings\">", 1)


def inject_before_body_end(source: str, block: str) -> str:
    return source.replace("</body>", block + "\n</body>", 1)


def strip_preview_notes(source: str) -> str:
    marker = '<div class="fd-preview-note">'
    while marker in source:
        start = source.find(marker)
        end = source.find("</div>", start)
        if end < 0:
            return source
        source = source[:start] + source[end + len("</div>") :]
    return source


def remove_analytics_shadow_test(source: str) -> str:
    marker = "<h2>اختبار الوقف الأقرب</h2>"
    start_title = source.find(marker)
    if start_title < 0:
        return source
    start = source.rfind("<section", 0, start_title)
    end = source.find("</section>", start_title)
    if start < 0 or end < 0:
        return source
    return source[:start] + source[end + len("</section>") :]


def apply_dashboard_financial_overlay(source: str, payload: dict[str, Any], *, preview: bool = False) -> str:
    source = inject_css(source, dashboard_css())
    source = remove_shadow_test(source)
    source = inject_after_market_pulse(source, render_market_pulse_overlay(payload))
    source = inject_before_body_end(source, dashboard_runtime_script(payload))
    if not preview:
        source = strip_preview_notes(source)
    return source


def apply_analytics_financial_overlay(source: str, payload: dict[str, Any], *, preview: bool = False) -> str:
    source = inject_css(source, analytics_css())
    source = remove_analytics_shadow_test(source)
    source = inject_before(
        source,
        '<section class="panel" style="margin-top:14px;">\n      <h2>الأخبار وروابط تفسير الحركة</h2>',
        render_analytics_overlay(payload),
    )
    if not preview:
        source = strip_preview_notes(source)
    return source


def main() -> int:
    payload = load_payload()

    dashboard = DASHBOARD_SRC.read_text(encoding="utf-8")
    dashboard = dashboard.replace(
        '<a class="link-btn" href="paper_portfolio_v2_analytics.html">التحليلات</a>',
        '<a class="link-btn" href="paper_portfolio_v2_analytics_financial_preview.html">تحليلات التشخيص</a>'
        '<a class="link-btn" href="paper_portfolio_v2_analytics.html">التحليلات</a>',
        1,
    )
    dashboard = apply_dashboard_financial_overlay(dashboard, payload, preview=True)
    DASHBOARD_OUT.write_text(dashboard, encoding="utf-8", newline="\n")

    analytics = ANALYTICS_SRC.read_text(encoding="utf-8")
    analytics = apply_analytics_financial_overlay(analytics, payload, preview=True)
    ANALYTICS_OUT.write_text(analytics, encoding="utf-8", newline="\n")

    print(f"Dashboard financial preview: {DASHBOARD_OUT}")
    print(f"Analytics financial preview: {ANALYTICS_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
