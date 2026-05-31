#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "market_data"
REPORTS = ROOT / "reports"
TRADES_CSV = REPORTS / "paper_trades_v2.csv"
OUT = REPORTS / "financial_diagnostics_lab.html"
JSON_OUT = REPORTS / "financial_diagnostics_lab.json"
BENCHMARKS = ("SPY", "QQQ", "SOXX")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
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


def stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def pct_change(start: float, end: float) -> float:
    return (end - start) / start * 100.0 if start else 0.0


def load_prices(ticker: str) -> list[dict[str, Any]]:
    rows = []
    for row in read_csv(DATA_DIR / f"{ticker}_daily.csv"):
        close = fnum(row.get("close"))
        rows.append(
            {
                "date": row.get("date", ""),
                "open": fnum(row.get("open")),
                "high": fnum(row.get("high")),
                "low": fnum(row.get("low")),
                "close": close,
                "volume": fnum(row.get("volume")),
            }
        )
    rows.sort(key=lambda item: item["date"])
    return rows


def add_indicators(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []
    returns: list[float] = []
    prev_close = 0.0

    for row in rows:
        close = fnum(row["close"])
        high = fnum(row["high"])
        low = fnum(row["low"])
        volume = fnum(row["volume"])
        ret = (close / prev_close - 1.0) if prev_close else 0.0
        returns.append(ret)
        closes.append(close)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)

        idx = len(closes) - 1
        row["ret1"] = ret * 100.0

        for period in (20, 50, 200):
            if len(closes) >= period:
                row[f"ma{period}"] = mean(closes[-period:])
                row[f"ret{period}"] = pct_change(closes[-period], close)
            else:
                row[f"ma{period}"] = 0.0
                row[f"ret{period}"] = 0.0

        if len(closes) >= 15:
            changes = [closes[i] - closes[i - 1] for i in range(idx - 13, idx + 1)]
            gains = [max(change, 0.0) for change in changes]
            losses = [abs(min(change, 0.0)) for change in changes]
            avg_gain = mean(gains)
            avg_loss = mean(losses)
            row["rsi14"] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
        else:
            row["rsi14"] = 50.0

        if len(returns) >= 21:
            ret_window = returns[-20:]
            row["vol20_ann"] = stdev(ret_window) * math.sqrt(252.0) * 100.0
            row["var60_95"] = percentile(returns[-60:], 0.05) * 100.0 if len(returns) >= 60 else percentile(ret_window, 0.05) * 100.0
        else:
            row["vol20_ann"] = 0.0
            row["var60_95"] = 0.0

        if len(returns) >= 64:
            ret_window = returns[-63:]
            sigma = stdev(ret_window)
            row["sharpe63"] = (mean(ret_window) / sigma * math.sqrt(252.0)) if sigma else 0.0
        else:
            row["sharpe63"] = 0.0

        if len(closes) >= 15:
            tr_values = []
            for i in range(idx - 13, idx + 1):
                prev = closes[i - 1] if i > 0 else closes[i]
                tr_values.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
            row["atr14_pct"] = mean(tr_values) / close * 100.0 if close else 0.0
        else:
            row["atr14_pct"] = 0.0

        if len(closes) >= 20:
            support = min(lows[-20:])
            resistance = max(highs[-20:])
            row["support20"] = support
            row["resistance20"] = resistance
            row["support_gap_pct"] = (close - support) / close * 100.0 if close else 0.0
            row["resistance_gap_pct"] = (resistance - close) / close * 100.0 if close else 0.0
            row["volume_ratio20"] = volume / mean(volumes[-20:]) if mean(volumes[-20:]) else 0.0
        else:
            row["support20"] = low
            row["resistance20"] = high
            row["support_gap_pct"] = 0.0
            row["resistance_gap_pct"] = 0.0
            row["volume_ratio20"] = 1.0

        row["trend_score"] = trend_score(row)
        row["trend_label"] = trend_label(row["trend_score"])
        row["rsi_zone"] = rsi_zone(row["rsi14"])
        row["volatility_bucket"] = volatility_bucket(row["vol20_ann"])
        row["price_location"] = price_location(row["support_gap_pct"], row["resistance_gap_pct"])
        prev_close = close

    return rows


def trend_score(row: dict[str, Any]) -> int:
    close = fnum(row.get("close"))
    ma20 = fnum(row.get("ma20"))
    ma50 = fnum(row.get("ma50"))
    ma200 = fnum(row.get("ma200"))
    score = 0
    score += int(close > ma20 and ma20 > 0)
    score += int(close > ma50 and ma50 > 0)
    score += int(close > ma200 and ma200 > 0)
    score += int(ma20 > ma50 and ma50 > 0)
    score += int(ma50 > ma200 and ma200 > 0)
    return score


def trend_label(score: int) -> str:
    if score >= 4:
        return "صاعد قوي"
    if score == 3:
        return "صاعد"
    if score == 2:
        return "متذبذب"
    return "هابط"


