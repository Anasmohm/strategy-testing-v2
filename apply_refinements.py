#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

import design_strategies


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
STRATEGIES = REPORTS / "designed_strategies.csv"
REFINEMENTS = REPORTS / "strategy_refinements.csv"
V2_STRATEGIES = REPORTS / "designed_strategies_v2.csv"
V2_VERIFICATION = REPORTS / "strategy_verification_v2.csv"
COMPARISON = REPORTS / "strategy_verification_comparison.csv"
SELECTED_STRATEGIES = REPORTS / "selected_strategies.csv"
SELECTED_VERIFICATION = REPORTS / "selected_strategy_verification.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def to_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except ValueError:
        return 0.0


def apply_refinement(strategy: dict[str, object], refinement: dict[str, str]) -> dict[str, object]:
    updated = dict(strategy)
    proposed_rule = refinement["proposed_entry_rule"]
    if proposed_rule == "avoid_or_half_size":
        updated["size_multiplier"] = round(float(updated.get("size_multiplier", 1.0)) * 0.5, 2)
        updated["rationale"] = str(updated.get("rationale", "")) + " تعديل v2: لم يظهر نمط واضح، لذلك خفضنا الحجم بدل توسيع المخاطرة."
        return updated

    updated["entry_rule"] = proposed_rule
    updated["lookback"] = int(float(refinement["proposed_lookback"]))
    updated["target_pct"] = float(refinement["proposed_target_pct"])
    updated["initial_stop_pct"] = float(refinement["proposed_stop_pct"])
    updated["rationale"] = str(updated.get("rationale", "")) + " تعديل v2: " + refinement["proposed_change"]
    updated["version"] = "v2_refined"
    return updated


def main() -> int:
    strategies = read_csv(STRATEGIES)
    refinements = {row["ticker"]: row for row in read_csv(REFINEMENTS)}
    v2_strategies: list[dict[str, object]] = []
    for strategy in strategies:
        if strategy["ticker"] in refinements:
            v2_strategies.append(apply_refinement(strategy, refinements[strategy["ticker"]]))
        else:
            row = dict(strategy)
            row["version"] = "v1_kept"
            v2_strategies.append(row)

    v2_verification = [design_strategies.verify_strategy(strategy) for strategy in v2_strategies]
    v1_verification = {row["ticker"]: row for row in read_csv(REPORTS / "strategy_verification.csv")}

    comparison: list[dict[str, object]] = []
    selected_strategies: list[dict[str, object]] = []
    v2_by_ticker = {str(row["ticker"]): row for row in v2_strategies}
    v1_by_ticker = {str(row["ticker"]): row for row in strategies}
    v2_verification_by_ticker = {str(row["ticker"]): row for row in v2_verification}
    selected_verification: list[dict[str, object]] = []
    for row in v2_verification:
        ticker = str(row["ticker"])
        old = v1_verification.get(ticker, {})
        old_total = to_float(old, "total_return")
        new_total = float(row["total_return"])
        old_win = to_float(old, "win_rate")
        new_win = float(row["win_rate"])
        use_v2 = new_total > old_total
        chosen_strategy = dict(v2_by_ticker[ticker] if use_v2 else v1_by_ticker[ticker])
        chosen_strategy["selected_version"] = "v2_refined" if use_v2 else "v1_original"
        selected_strategies.append(chosen_strategy)
        selected_verification.append(v2_verification_by_ticker[ticker] if use_v2 else old)
        comparison.append(
            {
                "ticker": ticker,
                "old_pass": old.get("designed_pass", ""),
                "new_pass": row["designed_pass"],
                "old_trades": old.get("trades", ""),
                "new_trades": row["trades"],
                "old_win_rate": old_win,
                "new_win_rate": new_win,
                "old_total_return": old_total,
                "new_total_return": new_total,
                "return_delta": round(new_total - old_total, 2),
                "win_rate_delta": round(new_win - old_win, 2),
                "selected_version": chosen_strategy["selected_version"],
            }
        )

    write_csv(V2_STRATEGIES, v2_strategies)
    write_csv(V2_VERIFICATION, v2_verification)
    write_csv(COMPARISON, comparison)
    write_csv(SELECTED_STRATEGIES, selected_strategies)
    write_csv(SELECTED_VERIFICATION, selected_verification)
    improved = sum(1 for row in comparison if float(row["return_delta"]) > 0)
    passed = sum(1 for row in v2_verification if row["designed_pass"])
    selected_passed = sum(1 for row in selected_verification if str(row.get("designed_pass", "")).lower() == "true")
    print(f"V2 strategies: {len(v2_strategies)}")
    print(f"Improved total return: {improved}")
    print(f"V2 verified pass: {passed}")
    print(f"Selected verified pass: {selected_passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
