#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import data_analyst_lab
import experimental_decision_center as decision


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
OUT = REPORTS / "decision_hypothesis_preview.html"


def build_decision_payload() -> dict[str, object]:
    trades = decision.load_trades()
    equity = decision.load_equity()
    shadow_rows = decision.read_csv(decision.SHADOW_CSV)
    summary = decision.portfolio_summary(trades, equity)
    total_pnl = decision.fnum(summary["total_pnl"])
    grouped = {
        "ticker": decision.add_actions(decision.group_stats(trades, "ticker"), total_pnl),
        "timeframe": decision.add_actions(decision.group_stats(trades, "timeframe"), total_pnl),
        "behavior": decision.add_actions(decision.group_stats(trades, "behavior"), total_pnl),
        "entry_rule": decision.add_actions(decision.group_stats(trades, "entry_rule"), total_pnl),
        "entry_month": [],
    }
    grouped["entry_month"] = decision.month_decisions(
        decision.add_actions(decision.group_stats(trades, "entry_month"), total_pnl)
    )
    return {
        "trades": trades,
        "grouped": grouped,
        "summary": summary,
        "notes": decision.build_decision_notes(grouped["ticker"], grouped["timeframe"], grouped["entry_month"]),
        "news": decision.build_news_candidates(grouped),
        "shadow": shadow_rows,
        "fileTimestamp": decision.file_timestamp(),
    }


