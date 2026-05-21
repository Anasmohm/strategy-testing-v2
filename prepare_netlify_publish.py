#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
PUBLISH = ROOT / "publish_dashboard"

FILES = {
    "paper_portfolio_v2_dashboard.html": "paper_portfolio_v2_dashboard.html",
    "paper_portfolio_v2_analytics.html": "paper_portfolio_v2_analytics.html",
    "strategy_v2_dashboard.html": "strategy_v2_dashboard.html",
}


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
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
  <meta http-equiv="refresh" content="0; url=paper_portfolio_v2_dashboard.html">
  <title>V2 Dashboard</title>
</head>
<body>
  <a href="paper_portfolio_v2_dashboard.html">فتح الداشبورد</a>
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
Run this after every local dashboard refresh:

python paper_portfolio_v2.py
python prepare_netlify_publish.py

Then deploy this folder to Netlify:
publish_dashboard
""",
    )
    print(f"Prepared Netlify publish folder: {PUBLISH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
