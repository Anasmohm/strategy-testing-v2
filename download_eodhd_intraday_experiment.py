#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import http.client
import json
import os
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PRIVATE_BASE = ROOT / "data" / "eodhd_private"
DAILY_ROOT = ROOT / "data" / "market_data"
SELECTED_STRATEGIES = ROOT / "reports" / "selected_strategies.csv"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
BENCHMARKS = ["QQQ", "SPY", "SOXX"]
DEFAULT_TICKERS = ["AMD", "ANET", "AVGO", "LRCX", "MRVL", "NVDA", "PANW", "SHOP", "TSLA"]
UTC = dt.timezone.utc
REGULAR_OPEN = dt.time(9, 30)
REGULAR_CLOSE = dt.time(16, 0)
EARLY_CLOSE_DATES = {
    dt.date(2020, 11, 27),
    dt.date(2020, 12, 24),
    dt.date(2021, 11, 26),
    dt.date(2022, 11, 25),
    dt.date(2023, 7, 3),
    dt.date(2023, 11, 24),
    dt.date(2024, 7, 3),
    dt.date(2024, 11, 29),
    dt.date(2024, 12, 24),
    dt.date(2025, 7, 3),
    dt.date(2025, 11, 28),
    dt.date(2025, 12, 24),
    dt.date(2026, 7, 3),
    dt.date(2026, 11, 27),
    dt.date(2026, 12, 24),
}
EARLY_CLOSE = dt.time(13, 0)


def user_environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value).strip()
        except (FileNotFoundError, OSError):
            return ""
    return ""


def api_token() -> str:
    token = user_environment_value("EODHD_API_TOKEN")
    if not token:
        raise SystemExit("EODHD_API_TOKEN is not saved in the user environment.")
    return token


def symbols_from_strategies() -> list[str]:
    if not SELECTED_STRATEGIES.exists():
        return DEFAULT_TICKERS + BENCHMARKS
    with SELECTED_STRATEGIES.open(newline="", encoding="utf-8-sig") as handle:
        tickers = sorted({row["ticker"].strip().upper() for row in csv.DictReader(handle) if row.get("ticker")})
    return tickers + [ticker for ticker in BENCHMARKS if ticker not in tickers]


def provider_symbol(ticker: str) -> str:
    return ticker if "." in ticker else f"{ticker}.US"


def request_json(path: str, params: dict[str, object], attempts: int = 4) -> object:
    values = {"api_token": api_token(), "fmt": "json", **params}
    url = f"https://eodhd.com/api/{path}?{urllib.parse.urlencode(values)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "StrategyTestingV2-EODHD-Experiment/1.0", "Accept": "application/json"},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                raise RuntimeError(f"EODHD request failed with HTTP {exc.code} for {path}.") from exc
        except (urllib.error.URLError, http.client.IncompleteRead, ConnectionResetError, TimeoutError, socket.timeout) as exc:
            if attempt == attempts:
                raise RuntimeError(f"EODHD connection failed after {attempts} attempts for {path}: {exc}") from exc
        time.sleep(attempt * 2)
    raise RuntimeError(f"EODHD request failed for {path}.")


def day_timestamp(date_value: dt.date, last_second: bool = False) -> int:
    clock = dt.time.max if last_second else dt.time.min
    return int(dt.datetime.combine(date_value, clock, tzinfo=UTC).timestamp())


def fetch_splits(symbol: str, start: dt.date, through: dt.date) -> list[tuple[dt.date, float]]:
    payload = request_json(
        f"splits/{urllib.parse.quote(provider_symbol(symbol))}",
        {"from": start.isoformat(), "to": through.isoformat()},
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected split response for {symbol}.")
    splits: list[tuple[dt.date, float]] = []
    for row in payload:
        ratio = str(row.get("split", "")).split("/")
        if len(ratio) != 2 or not float(ratio[1]):
            continue
        splits.append((dt.date.fromisoformat(str(row["date"])), float(ratio[0]) / float(ratio[1])))
    return sorted(splits)


def split_factor(bar_date: dt.date, splits: list[tuple[dt.date, float]]) -> float:
    factor = 1.0
    for effective_date, ratio in splits:
        if bar_date < effective_date:
            factor *= ratio
    return factor


def nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> dt.date:
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (occurrence - 1))


