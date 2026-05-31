#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import eodhd_official_data as eodhd
import paper_portfolio_v2 as v2
import paper_portfolio_v31 as v31


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SUMMARY_CSV = REPORTS / "experimental_profit_protection_v31_summary.csv"
REPORT_HTML = REPORTS / "experimental_profit_protection_v31.html"


@dataclass(frozen=True)
class Policy:
    key: str
    label: str
    mode: str
    step_pct: float = 0.0
    activation_fraction: float = 0.0
    atr_multiplier: float = 0.0
    min_buffer_pct: float = 0.0
    max_buffer_pct: float = 0.0
    protection_trigger_pct: float = 0.0
    protection_lock_pct: float = 0.0
    update_timing: str = "intraday"


POLICIES = [
    Policy("no_trailing", "بلا وقف متحرك: الهدف أو الوقف الأصلي", "step", step_pct=1000.0),
    Policy("current_1pct", "الحالي: قفل درجات بنسبة 1 بالمئة", "step", step_pct=1.0),
    Policy("step_1_8pct", "قفل درجات بنسبة 1.8 بالمئة", "step", step_pct=1.8),
    Policy("atr_40_075", "تفعيل 40 بالمئة من الهدف | مسافة ATR بمضاعف 0.75", "atr", activation_fraction=0.40, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("atr_50_050", "تفعيل 50 بالمئة من الهدف | مسافة ATR بمضاعف 0.50", "atr", activation_fraction=0.50, atr_multiplier=0.50, min_buffer_pct=0.75, max_buffer_pct=2.5),
    Policy("atr_50_075", "تفعيل 50 بالمئة من الهدف | مسافة ATR بمضاعف 0.75", "atr", activation_fraction=0.50, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("atr_50_100", "تفعيل 50 بالمئة من الهدف | مسافة ATR بمضاعف 1.00", "atr", activation_fraction=0.50, atr_multiplier=1.00, min_buffer_pct=1.25, max_buffer_pct=4.0),
    Policy("atr_60_075", "تفعيل 60 بالمئة من الهدف | مسافة ATR بمضاعف 0.75", "atr", activation_fraction=0.60, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("atr_60_100", "تفعيل 60 بالمئة من الهدف | مسافة ATR بمضاعف 1.00", "atr", activation_fraction=0.60, atr_multiplier=1.00, min_buffer_pct=1.25, max_buffer_pct=4.0),
    Policy("stage_be1_target", "تعادل عند ربح 1 بالمئة ثم انتظار الهدف", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.0, activation_fraction=2.0),
    Policy("stage_be1_50_050", "تعادل عند 1 بالمئة | تتبع بعد نصف الهدف بمسافة 0.50 ATR", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.0, activation_fraction=0.50, atr_multiplier=0.50, min_buffer_pct=0.75, max_buffer_pct=2.5),
    Policy("stage_be1_50_075", "تعادل عند 1 بالمئة | تتبع بعد نصف الهدف بمسافة 0.75 ATR", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.0, activation_fraction=0.50, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("stage_lock05_50_075", "تأمين 0.5 بالمئة عند 1 بالمئة | تتبع بعد نصف الهدف بمسافة 0.75 ATR", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.5, activation_fraction=0.50, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("stage_be1_60_075", "تعادل عند 1 بالمئة | تتبع بعد 60 بالمئة من الهدف بمسافة 0.75 ATR", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.0, activation_fraction=0.60, atr_multiplier=0.75, min_buffer_pct=1.0, max_buffer_pct=3.0),
    Policy("stage_be1_60_100", "تعادل عند 1 بالمئة | تتبع بعد 60 بالمئة من الهدف بمسافة 1.00 ATR", "staged", protection_trigger_pct=1.0, protection_lock_pct=0.0, activation_fraction=0.60, atr_multiplier=1.00, min_buffer_pct=1.25, max_buffer_pct=4.0),
]


def fnum(value: Any, default: float = 0.0) -> float:
    return v31.fnum(value, default)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def update_stop(trade: dict[str, Any], high_price: float, policy: Policy) -> None:
    entry = fnum(trade["entry_price"])
    highest = max(fnum(trade.get("highest_price"), entry), high_price)
    trade["highest_price"] = round(highest, 4)
    gain_pct = (highest / entry - 1) * 100
    if policy.mode == "step":
        if gain_pct < policy.step_pct:
            return
        locked_gain = math.floor(gain_pct / policy.step_pct) * policy.step_pct
        candidate = entry * (1 + locked_gain / 100)
    elif policy.mode == "atr":
        activation_pct = fnum(trade["target_pct"]) * policy.activation_fraction
        if gain_pct < activation_pct:
            return
        buffer_pct = min(
            policy.max_buffer_pct,
            max(policy.min_buffer_pct, fnum(trade["entry_atr_pct"]) * policy.atr_multiplier),
        )
        candidate = max(entry, highest * (1 - buffer_pct / 100))
        trade["active_buffer_pct"] = round(buffer_pct, 4)
    else:
        if gain_pct >= policy.protection_trigger_pct:
            candidate = entry * (1 + policy.protection_lock_pct / 100)
            trade["stop_price"] = round(max(fnum(trade["stop_price"]), candidate), 4)
        activation_pct = fnum(trade["target_pct"]) * policy.activation_fraction
        if gain_pct < activation_pct or policy.atr_multiplier <= 0:
            return
        buffer_pct = min(
            policy.max_buffer_pct,
            max(policy.min_buffer_pct, fnum(trade["entry_atr_pct"]) * policy.atr_multiplier),
        )
        candidate = max(entry * (1 + policy.protection_lock_pct / 100), highest * (1 - buffer_pct / 100))
        trade["active_buffer_pct"] = round(buffer_pct, 4)
    trade["stop_price"] = round(max(fnum(trade["stop_price"]), candidate), 4)


def simulate(
    strategies: list[dict[str, Any]],
    policy: Policy,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    tickers = sorted({str(strategy["ticker"]) for strategy in strategies})
    daily = {ticker: eodhd.read_daily_bars(ticker) for ticker in tickers}
    intraday = {ticker: eodhd.intraday_by_date(ticker) for ticker in tickers}
    index_maps = {ticker: {bar.date: idx for idx, bar in enumerate(bars)} for ticker, bars in daily.items()}
    market_cache = v31.official_market_cache()
    start_date = period_start or v31.CONFIG["start_date"]
    dates = sorted(
        {
            bar.date
            for bars in daily.values()
            for bar in bars
            if bar.date >= start_date and (period_end is None or bar.date <= period_end)
        }
    )
    state: dict[str, Any] = {
        "initial_capital": v2.INITIAL_CAPITAL,
        "cash": v2.INITIAL_CAPITAL,
        "trades": [],
        "snapshots": [],
        "skipped": [],
        "quality_gate": [],
        "next_id": 1,
        "policy": policy.key,
        "period_start": start_date,
        "period_end": period_end or "",
    }
    open_trades: list[dict[str, Any]] = []

    for current_date in dates:
        for trade in list(open_trades):
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or current_date <= str(trade["entry_date"]):
                continue
            day_bar = daily[ticker][idx]
            trade["held_sessions"] = int(trade.get("held_sessions", 0)) + 1
            intraday_bars = intraday[ticker].get(current_date, [])
            if not intraday_bars:
                raise RuntimeError(f"Missing EODHD 5m session for {ticker} on {current_date}.")
            closed = False
            for bar in intraday_bars:
                stop = fnum(trade["stop_price"])
                target = fnum(trade["exit_price"])
                if fnum(bar["low"]) <= stop:
                    outcome = "TRAILING_WIN" if stop >= fnum(trade["entry_price"]) else "LOSS"
                    v2.close_trade(state, trade, current_date, stop, "experimental stop", outcome)
                    trade["close_time_et"] = str(bar["time_et"])
                    open_trades.remove(trade)
                    closed = True
                    break
                if fnum(bar["high"]) >= target:
                    v2.close_trade(state, trade, current_date, target, "strategy target", "WIN")
                    trade["close_time_et"] = str(bar["time_et"])
                    open_trades.remove(trade)
                    closed = True
                    break
                if policy.update_timing == "intraday":
                    # A stop calculated from this bar is first executable on the next bar.
                    update_stop(trade, fnum(bar["high"]), policy)
            if closed:
                continue
            if int(trade["held_sessions"]) >= int(trade["hold_days"]):
                pnl_pct = (day_bar.close / fnum(trade["entry_price"]) - 1) * 100
                outcome = "TIMEOUT_WIN" if pnl_pct > 0 else "TIMEOUT_LOSS"
                v2.close_trade(state, trade, current_date, day_bar.close, "holding period ended", outcome)
                trade["close_time_et"] = "16:00:00"
                open_trades.remove(trade)
                continue
            if policy.update_timing == "daily_close":
                # Daily strategies may only raise protection after the completed daily close.
                update_stop(trade, day_bar.close, policy)
            elif policy.update_timing == "daily_high_next_session":
                # Use the completed session high, but expose the raised stop only next session.
                session_high = max(fnum(bar["high"]) for bar in intraday_bars)
                update_stop(trade, session_high, policy)

        for strategy in strategies:
            ticker = str(strategy["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None or idx == 0:
                continue
            bars = daily[ticker]
            if not v31.hybrid_entry_signal(strategy, bars, idx, market_cache):
                continue
            if any(
                trade["status"] == "OPEN"
                and trade["ticker"] == ticker
                and trade.get("strategy_id") == strategy.get("strategy_id")
                for trade in open_trades
            ):
                continue
            bar = bars[idx]
            cash = fnum(state["cash"])
            target_alloc = cash * v2.POSITION_CAP_PCT * min(fnum(strategy.get("size_multiplier"), 1.0), 1.0)
            adv = v2.avg_dollar_volume(bars, idx)
            liquidity_cap = adv * v2.MAX_TRADE_ADV_PCT if adv else target_alloc
            allocation = min(cash, target_alloc, liquidity_cap)
            shares = math.floor(allocation / bar.close) if bar.close > 0 else 0
            if shares <= 0:
                continue
            entry = bar.close
            target_pct = fnum(strategy["target_pct"])
            target = entry * (1 + target_pct / 100)
            technical_stop = v31.stop_price(strategy, bars, idx)
            atr_value = v2.atr(bars, idx) or 0.0
            capital = shares * entry
            trade = {
                "id": f"XP-{state['next_id']:04d}",
                "ticker": ticker,
                "strategy_id": strategy.get("strategy_id", ""),
                "strategy_source": strategy.get("strategy_source", ""),
                "timeframe": strategy.get("timeframe", ""),
                "status": "OPEN",
                "outcome": "OPEN",
                "entry_date": current_date,
                "entry_price": round(entry, 4),
                "shares": shares,
                "capital": round(capital, 2),
                "stop_price": round(technical_stop, 4),
                "initial_stop_price": round(technical_stop, 4),
                "highest_price": round(entry, 4),
                "target_pct": target_pct,
                "exit_price": round(target, 4),
                "entry_atr_pct": round(atr_value / entry * 100 if entry else 0.0, 4),
                "hold_days": int(fnum(strategy["hold_days"])),
                "held_sessions": 0,
                "latest_price": round(entry, 4),
                "market_value": round(capital, 2),
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "realized_pnl": 0.0,
                "realized_pnl_pct": 0.0,
                "close_date": "",
                "close_time_et": "",
                "close_price": "",
                "close_reason": "",
            }
            state["next_id"] += 1
            state["cash"] = round(cash - capital, 2)
            state["trades"].append(trade)
            open_trades.append(trade)

        for trade in open_trades:
            ticker = str(trade["ticker"])
            idx = index_maps[ticker].get(current_date)
            if idx is None:
                continue
            close = daily[ticker][idx].close
            market_value = int(trade["shares"]) * close
            trade["latest_price"] = round(close, 4)
            trade["market_value"] = round(market_value, 2)
            trade["unrealized_pnl"] = round(market_value - fnum(trade["capital"]), 2)
            trade["unrealized_pnl_pct"] = round((close / fnum(trade["entry_price"]) - 1) * 100, 2)
        state["snapshots"].append(
            {
                "date": current_date,
                "value": v2.portfolio_value(state),
                "cash": round(fnum(state["cash"]), 2),
                "open_trades": len(open_trades),
            }
        )
    return state


def render(rows: list[dict[str, Any]]) -> str:
    best = max(rows, key=lambda row: fnum(row["portfolio_value"]))
    current = next(row for row in rows if row["key"] == "current_1pct")
    table_rows = "".join(
        "<tr class='{}'><td>{}</td><td class='num'>{}</td><td class='num {}'>{}</td>"
        "<td class='num {}'>{}</td><td class='num negative'>{}</td><td class='num'>{} / {}</td>"
        "<td class='num'>{}</td><td class='num'>{}</td></tr>".format(
            "best" if row["key"] == best["key"] else "",
            html.escape(str(row["label"])),
            f"${fnum(row['portfolio_value']):,.2f}",
            "positive" if fnum(row["period_return_pct"]) >= 0 else "negative",
            f"{fnum(row['period_return_pct']):,.2f}%",
            "positive" if fnum(row["delta_value"]) >= 0 else "negative",
            f"${fnum(row['delta_value']):,.2f}",
            f"{fnum(row['max_drawdown_pct']):,.2f}%",
            row["wins"],
            row["losses"],
            f"{fnum(row['avg_win_pct']):,.2f}%",
            f"{fnum(row['avg_loss_pct']):,.2f}%",
        )
        for row in rows
    )
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>اختبار حماية الربح المرنة</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f4f7fb;color:#09243d;font-family:Tahoma,Arial,sans-serif}}
.wrap{{max-width:1220px;margin:auto;padding:28px}} h1{{margin:0 0 8px;font-size:29px}} p{{color:#567089;line-height:1.9}}
.notice{{background:#fff5de;border:1px solid #e7bd62;border-radius:8px;padding:13px 17px;margin:18px 0}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}} .card,.panel{{background:#fff;border:1px solid #d7e1ea;border-radius:8px;padding:18px}}
.card span{{display:block;color:#62788c;margin-bottom:8px}} .card strong{{font-size:28px;direction:ltr;display:block}}
.positive{{color:#087852}} .negative{{color:#b53434}} table{{width:100%;border-collapse:collapse;background:#fff}}
th,td{{padding:13px 10px;border-bottom:1px solid #e2eaf2;text-align:right}} th{{background:#eaf0f6;color:#23415d}}
.num,.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}} td.num{{text-align:left}} tr.best{{background:#eaf7f1}} .explain{{margin-top:18px;line-height:2}}
@media(max-width:820px){{.cards{{grid-template-columns:1fr}} .panel{{overflow-x:auto}} table{{min-width:920px}}}}
</style></head><body><main class="wrap">
<h1>اختبار حماية الربح المرنة</h1>
<p>اختبار جانبي فقط: الدخول والمؤشرات اليومية ومصدر البيانات وتنفيذ الخروج بخمس دقائق ثابتة. المتغير الوحيد هو طريقة تحريك الوقف بعد الدخول.</p>
<div class="notice">لم يتم تعديل المحفظة الرسمية أو الداشبورد الرئيسي. نتائج هذا الاختبار تاريخية وتحتاج تحقق إضافي قبل أي اعتماد.</div>
<section class="cards">
<article class="card"><span>السياسة الحالية</span><strong>${fnum(current['portfolio_value']):,.2f}</strong><small>عائد الفترة <span class="ltr">{fnum(current['period_return_pct']):,.2f}%</span></small></article>
<article class="card"><span>أفضل نتيجة في الاختبار</span><strong class="positive">${fnum(best['portfolio_value']):,.2f}</strong><small>{html.escape(str(best['label']))}</small></article>
<article class="card"><span>فرق الأفضل عن الحالية</span><strong class="positive">${fnum(best['delta_value']):,.2f}</strong><small>السحب الأقصى <span class="ltr">{fnum(best['max_drawdown_pct']):,.2f}%</span></small></article>
</section>
<section class="panel"><table><thead><tr><th>السياسة</th><th>قيمة المحفظة</th><th>عائد الفترة</th><th>الفرق عن الحالية</th><th>السحب الأقصى</th><th>رابحة / خاسرة</th><th>متوسط الرابحة</th><th>متوسط الخاسرة</th></tr></thead><tbody>{table_rows}</tbody></table></section>
<section class="panel explain">
<strong>طريقة السياسة المرنة</strong>
<p>يبدأ الوقف المتحرك فقط بعد وصول الصفقة إلى جزء محدد من هدفها. بعد ذلك يبقى الوقف خلف أعلى سعر بمسافة محسوبة من تذبذب السهم اليومي عند لحظة الدخول، ولا يستخدم أي بيانات مستقبلية. الوقف الذي يتغير في شمعة خمس دقائق يصبح قابلا للتنفيذ ابتداء من الشمعة التالية.</p>
</section>
</main></body></html>"""


def main() -> int:
    strategies = v31.load_hybrid_strategies()
    results: list[dict[str, Any]] = []
    for policy in POLICIES:
        state = simulate(strategies, policy)
        summary = v31.portfolio_summary(state, policy.label)
        results.append(
            {
                "key": policy.key,
                "label": policy.label,
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
        )
    baseline = next(row for row in results if row["key"] == "current_1pct")
    for row in results:
        row["delta_value"] = round(fnum(row["portfolio_value"]) - fnum(baseline["portfolio_value"]), 2)
        row["delta_return_pct"] = round(fnum(row["period_return_pct"]) - fnum(baseline["period_return_pct"]), 2)
    write_csv(SUMMARY_CSV, results)
    REPORT_HTML.write_text(render(results), encoding="utf-8", newline="\n")
    print(json.dumps(sorted(results, key=lambda row: fnum(row["portfolio_value"]), reverse=True), ensure_ascii=False, indent=2))
    print(f"Report: {REPORT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
