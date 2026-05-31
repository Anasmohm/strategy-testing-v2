#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
PUBLISH = ROOT / "publish_dashboard"

FILES = {
    "portfolio_dashboard.html": "portfolio_dashboard.html",
    "portfolio_analytics.html": "portfolio_analytics.html",
    "portfolio_business_intelligence.html": "portfolio_business_intelligence.html",
    "portfolio_financial_diagnostics.html": "portfolio_financial_diagnostics.html",
}


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    if PUBLISH.exists():
        shutil.rmtree(PUBLISH)
    PUBLISH.mkdir(exist_ok=True)
    for src_name, dst_name in FILES.items():
        src = REPORTS / src_name
        if not src.exists():
            raise FileNotFoundError(f"Missing generated report: {src}")
        shutil.copy2(src, PUBLISH / dst_name)

    write_text(
        PUBLISH / "index.html",
        """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url=portfolio_dashboard.html">
  <title>Official Portfolio Dashboard</title>
</head>
<body>
  <a href="portfolio_dashboard.html">فتح داشبورد المحفظة المعتمدة</a>
</body>
</html>
""",
    )
    write_text(
        PUBLISH / "robots.txt",
        """User-agent: *
Disallow: /
""",
    )
    write_text(
        PUBLISH / "_headers",
        """/*
  X-Robots-Tag: noindex, nofollow, noarchive
  Cache-Control: no-store, no-cache, must-revalidate, max-age=0
  Pragma: no-cache

/*.html
  Cache-Control: no-store, no-cache, must-revalidate, max-age=0
""",
    )
    write_text(
        PUBLISH / "README.txt",
        """This folder is the public Netlify package.
It intentionally contains only the rendered dashboard pages, not Python source files.

Approved default dashboard:
portfolio_dashboard.html

Approved investment engine:
V3.1 Hybrid

Approved market data source:
EODHD EOD-IntraDay All World, five-minute regular-session bars.

Execution model:
Raised trailing stops apply beginning with the next five-minute bar.

Comparison pages are kept in the reports folder only and are not published here.

Run this after every local dashboard refresh:

python portfolio.py
python build_dashboard.py
python prepare_netlify_publish.py

Then deploy this folder to Netlify:
publish_dashboard
""",
    )
    print(f"Prepared Netlify publish folder: {PUBLISH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