def eastern_offset(timestamp: dt.datetime) -> dt.timedelta:
    year = timestamp.year
    dst_start_date = nth_weekday(year, 3, 6, 2)
    dst_end_date = nth_weekday(year, 11, 6, 1)
    dst_start_utc = dt.datetime.combine(dst_start_date, dt.time(7), tzinfo=UTC)
    dst_end_utc = dt.datetime.combine(dst_end_date, dt.time(6), tzinfo=UTC)
    return dt.timedelta(hours=-4 if dst_start_utc <= timestamp < dst_end_utc else -5)


def in_regular_session(timestamp: dt.datetime) -> tuple[bool, dt.datetime]:
    eastern = timestamp + eastern_offset(timestamp)
    clock = eastern.time().replace(tzinfo=None)
    close = EARLY_CLOSE if eastern.date() in EARLY_CLOSE_DATES else REGULAR_CLOSE
    return REGULAR_OPEN <= clock <= close, eastern


def fetch_intraday_chunk(symbol: str, start: dt.date, end: dt.date, interval: str) -> list[dict[str, object]]:
    payload = request_json(
        f"intraday/{urllib.parse.quote(provider_symbol(symbol))}",
        {
            "interval": interval,
            "from": day_timestamp(start),
            "to": day_timestamp(end, last_second=True),
        },
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected intraday response for {symbol}.")
    return payload


def chunks(start: dt.date, end: dt.date, days: int) -> list[tuple[dt.date, dt.date]]:
    ranges: list[tuple[dt.date, dt.date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + dt.timedelta(days=days - 1), end)
        ranges.append((current, chunk_end))
        current = chunk_end + dt.timedelta(days=1)
    return ranges


def normalize_rows(raw_rows: list[dict[str, object]], splits: list[tuple[dt.date, float]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for raw in raw_rows:
        datetime_text = str(raw.get("datetime", ""))
        required_values = [raw.get(field) for field in ("open", "high", "low", "close")]
        if not datetime_text or any(value is None for value in required_values):
            continue
        timestamp = dt.datetime.strptime(datetime_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        regular, eastern = in_regular_session(timestamp)
        if not regular:
            continue
        date_value = eastern.date()
        factor = split_factor(date_value, splits)
        normalized.append(
            {
                "datetime_utc": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "date": date_value.isoformat(),
                "time_et": eastern.strftime("%H:%M:%S"),
                "open": float(raw["open"]) / factor,
                "high": float(raw["high"]) / factor,
                "low": float(raw["low"]) / factor,
                "close": float(raw["close"]) / factor,
                "volume": int(round(float(raw.get("volume", 0) or 0) * factor)),
                "split_adjustment_factor": factor,
            }
        )
    return normalized


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "datetime_utc",
        "date",
        "time_et",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "split_adjustment_factor",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def aggregate_daily(rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["date"]), []).append(row)
    daily: dict[str, dict[str, float]] = {}
    for date_value, bars in grouped.items():
        ordered = sorted(bars, key=lambda row: str(row["datetime_utc"]))
        daily[date_value] = {
            "open": float(ordered[0]["open"]),
            "high": max(float(row["high"]) for row in ordered),
            "low": min(float(row["low"]) for row in ordered),
            "close": float(ordered[-1]["close"]),
            "volume": sum(float(row["volume"]) for row in ordered),
        }
    return daily


def session_minimum_bars(interval: str) -> int:
    return {"1m": 350, "5m": 70, "1h": 5}[interval]


def session_coverage(rows: list[dict[str, object]], interval: str) -> dict[str, object]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["date"])] = counts.get(str(row["date"]), 0) + 1
    values = list(counts.values())
    threshold = session_minimum_bars(interval)
    unexpected_partial = [
        date_value
        for date_value, value in counts.items()
        if value < threshold and dt.date.fromisoformat(date_value) not in EARLY_CLOSE_DATES
    ]
    return {
        "partial_session_days": sum(1 for value in values if value < threshold),
        "expected_early_close_days": sum(1 for date_value in counts if dt.date.fromisoformat(date_value) in EARLY_CLOSE_DATES),
        "unexpected_partial_session_days": len(unexpected_partial),
        "partial_session_threshold_bars": threshold,
        "min_bars_in_session": min(values) if values else 0,
        "median_bars_in_session": round(statistics.median(values), 2) if values else 0,
    }


def quality_vs_current_daily(symbol: str, minute_rows: list[dict[str, object]]) -> dict[str, object]:
    path = DAILY_ROOT / f"{symbol}_daily.csv"
    if not path.exists():
        return {"symbol": symbol, "common_days": 0}
    with path.open(newline="", encoding="utf-8") as handle:
        existing = {row["date"]: row for row in csv.DictReader(handle)}
    daily = aggregate_daily(minute_rows)
    comparisons: list[tuple[float, float]] = []
    for date_value, intraday in daily.items():
        current = existing.get(date_value)
        if not current or not float(current["close"]):
            continue
        close_pct = (intraday["close"] / float(current["close"]) - 1) * 100
        volume_pct = (intraday["volume"] / float(current["volume"]) - 1) * 100 if float(current["volume"]) else 0.0
        comparisons.append((abs(close_pct), abs(volume_pct)))
    if not comparisons:
        return {"symbol": symbol, "common_days": 0}
    close_values = [value[0] for value in comparisons]
    volume_values = [value[1] for value in comparisons]
    return {
        "symbol": symbol,
        "common_days": len(comparisons),
        "median_abs_close_diff_pct": round(statistics.median(close_values), 6),
        "max_abs_close_diff_pct": round(max(close_values), 6),
        "median_abs_volume_diff_pct": round(statistics.median(volume_values), 6),
    }


def expected_trading_days(symbol: str, start: dt.date, end: dt.date) -> list[str]:
    path = DAILY_ROOT / f"{symbol}_daily.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            row["date"]
            for row in csv.DictReader(handle)
            if start.isoformat() <= row["date"] <= end.isoformat()
        ]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download split-adjusted regular-session EODHD intraday data for an isolated portfolio experiment."
    )
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date.fromisoformat(CONFIG["start_date"]))
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--interval", default="5m", choices=["1m", "5m", "1h"])
    parser.add_argument("--chunk-days", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="Download symbols again even when a local file is present.")
    args = parser.parse_args()
    if args.chunk_days < 1 or args.chunk_days > 120:
        raise SystemExit("--chunk-days must be between 1 and 120 for the EODHD intraday endpoint.")
    if args.end < args.start:
        raise SystemExit("--end must not be earlier than --start.")
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8.")

    symbols = [symbol.upper().replace(".US", "") for symbol in (args.symbols or symbols_from_strategies())]
    private_root = PRIVATE_BASE / f"historical_{args.interval}_rth_adjusted"
    private_root.mkdir(parents=True, exist_ok=True)
    previous_summary_path = private_root / "pull_summary.csv"
    previous_summary = {}
    if previous_summary_path.exists():
        with previous_summary_path.open(newline="", encoding="utf-8") as handle:
            previous_summary = {row["symbol"]: row for row in csv.DictReader(handle)}
    pull_summary: list[dict[str, object]] = []
    quality_summary: list[dict[str, object]] = []
    missing_day_rows: list[dict[str, object]] = []
    for index, symbol in enumerate(symbols, start=1):
        print(f"[{index}/{len(symbols)}] Pulling {symbol}...", flush=True)
        output_path = private_root / f"{symbol}_{args.interval}_rth_adjusted.csv"
        expected_days = expected_trading_days(symbol, args.start, args.end)
        expected_set = set(expected_days)
        existing_rows = read_rows(output_path)
        retained_rows = [row for row in existing_rows if not expected_set or str(row["date"]) in expected_set]
        extra_rows_removed = len(existing_rows) - len(retained_rows)
        if extra_rows_removed:
            write_rows(output_path, retained_rows)
        existing_dates = {str(row["date"]) for row in retained_rows}
        if existing_rows and not args.force:
            missing_days = [date_value for date_value in expected_days if date_value not in existing_dates]
            missing_day_rows.extend({"symbol": symbol, "missing_date": date_value} for date_value in missing_days)
            status = "COMPLETE_EXISTING" if not missing_days else "INCOMPLETE_EXISTING"
            coverage_stats = session_coverage(retained_rows, args.interval)
            quality_summary.append(quality_vs_current_daily(symbol, retained_rows))
            pull_summary.append(
                {
                    "symbol": symbol,
                    "requested_start": args.start.isoformat(),
                    "requested_end": args.end.isoformat(),
                    "api_requests": 0,
                    "raw_bars_received": "",
                    "invalid_raw_bars_skipped": previous_summary.get(symbol, {}).get("invalid_raw_bars_skipped", ""),
                    "regular_session_bars": len(retained_rows),
                    "expected_trading_days": len(expected_days),
                    "received_trading_days": len(existing_dates),
                    "missing_trading_days": len(missing_days),
                    "coverage_status": status,
                    **coverage_stats,
                    "extra_rows_removed": extra_rows_removed,
                    "split_events": previous_summary.get(symbol, {}).get("split_events", ""),
                    "split_adjusted_bars": sum(
                        1 for row in retained_rows if float(row["split_adjustment_factor"]) != 1.0
                    ),
                    "first_bar_utc": retained_rows[0]["datetime_utc"] if retained_rows else "",
                    "last_bar_utc": retained_rows[-1]["datetime_utc"] if retained_rows else "",
                    "file": output_path.name,
                }
            )
            print(
                f"  retained existing file with {len(retained_rows):,} bars; "
                f"{len(missing_days)} missing trading day(s); removed {extra_rows_removed} extra row(s).",
                flush=True,
            )
            continue

        splits = fetch_splits(symbol, args.start, dt.date.today())
        by_time: dict[str, dict[str, object]] = {}
        raw_count = 0
        invalid_raw_count = 0
        ranges = chunks(args.start, args.end, args.chunk_days)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            responses = list(pool.map(lambda period: fetch_intraday_chunk(symbol, *period, args.interval), ranges))
        for raw_rows in responses:
            raw_count += len(raw_rows)
            invalid_raw_count += sum(
                1
                for row in raw_rows
                if not row.get("datetime")
                or any(row.get(field) is None for field in ("open", "high", "low", "close"))
            )
            for row in normalize_rows(raw_rows, splits):
                by_time[str(row["datetime_utc"])] = row
        minute_rows = [
            by_time[key]
            for key in sorted(by_time)
            if not expected_set or str(by_time[key]["date"]) in expected_set
        ]
        write_rows(output_path, minute_rows)
        adjusted_rows = sum(1 for row in minute_rows if float(row["split_adjustment_factor"]) != 1.0)
        received_days = {str(row["date"]) for row in minute_rows}
        missing_days = [date_value for date_value in expected_days if date_value not in received_days]
        missing_day_rows.extend({"symbol": symbol, "missing_date": date_value} for date_value in missing_days)
        coverage_stats = session_coverage(minute_rows, args.interval)
        pull_summary.append(
            {
                "symbol": symbol,
                "requested_start": args.start.isoformat(),
                "requested_end": args.end.isoformat(),
                "api_requests": len(ranges) + 1,
                "raw_bars_received": raw_count,
                "invalid_raw_bars_skipped": invalid_raw_count,
                "regular_session_bars": len(minute_rows),
                "expected_trading_days": len(expected_days),
                "received_trading_days": len(received_days),
                "missing_trading_days": len(missing_days),
                "coverage_status": "COMPLETE" if not missing_days else "INCOMPLETE",
                **coverage_stats,
                "extra_rows_removed": len(by_time) - len(minute_rows),
                "split_events": len(splits),
                "split_adjusted_bars": adjusted_rows,
                "first_bar_utc": minute_rows[0]["datetime_utc"] if minute_rows else "",
                "last_bar_utc": minute_rows[-1]["datetime_utc"] if minute_rows else "",
                "file": output_path.name,
            }
        )
        quality_summary.append(quality_vs_current_daily(symbol, minute_rows))
        print(
            f"  saved {len(minute_rows):,} regular-session bars; "
            f"{len(splits)} split event(s); {adjusted_rows:,} adjusted rows; "
            f"{len(missing_days)} missing trading day(s); {invalid_raw_count} invalid bar(s) skipped.",
            flush=True,
        )
    write_csv(private_root / "pull_summary.csv", pull_summary)
    write_csv(private_root / "daily_quality_vs_current_source.csv", quality_summary)
    if missing_day_rows:
        write_csv(private_root / "missing_trading_days.csv", missing_day_rows)
    else:
        missing_path = private_root / "missing_trading_days.csv"
        if missing_path.exists():
            missing_path.unlink()
    metadata = {
        "source": "EODHD EOD-IntraDay All World",
        "interval": args.interval,
        "session": "US regular trading hours 09:30-16:00 America/New_York inclusive",
        "price_adjustment": "Split adjusted to current share scale using EODHD splits endpoint.",
        "requested_start": args.start.isoformat(),
        "requested_end": args.end.isoformat(),
        "symbols": symbols,
        "generated_at_utc": dt.datetime.now(tz=UTC).isoformat(),
        "private_data_notice": "Do not publish raw provider files or API tokens.",
    }
    (private_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Experiment pull complete. Summary saved under {private_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
