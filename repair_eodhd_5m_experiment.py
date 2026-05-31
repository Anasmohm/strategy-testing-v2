#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path

import download_eodhd_intraday_experiment as downloader


ROOT = Path(__file__).resolve().parent
FIVE_MINUTE_ROOT = ROOT / "data" / "eodhd_private" / "historical_5m_rth_adjusted"


def read_rows(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def group_by_date(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["date"])].append(row)
    return grouped


def resample_five_minutes(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        timestamp = dt.datetime.strptime(str(row["datetime_utc"]), "%Y-%m-%d %H:%M:%S")
        bucket = timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0)
        grouped[bucket.strftime("%Y-%m-%d %H:%M:%S")].append(row)
    aggregated: list[dict[str, object]] = []
    for bucket in sorted(grouped):
        values = sorted(grouped[bucket], key=lambda row: str(row["datetime_utc"]))
        aggregated.append(
            {
                "datetime_utc": bucket,
                "date": values[0]["date"],
                "time_et": dt.datetime.strptime(str(values[0]["time_et"]), "%H:%M:%S")
                .replace(minute=(dt.datetime.strptime(str(values[0]["time_et"]), "%H:%M:%S").minute // 5) * 5, second=0)
                .strftime("%H:%M:%S"),
                "open": float(values[0]["open"]),
                "high": max(float(row["high"]) for row in values),
                "low": min(float(row["low"]) for row in values),
                "close": float(values[-1]["close"]),
                "volume": sum(int(float(row["volume"])) for row in values),
                "split_adjustment_factor": float(values[0]["split_adjustment_factor"]),
            }
        )
    return aggregated


def repair_session(symbol: str, date_value: str, split_events: list[tuple[dt.date, float]]) -> tuple[str, list[dict[str, object]], str]:
    day = dt.date.fromisoformat(date_value)
    source_interval = "5m" if day in downloader.EARLY_CLOSE_DATES else "1m"
    raw_rows = downloader.fetch_intraday_chunk(symbol, day, day, source_interval)
    normalized = downloader.normalize_rows(raw_rows, split_events)
    rebuilt = normalized if source_interval == "5m" else resample_five_minutes(normalized)
    return date_value, rebuilt, source_interval


def write_report(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair partial EODHD 5-minute sessions by resampling available 1-minute data.")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--full-session-bars", type=int, default=79)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8.")

    files = sorted(FIVE_MINUTE_ROOT.glob("*_5m_rth_adjusted.csv"))
    selected = {symbol.upper() for symbol in args.symbols} if args.symbols else None
    files = [path for path in files if selected is None or path.name.split("_")[0] in selected]
    if not files:
        raise SystemExit("No 5-minute experiment files were found.")

    report: list[dict[str, object]] = []
    for index, path in enumerate(files, start=1):
        symbol = path.name.split("_")[0]
        rows = read_rows(path)
        by_date = group_by_date(rows)
        partial_dates = sorted(
            date_value
            for date_value, values in by_date.items()
            if len(values) < args.full_session_bars or dt.date.fromisoformat(date_value) in downloader.EARLY_CLOSE_DATES
        )
        split_events = downloader.fetch_splits(symbol, dt.date.fromisoformat(min(by_date)), dt.date.today())
        print(f"[{index}/{len(files)}] Repairing {symbol}: {len(partial_dates)} candidate session(s).", flush=True)
        if not partial_dates:
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda value: repair_session(symbol, value, split_events), partial_dates))
        changed = False
        for date_value, rebuilt, source_interval in results:
            original_count = len(by_date[date_value])
            rebuilt_count = len(rebuilt)
            action = "retained_original"
            is_early_close = dt.date.fromisoformat(date_value) in downloader.EARLY_CLOSE_DATES
            if rebuilt_count > original_count or (is_early_close and rebuilt_count > 0 and rebuilt_count != original_count):
                by_date[date_value] = rebuilt
                changed = True
                action = "restored_early_close_5m" if is_early_close else "replaced_from_1m"
            report.append(
                {
                    "symbol": symbol,
                    "date": date_value,
                    "original_5m_bars": original_count,
                    "rebuilt_5m_bars": rebuilt_count,
                    "added_bars": max(rebuilt_count - original_count, 0),
                    "repair_source_interval": source_interval,
                    "action": action,
                }
            )
        if changed:
            repaired_rows = [row for date_value in sorted(by_date) for row in sorted(by_date[date_value], key=lambda item: str(item["datetime_utc"]))]
            downloader.write_rows(path, repaired_rows)
    if report:
        write_report(FIVE_MINUTE_ROOT / "repair_from_1m_summary.csv", report)
    replacements = [row for row in report if row["action"] != "retained_original"]
    print(f"Repair complete: {len(replacements)} session(s) corrected or improved.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
