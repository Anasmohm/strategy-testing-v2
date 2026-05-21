#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
MARKET_DATA = DATA / "market_data"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TICKERS = json.loads((DATA / "tickers.json").read_text(encoding="utf-8"))["tickers"]
START_DATE = dt.date.fromisoformat(CONFIG["start_date"])


@dataclass(frozen=True)
class Bar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def bars_path(ticker: str) -> Path:
    return MARKET_DATA / f"{ticker.upper()}_daily.csv"


def read_cached_bars(ticker: str) -> list[Bar]:
    path = bars_path(ticker)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            Bar(
                date=parse_date(row["date"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(float(row["volume"])),
            )
            for row in csv.DictReader(handle)
        ]


def write_cached_bars(ticker: str, bars: list[Bar]) -> None:
    MARKET_DATA.mkdir(parents=True, exist_ok=True)
    unique = {bar.date: bar for bar in bars}
    ordered = [unique[date] for date in sorted(unique)]
    with bars_path(ticker).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for bar in ordered:
            writer.writerow(
                {
                    "date": bar.date.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            )


def fetch_yahoo_daily_range(ticker: str, start: dt.date, end: dt.date) -> list[Bar]:
    period1 = int(dt.datetime.combine(start, dt.time.min).timestamp())
    period2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min).timestamp())
    params = urllib.parse.urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    request = urllib.request.Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{params}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(chart["error"])
    result = chart.get("result") or []
    if not result:
        return []
    data = result[0]
    timestamps = data.get("timestamp") or []
    quote = (data.get("indicators", {}).get("quote") or [{}])[0]
    bars: list[Bar] = []
    for index, timestamp in enumerate(timestamps):
        values = [
            quote.get("open", [None] * len(timestamps))[index],
            quote.get("high", [None] * len(timestamps))[index],
            quote.get("low", [None] * len(timestamps))[index],
            quote.get("close", [None] * len(timestamps))[index],
        ]
        if any(value is None for value in values):
            continue
        bars.append(
            Bar(
                date=dt.datetime.fromtimestamp(timestamp).date(),
                open=float(values[0]),
                high=float(values[1]),
                low=float(values[2]),
                close=float(values[3]),
                volume=int((quote.get("volume", [0] * len(timestamps))[index]) or 0),
            )
        )
    return bars


def load_incremental_bars(ticker: str) -> list[Bar]:
    cached = read_cached_bars(ticker)
    today = dt.date.today()
    required_start = START_DATE - dt.timedelta(days=260)
    fresh: list[Bar] = []
    if cached:
        if cached[0].date > required_start:
            fresh.extend(fetch_yahoo_daily_range(ticker, required_start, cached[0].date - dt.timedelta(days=1)))
        start = cached[-1].date
    else:
        start = required_start
    fresh.extend(fetch_yahoo_daily_range(ticker, start, today))
    write_cached_bars(ticker, cached + fresh)
    return [bar for bar in read_cached_bars(ticker) if bar.date >= required_start]


def pct_change(start: float, end: float) -> float:
    return (end / start - 1) * 100 if start else 0.0


def max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    worst = 0.0
    for close in closes:
        peak = max(peak, close)
        worst = min(worst, close / peak - 1)
    return worst * 100


def diagnose(ticker: str, bars: list[Bar]) -> dict[str, object]:
    test_bars = [bar for bar in bars if bar.date >= START_DATE]
    closes = [bar.close for bar in test_bars]
    if len(closes) < 120:
        raise ValueError("not enough bars")

    daily_returns = [pct_change(closes[i - 1], closes[i]) for i in range(1, len(closes))]
    up_days = sum(1 for value in daily_returns if value > 0)
    avg_range = statistics.mean((bar.high - bar.low) / bar.close * 100 for bar in test_bars)
    avg_volume_value = statistics.mean(bar.close * bar.volume for bar in test_bars[-60:])
    trend_return = pct_change(closes[0], closes[-1])
    drawdown = max_drawdown(closes)

    twenty_high_breaks = 0
    successful_breaks = 0
    for i in range(20, len(test_bars) - 10):
        previous_high = max(bar.high for bar in test_bars[i - 20 : i])
        if test_bars[i].close > previous_high:
            twenty_high_breaks += 1
            if test_bars[i + 10].close > test_bars[i].close:
                successful_breaks += 1

    pullback_events = 0
    pullback_success = 0
    for i in range(5, len(closes) - 10):
        five_day_drop = pct_change(closes[i - 5], closes[i])
        if five_day_drop <= -5:
            pullback_events += 1
            if closes[i + 10] > closes[i]:
                pullback_success += 1

    breakout_success_rate = successful_breaks / twenty_high_breaks * 100 if twenty_high_breaks else 0.0
    pullback_success_rate = pullback_success / pullback_events * 100 if pullback_events else 0.0
    trend_score = min(100.0, max(0.0, trend_return / max(abs(drawdown), 1) * 50 + 50))

    if breakout_success_rate >= 58 and twenty_high_breaks >= 8:
        behavior = "breakout"
        design = "اختراق قمم 20-55 يوم مع وقف متحرك وتأكيد حجم."
    elif pullback_success_rate >= 58 and pullback_events >= 8:
        behavior = "pullback_recovery"
        design = "شراء ارتداد بعد هبوط حاد مع فلتر ترند وخروج سريع."
    elif trend_score >= 65:
        behavior = "trend_following"
        design = "تتبع ترند باستخدام متوسطات وخروج بالوقف المتحرك."
    else:
        behavior = "mixed_or_choppy"
        design = "حجم أصغر أو تجنب حتى يظهر نمط أوضح."

    return {
        "ticker": ticker,
        "bars": len(test_bars),
        "behavior": behavior,
        "proposed_design": design,
        "trend_return_pct": round(trend_return, 2),
        "max_drawdown_pct": round(drawdown, 2),
        "avg_daily_range_pct": round(avg_range, 2),
        "up_day_rate_pct": round(up_days / len(daily_returns) * 100, 2),
        "breakout_events": twenty_high_breaks,
        "breakout_success_rate_pct": round(breakout_success_rate, 2),
        "pullback_events": pullback_events,
        "pullback_success_rate_pct": round(pullback_success_rate, 2),
        "avg_60d_dollar_volume": round(avg_volume_value, 2),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for ticker in TICKERS:
        print(f"Diagnosing {ticker}...", flush=True)
        try:
            bars = load_incremental_bars(ticker)
            rows.append(diagnose(ticker, bars))
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
        time.sleep(0.2)
    write_csv(REPORTS / "stock_diagnosis.csv", rows)
    (REPORTS / "diagnosis_errors.txt").write_text("\n".join(errors), encoding="utf-8")
    print(f"Done. Diagnosed: {len(rows)}. Errors: {len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
