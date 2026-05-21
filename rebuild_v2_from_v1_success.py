#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
V1_ROOT = Path(r"C:\Users\anasbinessa\Documents\New project")
V1_RULES = V1_ROOT / "reports" / "passing_rules.csv"
OUT = REPORTS / "selected_strategies.csv"
V1_TICKERS = {"AMD", "ANET", "AVGO", "LRCX", "MRVL", "NVDA", "PANW", "SHOP", "TSLA"}
ACTIVE_TIMEFRAMES = {"swing", "monthly"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_params(text: str) -> dict[str, str]:
    params = {}
    for part in text.split(";"):
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def target_for_timeframe(timeframe: str) -> float:
    if timeframe == "monthly":
        return 10.0
    if timeframe == "short_term_daily_proxy":
        return 3.0
    return 5.0


def hold_for_timeframe(timeframe: str) -> int:
    if timeframe == "monthly":
        return 21
    if timeframe == "short_term_daily_proxy":
        return 3
    return 10


def build_strategy(row: dict[str, str]) -> dict[str, object]:
    params = parse_params(row["params"])
    ticker = row["ticker"]
    timeframe = row["timeframe"]
    strategy = row["strategy"]
    target_pct = target_for_timeframe(timeframe)
    base = {
        "ticker": ticker,
        "timeframe": timeframe,
        "behavior": f"v1_success_{timeframe}",
        "selected_version": "v2_from_v1_success",
        "version": "v3_v1_success_based",
        "target_pct": target_pct,
        "initial_stop_pct": 99,
        "hold_days": hold_for_timeframe(timeframe),
        "size_multiplier": 1.0,
        "volume_filter": 1.0,
        "risk_tier": "benchmark",
        "stop_model": "v1_atr_support",
        "v1_strategy": strategy,
        "v1_params": row["params"],
        "v1_rule_win_rate": row["win_rate"],
        "v1_rule_total_return": row["total_return"],
        "rationale": "تخصيص مبني على قواعد النسخة الأولى التي أثبتت نجاحها على السهم نفسه، مع الاحتفاظ بوقف ATR والدعم.",
    }
    if strategy == "Breakout":
        lookback = int(float(params["lookback"]))
        base.update(
            {
                "strategy_id": f"{ticker}_{timeframe}_breakout_{lookback}",
                "entry_rule": "v1_breakout",
                "lookback": lookback,
                "rsi_period": "",
                "rsi_cross_above": "",
            }
        )
        return base
    if strategy == "RSI recovery":
        period = int(float(params["period"]))
        cross = float(params["cross_above"])
        base.update(
            {
                "strategy_id": f"{ticker}_{timeframe}_rsi_{period}_{cross:g}",
                "entry_rule": "v1_rsi_recovery",
                "lookback": period,
                "rsi_period": period,
                "rsi_cross_above": cross,
            }
        )
        return base
    raise ValueError(f"Unsupported V1 strategy: {strategy}")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rows = [
        row
        for row in read_csv(V1_RULES)
        if row["ticker"] in V1_TICKERS and row["timeframe"] in ACTIVE_TIMEFRAMES
    ]
    strategies = [build_strategy(row) for row in rows]
    write_csv(OUT, strategies)
    print(f"Wrote {len(strategies)} V1-success-based strategies for {len({row['ticker'] for row in strategies})} tickers")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
