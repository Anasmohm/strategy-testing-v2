#!/usr/bin/env python3
"""Build the approved reports for this portfolio through the shared runtime."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paper_portfolio_v31 import main


if __name__ == "__main__":
    raise SystemExit(main())