def rsi_zone(rsi: float) -> str:
    if rsi >= 70:
        return "تشبع شراء"
    if rsi >= 60:
        return "زخم مرتفع"
    if rsi >= 45:
        return "متوازن"
    if rsi >= 30:
        return "ضعف"
    return "تشبع بيع"


def volatility_bucket(vol: float) -> str:
    if vol >= 60:
        return "تذبذب عال"
    if vol >= 35:
        return "تذبذب متوسط"
    return "تذبذب منخفض"


def price_location(support_gap: float, resistance_gap: float) -> str:
    if resistance_gap <= 2.0:
        return "قريب من مقاومة"
    if support_gap <= 2.0:
        return "قريب من دعم"
    return "منتصف النطاق"


def risk_label(row: dict[str, Any]) -> str:
    vol = fnum(row.get("vol20_ann"))
    var = fnum(row.get("var60_95"))
    atr = fnum(row.get("atr14_pct"))
    if vol >= 60 or var <= -4.0 or atr >= 5.0:
        return "مرتفع"
    if vol >= 35 or var <= -2.5 or atr >= 3.0:
        return "متوسط"
    return "منخفض"


def technical_score(row: dict[str, Any]) -> float:
    trend = fnum(row.get("trend_score")) / 5.0 * 45.0
    sharpe = max(0.0, min(20.0, (fnum(row.get("sharpe63")) + 1.0) / 3.0 * 20.0))
    vol = fnum(row.get("vol20_ann"))
    vol_component = 15.0 if vol < 35 else 10.0 if vol < 60 else 5.0
    rsi = fnum(row.get("rsi14"))
    rsi_component = 15.0 if 40 <= rsi <= 65 else 10.0 if 30 <= rsi < 70 else 5.0
    location_component = 10.0 if row.get("price_location") != "قريب من مقاومة" else 5.0
    return round(trend + sharpe + vol_component + rsi_component + location_component, 2)


def score_label(score: float) -> str:
    if score >= 75:
        return "داعم قوي"
    if score >= 60:
        return "داعم"
    if score >= 45:
        return "محايد"
    return "ضغط"


def find_row_on_or_before(rows: list[dict[str, Any]], date_text: str) -> dict[str, Any] | None:
    if not rows:
        return None
    candidate = None
    for row in rows:
        if row["date"] <= date_text:
            candidate = row
        else:
            break
    return candidate


def market_alignment(stock_row: dict[str, Any] | None, market_row: dict[str, Any] | None) -> str:
    if not stock_row or not market_row:
        return "غير محدد"
    stock_ret = fnum(stock_row.get("ret20"))
    market_ret = fnum(market_row.get("ret20"))
    if market_ret >= 0 and stock_ret >= market_ret:
        return "أقوى من السوق"
    if market_ret >= 0 and stock_ret >= 0:
        return "مع السوق"
    if market_ret >= 0 and stock_ret < 0:
        return "متأخر عن السوق"
    if market_ret < 0 and stock_ret >= 0:
        return "قوة دفاعية"
    return "ضغط سوقي"


def load_trades() -> list[dict[str, Any]]:
    trades = []
    for row in read_csv(TRADES_CSV):
        status = row.get("status", "")
        realized = fnum(row.get("realized_pnl"))
        unrealized = fnum(row.get("unrealized_pnl"))
        pnl = realized if status == "CLOSED" else unrealized
        pnl_pct = fnum(row.get("realized_pnl_pct"))
        if status != "CLOSED":
            entry = fnum(row.get("entry_price"))
            latest = fnum(row.get("latest_price"))
            pnl_pct = pct_change(entry, latest)
        trades.append(
            {
                **row,
                "ticker": row.get("ticker", ""),
                "timeframe": row.get("timeframe", ""),
                "status": status,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "capital": fnum(row.get("capital")),
                "shares": inum(row.get("shares")),
            }
        )
    return trades


def group_stats(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "غير محدد")].append(row)
    output = []
    for name, items in buckets.items():
        closed = [item for item in items if item.get("status") == "CLOSED"]
        wins = [item for item in closed if fnum(item.get("pnl")) > 0]
        losses = [item for item in closed if fnum(item.get("pnl")) < 0]
        pcts = [fnum(item.get("pnl_pct")) for item in closed]
        pnl = sum(fnum(item.get("pnl")) for item in items)
        output.append(
            {
                "name": name,
                "trades": len(items),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
                "pnl": round(pnl, 2),
                "avg_pct": round(mean(pcts), 2),
                "median_pct": round(statistics.median(pcts), 2) if pcts else 0.0,
                "best_pct": round(max(pcts), 2) if pcts else 0.0,
                "worst_pct": round(min(pcts), 2) if pcts else 0.0,
            }
        )
    return sorted(output, key=lambda item: fnum(item["pnl"]), reverse=True)


