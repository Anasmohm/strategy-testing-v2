#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DIAGNOSIS = REPORTS / "stock_diagnosis.csv"
STRATEGIES = REPORTS / "designed_strategies.csv"
VERIFICATION = REPORTS / "strategy_verification.csv"
REFINEMENTS = REPORTS / "strategy_refinements.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def to_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except ValueError:
        return 0.0


def refine(row: dict[str, str]) -> dict[str, object]:
    ticker = row["ticker"]
    behavior = row["behavior"]
    trades = to_float(row, "trades")
    win_rate = to_float(row, "win_rate")
    avg_return = to_float(row, "avg_return")
    loss_count = to_float(row, "loss_count")
    avg_range = to_float(row, "avg_daily_range_pct")
    breakout_rate = to_float(row, "breakout_success_rate_pct")
    pullback_rate = to_float(row, "pullback_success_rate_pct")
    drawdown = abs(to_float(row, "max_drawdown_pct"))
    current_target = to_float(row, "target_pct")
    current_stop = to_float(row, "initial_stop_pct")
    entry_rule = row["entry_rule"]

    if trades < 8:
        failure_reason = "قلة إشارات التحقق"
        if behavior == "breakout":
            proposed_change = "خفض lookback من 55/100 إلى 20 أو إزالة جزء من فلتر الحجم لزيادة الإشارات."
            new_entry_rule = "close_above_prior_high"
            new_lookback = 20
        elif behavior == "trend_following":
            proposed_change = "استخدام pullback أقصر داخل الترند أو السماح بالدخول عند اختراق متوسط 20."
            new_entry_rule = "trend_pullback_resume"
            new_lookback = 10
        else:
            proposed_change = "توسيع شروط الدخول قليلًا مع بقاء فلتر الترند."
            new_entry_rule = entry_rule
            new_lookback = max(5, int(to_float(row, "lookback") or 20) // 2)
        new_target = max(3.0, current_target * 0.9)
        new_stop = current_stop
    elif win_rate < 50:
        failure_reason = "نسبة فوز ضعيفة"
        if pullback_rate > breakout_rate + 5:
            proposed_change = "تحويل التصميم إلى ارتداد بعد هبوط لأن الارتداد أنجح من الاختراق تاريخيًا."
            new_entry_rule = "five_day_drop_recovery"
            new_lookback = 5
        elif breakout_rate > pullback_rate + 5:
            proposed_change = "تحويل التصميم إلى اختراق مؤكد لأن الاختراق أنجح من الارتداد تاريخيًا."
            new_entry_rule = "close_above_prior_high"
            new_lookback = 20
        else:
            proposed_change = "تقليل حجم الصفقة أو تجنب السهم حتى يظهر نمط أوضح."
            new_entry_rule = "avoid_or_half_size"
            new_lookback = int(to_float(row, "lookback") or 20)
        new_target = max(3.0, current_target * 0.8)
        new_stop = max(2.0, current_stop * 0.85)
    elif avg_return <= 0:
        failure_reason = "العائد المتوسط غير كاف"
        proposed_change = "تقليل الهدف وزيادة الاعتماد على الوقف المتحرك لجني أرباح أسرع."
        new_entry_rule = entry_rule
        new_lookback = int(to_float(row, "lookback") or 20)
        new_target = max(3.0, current_target * 0.75)
        new_stop = current_stop
    elif loss_count / max(trades, 1) > 0.35:
        failure_reason = "عدد خسائر مرتفع"
        proposed_change = "استخدام وقف أوسع قليلًا مع فلتر حجم/ترند أقوى، أو تقليل حجم الصفقة."
        new_entry_rule = entry_rule
        new_lookback = int(to_float(row, "lookback") or 20)
        new_target = current_target
        new_stop = min(max(current_stop * 1.2, avg_range * 1.5), drawdown / 4 if drawdown else current_stop * 1.2)
    else:
        failure_reason = "فشل حدود التحقق رغم وجود إشارات"
        proposed_change = "يحتاج اختبار بديل مخصص يدويًا؛ لا توجد إشارة واضحة من المقاييس الحالية."
        new_entry_rule = entry_rule
        new_lookback = int(to_float(row, "lookback") or 20)
        new_target = current_target
        new_stop = current_stop

    return {
        "ticker": ticker,
        "behavior": behavior,
        "failure_reason": failure_reason,
        "current_entry_rule": entry_rule,
        "proposed_entry_rule": new_entry_rule,
        "current_lookback": row.get("lookback", ""),
        "proposed_lookback": new_lookback,
        "current_target_pct": current_target,
        "proposed_target_pct": round(new_target, 2),
        "current_stop_pct": current_stop,
        "proposed_stop_pct": round(new_stop, 2),
        "trades": int(trades),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "loss_count": int(loss_count),
        "proposed_change": proposed_change,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    diagnosis = {row["ticker"]: row for row in read_csv(DIAGNOSIS)}
    strategies = {row["ticker"]: row for row in read_csv(STRATEGIES)}
    verification = read_csv(VERIFICATION)
    failed = [row for row in verification if str(row.get("designed_pass", "")).lower() != "true"]
    merged = []
    for row in failed:
        ticker = row["ticker"]
        combined = {}
        combined.update(diagnosis.get(ticker, {}))
        combined.update(strategies.get(ticker, {}))
        combined.update(row)
        merged.append(refine(combined))
    write_csv(REFINEMENTS, merged)
    print(f"Failed strategies analyzed: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
