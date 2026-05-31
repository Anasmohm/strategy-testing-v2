#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

import design_strategies
import download_eodhd_intraday_experiment as provider


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
PRIVATE_ROOT = ROOT / "data" / "eodhd_private" / "historical_5m_rth_adjusted"
DAILY_HISTORY_ROOT = ROOT / "data" / "eodhd_private" / "historical_daily_split_adjusted"
DAILY_ROOT = ROOT / "data" / "market_data"
INTERVAL = "5m"
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
PORTFOLIO_TICKERS = ["AMD", "ANET", "AVGO", "LRCX", "MRVL", "NVDA", "PANW", "SHOP", "TSLA"]
DEFAULT_WARMUP_START = dt.date(2023, 1, 1)
DEFAULT_DAILY_HISTORY_START = dt.date(2020, 1, 1)
REFRESH_WORKERS = 4


def configured_warmup_start() -> dt.date:
    value = str(CONFIG.get("market_data_warmup_start_date", DEFAULT_WARMUP_START.isoformat()))
    return dt.date.fromisoformat(value)


def configured_daily_history_start() -> dt.date:
    value = str(CONFIG.get("market_data_daily_history_start_date", DEFAULT_DAILY_HISTORY_START.isoformat()))
    return dt.date.fromisoformat(value)


def configured_symbols() -> list[str]:
    return PORTFOLIO_TICKERS + BENCHMARKS


def intraday_path(ticker: str) -> Path:
    return PRIVATE_ROOT / f"{ticker}_{INTERVAL}_rth_adjusted.csv"


def daily_history_path(ticker: str) -> Path:
    return DAILY_HISTORY_ROOT / f"{ticker}_daily_split_adjusted.csv"


