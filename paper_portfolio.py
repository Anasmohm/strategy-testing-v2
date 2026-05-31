#!/usr/bin/env python3
"""Compatibility runner for the approved paper portfolio.

Runs the official V3.1 Hybrid portfolio. Use paper_portfolio_v2.py only when
you explicitly want the archived V2 benchmark.
"""
from __future__ import annotations

from paper_portfolio_v31 import main


if __name__ == "__main__":
    raise SystemExit(main())
