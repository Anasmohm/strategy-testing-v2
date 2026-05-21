#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
DIAGNOSIS = REPORTS / "stock_diagnosis.csv"
STRATEGIES = REPORTS / "designed_strategies.csv"
VERIFICATION = REPORTS / "strategy_verification.csv"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
START_DATE = CONFIG["start_date"]


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_bars(ticker: str) -> list[Bar]:
    path = DATA / "market_data" / f"{ticker}_daily.csv"
    rows = read_csv(path)
    return [
        Bar(
            date=row["date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(float(row["volume"])),
        )
        for row in rows
    ]


def pct(start: float, end: float) -> float:
    return (end / start - 1) * 100 if start else 0.0


def avg_range_pct(bars: list[Bar], end_index: int, lookback: int = 14) -> float:
    sample = bars[max(0, end_index - lookback + 1) : end_index + 1]
    if not sample:
        return 0.0
    return statistics.mean((bar.high - bar.low) / bar.close * 100 for bar in sample)


def avg_volume(bars: list[Bar], end_index: int, lookback: int = 20) -> float:
    sample = bars[max(0, end_index - lookback + 1) : end_index + 1]
    if not sample:
        return 0.0
    return statistics.mean(bar.volume for bar in sample)


def moving_average(values: list[float], index: int, lookback: int) -> float | None:
    if index + 1 < lookback:
        return None
    return statistics.mean(values[index - lookback + 1 : index + 1])


def rsi(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if index >= period:
            avg_gain = sum(gains[index - period : index]) / period
            avg_loss = sum(losses[index - period : index]) / period
            out[index] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out


def design_strategy(row: dict[str, str]) -> dict[str, object]:
    behavior = row["behavior"]
    ticker = row["ticker"]
    avg_range = float(row["avg_daily_range_pct"])
    drawdown = abs(float(row["max_drawdown_pct"]))

    if behavior == "breakout":
        entry_rule = "close_above_prior_high"
        lookback = 55 if float(row["breakout_success_rate_pct"]) >= 65 else 20
        hold_days = 10
        target_pct = max(5.0, min(12.0, avg_range * 2.2))
        stop_pct = max(3.0, min(12.0, avg_range * 1.8))
        volume_filter = 1.05
        rationale = "السهم ينجح تاريخيًا بعد اختراق القمم، لذلك التصميم يركز على اختراق مؤكد بحجم أعلى من المتوسط."
    elif behavior == "pullback_recovery":
        entry_rule = "five_day_drop_recovery"
        lookback = 5
        hold_days = 8
        target_pct = max(4.0, min(10.0, avg_range * 1.8))
        stop_pct = max(3.0, min(10.0, avg_range * 1.5))
        volume_filter = 0.85
        rationale = "السهم يميل للتعافي بعد الهبوط، لذلك التصميم ينتظر هبوطًا واضحًا ثم يوم تعافٍ."
    elif behavior == "trend_following":
        entry_rule = "trend_pullback_resume"
        lookback = 20
        hold_days = 15
        target_pct = max(5.0, min(14.0, avg_range * 2.4))
        stop_pct = max(3.5, min(12.0, avg_range * 1.7))
        volume_filter = 0.9
        rationale = "السهم أقرب للترند، لذلك التصميم يدخل عند استئناف الاتجاه بعد تهدئة قصيرة."
    else:
        entry_rule = "reduced_size_breakout_only"
        lookback = 100
        hold_days = 7
        target_pct = max(3.0, min(7.0, avg_range * 1.4))
        stop_pct = max(2.5, min(8.0, avg_range * 1.2))
        volume_filter = 1.15
        rationale = "السلوك مختلط، لذلك التصميم أكثر تحفظًا ويحتاج اختراقًا قويًا وحجمًا أعلى."

    risk_tier = "high" if drawdown >= 45 or avg_range >= 5 else "medium" if drawdown >= 25 or avg_range >= 3 else "low"
    size_multiplier = 0.5 if risk_tier == "high" else 0.75 if risk_tier == "medium" else 1.0

    return {
        "ticker": ticker,
        "behavior": behavior,
        "entry_rule": entry_rule,
        "lookback": lookback,
        "hold_days": hold_days,
        "target_pct": round(target_pct, 2),
        "initial_stop_pct": round(stop_pct, 2),
        "volume_filter": round(volume_filter, 2),
        "risk_tier": risk_tier,
        "size_multiplier": size_multiplier,
        "rationale": rationale,
    }


def entry_signal(strategy: dict[str, object], bars: list[Bar], index: int) -> bool:
    if index < 120:
        return False
    closes = [bar.close for bar in bars]
    rule = strategy["entry_rule"]
    lookback = int(strategy["lookback"])
    vol_filter = float(strategy["volume_filter"])
    avg_vol = avg_volume(bars, index - 1)
    volume_ok = bars[index].volume >= avg_vol * vol_filter if avg_vol else True

    if rule == "close_above_prior_high":
        prior_high = max(bar.high for bar in bars[index - lookback : index])
        return bars[index].close > prior_high and volume_ok

    if rule == "five_day_drop_recovery":
        drop = pct(closes[index - 5], closes[index - 1])
        return drop <= -5 and bars[index].close > bars[index - 1].close and bars[index].close > bars[index].open

    if rule == "trend_pullback_resume":
        ma50 = moving_average(closes, index, 50)
        ma100 = moving_average(closes, index, 100)
        if ma50 is None or ma100 is None:
            return False
        recent_pullback = pct(closes[index - 5], closes[index - 1]) <= -2
        return closes[index] > ma50 > ma100 and recent_pullback and closes[index] > closes[index - 1]

    if rule == "reduced_size_breakout_only":
        prior_high = max(bar.high for bar in bars[index - lookback : index])
        return bars[index].close > prior_high and volume_ok

    if rule == "v1_breakout":
        prior_high = max(bar.high for bar in bars[index - lookback : index])
        return bars[index].close > prior_high

    if rule == "v1_rsi_recovery":
        period = int(strategy.get("rsi_period", lookback))
        threshold = float(strategy.get("rsi_cross_above", 35))
        values = rsi(closes, period)
        return (
            index > 0
            and values[index - 1] is not None
            and values[index] is not None
            and values[index - 1] < threshold
            and values[index] >= threshold
        )

    return False


def verify_strategy(strategy: dict[str, object]) -> dict[str, object]:
    bars = read_bars(str(strategy["ticker"]))
    trades: list[float] = []
    outcomes: list[str] = []
    i = 0
    while i < len(bars) - 2:
        if not entry_signal(strategy, bars, i):
            i += 1
            continue
        entry = bars[i].close
        target = entry * (1 + float(strategy["target_pct"]) / 100)
        stop = entry * (1 - float(strategy["initial_stop_pct"]) / 100)
        hold_days = int(strategy["hold_days"])
        exit_price = bars[min(i + hold_days, len(bars) - 1)].close
        outcome = "TIME"
        for offset in range(1, min(hold_days, len(bars) - i - 1) + 1):
            bar = bars[i + offset]
            if bar.low <= stop:
                exit_price = stop
                outcome = "LOSS"
                break
            if bar.high >= target:
                exit_price = target
                outcome = "WIN"
                break
        trades.append(pct(entry, exit_price))
        outcomes.append(outcome)
        i += hold_days

    if not trades:
        return {
            "ticker": strategy["ticker"],
            "trades": 0,
            "win_rate": 0,
            "avg_return": 0,
            "median_return": 0,
            "total_return": 0,
            "loss_count": 0,
            "designed_pass": False,
        }

    wins = sum(1 for value in trades if value > 0)
    total = math.prod(1 + value / 100 for value in trades) - 1
    return {
        "ticker": strategy["ticker"],
        "trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 2),
        "avg_return": round(statistics.mean(trades), 2),
        "median_return": round(statistics.median(trades), 2),
        "total_return": round(total * 100, 2),
        "loss_count": outcomes.count("LOSS"),
        "designed_pass": len(trades) >= 8 and wins / len(trades) >= 0.55 and statistics.mean(trades) > 0,
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
    diagnosis = read_csv(DIAGNOSIS)
    strategies = [design_strategy(row) for row in diagnosis]
    verification = [verify_strategy(strategy) for strategy in strategies]
    write_csv(STRATEGIES, strategies)
    write_csv(VERIFICATION, verification)
    passed = sum(1 for row in verification if row["designed_pass"])
    print(f"Designed: {len(strategies)}")
    print(f"Verified pass: {passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