def read_intraday_rows(ticker: str) -> list[dict[str, str]]:
    path = intraday_path(ticker)
    if not path.exists():
        raise FileNotFoundError(
            f"Official EODHD data is missing for {ticker}. Run: python eodhd_official_data.py refresh"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def intraday_by_date(ticker: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in read_intraday_rows(ticker):
        grouped.setdefault(row["date"], []).append(
            {
                "datetime_utc": row["datetime_utc"],
                "time_et": row["time_et"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(float(row["volume"])),
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda item: str(item["datetime_utc"]))
    return grouped


def aggregate_intraday_bars(ticker: str) -> list[design_strategies.Bar]:
    grouped = intraday_by_date(ticker)
    bars: list[design_strategies.Bar] = []
    for date_value in sorted(grouped):
        rows = grouped[date_value]
        bars.append(
            design_strategies.Bar(
                date=date_value,
                open=float(rows[0]["open"]),
                high=max(float(row["high"]) for row in rows),
                low=min(float(row["low"]) for row in rows),
                close=float(rows[-1]["close"]),
                volume=sum(int(row["volume"]) for row in rows),
            )
        )
    return bars


def read_daily_history_bars(ticker: str) -> list[design_strategies.Bar]:
    path = daily_history_path(ticker)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            design_strategies.Bar(
                date=str(row["date"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(float(row["volume"])),
            )
            for row in csv.DictReader(handle)
        ]


def read_daily_bars(ticker: str) -> list[design_strategies.Bar]:
    combined = {bar.date: bar for bar in read_daily_history_bars(ticker)}
    combined.update({bar.date: bar for bar in aggregate_intraday_bars(ticker)})
    return [combined[date_value] for date_value in sorted(combined)]


def fetch_session_dates(ticker: str, start: dt.date, end: dt.date) -> list[str]:
    payload = provider.request_json(
        f"eod/{provider.provider_symbol(ticker)}",
        {"from": start.isoformat(), "to": end.isoformat(), "period": "d"},
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected EODHD daily calendar response for {ticker}.")
    return sorted(
        {
            str(row.get("date"))
            for row in payload
            if row.get("date") and start.isoformat() <= str(row.get("date")) <= end.isoformat()
        }
    )


def merge_ranges(dates: list[str], max_gap_days: int = 4) -> list[tuple[dt.date, dt.date]]:
    if not dates:
        return []
    ordered = [dt.date.fromisoformat(value) for value in sorted(set(dates))]
    ranges: list[tuple[dt.date, dt.date]] = []
    start = ordered[0]
    previous = ordered[0]
    for current in ordered[1:]:
        if (current - previous).days <= max_gap_days:
            previous = current
            continue
        ranges.append((start, previous))
        start = current
        previous = current
    ranges.append((start, previous))
    return ranges


def is_trailing_missing(expected_dates: list[str], missing_dates: list[str]) -> bool:
    if not missing_dates:
        return False
    expected_order = list(expected_dates)
    missing_order = list(missing_dates)
    return expected_order[-len(missing_order) :] == missing_order


def write_daily_file(ticker: str, bars: list[design_strategies.Bar]) -> None:
    DAILY_ROOT.mkdir(parents=True, exist_ok=True)
    path = DAILY_ROOT / f"{ticker}_daily.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow([bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume])


def refresh_daily_history(ticker: str, start: dt.date, end: dt.date) -> None:
    DAILY_HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    payload = provider.request_json(
        f"eod/{provider.provider_symbol(ticker)}",
        {"from": start.isoformat(), "to": end.isoformat(), "period": "d"},
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected EODHD daily history response for {ticker}.")
    splits = provider.fetch_splits(ticker, start, end)
    with daily_history_path(ticker).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume", "split_adjustment_factor"])
        for row in payload:
            date_value = dt.date.fromisoformat(str(row["date"]))
            factor = provider.split_factor(date_value, splits)
            writer.writerow(
                [
                    date_value.isoformat(),
                    float(row["open"]) / factor,
                    float(row["high"]) / factor,
                    float(row["low"]) / factor,
                    float(row["close"]) / factor,
                    int(round(float(row.get("volume", 0) or 0) * factor)),
                    factor,
                ]
            )


def refresh_symbol(ticker: str, start: dt.date, end: dt.date) -> dict[str, Any]:
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    expected_dates = fetch_session_dates(ticker, start, end)
    expected_set = set(expected_dates)
    existing_rows = provider.read_rows(intraday_path(ticker))
    retained: list[dict[str, Any]] = []
    for row in existing_rows:
        row_date_text = str(row.get("date", ""))
        try:
            row_date = dt.date.fromisoformat(row_date_text)
        except ValueError:
            continue
        if start <= row_date <= end and row_date_text not in expected_set:
            continue
        retained.append(row)
    have_dates = {str(row["date"]) for row in retained if str(row.get("date", "")) in expected_set}
    missing_dates = [date_value for date_value in expected_dates if date_value not in have_dates]
    splits = provider.fetch_splits(ticker, start, end)
    by_time = {str(row["datetime_utc"]): row for row in retained}
    request_count = 1
    invalid_rows = 0
    raw_rows = 0
    chunks = [
        (chunk_start, chunk_end)
        for range_start, range_end in merge_ranges(missing_dates)
        for chunk_start, chunk_end in provider.chunks(range_start, range_end, 120)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=REFRESH_WORKERS) as pool:
        payloads = list(pool.map(lambda period: provider.fetch_intraday_chunk(ticker, *period, INTERVAL), chunks))
    for payload in payloads:
        request_count += 1
        raw_rows += len(payload)
        invalid_rows += sum(
            1
            for row in payload
            if not row.get("datetime")
            or any(row.get(field) is None for field in ("open", "high", "low", "close"))
        )
        for row in provider.normalize_rows(payload, splits):
            if str(row["date"]) in expected_set:
                by_time[str(row["datetime_utc"])] = row
    final_rows = [by_time[key] for key in sorted(by_time)]
    provider.write_rows(intraday_path(ticker), final_rows)
    received_dates = {str(row["date"]) for row in final_rows}
    still_missing = [date_value for date_value in expected_dates if date_value not in received_dates]
    coverage = provider.session_coverage(final_rows, INTERVAL)
    deferred_latest = is_trailing_missing(expected_dates, still_missing)
    if still_missing and not deferred_latest:
        raise RuntimeError(f"EODHD 5m coverage is missing {len(still_missing)} session(s) for {ticker}.")
    if int(coverage["unexpected_partial_session_days"]) > 0:
        raise RuntimeError(f"EODHD 5m has incomplete regular sessions for {ticker}; build halted.")
    bars = read_daily_bars(ticker)
    write_daily_file(ticker, bars)
    return {
        "symbol": ticker,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "api_requests": request_count,
        "raw_bars_received": raw_rows,
        "invalid_raw_bars_skipped": invalid_rows,
        "regular_session_bars": len(final_rows),
        "expected_trading_days": len(expected_dates),
        "received_trading_days": len(received_dates),
        "missing_trading_days": len(still_missing),
        "coverage_status": "DEFERRED_LATEST" if deferred_latest else "COMPLETE",
        "deferred_latest_sessions": ";".join(still_missing) if deferred_latest else "",
        **coverage,
        "split_events": len(splits),
        "first_bar_utc": final_rows[0]["datetime_utc"] if final_rows else "",
        "last_bar_utc": final_rows[-1]["datetime_utc"] if final_rows else "",
        "file": intraday_path(ticker).name,
    }


def write_summary(rows: list[dict[str, Any]]) -> None:
    path = PRIVATE_ROOT / "official_refresh_summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "source": "EODHD EOD-IntraDay All World",
        "interval": INTERVAL,
        "use": "Approved portfolio data source",
        "execution_order": "Targets and known stops use five-minute bars; a raised daily-high trailing stop applies from the following trading session.",
        "generated_at_utc": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "private_data_notice": "Raw provider files and API token are not published.",
    }
    (PRIVATE_ROOT / "official_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def refresh(start: dt.date, end: dt.date) -> None:
    summaries: list[dict[str, Any]] = []
    failures: list[str] = []
    for ticker in configured_symbols():
        print(f"Refreshing EODHD 5m official data: {ticker}", flush=True)
        refresh_daily_history(ticker, configured_daily_history_start(), end)
        try:
            summary = refresh_symbol(ticker, start, end)
        except RuntimeError as exc:
            failures.append(f"{ticker}: {exc}")
            print(f"  validation deferred for repair: {exc}", flush=True)
            continue
        summaries.append(summary)
        print(
            f"  {summary['received_trading_days']} sessions, "
            f"{summary['regular_session_bars']:,} bars, "
            f"{summary['api_requests']} API request(s)",
            flush=True,
        )
    if summaries:
        write_summary(summaries)
    if failures:
        raise RuntimeError("EODHD refresh requires session repair:\n" + "\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh approved EODHD five-minute portfolio market data.")
    parser.add_argument("command", nargs="?", default="refresh", choices=["refresh"])
    parser.add_argument("--start", type=dt.date.fromisoformat, default=configured_warmup_start())
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.datetime.now(tz=dt.timezone.utc).date())
    args = parser.parse_args()
    refresh(args.start, args.end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
