#!/usr/bin/env python3
"""Organization-level utilities for portfolio output isolation.

The root reports folder remains a compatibility surface for the existing local
dashboard and publishing workflow. Each approved portfolio also receives its
own synchronized official report package below ``portfolios``.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
PORTFOLIOS = ROOT / "portfolios"
DEPARTMENTS = ROOT / "departments"
DEFAULT_ACTIVE_PORTFOLIO_ID = "sharia_us_growth_v1"

OFFICIAL_REPORT_FILES = (
    "portfolio_dashboard.html",
    "portfolio_analytics.html",
    "portfolio_business_intelligence.html",
    "portfolio_financial_diagnostics.html",
    "portfolio_financial_diagnostics.json",
    "portfolio_simulation.html",
    "portfolio_trades.csv",
    "portfolio_equity_curve.csv",
    "portfolio_ledger.csv",
    "portfolio_strategies.csv",
    "portfolio_execution_metadata.json",
)


def active_portfolio_id(config: dict[str, Any]) -> str:
    return str(config.get("active_portfolio_id", DEFAULT_ACTIVE_PORTFOLIO_ID))


def write_management_briefs(
    config: dict[str, Any],
    portfolio_id: str,
    execution_metadata: dict[str, Any],
    synchronized_at_local: str,
) -> None:
    summary = execution_metadata.get("portfolio_summary", {})
    common = {
        "as_of_market_date": summary.get("end_date"),
        "synchronized_at_local": synchronized_at_local,
        "portfolio_id": portfolio_id,
        "display_name_ar": config.get("portfolio_display_name_ar", portfolio_id),
        "primary_status_source": f"portfolios/{portfolio_id}/status/latest_portfolio_status.json",
        "read_full_reports_only_when_required": True,
    }
    briefs = {
        "data_management": {
            **common,
            "responsibility_ar": "سلامة بيانات السوق واكتمال الجلسات المستخدمة في المحاكاة",
            "market_data_source": execution_metadata.get("market_data_source"),
            "market_data_interval": execution_metadata.get("market_data_interval"),
            "execution_model": execution_metadata.get("execution_model"),
            "data_checks": execution_metadata.get("execution_diagnostics", {}),
            "escalate_if_ar": "تعذر التحديث أو ظهرت جلسة ناقصة أو تغير مصدر البيانات",
        },
        "investment_research": {
            **common,
            "responsibility_ar": "متابعة صلاحية الاستراتيجية ونتائجها قبل اقتراح أي تعديل",
            "approved_policy_ar": "وقف متحرك مبني على أعلى سعر يومي ويصبح فعالا في الجلسة التالية",
            "trailing_stop_step_pct": execution_metadata.get("trailing_stop_step_pct"),
            "selection_period": execution_metadata.get("trailing_stop_selection_period"),
            "evaluation_period_start": execution_metadata.get("conservative_evaluation_period_start"),
            "key_results": {
                "period_return_pct": summary.get("period_return_pct"),
                "win_rate": summary.get("win_rate"),
                "avg_win_pct": summary.get("avg_win_pct"),
                "avg_loss_pct": summary.get("avg_loss_pct"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
            },
            "escalate_if_ar": "تراجع العائد أو ارتفاع السحب أو طلب اختبار استراتيجية بديلة",
        },
        "solutions": {
            **common,
            "responsibility_ar": "تشغيل البناء والتحديث والنشر وحماية فصل التقارير الرسمية عن المراجعات",
            "official_build_ar": "التحديث المعتاد يبني المحفظة المعتمدة فقط",
            "comparison_review_ar": "المقارنات التاريخية تشغل عند طلب مراجعة المجلس فقط",
            "published_dashboard": "publish_dashboard/portfolio_dashboard.html",
            "escalate_if_ar": "فشل البناء أو توقف النشر أو اختلفت نتيجة المحفظة بعد تعديل تقني",
        },
        "portfolio_management": {
            **common,
            "responsibility_ar": "متابعة أداء المحفظة والمخاطر والصفقات المفتوحة وفق التفويض المعتمد",
            "portfolio_value": summary.get("portfolio_value"),
            "pnl": summary.get("pnl"),
            "period_return_pct": summary.get("period_return_pct"),
            "closed_trades": summary.get("closed"),
            "open_trades": summary.get("open"),
            "wins": summary.get("wins"),
            "losses": summary.get("losses"),
            "max_drawdown_pct": summary.get("max_drawdown_pct"),
            "escalate_if_ar": "تجاوز المخاطر أو ظهور حاجة لتغيير التفويض أو قواعد رأس المال",
        },
    }
    for department_id, brief in briefs.items():
        briefing_dir = DEPARTMENTS / department_id / "briefings"
        briefing_dir.mkdir(parents=True, exist_ok=True)
        (briefing_dir / "current_brief.json").write_text(
            json.dumps(brief, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )


def sync_active_portfolio_outputs(config: dict[str, Any]) -> Path:
    """Copy official output only into the active portfolio's isolated workspace."""
    portfolio_id = active_portfolio_id(config)
    portfolio_root = PORTFOLIOS / portfolio_id
    portfolio_reports = portfolio_root / "reports"
    portfolio_status = portfolio_root / "status"
    portfolio_config = portfolio_root / "config"
    portfolio_reports.mkdir(parents=True, exist_ok=True)
    portfolio_status.mkdir(parents=True, exist_ok=True)
    portfolio_config.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for filename in OFFICIAL_REPORT_FILES:
        source = REPORTS / filename
        if not source.exists():
            continue
        shutil.copy2(source, portfolio_reports / filename)
        copied.append(filename)

    (portfolio_config / "runtime_config_snapshot.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    metadata_path = REPORTS / "portfolio_execution_metadata.json"
    execution_metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    synchronized_at_local = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest_status = {
        "portfolio_id": portfolio_id,
        "display_name_ar": config.get("portfolio_display_name_ar", portfolio_id),
        "status": "approved_paper_portfolio",
        "managing_department": "portfolio_management",
        "synchronized_at_local": synchronized_at_local,
        "compatibility_dashboard": "reports/portfolio_dashboard.html",
        "organized_dashboard": f"portfolios/{portfolio_id}/reports/portfolio_dashboard.html",
        "official_files": copied,
        "execution_metadata": execution_metadata,
    }
    (portfolio_status / "latest_portfolio_status.json").write_text(
        json.dumps(latest_status, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    write_management_briefs(config, portfolio_id, execution_metadata, synchronized_at_local)
    return portfolio_root
