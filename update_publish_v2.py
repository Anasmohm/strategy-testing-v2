#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import eodhd_official_data


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
LOG = REPORTS / "update_publish_v2.log"
SELECTED = REPORTS / "selected_strategies.csv"
DEFAULT_TICKERS = ["AMD", "ANET", "AVGO", "LRCX", "MRVL", "NVDA", "PANW", "SHOP", "TSLA"]
MARKET_BENCHMARKS = ["QQQ", "SPY", "SOXX"]


def log(message: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")
    print(message, flush=True)


def selected_tickers() -> list[str]:
    if not SELECTED.exists():
        return DEFAULT_TICKERS
    with SELECTED.open(newline="", encoding="utf-8-sig") as handle:
        tickers = sorted({row.get("ticker", "").strip().upper() for row in csv.DictReader(handle) if row.get("ticker")})
    return tickers or DEFAULT_TICKERS


def refresh_market_data() -> None:
    end = dt.datetime.now(tz=dt.timezone.utc).date()
    try:
        eodhd_official_data.refresh(eodhd_official_data.configured_warmup_start(), end)
        log(f"EODHD 5m official market data refreshed through available sessions up to {end.isoformat()}")
    except Exception as exc:
        cached = all(eodhd_official_data.intraday_path(ticker).exists() for ticker in eodhd_official_data.configured_symbols())
        if not cached:
            raise
        log(f"EODHD refresh unavailable; rebuilding from existing cached 5m data: {exc}")


def run_step(args: list[str], label: str, required: bool = True) -> bool:
    log(f"running {label}: {' '.join(args)}")
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.stdout.strip():
        log(result.stdout.strip()[-3000:])
    if result.stderr.strip():
        log(result.stderr.strip()[-3000:])
    if result.returncode != 0:
        log(f"{label} failed with exit code {result.returncode}")
        if required:
            raise SystemExit(result.returncode)
        return False
    return True


def netlify_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    path_cmd = shutil.which("netlify.cmd") or shutil.which("netlify")
    if path_cmd:
        commands.append([path_cmd, "deploy", "--prod"])

    appdata = os.environ.get("APPDATA")
    if appdata:
        cmd = Path(appdata) / "npm" / "netlify.cmd"
        if cmd.exists():
            commands.append([str(cmd), "deploy", "--prod"])
        run_js = Path(appdata) / "npm" / "node_modules" / "netlify-cli" / "bin" / "run.js"
        node_candidates = [r"C:\Program Files\nodejs\node.exe"]
        path_node = shutil.which("node")
        if path_node:
            node_candidates.append(path_node)
        for node in node_candidates:
            if run_js.exists() and Path(node).exists():
                commands.append([node, str(run_js), "deploy", "--prod"])
    return commands


def deploy_to_netlify() -> None:
    last_error = "Netlify CLI was not found."
    for command in netlify_commands():
        try:
            if run_step(command, "netlify deploy", required=False):
                return
        except PermissionError as exc:
            last_error = str(exc)
            log(f"netlify command permission error: {exc}")
    raise SystemExit(f"Netlify deploy failed. Last error: {last_error}")


def main() -> int:
    log("starting approved V3.1 update and publish")
    refresh_market_data()
    run_step([sys.executable, str(ROOT / "paper_portfolio_v31.py")], "build approved V3.1 portfolio")
    run_step([sys.executable, str(ROOT / "prepare_netlify_publish.py")], "prepare netlify publish")
    deploy_to_netlify()
    log("finished approved V3.1 update and publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