def render(payload: dict[str, object]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>معاينة مركز القرار والتحقق</title>
  <style>
    :root {{
      --bg:#f4f7fa; --panel:#fff; --text:#071827; --muted:#60758b; --line:#d7e2ec;
      --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    .wrap {{ max-width:1540px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }}
    h1 {{ margin:0; font-size:28px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:18px; }}
    a {{ color:var(--blue); text-decoration:none; }}
    .sub,.note {{ color:var(--muted); }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .btn,select,input {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; font:inherit; color:var(--text); }}
    .btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .panel,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .metric .label {{ color:var(--muted); }}
    .metric .value {{ direction:ltr; text-align:right; font-size:30px; font-weight:800; margin-top:6px; }}
    .decision {{ cursor:pointer; min-height:150px; }}
    .decision:hover {{ border-color:var(--blue); }}
    .hypothesis {{ display:grid; grid-template-columns:220px 1fr; gap:12px; border-top:1px solid var(--line); padding:14px 0; }}
    .hypothesis:first-child {{ border-top:0; }}
    .grade {{ display:inline-flex; border-radius:999px; padding:4px 10px; font-weight:700; border:1px solid var(--line); background:#f8fbfd; }}
    .grade.high {{ color:var(--green); border-color:#b7decf; background:#edf8f4; }}
    .grade.mid {{ color:var(--amber); border-color:#f0d394; background:#fff8e7; }}
    .grade.low {{ color:var(--muted); }}
    .qa {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:10px; }}
    .qa div {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fbfdff; }}
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
    .shadow-grid,.news-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .news-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    .news-links {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .news-links a {{ border:1px solid var(--line); border-radius:999px; padding:5px 10px; background:#f8fbfd; }}
    .preview-badge {{ display:inline-flex; border:1px solid #f0c572; background:#fff8e7; color:#7b5200; border-radius:999px; padding:4px 10px; margin-top:7px; }}
    .page-tabs {{
      position: sticky;
      top: 0;
      z-index: 5;
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin:14px 0;
      padding:10px 0;
      background:var(--bg);
    }}
    .page-tab.active {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .tab-section {{ display:none; }}
    .tab-section.active {{ display:block; }}
    .section-lead {{
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:flex-start;
      margin-bottom:12px;
    }}
    .section-lead p {{ margin:0; color:var(--muted); }}
    .summary-note {{
      border:1px solid var(--line);
      background:#fbfdff;
      border-radius:8px;
      padding:12px;
      color:var(--muted);
    }}
    @media (max-width:1000px) {{
      header {{ display:block; }}
      .grid,.two,.qa,.hypothesis,.chart-grid,.shadow-grid,.news-grid {{ grid-template-columns:1fr; }}
      .controls {{ grid-template-columns:1fr; }}
      .section-lead {{ display:block; }}
      .nav {{ margin-top:12px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>معاينة مركز القرار والتحقق</h1>
        <div class="sub">دمج تجريبي بين مركز القرار والتحليلات وبين مختبر Data Analyst. هذه الصفحة لا تستبدل المعتمدة بعد.</div>
        <div class="preview-badge">معاينة فقط | آخر تحديث للصفقات: <span id="fileTimestamp"></span></div>
      </div>
      <nav class="nav">
        <a class="btn" href="paper_portfolio_v2_dashboard.html">المحفظة</a>
        <a class="btn" href="paper_portfolio_v2_analytics.html">التحليلات المعتمدة</a>
        <a class="btn" href="data_analyst_lab.html">مختبر الفرضيات</a>
      </nav>
    </header>

    <section class="grid" id="summaryCards"></section>

    <nav class="page-tabs" aria-label="أقسام مركز القرار">
      <button class="btn page-tab active" data-tab="overview">ملخص القرار</button>
      <button class="btn page-tab" data-tab="validation">اختبار القوة</button>
      <button class="btn page-tab" data-tab="explore">الاستكشاف والوزن</button>
      <button class="btn page-tab" data-tab="news">الأخبار</button>
      <button class="btn page-tab" data-tab="trades">الصفقات</button>
    </nav>

    <section class="tab-section active" id="tab-overview">
      <div class="section-lead">
        <div>
          <h2>ملخص القرار</h2>
          <p>هنا نبدأ بالقراءة التنفيذية: ماذا يستحق الانتباه الآن قبل الدخول في التفاصيل.</p>
        </div>
        <div class="summary-note">الصفحة تعرض معاينة دمج، لذلك لا تعدل المحفظة ولا تستبدل الصفحة المعتمدة حتى نقرر.</div>
      </div>
      <div class="grid" id="decisionNotes"></div>
    </section>

    <section class="tab-section" id="tab-validation">
      <div class="section-lead">
        <div>
          <h2>اختبار قوة الاستنتاج</h2>
          <p>هذا القسم يمنعنا من اتخاذ قرار بسبب رقم لافت فقط. كل فرضية تعرض: ماذا وجدنا، لماذا يهم، وماذا نفعل.</p>
        </div>
      </div>
      <div class="panel">
        <div id="hypotheses"></div>
      </div>
      <section class="two" style="margin-top:14px;">
        <div class="panel">
          <h2>اختبار الوقف الأقرب</h2>
          <div class="note">قراءة من اختبار الظل، لا تغير المحفظة الأساسية.</div>
          <div class="shadow-grid" id="shadowCards"></div>
        </div>
        <div class="panel">
          <h2>فحص جودة البيانات</h2>
          <div id="profile"></div>
        </div>
      </section>
      <section class="panel" style="margin-top:14px;">
        <h2>أفضل وأسوأ القراءات</h2>
        <div class="note">هذا الجدول كان ناقصًا من الدمج الأول. يجمع أفضل وأسوأ الأسهم، الأطر، قواعد الدخول، والأشهر حتى لا نعتمد على زاوية واحدة.</div>
        <div style="overflow:auto;">
          <table>
            <thead>
              <tr>
                <th>الفئة</th>
                <th>البند</th>
                <th>الاتجاه</th>
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
    </section>

    <section class="tab-section" id="tab-explore">
      <div class="section-lead">
        <div>
          <h2>الاستكشاف والوزن</h2>
          <p>هنا تفحص السهم أو الإطار أو الشهر قبل التفكير بتغيير الوزن أو الكاش.</p>
        </div>
      </div>
      <div class="panel">
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
      </div>
    </section>

    <section class="tab-section" id="tab-news">
      <div class="section-lead">
        <div>
          <h2>الأخبار وروابط تفسير الحركة</h2>
          <p>روابط بحث جاهزة للأسهم والأشهر التي قادت الربح أو الضغط. تفسيرية فقط ولا تدخل في حساب المحاكاة.</p>
        </div>
      </div>
      <div class="news-grid" id="newsGrid"></div>
    </section>

    <section class="tab-section" id="tab-trades">
      <div class="section-lead">
        <div>
          <h2>الصفقات خلف القراءة</h2>
          <p>هذا هو مسار التدقيق: كل قراءة فوق يمكن الرجوع إلى الصفقات التي صنعتها.</p>
        </div>
      </div>
      <div class="panel" style="overflow:auto;">
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
      </div>
    </section>
  </div>

  <script id="payload" type="application/json">{data_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const decision = payload.decision;
    const analyst = payload.analyst;
    const state = {{ group: 'ticker', filterKey: '', filterValue: '' }};
    const money = (n) => '$' + Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    const pct = (n) => Number(n || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + '%';
    const cls = (n) => Number(n || 0) < 0 ? 'neg' : 'pos';
    document.getElementById('fileTimestamp').textContent = decision.fileTimestamp;

    function card(label, value, detail, tone='') {{
      return `<article class="card metric"><div class="label">${{label}}</div><div class="value ${{tone}}">${{value}}</div><div class="note">${{detail}}</div></article>`;
    }}

    function renderSummary() {{
      const s = decision.summary;
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
      document.getElementById('decisionNotes').innerHTML = decision.notes.map((n) => `
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
          showPageTab('explore');
          renderAll();
        }});
      }});
    }}

    function gradeClass(text) {{
      if (text.includes('عالية')) return 'high';
      if (text.includes('متوسطة')) return 'mid';
      return 'low';
    }}

    function renderHypotheses() {{
      document.getElementById('hypotheses').innerHTML = analyst.hypotheses.map((h) => `
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
      const p = analyst.profile;
      const missing = p.missing.filter(r => Number(r.missing) > 0);
      document.getElementById('profile').innerHTML = `
        <div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr));">
          <div class="card"><div class="label">الصفوف</div><div class="value num">${{p.rows}}</div></div>
          <div class="card"><div class="label">مكرر ID</div><div class="value num">${{p.duplicate_ids}}</div></div>
          <div class="card"><div class="label">قيم شاذة</div><div class="value num">${{p.outlier_count}}</div></div>
          <div class="card"><div class="label">نطاق البيانات</div><div class="note">${{p.start_date}} إلى ${{p.end_date}}</div></div>
        </div>
        <div class="note" style="margin-top:10px;">الفراغات المؤثرة: ${{missing.length ? missing.map(r => `${{r.column}} (${{r.missing}})`).join('، ') : 'لا توجد فراغات مؤثرة في الأعمدة الأساسية.'}}</div>
      `;
    }}

    function renderRanks() {{
      const blocks = [
        ['السهم', analyst.tables.ticker || []],
        ['الإطار', analyst.tables.timeframe || []],
        ['قاعدة الدخول', analyst.tables.entry_rule || []],
        ['الشهر', analyst.tables.month || []],
      ];
      const rows = [];
      blocks.forEach(([label, items]) => {{
        const eligible = items.filter(r => Number(r.closed || 0) > 0);
        eligible
          .slice()
          .sort((a,b) => Number(b.return_on_capital || 0) - Number(a.return_on_capital || 0))
          .slice(0, 3)
          .forEach(r => rows.push([label, 'أفضل', r]));
        eligible
          .slice()
          .sort((a,b) => Number(a.return_on_capital || 0) - Number(b.return_on_capital || 0))
          .slice(0, 3)
          .forEach(r => rows.push([label, 'أضعف', r]));
      }});
      document.getElementById('rankRows').innerHTML = rows.map(([label, side, r]) => `
        <tr>
          <td>${{label}}</td>
          <td><strong class="${{label === 'قاعدة الدخول' ? 'ltr' : ''}}">${{r.name}}</strong></td>
          <td class="${{side === 'أفضل' ? 'pos' : 'neg'}}">${{side}}</td>
          <td class="num">${{r.closed}}</td>
          <td class="num">${{pct(r.win_rate)}}</td>
          <td class="num ${{cls(r.pnl)}}">${{money(r.pnl)}}</td>
          <td class="num ${{cls(r.return_on_capital)}}">${{pct(r.return_on_capital)}}</td>
          <td class="num ${{cls(r.avg_pct)}}">${{pct(r.avg_pct)}}</td>
          <td class="num neg">${{pct(r.worst_pct)}}</td>
        </tr>
      `).join('');
    }}

    function renderShadow() {{
      const base = decision.shadow.find(r => r.scenario === 'baseline') || {{}};
      const shadow = decision.shadow.find(r => r.scenario === 'shadow_tighter_stop') || {{}};
      const diff = Number(shadow.portfolio_value || 0) - Number(base.portfolio_value || 0);
      document.getElementById('shadowCards').innerHTML = [
        card('فرق القيمة', money(diff), 'الوقف الأقرب مقارنة بالأساس', cls(diff)),
        card('فرق الخسائر', String(Number(shadow.losses || 0) - Number(base.losses || 0)), 'زيادة/نقصان الخاسرة', Number(shadow.losses || 0) > Number(base.losses || 0) ? 'neg' : 'pos'),
        card('أسوأ خسارة', pct(shadow.worst_loss_pct || 0), 'بعد الوقف الأقرب', 'neg'),
        card('رابحات تحولت لخسائر', String(shadow.winners_turned_loss || 0), 'مؤشر خطر تضييق الوقف', 'warn')
      ].join('');
    }}

    function renderNews() {{
      const grid = document.getElementById('newsGrid');
      const items = decision.news || [];
      grid.innerHTML = items.map((item) => `
        <article class="card">
          <div class="label">${{item.section}}</div>
          <h3><span class="ltr">${{item.ticker}}</span></h3>
          <div class="note">الربح: <span class="${{cls(item.pnl)}} num">${{money(item.pnl)}}</span>
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
      return decision.trades.filter(t => {{
        if (state.filterKey && String(t[state.filterKey] || '') !== state.filterValue) return false;
        if (!search) return true;
        return [t.id,t.ticker,t.timeframe,t.entry_month,t.entry_rule,t.behavior,t.strategy_id,t.status,t.outcome]
          .some(x => String(x || '').toLowerCase().includes(search));
      }});
    }}

    function rowsForGroup(trades) {{
      const base = decision.grouped[state.group] || [];
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

    function showPageTab(name) {{
      document.querySelectorAll('.page-tab').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.tab === name);
      }});
      document.querySelectorAll('.tab-section').forEach(section => {{
        section.classList.toggle('active', section.id === 'tab-' + name);
      }});
    }}

    document.querySelectorAll('.page-tab').forEach(btn => {{
      btn.addEventListener('click', () => showPageTab(btn.dataset.tab));
    }});
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
    renderHypotheses();
    renderShadow();
    renderProfile();
    renderRanks();
    renderNews();
    renderAll();
  </script>
</body>
</html>
"""


def main() -> int:
    payload = {
        "decision": build_decision_payload(),
        "analyst": data_analyst_lab.build_payload(),
    }
    OUT.write_text(render(payload), encoding="utf-8", newline="\n")
    print(f"Decision + hypothesis preview: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
