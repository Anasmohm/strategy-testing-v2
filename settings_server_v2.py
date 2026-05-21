#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"


def load_config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def save_config(config: dict[str, object]) -> None:
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def rebuild() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "update_publish_v2.py")], cwd=ROOT, capture_output=True, text=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(200, {"ok": True})

    def do_GET(self) -> None:
        if self.path != "/settings":
            self._send(404, {"ok": False})
            return
        self._send(200, load_config())

    def do_POST(self) -> None:
        if self.path == "/refresh":
            result = rebuild()
            self._send(
                200 if result.returncode == 0 else 500,
                {"ok": result.returncode == 0, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
            )
            return
        if self.path != "/settings":
            self._send(404, {"ok": False})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        config = load_config()
        config.update(
            {
                "initial_capital": float(payload["initial_capital"]),
                "position_cap_pct": float(payload["position_cap_pct"]),
                "max_trade_adv_pct": float(payload["max_trade_adv_pct"]),
                "liquidity_lookback_days": int(payload["liquidity_lookback_days"]),
                "trailing_stop_step_pct": float(payload["trailing_stop_step_pct"]),
                "min_acceptable_annual_return_pct": float(payload["min_acceptable_annual_return_pct"]),
                "portfolio_universe": "v1_benchmark_tickers",
                "benchmark_comparison_mode": True,
            }
        )
        save_config(config)
        result = rebuild()
        self._send(
            200 if result.returncode == 0 else 500,
            {"ok": result.returncode == 0, "settings": config, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
        )


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)
    print("V2 settings server: http://127.0.0.1:8766")
    server.serve_forever()


if __name__ == "__main__":
    main()
