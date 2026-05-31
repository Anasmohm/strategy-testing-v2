#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PRIVATE_DATA = ROOT / "data" / "eodhd_private"
ENDPOINT = "https://eodhd.com/api/intraday/{symbol}"


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


def unix_day_bounds(date_value: dt.date) -> tuple[int, int]:
    start = dt.datetime.combine(date_value, dt.time.min, tzinfo=dt.timezone.utc)
    end = dt.datetime.combine(date_value, dt.time.max, tzinfo=dt.timezone.utc)
    return int(start.timestamp()), int(end.timestamp())


def fetch_intraday(symbol: str, date_value: dt.date, interval: str) -> list[dict[str, object]]:
    token = user_environment_value("EODHD_API_TOKEN")
    if not token:
        raise SystemExit("EODHD_API_TOKEN is not saved in the user environment.")
    start, end = unix_day_bounds(date_value)
    query = urllib.parse.urlencode(
        {
            "api_token": token,
            "fmt": "json",
            "interval": interval,
            "from": start,
            "to": end,
        }
    )
    request = urllib.request.Request(
        f"{ENDPOINT.format(symbol=urllib.parse.quote(symbol))}?{query}",
        headers={"User-Agent": "StrategyTestingV2/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"EODHD request failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"EODHD connection failed: {exc.reason}") from exc
    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("error") or "Unexpected API response."
        raise RuntimeError(f"EODHD did not return intraday bars: {detail}")
    if not isinstance(payload, list):
        raise RuntimeError("EODHD returned an unsupported intraday response.")
    return payload


def save_sample(symbol: str, date_value: dt.date, interval: str, rows: list[dict[str, object]]) -> Path:
    PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace(".", "_")
    path = PRIVATE_DATA / f"{safe_symbol}_{interval}_{date_value:%Y%m%d}.csv"
    fields = ["timestamp", "gmtoffset", "datetime", "open", "high", "low", "close", "volume"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EODHD intraday access without changing portfolio data.")
    parser.add_argument("--symbol", default="AMD.US")
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--interval", default="1m", choices=["1m", "5m", "1h"])
    args = parser.parse_args()

    rows = fetch_intraday(args.symbol, args.date, args.interval)
    if not rows:
        print(f"No intraday bars returned for {args.symbol} on {args.date.isoformat()}.")
        return 2
    path = save_sample(args.symbol, args.date, args.interval, rows)
    timestamps = [str(row.get("datetime", "")) for row in rows if row.get("datetime")]
    volumes = [float(row.get("volume", 0) or 0) for row in rows]
    print(f"EODHD validation succeeded: {args.symbol} {args.interval} {args.date.isoformat()}")
    print(f"Bars returned: {len(rows)}")
    if timestamps:
        print(f"Coverage: {timestamps[0]} through {timestamps[-1]}")
    print(f"Total volume in sample: {sum(volumes):,.0f}")
    print(f"Private sample saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
