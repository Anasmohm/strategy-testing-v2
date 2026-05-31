#!/usr/bin/env python3
from __future__ import annotations

import sys

from update_publish_v2 import ROOT, log, refresh_market_data, run_step


def main() -> int:
    log("starting approved V3.1 GitHub Pages update")
    refresh_market_data()
    run_step([sys.executable, str(ROOT / "paper_portfolio_v31.py")], "build approved V3.1 dashboard")
    run_step([sys.executable, str(ROOT / "prepare_github_pages.py")], "prepare GitHub Pages")
    log("finished approved V3.1 GitHub Pages update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