def enrich_trades(
    trades: list[dict[str, Any]],
    prices_by_ticker: dict[str, list[dict[str, Any]]],
    spy_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched = []
    for trade in trades:
        ticker = str(trade.get("ticker"))
        rows = prices_by_ticker.get(ticker, [])
        entry_row = find_row_on_or_before(rows, str(trade.get("entry_date", "")))
        latest_row = rows[-1] if rows else None
        market_entry = find_row_on_or_before(spy_rows, str(trade.get("entry_date", "")))
        trade = dict(trade)
        if entry_row:
            trade.update(
                {
                    "entry_trend": entry_row.get("trend_label"),
                    "entry_rsi_zone": entry_row.get("rsi_zone"),
                    "entry_volatility": entry_row.get("volatility_bucket"),
                    "entry_location": entry_row.get("price_location"),
                    "entry_rsi14": round(fnum(entry_row.get("rsi14")), 2),
                    "entry_vol20_ann": round(fnum(entry_row.get("vol20_ann")), 2),
                    "entry_sharpe63": round(fnum(entry_row.get("sharpe63")), 2),
                    "entry_var60_95": round(fnum(entry_row.get("var60_95")), 2),
                    "entry_market_alignment": market_alignment(entry_row, market_entry),
                    "entry_technical_score": technical_score(entry_row),
                }
            )
        else:
            trade.update(
                {
                    "entry_trend": "غير محدد",
                    "entry_rsi_zone": "غير محدد",
                    "entry_volatility": "غير محدد",
                    "entry_location": "غير محدد",
                    "entry_rsi14": 0.0,
                    "entry_vol20_ann": 0.0,
                    "entry_sharpe63": 0.0,
                    "entry_var60_95": 0.0,
                    "entry_market_alignment": "غير محدد",
                    "entry_technical_score": 0.0,
                }
            )
        if latest_row:
            trade["latest_trend"] = latest_row.get("trend_label")
            trade["latest_risk"] = risk_label(latest_row)
            trade["latest_score"] = technical_score(latest_row)
        enriched.append(trade)
    return enriched


def ticker_diagnostics(
    tickers: list[str],
    prices_by_ticker: dict[str, list[dict[str, Any]]],
    trades: list[dict[str, Any]],
    spy_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        by_ticker[str(trade.get("ticker"))].append(trade)
    latest_spy = spy_rows[-1] if spy_rows else None
    rows = []
    for ticker in tickers:
        price_rows = prices_by_ticker.get(ticker, [])
        latest = price_rows[-1] if price_rows else {}
        ticker_trades = by_ticker.get(ticker, [])
        closed = [trade for trade in ticker_trades if trade.get("status") == "CLOSED"]
        wins = [trade for trade in closed if fnum(trade.get("pnl")) > 0]
        losses = [trade for trade in closed if fnum(trade.get("pnl")) < 0]
        pnl = sum(fnum(trade.get("pnl")) for trade in ticker_trades)
        score = technical_score(latest) if latest else 0.0
        rows.append(
            {
                "ticker": ticker,
                "date": latest.get("date", ""),
                "close": round(fnum(latest.get("close")), 2),
                "trend": latest.get("trend_label", "غير محدد"),
                "trend_score": inum(latest.get("trend_score")),
                "rsi14": round(fnum(latest.get("rsi14")), 2),
                "rsi_zone": latest.get("rsi_zone", "غير محدد"),
                "ma20": round(fnum(latest.get("ma20")), 2),
                "ma50": round(fnum(latest.get("ma50")), 2),
                "ma200": round(fnum(latest.get("ma200")), 2),
                "vol20_ann": round(fnum(latest.get("vol20_ann")), 2),
                "atr14_pct": round(fnum(latest.get("atr14_pct")), 2),
                "var60_95": round(fnum(latest.get("var60_95")), 2),
                "sharpe63": round(fnum(latest.get("sharpe63")), 2),
                "support20": round(fnum(latest.get("support20")), 2),
                "resistance20": round(fnum(latest.get("resistance20")), 2),
                "support_gap_pct": round(fnum(latest.get("support_gap_pct")), 2),
                "resistance_gap_pct": round(fnum(latest.get("resistance_gap_pct")), 2),
                "location": latest.get("price_location", "غير محدد"),
                "risk": risk_label(latest),
                "market_alignment": market_alignment(latest, latest_spy),
                "technical_score": score,
                "score_label": score_label(score),
                "trades": len(ticker_trades),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
                "pnl": round(pnl, 2),
                "avg_pct": round(mean([fnum(trade.get("pnl_pct")) for trade in closed]), 2) if closed else 0.0,
            }
        )
    return sorted(rows, key=lambda item: (fnum(item["technical_score"]), fnum(item["pnl"])), reverse=True)


def market_diagnostics(prices_by_ticker: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for ticker in BENCHMARKS:
        latest = prices_by_ticker.get(ticker, [])[-1] if prices_by_ticker.get(ticker) else {}
        score = technical_score(latest) if latest else 0.0
        rows.append(
            {
                "ticker": ticker,
                "date": latest.get("date", ""),
                "close": round(fnum(latest.get("close")), 2),
                "trend": latest.get("trend_label", "غير محدد"),
                "ret20": round(fnum(latest.get("ret20")), 2),
                "ret50": round(fnum(latest.get("ret50")), 2),
                "vol20_ann": round(fnum(latest.get("vol20_ann")), 2),
                "sharpe63": round(fnum(latest.get("sharpe63")), 2),
                "var60_95": round(fnum(latest.get("var60_95")), 2),
                "technical_score": score,
                "score_label": score_label(score),
            }
        )
    return rows


def diagnostic_findings(groups: dict[str, list[dict[str, Any]]], overall: dict[str, float]) -> list[dict[str, str]]:
    findings = []
    labels = {
        "entry_trend": "الترند وقت الدخول",
        "entry_rsi_zone": "RSI وقت الدخول",
        "entry_volatility": "التذبذب وقت الدخول",
        "entry_location": "مكان السعر",
        "entry_market_alignment": "علاقة السهم بالسوق",
    }
    for key, rows in groups.items():
        for row in rows:
            if inum(row.get("closed")) < 10:
                continue
            avg_delta = fnum(row.get("avg_pct")) - overall["avg_pct"]
            win_delta = fnum(row.get("win_rate")) - overall["win_rate"]
            if avg_delta >= 1.0 and win_delta >= 0:
                tone = "داعم"
                action = "نختبر رفع أولوية هذا السياق عند تحقق الإشارة."
            elif avg_delta <= -1.0 or fnum(row.get("worst_pct")) <= overall["worst_pct"] - 3.0:
                tone = "ضغط"
                action = "نختبره كفلتر تحذير قبل الدخول أو لتخفيف حجم الصفقة."
            else:
                tone = "محايد"
                action = "نراقبه بدون تعديل حتى يظهر فرق أكبر."
            findings.append(
                {
                    "dimension": labels.get(key, key),
                    "name": str(row.get("name")),
                    "tone": tone,
                    "closed": str(row.get("closed")),
                    "win_rate": f"{fnum(row.get('win_rate')):.2f}%",
                    "avg_pct": f"{fnum(row.get('avg_pct')):.2f}%",
                    "worst_pct": f"{fnum(row.get('worst_pct')):.2f}%",
                    "action": action,
                }
            )
    tone_order = {"داعم": 0, "ضغط": 1, "محايد": 2}
    return sorted(findings, key=lambda item: (tone_order.get(item["tone"], 9), item["dimension"], item["name"]))


def build_payload() -> dict[str, Any]:
    trades = load_trades()
    tickers = sorted({str(trade.get("ticker")) for trade in trades if trade.get("ticker")})
    all_price_tickers = sorted(set(tickers).union(BENCHMARKS))
    prices_by_ticker = {ticker: add_indicators(load_prices(ticker)) for ticker in all_price_tickers}
    spy_rows = prices_by_ticker.get("SPY", [])
    enriched_trades = enrich_trades(trades, prices_by_ticker, spy_rows)
    closed = [trade for trade in enriched_trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if fnum(trade.get("pnl")) > 0]
    losses = [trade for trade in closed if fnum(trade.get("pnl")) < 0]
    overall = {
        "trades": len(enriched_trades),
        "closed": len(closed),
        "open": len(enriched_trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
        "avg_pct": round(mean([fnum(trade.get("pnl_pct")) for trade in closed]), 2) if closed else 0.0,
        "worst_pct": round(min([fnum(trade.get("pnl_pct")) for trade in closed]), 2) if closed else 0.0,
        "total_pnl": round(sum(fnum(trade.get("pnl")) for trade in enriched_trades), 2),
    }
    groups = {
        "entry_trend": group_stats(enriched_trades, "entry_trend"),
        "entry_rsi_zone": group_stats(enriched_trades, "entry_rsi_zone"),
        "entry_volatility": group_stats(enriched_trades, "entry_volatility"),
        "entry_location": group_stats(enriched_trades, "entry_location"),
        "entry_market_alignment": group_stats(enriched_trades, "entry_market_alignment"),
    }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_files": {
            "trades": str(TRADES_CSV.relative_to(ROOT)),
            "market_data": str(DATA_DIR.relative_to(ROOT)),
        },
        "summary": overall,
        "market": market_diagnostics(prices_by_ticker),
        "tickers": ticker_diagnostics(tickers, prices_by_ticker, enriched_trades, spy_rows),
        "groups": groups,
        "findings": diagnostic_findings(groups, overall),
        "open_trades": [trade for trade in enriched_trades if trade.get("status") != "CLOSED"],
        "trade_samples": sorted(closed, key=lambda item: fnum(item.get("pnl_pct")))[:12]
        + sorted(closed, key=lambda item: fnum(item.get("pnl_pct")), reverse=True)[:12],
    }


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def money(value: Any) -> str:
    return f"${fnum(value):,.2f}"


def pct(value: Any) -> str:
    return f"{fnum(value):,.2f}%"


def cls(value: Any) -> str:
    return "neg" if fnum(value) < 0 else "pos"


def tone_class(text: str) -> str:
    if text in {"داعم", "داعم قوي", "صاعد", "صاعد قوي", "أقوى من السوق"}:
        return "pos"
    if text in {"ضغط", "هابط", "مرتفع", "تشبع شراء", "متأخر عن السوق", "ضغط سوقي"}:
        return "neg"
    return "warn"


def render_metric(label: str, value: str, note: str, tone: str = "") -> str:
    return f"""
    <article class="card metric">
      <div class="label">{esc(label)}</div>
      <div class="value {tone}">{value}</div>
      <div class="note">{esc(note)}</div>
    </article>
    """


def render_group_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="9">لا توجد بيانات.</td></tr>'
    return "\n".join(
        f"""
        <tr>
          <td><strong>{esc(row["name"])}</strong></td>
          <td class="num">{esc(row["closed"])}</td>
          <td class="num">{esc(row["wins"])} / {esc(row["losses"])}</td>
          <td class="num">{pct(row["win_rate"])}</td>
          <td class="num {cls(row["pnl"])}">{money(row["pnl"])}</td>
          <td class="num {cls(row["avg_pct"])}">{pct(row["avg_pct"])}</td>
          <td class="num {cls(row["median_pct"])}">{pct(row["median_pct"])}</td>
          <td class="num pos">{pct(row["best_pct"])}</td>
          <td class="num neg">{pct(row["worst_pct"])}</td>
        </tr>
        """
        for row in rows
    )


def render(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    market_rows = "\n".join(
        f"""
        <tr>
          <td><strong class="ltr">{esc(row["ticker"])}</strong></td>
          <td>{esc(row["date"])}</td>
          <td class="num">{money(row["close"])}</td>
          <td class="{tone_class(row["trend"])}">{esc(row["trend"])}</td>
          <td class="num {cls(row["ret20"])}">{pct(row["ret20"])}</td>
          <td class="num {cls(row["ret50"])}">{pct(row["ret50"])}</td>
          <td class="num">{pct(row["vol20_ann"])}</td>
          <td class="num {cls(row["sharpe63"])}">{esc(row["sharpe63"])}</td>
          <td class="num neg">{pct(row["var60_95"])}</td>
          <td class="{tone_class(row["score_label"])}">{esc(row["score_label"])}</td>
        </tr>
        """
        for row in payload["market"]
    )
    ticker_rows = "\n".join(
        f"""
        <tr data-search="{esc(row["ticker"])} {esc(row["trend"])} {esc(row["rsi_zone"])} {esc(row["risk"])} {esc(row["market_alignment"])}">
          <td><strong class="ltr">{esc(row["ticker"])}</strong></td>
          <td>{esc(row["date"])}</td>
          <td class="num">{money(row["close"])}</td>
          <td class="{tone_class(row["trend"])}">{esc(row["trend"])} <span class="chip">{esc(row["trend_score"])}/5</span></td>
          <td>{esc(row["rsi_zone"])} <span class="chip num">{esc(row["rsi14"])}</span></td>
          <td class="num">{money(row["ma20"])} / {money(row["ma50"])} / {money(row["ma200"])}</td>
          <td>{esc(row["location"])} <span class="chip">دعم {pct(row["support_gap_pct"])}</span> <span class="chip">مقاومة {pct(row["resistance_gap_pct"])}</span></td>
          <td class="{tone_class(row["risk"])}">{esc(row["risk"])} <span class="chip">Vol {pct(row["vol20_ann"])}</span> <span class="chip">VaR {pct(row["var60_95"])}</span></td>
          <td class="num {cls(row["sharpe63"])}">{esc(row["sharpe63"])}</td>
          <td class="{tone_class(row["market_alignment"])}">{esc(row["market_alignment"])}</td>
          <td class="{tone_class(row["score_label"])}">{esc(row["score_label"])} <span class="chip num">{esc(row["technical_score"])}</span></td>
          <td class="num">{esc(row["closed"])}</td>
          <td class="num">{pct(row["win_rate"])}</td>
          <td class="num {cls(row["pnl"])}">{money(row["pnl"])}</td>
        </tr>
        """
        for row in payload["tickers"]
    )
    finding_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(row["dimension"])}</td>
          <td><strong>{esc(row["name"])}</strong></td>
          <td class="{tone_class(row["tone"])}">{esc(row["tone"])}</td>
          <td class="num">{esc(row["closed"])}</td>
          <td class="num">{esc(row["win_rate"])}</td>
          <td class="num">{esc(row["avg_pct"])}</td>
          <td class="num neg">{esc(row["worst_pct"])}</td>
          <td>{esc(row["action"])}</td>
        </tr>
        """
        for row in payload["findings"]
    )
    open_rows = "\n".join(
        f"""
        <tr data-search="{esc(trade.get("ticker"))} {esc(trade.get("timeframe"))} {esc(trade.get("latest_trend"))} {esc(trade.get("latest_risk"))}">
          <td>{esc(trade.get("id"))}</td>
          <td><strong class="ltr">{esc(trade.get("ticker"))}</strong></td>
          <td>{esc(trade.get("timeframe"))}</td>
          <td>{esc(trade.get("entry_date"))}</td>
          <td class="num">{money(trade.get("entry_price"))}</td>
          <td class="num">{money(trade.get("latest_price"))}</td>
          <td class="num {cls(trade.get("pnl"))}">{money(trade.get("pnl"))}</td>
          <td class="num {cls(trade.get("pnl_pct"))}">{pct(trade.get("pnl_pct"))}</td>
          <td>{esc(trade.get("latest_trend"))}</td>
          <td class="{tone_class(str(trade.get("latest_risk")))}">{esc(trade.get("latest_risk"))}</td>
          <td class="num">{esc(trade.get("latest_score"))}</td>
        </tr>
        """
        for trade in payload["open_trades"]
    )
    trade_sample_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(trade.get("id"))}</td>
          <td><strong class="ltr">{esc(trade.get("ticker"))}</strong></td>
          <td>{esc(trade.get("timeframe"))}</td>
          <td>{esc(trade.get("entry_date"))}</td>
          <td>{esc(trade.get("outcome"))}</td>
          <td class="num {cls(trade.get("pnl_pct"))}">{pct(trade.get("pnl_pct"))}</td>
          <td>{esc(trade.get("entry_trend"))}</td>
          <td>{esc(trade.get("entry_rsi_zone"))} <span class="chip num">{esc(trade.get("entry_rsi14"))}</span></td>
          <td>{esc(trade.get("entry_volatility"))}</td>
          <td>{esc(trade.get("entry_location"))}</td>
          <td>{esc(trade.get("entry_market_alignment"))}</td>
          <td class="num">{esc(trade.get("entry_technical_score"))}</td>
        </tr>
        """
        for trade in payload["trade_samples"]
    )
    tabs = [
        ("summary", "الملخص"),
        ("tickers", "تشخيص الأسهم"),
        ("contexts", "سياقات الدخول"),
        ("market", "السوق"),
        ("open", "المفتوحة"),
        ("samples", "أمثلة الصفقات"),
    ]
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>مختبر التشخيص المالي والفني</title>
  <style>
    :root {{
      --bg:#f4f7fa; --panel:#fff; --text:#071827; --muted:#60758b; --line:#d7e2ec;
      --blue:#1d6597; --green:#14745f; --red:#a8373d; --amber:#a66b00; --soft:#eaf1f7;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma, Arial, sans-serif; line-height:1.65; }}
    .wrap {{ max-width:1600px; margin:0 auto; padding:22px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:14px; }}
    h1 {{ margin:0; font-size:28px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:18px; }}
    a {{ color:var(--blue); text-decoration:none; }}
    .sub,.note {{ color:var(--muted); }}
    .nav,.tabs {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .tabs {{ position:sticky; top:0; z-index:3; padding:10px 0; background:var(--bg); margin:12px 0; }}
    .btn,input {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; font:inherit; color:var(--text); }}
    .btn.active,.btn.primary {{ background:var(--blue); color:#fff; border-color:var(--blue); }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .panel,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .metric .label {{ color:var(--muted); }}
    .metric .value {{ direction:ltr; text-align:right; font-size:28px; font-weight:800; margin-top:6px; }}
    .tab-section {{ display:none; }}
    .tab-section.active {{ display:block; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
    th {{ background:var(--soft); color:#24364d; position:sticky; top:54px; z-index:2; }}
    tbody tr:hover {{ background:#f8fbfd; }}
    .num {{ direction:ltr; text-align:right; font-variant-numeric:tabular-nums; }}
    .ltr {{ direction:ltr; unicode-bidi:isolate; display:inline-block; }}
    .pos {{ color:var(--green); font-weight:700; }}
    .neg {{ color:var(--red); font-weight:700; }}
    .warn {{ color:var(--amber); font-weight:700; }}
    .chip {{ display:inline-flex; border:1px solid var(--line); background:#f8fbfd; border-radius:999px; padding:2px 8px; margin:2px; font-weight:400; color:var(--muted); }}
    .badge {{ display:inline-flex; border:1px solid #f0c572; background:#fff8e7; color:#7b5200; border-radius:999px; padding:4px 10px; margin-top:7px; }}
    .tools {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:10px 0; }}
    .tools input {{ min-width:280px; }}
    .section-lead {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:12px; }}
    .summary-note {{ border:1px solid var(--line); background:#fbfdff; border-radius:8px; padding:12px; color:var(--muted); }}
    @media (max-width:1050px) {{
      header,.section-lead {{ display:block; }}
      .grid,.two {{ grid-template-columns:1fr; }}
      .tools input {{ min-width:0; width:100%; }}
      .nav {{ margin-top:12px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>مختبر التشخيص المالي والفني</h1>
        <div class="sub">تجربة جانبية مبنية على Financial Analysis Agent: مؤشرات فنية ومخاطر وربطها بنتائج الصفقات. لا تغيّر المحفظة ولا تعتمد كتوصية شراء أو بيع.</div>
        <div class="badge">تجريبي فقط | آخر توليد: {esc(payload["generated_at"])}</div>
      </div>
      <nav class="nav">
        <a class="btn" href="paper_portfolio_v2_dashboard.html">المحفظة</a>
        <a class="btn" href="paper_portfolio_v2_analytics.html">التحليلات المعتمدة</a>
        <a class="btn" href="decision_hypothesis_preview.html">معاينة الدمج</a>
      </nav>
    </header>

    <section class="grid">
      {render_metric("الصفقات", esc(summary["trades"]), f"مغلقة {summary['closed']} / مفتوحة {summary['open']}")}
      {render_metric("نسبة الفوز", pct(summary["win_rate"]), f"{summary['wins']} رابحة / {summary['losses']} خاسرة")}
      {render_metric("متوسط الصفقة", pct(summary["avg_pct"]), "متوسط نسبة الربح/الخسارة للصفقات المغلقة", cls(summary["avg_pct"]))}
      {render_metric("إجمالي الربح", money(summary["total_pnl"]), "محقق + غير محقق حسب ملف الصفقات", cls(summary["total_pnl"]))}
    </section>

    <nav class="tabs" aria-label="أقسام مختبر التشخيص">
      {''.join(f'<button class="btn {"active" if i == 0 else ""}" data-tab="{key}">{label}</button>' for i, (key, label) in enumerate(tabs))}
    </nav>

    <section class="tab-section active" id="tab-summary">
      <div class="section-lead">
        <div>
          <h2>وش يضيف هذا المختبر؟</h2>
          <p class="note">يربط حالة السهم الفنية وقت الدخول بنتيجة الصفقة. الهدف أن نعرف هل بعض السياقات تستحق فلتر، تخفيف حجم، أو فقط مراقبة.</p>
        </div>
        <div class="summary-note">معيار النجاح هنا ليس زيادة الأرقام مباشرة؛ معيار النجاح أن يفسر الخسائر أو يكشف سياق دخول أضعف من غيره.</div>
      </div>
      <div class="grid">
        <article class="card"><h3>الترند</h3><div class="note">يقيس موقع السعر مقابل MA20 و MA50 و MA200 وترتيب المتوسطات.</div></article>
        <article class="card"><h3>RSI</h3><div class="note">يميز هل الدخول كان بزخم متوازن، ضعف، أو تشبع شراء قد يزيد خطر الانعكاس.</div></article>
        <article class="card"><h3>المخاطر</h3><div class="note">Volatility و VaR و ATR لتقدير هل السهم طبيعي أو يحتاج حجم صفقة أصغر.</div></article>
        <article class="card"><h3>الدعم والمقاومة</h3><div class="note">يفحص هل الدخول قريب من مقاومة أو دعم أو في منتصف النطاق.</div></article>
      </div>
      <section class="panel" style="margin-top:14px; overflow:auto;">
        <h2>أهم الاستنتاجات التجريبية</h2>
        <table>
          <thead><tr><th>البعد</th><th>السياق</th><th>التقييم</th><th>الصفقات</th><th>الفوز</th><th>متوسط %</th><th>أسوأ %</th><th>الإجراء المقترح</th></tr></thead>
          <tbody>{finding_rows or '<tr><td colspan="8">لا توجد فروقات كافية حتى الآن.</td></tr>'}</tbody>
        </table>
      </section>
    </section>

    <section class="tab-section" id="tab-tickers">
      <div class="section-lead">
        <div><h2>تشخيص الأسهم التسعة</h2><p class="note">قراءة فنية ومخاطر لكل سهم حاليًا، مع ربط مختصر بنتائج المحفظة.</p></div>
        <div class="tools"><input id="tickerSearch" placeholder="بحث: سهم، ترند، خطر، RSI"></div>
      </div>
      <div class="panel" style="overflow:auto;">
        <table id="tickerTable">
          <thead><tr><th>السهم</th><th>التاريخ</th><th>السعر</th><th>الترند</th><th>RSI</th><th>MA20 / MA50 / MA200</th><th>الموقع</th><th>المخاطر</th><th>Sharpe</th><th>السوق</th><th>النتيجة الفنية</th><th>الصفقات</th><th>الفوز</th><th>ربح المحفظة</th></tr></thead>
          <tbody>{ticker_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="tab-section" id="tab-contexts">
      <div class="section-lead">
        <div><h2>سياقات الدخول</h2><p class="note">هذه أهم إضافة عملية: هل الدخول في ترند معين أو RSI معين أنتج صفقات أفضل أو أسوأ؟</p></div>
      </div>
      <div class="two">
        <div class="panel" style="overflow:auto;"><h3>الترند وقت الدخول</h3><table><thead><tr><th>السياق</th><th>مغلقة</th><th>رابحة / خاسرة</th><th>الفوز</th><th>الربح</th><th>متوسط %</th><th>وسيط %</th><th>أفضل %</th><th>أسوأ %</th></tr></thead><tbody>{render_group_rows(payload["groups"]["entry_trend"])}</tbody></table></div>
        <div class="panel" style="overflow:auto;"><h3>RSI وقت الدخول</h3><table><thead><tr><th>السياق</th><th>مغلقة</th><th>رابحة / خاسرة</th><th>الفوز</th><th>الربح</th><th>متوسط %</th><th>وسيط %</th><th>أفضل %</th><th>أسوأ %</th></tr></thead><tbody>{render_group_rows(payload["groups"]["entry_rsi_zone"])}</tbody></table></div>
        <div class="panel" style="overflow:auto;"><h3>التذبذب وقت الدخول</h3><table><thead><tr><th>السياق</th><th>مغلقة</th><th>رابحة / خاسرة</th><th>الفوز</th><th>الربح</th><th>متوسط %</th><th>وسيط %</th><th>أفضل %</th><th>أسوأ %</th></tr></thead><tbody>{render_group_rows(payload["groups"]["entry_volatility"])}</tbody></table></div>
        <div class="panel" style="overflow:auto;"><h3>مكان السعر وقت الدخول</h3><table><thead><tr><th>السياق</th><th>مغلقة</th><th>رابحة / خاسرة</th><th>الفوز</th><th>الربح</th><th>متوسط %</th><th>وسيط %</th><th>أفضل %</th><th>أسوأ %</th></tr></thead><tbody>{render_group_rows(payload["groups"]["entry_location"])}</tbody></table></div>
      </div>
      <section class="panel" style="overflow:auto; margin-top:14px;"><h3>علاقة السهم بالسوق وقت الدخول</h3><table><thead><tr><th>السياق</th><th>مغلقة</th><th>رابحة / خاسرة</th><th>الفوز</th><th>الربح</th><th>متوسط %</th><th>وسيط %</th><th>أفضل %</th><th>أسوأ %</th></tr></thead><tbody>{render_group_rows(payload["groups"]["entry_market_alignment"])}</tbody></table></section>
    </section>

    <section class="tab-section" id="tab-market">
      <div class="section-lead">
        <div><h2>قراءة السوق والمؤشرات</h2><p class="note">SPY للسوق العام، QQQ للتقنية، SOXX لأشباه الموصلات. هذه قراءة سياقية فقط.</p></div>
      </div>
      <div class="panel" style="overflow:auto;">
        <table>
          <thead><tr><th>المؤشر</th><th>التاريخ</th><th>السعر</th><th>الترند</th><th>20 يوم</th><th>50 يوم</th><th>Vol</th><th>Sharpe</th><th>VaR</th><th>النتيجة</th></tr></thead>
          <tbody>{market_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="tab-section" id="tab-open">
      <div class="section-lead">
        <div><h2>الصفقات المفتوحة مع التشخيص الحالي</h2><p class="note">هل الصفقة المفتوحة حاليًا ما زالت في سياق فني جيد أو بدأت تدخل منطقة خطر؟</p></div>
        <div class="tools"><input id="openSearch" placeholder="بحث في الصفقات المفتوحة"></div>
      </div>
      <div class="panel" style="overflow:auto;">
        <table id="openTable">
          <thead><tr><th>رقم</th><th>السهم</th><th>الإطار</th><th>الدخول</th><th>سعر الدخول</th><th>آخر سعر</th><th>ربح/خسارة</th><th>النسبة</th><th>الترند الحالي</th><th>الخطر الحالي</th><th>النتيجة الفنية</th></tr></thead>
          <tbody>{open_rows or '<tr><td colspan="11">لا توجد صفقات مفتوحة.</td></tr>'}</tbody>
        </table>
      </div>
    </section>

    <section class="tab-section" id="tab-samples">
      <div class="section-lead">
        <div><h2>أمثلة من أقوى وأضعف الصفقات</h2><p class="note">هذا يوضح كيف كانت المؤشرات وقت الدخول في الصفقات التي صنعت الطرفين: أفضل ربح وأسوأ خسارة.</p></div>
      </div>
      <div class="panel" style="overflow:auto;">
        <table>
          <thead><tr><th>رقم</th><th>السهم</th><th>الإطار</th><th>الدخول</th><th>النتيجة</th><th>%</th><th>الترند</th><th>RSI</th><th>التذبذب</th><th>الموقع</th><th>السوق</th><th>النتيجة الفنية</th></tr></thead>
          <tbody>{trade_sample_rows}</tbody>
        </table>
      </div>
    </section>
  </div>

  <script id="payload" type="application/json">{data_json}</script>
  <script>
    function showTab(name) {{
      document.querySelectorAll('.tabs .btn').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === name));
      document.querySelectorAll('.tab-section').forEach(section => section.classList.toggle('active', section.id === 'tab-' + name));
    }}
    document.querySelectorAll('.tabs .btn').forEach(btn => btn.addEventListener('click', () => showTab(btn.dataset.tab)));
    function bindSearch(inputId, tableId) {{
      const input = document.getElementById(inputId);
      const table = document.getElementById(tableId);
      if (!input || !table) return;
      input.addEventListener('input', () => {{
        const q = input.value.trim().toLowerCase();
        table.querySelectorAll('tbody tr').forEach(row => {{
          const hay = (row.dataset.search || row.textContent).toLowerCase();
          row.style.display = hay.includes(q) ? '' : 'none';
        }});
      }});
    }}
    bindSearch('tickerSearch', 'tickerTable');
    bindSearch('openSearch', 'openTable');
  </script>
</body>
</html>
"""


def main() -> int:
    payload = build_payload()
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    OUT.write_text(render(payload), encoding="utf-8", newline="\n")
    print(f"Financial diagnostics lab: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
