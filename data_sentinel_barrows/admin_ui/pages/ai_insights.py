# pages/ai_insights.py

import dash
import re
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import requests
import json
import logging
from datetime import date, timedelta
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import error_alert, info_alert, status_badge

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/ai-insights",
    name="AI Insights"
)

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

MODEL_ENDPOINT = "databricks-gpt-oss-20b"
MAX_TOKENS     = 8192
TEMPERATURE    = 0.2

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.Div([
        html.Span("🤖", style={"fontSize": "28px", "marginRight": "12px"}),
        html.Div([
            html.H2("AI Pipeline Insights", className="mb-0 text-white"),
            html.P(
                "Select a business date and let the AI analyse what happened "
                "across all four agents.",
                className="text-muted mb-0 small",
            ),
        ]),
    ], className="d-flex align-items-center mt-4 mb-4"),

    dcc.Location(id="ai-insights-location", refresh=False),

    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Business Date", className="text-white fw-bold"),
                    dbc.Input(
                        id          = "insights-date-input",
                        type        = "text",
                        placeholder = "YYYY-MM-DD  e.g. 2026-06-21",
                        value       = "2026-06-21",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555",
                            "fontSize"       : "16px"
                        }
                    ),
                    dbc.FormText(
                        "Available dates: 2026-06-19 through 2026-07-20",
                        className="text-muted"
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "🔍 Generate Insights",
                        id        = "generate-insights-btn",
                        color     = "primary",
                        size      = "lg",
                        className = "d-block w-100",
                        n_clicks  = 0
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Alert(
                        [
                            html.Strong("Note: "),
                            "AI generation takes 30-60 seconds. "
                            "The model reads data from all four agents "
                            "before generating the narrative."
                        ],
                        color     = "info",
                        className = "mb-0 small"
                    )
                ], md=5)
            ])
        ])
    ], className="mb-4"),

    html.Div(id="insights-alert"),
    dcc.Loading(
        id    = "ai-summary-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="insights-summary-section"),
    ),

    dcc.Loading(
        id    = "ai-insights-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="insights-narrative-section"),
    ),

    dcc.Store(id="insights-evidence-store", data=None)

], fluid=True)


# ── Data loaders ───────────────────────────────────────────────────────────

def load_agent1_data(business_date: str) -> dict:
    try:
        runs_df = execute_query(f"""
            SELECT
                validation_run_id,
                SUBSTRING_INDEX(fully_qualified_name, '.', -1) AS table_name,
                fully_qualified_name,
                overall_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true THEN 'YES' ELSE 'NO' END AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date = :business_date
            ORDER BY fully_qualified_name
        """, {"business_date": business_date})

        if runs_df.empty:
            return {"available": False, "runs": [], "failed_checks": []}

        runs       = []
        all_failed = []

        for _, run in runs_df.iterrows():
            run_id   = run["validation_run_id"]
            run_dict = {
                "table_name"           : str(run.get("table_name", "")),
                "fully_qualified_name" : str(run.get("fully_qualified_name", "")),
                "overall_status"       : str(run.get("overall_status", "")),
                "total_checks_run"     : int(run.get("total_checks_run") or 0),
                "total_checks_passed"  : int(run.get("total_checks_passed") or 0),
                "total_checks_warned"  : int(run.get("total_checks_warned") or 0),
                "total_checks_critical": int(run.get("total_checks_critical") or 0),
                "ai_enrichment_status" : str(run.get("ai_enrichment_status", "")),
                "alert_sent"           : str(run.get("alert_sent", "NO"))
            }
            runs.append(run_dict)

            failed_df = execute_query(f"""
                SELECT
                    check_type, check_level, column_name, check_status,
                    ROUND(observed_value, 4)       AS observed_value,
                    ROUND(baseline_value, 4)       AS baseline_value,
                    ROUND(deviation_percentage, 4) AS deviation_pct,
                    threshold_warning, threshold_critical,
                    ai_summary, ai_failure_category
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
                WHERE validation_run_id = :run_id
                  AND check_status IN ('CRITICAL', 'WARNING')
                ORDER BY
                    CASE check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                    check_type
            """, {"run_id": run_id})

            for _, chk in failed_df.iterrows():
                all_failed.append({
                    "table_name"        : run_dict["table_name"],
                    "check_type"        : str(chk.get("check_type", "")),
                    "check_level"       : str(chk.get("check_level", "")),
                    "column_name"       : str(chk.get("column_name", "") or "table-level"),
                    "check_status"      : str(chk.get("check_status", "")),
                    "observed_value"    : float(chk.get("observed_value") or 0),
                    "baseline_value"    : float(chk.get("baseline_value") or 0),
                    "deviation_pct"     : float(chk.get("deviation_pct") or 0),
                    "threshold_critical": float(chk.get("threshold_critical") or 0),
                    "ai_summary"        : str(chk.get("ai_summary") or ""),
                    "ai_category"       : str(chk.get("ai_failure_category") or "")
                })

        return {"available": True, "runs": runs, "failed_checks": all_failed}

    except Exception as e:
        logger.error(f"Failed to load Agent 1 data: {str(e)}")
        return {"available": False, "error": str(e)}


def load_agent2_data(business_date: str) -> dict:
    try:
        runs_df = execute_query(f"""
            SELECT
                reconciliation_run_id,
                SUBSTRING_INDEX(source_fully_qualified_name, '.', -1) AS table_name,
                source_fully_qualified_name,
                overall_status,
                total_checks_run, total_checks_passed,
                total_checks_warned, total_checks_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true THEN 'YES' ELSE 'NO' END AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date = :business_date
            ORDER BY source_fully_qualified_name
        """, {"business_date": business_date})

        if runs_df.empty:
            return {"available": False, "runs": [], "failed_checks": []}

        runs       = []
        all_failed = []

        for _, run in runs_df.iterrows():
            run_id   = run["reconciliation_run_id"]
            run_dict = {
                "table_name"           : str(run.get("table_name", "")),
                "overall_status"       : str(run.get("overall_status", "")),
                "total_checks_run"     : int(run.get("total_checks_run") or 0),
                "total_checks_passed"  : int(run.get("total_checks_passed") or 0),
                "total_checks_warned"  : int(run.get("total_checks_warned") or 0),
                "total_checks_critical": int(run.get("total_checks_critical") or 0),
                "ai_enrichment_status" : str(run.get("ai_enrichment_status", "")),
                "alert_sent"           : str(run.get("alert_sent", "NO"))
            }
            runs.append(run_dict)

            failed_df = execute_query(f"""
                SELECT
                    from_layer, to_layer, check_type, metric_name,
                    check_status,
                    ROUND(source_value, 2)         AS source_value,
                    ROUND(target_value, 2)         AS target_value,
                    ROUND(deviation_percentage, 2) AS deviation_pct,
                    threshold_warning, threshold_critical,
                    agent1_overall_status, ai_summary, ai_failure_category
                FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
                WHERE reconciliation_run_id = :run_id
                  AND check_status IN ('CRITICAL', 'WARNING')
                ORDER BY
                    CASE check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                    from_layer, check_type
            """, {"run_id": run_id})

            for _, chk in failed_df.iterrows():
                all_failed.append({
                    "table_name"   : run_dict["table_name"],
                    "from_layer"   : str(chk.get("from_layer", "")),
                    "to_layer"     : str(chk.get("to_layer", "")),
                    "check_type"   : str(chk.get("check_type", "")),
                    "metric_name"  : str(chk.get("metric_name", "")),
                    "check_status" : str(chk.get("check_status", "")),
                    "source_value" : float(chk.get("source_value") or 0),
                    "target_value" : float(chk.get("target_value") or 0),
                    "deviation_pct": float(chk.get("deviation_pct") or 0),
                    "agent1_status": str(chk.get("agent1_overall_status") or ""),
                    "ai_summary"   : str(chk.get("ai_summary") or ""),
                    "ai_category"  : str(chk.get("ai_failure_category") or "")
                })

        return {"available": True, "runs": runs, "failed_checks": all_failed}

    except Exception as e:
        logger.error(f"Failed to load Agent 2 data: {str(e)}")
        return {"available": False, "error": str(e)}


def load_agent3_data() -> dict:
    try:
        df = execute_query(f"""
            SELECT
                SUBSTRING_INDEX(target_fully_qualified_name, '.', -1) AS target_table,
                target_fully_qualified_name,
                overall_status,
                total_checks_run, total_checks_passed,
                total_checks_warned, total_checks_critical,
                ai_failure_category,
                ROUND(ai_confidence_score, 2) AS ai_confidence,
                ai_summary, ai_recommended_action,
                check_results, business_date, review_timestamp
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY transformation_id
                        ORDER BY
                            CASE overall_status
                                WHEN 'CRITICAL' THEN 1
                                WHEN 'WARNING'  THEN 2
                                WHEN 'PASS'     THEN 3
                                ELSE 4
                            END,
                            review_timestamp DESC
                    ) AS rn
                FROM {CATALOG}.{SCHEMA}.uc3_review_results_b
            )
            WHERE rn = 1
            ORDER BY review_timestamp DESC
            LIMIT 10
        """)

        if df.empty:
            return {"available": False, "reviews": []}

        reviews = []
        for _, row in df.iterrows():
            failed_check_names = []
            try:
                cr = json.loads(str(row.get("check_results") or "[]"))
                failed_check_names = [
                    c.get("check_name", "")
                    for c in cr
                    if c.get("check_status") in ("CRITICAL", "WARNING")
                ]
            except Exception:
                pass

            bd_raw = row.get("business_date")
            bdate  = str(bd_raw)[:10] if bd_raw is not None else ""

            reviews.append({
                "target_table"         : str(row.get("target_table", "")),
                "overall_status"       : str(row.get("overall_status", "")),
                "total_checks_critical": int(row.get("total_checks_critical") or 0),
                "total_checks_warned"  : int(row.get("total_checks_warned") or 0),
                "ai_failure_category"  : str(row.get("ai_failure_category") or ""),
                "ai_confidence"        : float(row.get("ai_confidence") or 0),
                "ai_summary"           : str(row.get("ai_summary") or ""),
                "ai_recommended_action": str(row.get("ai_recommended_action") or ""),
                "failed_check_names"   : failed_check_names,
                "business_date"        : bdate,
                "review_timestamp"     : str(row.get("review_timestamp", "")),
                "check_results_raw"    : str(row.get("check_results") or "[]"),
            })

        return {"available": True, "reviews": reviews}

    except Exception as e:
        logger.error(f"Failed to load Agent 3 data: {str(e)}")
        return {"available": False, "error": str(e)}


def load_agent4_data(business_date: str) -> dict:
    try:
        runs_df = execute_query(f"""
            SELECT
                validation_run_id,
                SUBSTRING_INDEX(gold_fully_qualified_name, '.', -1) AS gold_table,
                gold_fully_qualified_name,
                overall_status,
                total_kpis_checked, total_kpis_passed,
                total_kpis_warned, total_kpis_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true THEN 'YES' ELSE 'NO' END AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date = :business_date
            ORDER BY gold_fully_qualified_name
        """, {"business_date": business_date})

        if runs_df.empty:
            return {"available": False, "runs": [], "failed_kpis": []}

        runs       = []
        all_failed = []

        for _, run in runs_df.iterrows():
            run_id   = run["validation_run_id"]
            run_dict = {
                "gold_table"              : str(run.get("gold_table", "")),
                "gold_fully_qualified_name": str(run.get("gold_fully_qualified_name", "")),
                "overall_status"          : str(run.get("overall_status", "")),
                "total_kpis_checked"      : int(run.get("total_kpis_checked") or 0),
                "total_kpis_passed"       : int(run.get("total_kpis_passed") or 0),
                "total_kpis_warned"       : int(run.get("total_kpis_warned") or 0),
                "total_kpis_critical"     : int(run.get("total_kpis_critical") or 0),
                "ai_enrichment_status"    : str(run.get("ai_enrichment_status", "")),
                "alert_sent"              : str(run.get("alert_sent", "NO"))
            }
            runs.append(run_dict)

            failed_df = execute_query(f"""
                SELECT
                    kpi_name, kpi_column, check_type, check_status,
                    ROUND(observed_value, 4)       AS observed_value,
                    ROUND(expected_value, 4)       AS expected_value,
                    ROUND(deviation_percentage, 2) AS deviation_pct,
                    threshold_warning, threshold_critical,
                    ai_summary, ai_failure_category
                FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
                WHERE validation_run_id = :run_id
                  AND check_status IN ('CRITICAL', 'WARNING')
                ORDER BY
                    CASE check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                    kpi_name, check_type
            """, {"run_id": run_id})

            for _, kpi in failed_df.iterrows():
                all_failed.append({
                    "gold_table"    : run_dict["gold_table"],
                    "kpi_name"      : str(kpi.get("kpi_name", "")),
                    "kpi_column"    : str(kpi.get("kpi_column", "")),
                    "check_type"    : str(kpi.get("check_type", "")),
                    "check_status"  : str(kpi.get("check_status", "")),
                    "observed_value": float(kpi.get("observed_value") or 0),
                    "expected_value": float(kpi.get("expected_value") or 0),
                    "deviation_pct" : float(kpi.get("deviation_pct") or 0),
                    "ai_summary"    : str(kpi.get("ai_summary") or ""),
                    "ai_category"   : str(kpi.get("ai_failure_category") or "")
                })

        return {"available": True, "runs": runs, "failed_kpis": all_failed}

    except Exception as e:
        logger.error(f"Failed to load Agent 4 data: {str(e)}")
        return {"available": False, "error": str(e)}


# ── Summary section ────────────────────────────────────────────────────────

def build_summary_section(
    business_date: str,
    a1: dict, a2: dict, a3: dict, a4: dict
) -> html.Div:

    def status_badge(status):
        color = (
            "danger"    if status == "CRITICAL"
            else "warning" if status == "WARNING"
            else "success" if status == "PASS"
            else "secondary"
        )
        emoji = (
            "🔴" if status == "CRITICAL"
            else "🟡" if status == "WARNING"
            else "🟢" if status == "PASS"
            else "⚪"
        )
        return dbc.Badge(f"{emoji} {status}", color=color, className="ms-1")

    def agent_card(agent_label, icon, description, runs_info, available, border_color):
        body = (
            html.Div(runs_info)
            if available
            else dbc.Alert("No data for this date.", color="secondary", className="mb-0 small")
        )
        return dbc.Card([
            dbc.CardHeader(
                html.H6(f"{icon} {agent_label}", className="mb-0 text-white"),
                style={"backgroundColor": border_color}
            ),
            dbc.CardBody([
                html.P(description, className="text-muted small mb-2"),
                body
            ])
        ], style={"backgroundColor": "#2b2b2b", "border": f"1px solid {border_color}"})

    a1_runs_info = html.Div([
        html.Div([
            html.Span(r["table_name"], className="small text-white me-2"),
            status_badge(r["overall_status"]),
            html.Span(
                f"  {r['total_checks_critical']}C {r['total_checks_warned']}W",
                className="small text-muted ms-2"
            )
        ], className="mb-1")
        for r in a1["runs"]
    ]) if a1.get("available") else None

    a2_runs_info = html.Div([
        html.Div([
            html.Span(r["table_name"], className="small text-white me-2"),
            status_badge(r["overall_status"]),
            html.Span(
                f"  {r['total_checks_critical']}C {r['total_checks_warned']}W",
                className="small text-muted ms-2"
            )
        ], className="mb-1")
        for r in a2["runs"]
    ]) if a2.get("available") else None

    a3_runs_info = html.Div([
        html.Div([
            html.Span(r["target_table"], className="small text-white me-2"),
            status_badge(r["overall_status"]),
            html.Span(f"  {r['review_timestamp'][:10]}", className="small text-muted ms-2")
        ], className="mb-1")
        for r in a3["reviews"][:4]
    ]) if a3.get("available") else None

    a4_runs_info = html.Div([
        html.Div([
            html.Span(r["gold_table"], className="small text-white me-2"),
            status_badge(r["overall_status"]),
            html.Span(
                f"  {r['total_kpis_critical']}C {r['total_kpis_warned']}W",
                className="small text-muted ms-2"
            )
        ], className="mb-1")
        for r in a4["runs"]
    ]) if a4.get("available") else None

    return html.Div([
        html.H5(f"📊 Data Summary for {business_date}", className="mb-3 text-white"),
        dbc.Row([
            dbc.Col(agent_card("Validation Agent", "🔍", "Raw ingestion validation",
                               a1_runs_info, a1.get("available", False), "#375a7f"), md=3),
            dbc.Col(agent_card("Reconciliation Agent", "🔄", "Cross-layer reconciliation",
                               a2_runs_info, a2.get("available", False), "#2d6a4f"), md=3),
            dbc.Col(agent_card("Transformation Agent", "🧪", "Silver SQL review (latest)",
                               a3_runs_info, a3.get("available", False), "#6b3a7d"), md=3),
            dbc.Col(agent_card("KPI Assurance Agent", "📊", "Gold KPI validation",
                               a4_runs_info, a4.get("available", False), "#7d4a1a"), md=3),
        ], className="mb-4")
    ])


# ── Prompt builder ─────────────────────────────────────────────────────────

def build_insights_prompt(
    business_date: str,
    a1: dict, a2: dict, a3: dict, a4: dict
) -> str:

    a1_text = "NOT RUN for this date.\n"
    if a1.get("available"):
        a1_text = ""
        for run in a1["runs"]:
            a1_text += (
                f"  Table: {run['table_name']}\n"
                f"  Status: {run['overall_status']}\n"
                f"  Checks: {run['total_checks_run']} run, "
                f"{run['total_checks_critical']} CRITICAL, "
                f"{run['total_checks_warned']} WARNING\n\n"
            )
        if a1["failed_checks"]:
            a1_text += "  Failed checks (all):\n"
            for chk in a1["failed_checks"]:
                a1_text += (
                    f"    [{chk['check_status']}] "
                    f"{chk['table_name']} — "
                    f"{chk['check_type']} on {chk['column_name']}: "
                    f"observed {round(chk['observed_value'], 2)}, "
                    f"deviation {round(chk['deviation_pct'], 1)}%\n"
                )
        else:
            a1_text += "  No failed checks.\n"

    a2_text = "NOT RUN for this date.\n"
    if a2.get("available"):
        a2_text = ""
        for run in a2["runs"]:
            a2_text += (
                f"  Table: {run['table_name']}\n"
                f"  Status: {run['overall_status']}\n"
                f"  Checks: {run['total_checks_run']} run, "
                f"{run['total_checks_critical']} CRITICAL, "
                f"{run['total_checks_warned']} WARNING\n\n"
            )
        if a2["failed_checks"]:
            a2_text += "  Failed reconciliation checks (all):\n"
            sorted_checks = sorted(
                a2["failed_checks"],
                key=lambda x: (
                    0 if x["check_status"] == "CRITICAL" else 1,
                    0 if "ROW_COUNT" in x["check_type"] else 1
                )
            )
            for chk in sorted_checks:
                a2_text += (
                    f"    [{chk['check_status']}] "
                    f"{chk['table_name']} — "
                    f"{chk['from_layer']}→{chk['to_layer']} "
                    f"{chk['check_type']} ({chk['metric_name']}): "
                    f"source={round(chk['source_value'], 0)}, "
                    f"target={round(chk['target_value'], 0)}, "
                    f"deviation={round(chk['deviation_pct'], 1)}%\n"
                )
        else:
            a2_text += "  No failed reconciliation checks.\n"

    a3_text = "NOT AVAILABLE.\n"
    if a3.get("available"):
        a3_text = "Note: Transformation Agent runs code reviews — not date-specific. Latest reviews:\n"
        for rev in a3["reviews"][:4]:
            a3_text += (
                f"  [{rev['overall_status']}] "
                f"{rev['target_table']}: "
                f"{rev['total_checks_critical']} CRITICAL, "
                f"{rev['total_checks_warned']} WARNING"
            )
            if rev["failed_check_names"]:
                a3_text += f" — Failed: {', '.join(rev['failed_check_names'])}"
            if rev["ai_failure_category"]:
                a3_text += f" — AI: {rev['ai_failure_category']}"
            try:
                cr = json.loads(rev.get("check_results_raw", "[]") or "[]")
                for c in cr:
                    if c.get("check_name") == "ROW_COUNT_RATIO":
                        actual   = c.get("actual_survival")
                        expected = c.get("expected_survival")
                        src      = c.get("source_count")
                        tgt      = c.get("target_count")
                        bd       = c.get("business_date", "")
                        if actual is not None and expected is not None:
                            a3_text += (
                                f"\n    ROW_COUNT_RATIO: "
                                f"{src}→{tgt} rows "
                                f"({float(actual)*100:.1f}% survival "
                                f"vs {float(expected)*100:.1f}% expected)"
                                f" for date {bd}"
                            )
                        break
            except Exception:
                pass
            a3_text += "\n"

    a4_text = "NOT RUN for this date.\n"
    if a4.get("available"):
        a4_text = ""
        for run in a4["runs"]:
            a4_text += (
                f"  Gold Table: {run['gold_table']}\n"
                f"  Status: {run['overall_status']}\n"
                f"  KPIs: {run['total_kpis_checked']} checked, "
                f"{run['total_kpis_critical']} CRITICAL, "
                f"{run['total_kpis_warned']} WARNING\n\n"
            )
        if a4["failed_kpis"]:
            a4_text += "  Failed KPI checks (all):\n"
            for kpi in a4["failed_kpis"]:
                a4_text += (
                    f"    [{kpi['check_status']}] "
                    f"{kpi['gold_table']} — "
                    f"{kpi['kpi_name']} ({kpi['check_type']}): "
                    f"observed={round(kpi['observed_value'], 4)}, "
                    f"expected={round(kpi['expected_value'], 4)}, "
                    f"deviation={round(kpi['deviation_pct'], 1)}%\n"
                )
        else:
            a4_text += "  No failed KPI checks.\n"

    any_critical = (
        (a1.get("available") and any(r["total_checks_critical"] > 0 for r in a1.get("runs", [])))
        or (a2.get("available") and any(r["total_checks_critical"] > 0 for r in a2.get("runs", [])))
        or (a4.get("available") and any(r["total_kpis_critical"] > 0 for r in a4.get("runs", [])))
    )
    severity = "CRITICAL" if any_critical else "WARNING OR LOWER"

    key_findings = []

    if a2.get("available"):
        for chk in a2.get("failed_checks", []):
            if "ROW_COUNT" in chk.get("check_type", ""):
                src = int(chk["source_value"])
                tgt = int(chk["target_value"])
                dev = round(abs(chk["deviation_pct"]), 1)
                key_findings.append(
                    f"CRITICAL FINDING: Silver received only {tgt} of "
                    f"{src} raw records ({dev}% below expected survival rate). "
                    f"This is the primary cascade mechanism."
                )
                break

    if a3.get("available"):
        for rev in a3.get("reviews", []):
            if rev.get("overall_status") == "CRITICAL":
                try:
                    cr = json.loads(rev.get("check_results_raw", "[]") or "[]")
                    for c in cr:
                        if c.get("check_name") == "ROW_COUNT_RATIO":
                            actual   = c.get("actual_survival")
                            expected = c.get("expected_survival")
                            if actual and expected:
                                key_findings.append(
                                    f"AGENT 3 CONFIRMATION: Independent code review "
                                    f"confirmed {rev['target_table']} survival rate "
                                    f"at {float(actual)*100:.1f}% vs "
                                    f"{float(expected)*100:.1f}% expected — "
                                    f"classified as {rev.get('ai_failure_category', 'DATA_QUALITY_RISK')}."
                                )
                            break
                except Exception:
                    key_findings.append(
                        f"AGENT 3 CONFIRMATION: Independent code review "
                        f"confirmed {rev['target_table']} ROW_COUNT_RATIO CRITICAL."
                    )
                break

    if a4.get("available") and a4.get("failed_kpis"):
        largest = max(
            a4["failed_kpis"],
            key=lambda x: abs(x.get("deviation_pct") or 0)
        )
        key_findings.append(
            f"KEY KPI ANOMALY: {largest['kpi_name']} in "
            f"{largest['gold_table']} deviated "
            f"{round(abs(largest['deviation_pct']), 1)}% from baseline "
            f"(observed {round(largest['observed_value'], 4)} "
            f"vs expected {round(largest['expected_value'], 4)})."
        )

    key_findings_text = (
        "\n".join(f"  {i+1}. {f}" for i, f in enumerate(key_findings))
        if key_findings
        else "  No key findings pre-computed."
    )

    return f"""You are a senior data engineering lead analysing
the daily data quality report for a retail data platform.

BUSINESS DATE BEING ANALYSED: {business_date}
OVERALL SEVERITY: {severity}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALIDATION AGENT — RAW INGESTION VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{a1_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECONCILIATION AGENT — CROSS-LAYER RECONCILIATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{a2_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSFORMATION AGENT — SILVER TRANSFORMATION CODE REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{a3_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KPI ASSURANCE AGENT — GOLD KPI VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{a4_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRE-COMPUTED KEY FINDINGS
(You MUST reference all of these in your response)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{key_findings_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Write a concise data quality incident narrative for {business_date}.

MANDATORY REQUIREMENTS:

executive_summary:
  - 2-3 sentences only
  - Name the specific tables that failed
  - Include at least 2 specific deviation percentages from the evidence
  - Mention which layers were affected (raw, silver, gold)

what_went_wrong:
  - One bullet point per failed check
  - Format each bullet as: "<Agent Name>: table — check_type: numbers"
  - Do NOT summarise or group items — list each one separately

root_cause:
  - MUST name the Silver survival rate by number
  - Identify which layer the problem originated in
  - Explain the cascade mechanism in one sentence

cross_agent_correlation:
  - MUST mention all four agents by name
  - Explain how the Transformation Agent independently confirmed the Reconciliation Agent finding
  - Trace the cascade from the Validation Agent through to the KPI Assurance Agent

recommended_actions:
  - Numbered list of 4-5 specific actions
  - Reference specific table names from the evidence
  - Actions must be in pipeline order (raw → silver → gold)

watch_tomorrow:
  - 1-2 sentences
  - Name specific metrics and tables to monitor
  - Include a specific threshold

Respond with a JSON object with exactly these six string fields.
ALL six field values must be plain strings — never lists or objects.

{{
  "executive_summary"      : "...",
  "what_went_wrong"        : "...",
  "root_cause"             : "...",
  "cross_agent_correlation": "...",
  "recommended_actions"    : "...",
  "watch_tomorrow"         : "..."
}}

Respond with valid JSON only. No markdown. No text outside the JSON.
"""


# ── Model response extractor ───────────────────────────────────────────────

def extract_content(response_data: dict) -> str:
    choices = response_data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts     = []
        reasoning_text = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
            elif block_type == "reasoning":
                for s in block.get("summary", []):
                    if isinstance(s, dict):
                        t = s.get("text", "")
                        if t:
                            reasoning_text.append(t)
        if text_parts:
            return " ".join(text_parts)
        if reasoning_text:
            return " ".join(reasoning_text)
    return choices[0].get("text", "")


# ── Section card ───────────────────────────────────────────────────────────

def section_card(icon, title, content, border_color, text_color="#ffffff"):
    if content is None:
        content = "Not available."
    elif isinstance(content, list):
        content = "\n".join(str(item) for item in content if item)
    elif isinstance(content, dict):
        content = "\n".join(f"{k}: {v}" for k, v in content.items())
    else:
        content = str(content).strip() or "Not available."

    content = content.replace("\\n-", "\n-")
    content = content.replace("\\n•", "\n•")
    content = content.replace("\\n", "\n")

    lines            = content.strip().split("\n")
    content_elements = []

    for line in lines:
        line = line.strip()
        if not line:
            content_elements.append(html.Br())
        elif line.startswith("-") or line.startswith("•"):
            content_elements.append(
                html.Li(
                    line.lstrip("-•\\n").strip(),
                    style={"color": text_color, "marginBottom": "4px"}
                )
            )
        elif len(line) > 1 and line[0].isdigit() and line[1] in (".", ")"):
            content_elements.append(
                html.Li(
                    line[2:].strip(),
                    style={"color": text_color, "marginBottom": "4px"}
                )
            )
        else:
            content_elements.append(
                html.P(line, className="mb-1", style={"color": text_color})
            )

    has_list = any(isinstance(e, html.Li) for e in content_elements)
    if has_list:
        final_content = []
        list_items    = []
        for e in content_elements:
            if isinstance(e, html.Li):
                list_items.append(e)
            else:
                if list_items:
                    final_content.append(html.Ul(list_items, className="ps-3 mb-2"))
                    list_items = []
                if not isinstance(e, html.Br):
                    final_content.append(e)
        if list_items:
            final_content.append(html.Ul(list_items, className="ps-3 mb-2"))
    else:
        final_content = [e for e in content_elements if not isinstance(e, html.Br)]

    return dbc.Card([
        dbc.CardHeader(
            html.H5(f"{icon} {title}", className="mb-0 text-white"),
            style={"backgroundColor": border_color}
        ),
        dbc.CardBody(final_content)
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": f"1px solid {border_color}"})


# ── Phrase extractor ───────────────────────────────────────────────────────

def _extract_phrase_around_match(text, match_pos, window=7):
    """
    Extracts words around a percentage match.
    Takes more words after the match than before,
    since the description usually follows the number.
    """
    words      = text.split()
    char_count = 0
    match_word = 0

    for i, word in enumerate(words):
        char_count += len(word) + 1
        if char_count >= match_pos:
            match_word = i
            break

    # Take 3 words before and 10 words after
    # "failed with an 87.4% volume anomaly in the raw layer"
    # ← 3 before →  ↑    ← 10 after                      →
    start  = max(0, match_word - 3)
    end    = min(len(words), match_word + 11)
    phrase = " ".join(words[start:end]).strip()
    phrase = re.sub(r'^[^A-Za-z0-9£$€]+', '', phrase)
    phrase = re.sub(r'[,;:]+$', '', phrase).strip()
    return phrase


# ── Executive summary renderer ─────────────────────────────────────────────

def _render_executive_summary(
    text          : str,
    business_date : str,
    gold_tables   : list = None,
    overall_status: str  = None,
) -> html.Div:
    """
    Renders the executive summary in a structured scannable format.

    Severity is driven by overall_status from agent data (authoritative).
    Falls back to text keyword detection if overall_status not provided.
    Top 2 deviations by magnitude are extracted using phrase-level context.
    Table names come from AI text + Gold tables from A4 evidence.
    """

    if not text or not text.strip():
        return html.P(
            "No executive summary available.",
            style={"color": "#aaaaaa", "fontSize": "15px"}
        )

    text_lower = text.lower()

    # ── Severity ───────────────────────────────────────────────────────────
    # overall_status from agent data is the authoritative source.
    # The AI text may not always say "critical" even when the platform
    # status is CRITICAL — so we check agent data first.

    if overall_status == "CRITICAL" or "critical" in text_lower:
        severity        = "CRITICAL"
        severity_color  = "#ff6b6b"
        severity_bg     = "#3d0000"
        severity_border = "#ff6b6b"
        severity_emoji  = "🔴"
    elif overall_status == "WARNING" or "warning" in text_lower:
        severity        = "WARNING"
        severity_color  = "#ffa500"
        severity_bg     = "#3d2000"
        severity_border = "#ffa500"
        severity_emoji  = "🟡"
    elif overall_status == "PASS":
        severity        = "PASS"
        severity_color  = "#00c851"
        severity_bg     = "#002800"
        severity_border = "#00c851"
        severity_emoji  = "🟢"
    else:
        severity        = "DETECTED"
        severity_color  = "#4a9edd"
        severity_bg     = "#0f2035"
        severity_border = "#4a9edd"
        severity_emoji  = "🔵"

    # ── Layers affected ────────────────────────────────────────────────────
    layers_found = []
    for layer in ["raw", "silver", "gold"]:
        if layer in text_lower:
            layers_found.append(layer.upper())

    seen_layers   = set()
    layers_unique = []
    for l in layers_found:
        if l not in seen_layers:
            seen_layers.add(l)
            layers_unique.append(l)

    # ── Deviation percentages ──────────────────────────────────────────────
    # Use phrase-level extraction so each percentage gets its own
    # local context even when multiple percentages share a sentence.
    # Cap at top 2 by magnitude — prevents cross-date Agent 3
    # contamination from appearing in the panel.

    deviation_pattern = re.compile(r'([+-]?\d+\.?\d*)\s*%')
    all_deviations    = []

    for match in deviation_pattern.finditer(text):
        try:
            val = float(match.group(1))
            # Only include meaningful deviations — ignore small
            # threshold values and config percentages
            if abs(val) >= 10.0:
                phrase = _extract_phrase_around_match(
                    text, match.start(), window=7
                )
                all_deviations.append({
                    "value"  : match.group(1),
                    "abs_val": abs(val),
                    "context": phrase,
                })
        except (ValueError, TypeError):
            pass

    # Sort by magnitude — largest first
    all_deviations.sort(key=lambda x: x["abs_val"], reverse=True)

    # Deduplicate by value, keep only top 2
    seen_vals   = set()
    unique_devs = []
    for d in all_deviations:
        if d["value"] not in seen_vals:
            seen_vals.add(d["value"])
            unique_devs.append(d)
        if len(unique_devs) == 2:
            break

    # ── Table names ────────────────────────────────────────────────────────
    # First pass: regex on AI text for explicitly named tables
    table_pattern = re.compile(r'uc[124]_[a-z_]+')
    tables_found  = list(dict.fromkeys(table_pattern.findall(text_lower)))

    # Second pass: supplement with Gold tables from A4 evidence
    # These come directly from uc4_kpi_validation_run_b — no inference,
    # no hardcoding, straight from the database
    if gold_tables:
        for fqn in gold_tables:
            table_short = fqn.split(".")[-1].lower()
            if table_short not in tables_found:
                tables_found.append(table_short)

    # ── What happened ──────────────────────────────────────────────────────
    sentences_clean = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', text.strip())
        if s.strip() and len(s.strip()) > 20
    ]

    what_happened = sentences_clean[0] if sentences_clean else text.strip()

    # If the first sentence is generic (no numbers, no table names),
    # construct a more specific one from the extracted deviations
    has_numbers = bool(re.search(r'\d+', what_happened))
    has_tables  = bool(re.search(r'uc[124]_', what_happened.lower()))

    if not has_numbers and not has_tables and unique_devs:
        top_dev       = unique_devs[0]
        what_happened = (
            f"On {business_date}, {severity.lower()} data quality issues "
            f"were detected with a {top_dev['value']}% deviation from "
            f"expected values affecting "
            f"{len(layers_unique)} pipeline layer"
            f"{'s' if len(layers_unique) != 1 else ''}."
        )

    # ── Build layout ───────────────────────────────────────────────────────

    elements = []

    # ── Severity banner ────────────────────────────────────────────────────
    elements.append(
        html.Div([
            html.Span(
                f"{severity_emoji}  {severity}",
                style={
                    "color"      : severity_color,
                    "fontSize"   : "18px",
                    "fontWeight" : "800",
                    "marginRight": "16px",
                }
            ),
            html.Span(
                f"Business Date: {business_date}",
                style={
                    "color"   : "#aaaaaa",
                    "fontSize": "13px",
                }
            ),
            html.Span(
                f"  ·  {len(layers_unique)} layer"
                f"{'s' if len(layers_unique) != 1 else ''} affected"
                if layers_unique else "",
                style={
                    "color"   : "#666666",
                    "fontSize": "13px",
                }
            ),
        ], style={"marginBottom": "16px"})
    )

    # ── What happened ──────────────────────────────────────────────────────
    elements.append(
        html.Div([
            html.Span(
                "What happened",
                style={
                    "color"        : "#64748b",
                    "fontSize"     : "11px",
                    "fontWeight"   : "700",
                    "textTransform": "uppercase",
                    "letterSpacing": "1px",
                    "display"      : "block",
                    "marginBottom" : "6px",
                }
            ),
            html.P(
                what_happened,
                style={
                    "color"       : "#ffffff",
                    "fontSize"    : "15px",
                    "lineHeight"  : "1.5",
                    "marginBottom": "0",
                }
            ),
        ], style={"marginBottom": "20px"})
    )

    # ── Key deviations ─────────────────────────────────────────────────────
    if unique_devs:
        dev_items = []
        for idx, d in enumerate(unique_devs):
            try:
                val   = float(d["value"])
                color = (
                    "#ff6b6b" if abs(val) >= 40
                    else "#ffa500" if abs(val) >= 20
                    else "#4a9edd"
                )
            except (ValueError, TypeError):
                color = "#4a9edd"
                val   = 0

            # Position 0 = largest deviation = always pipeline/volume issue
            # Position 1 = second largest = always business/KPI impact
            if val >= 100:
                label = "Pipeline produced zero rows"
            elif idx == 0:
                label = "Volume shortfall"
            else:
                context_lower = d["context"].lower()
                if "net_amount" in context_lower or "total_net" in context_lower or "revenue" in context_lower:
                    label = "Net revenue deviation"
                elif "survival" in context_lower:
                    label = "Silver survival rate"
                elif "basket" in context_lower:
                    label = "Avg basket deviation"
                elif "return" in context_lower:
                    label = "Return rate deviation"
                elif "quantity" in context_lower:
                    label = "Quantity deviation"
                elif "kpi" in context_lower or "anomaly" in context_lower:
                    label = "KPI deviation"
                else:
                    label = "Business impact deviation"

            dev_items.append(
                dbc.Col([
                    html.Div(
                        f"{d['value']}%",
                        style={
                            "color"     : color,
                            "fontSize"  : "32px",
                            "fontWeight": "800",
                            "lineHeight": "1",
                            "fontFamily": "monospace",
                        }
                    ),
                    html.Div(
                        label,
                        style={
                            "color"     : color,
                            "fontSize"  : "12px",
                            "marginTop" : "6px",
                            "lineHeight": "1.3",
                            "fontWeight": "500",
                        }
                    ),
                ], style={
                    "borderLeft"  : f"3px solid {color}",
                    "paddingLeft" : "14px",
                    "marginBottom": "8px",
                })
            )

        elements.append(
            html.Div([
                html.Span(
                    "Key deviations",
                    style={
                        "color"        : "#64748b",
                        "fontSize"     : "11px",
                        "fontWeight"   : "700",
                        "textTransform": "uppercase",
                        "letterSpacing": "1px",
                        "display"      : "block",
                        "marginBottom" : "12px",
                    }
                ),
                dbc.Row(dev_items, className="g-3"),
            ], style={"marginBottom": "20px"})
        )

    # ── Layers affected ────────────────────────────────────────────────────
    if layers_unique:
        layer_colors = {
            "BRONZE": "#375a7f",
            "SILVER": "#2d6a4f",
            "GOLD"  : "#7d4a1a",
        }
        layer_pills = []
        for i, layer in enumerate(layers_unique):
            layer_pills.append(
                html.Span(
                    layer,
                    style={
                        "backgroundColor": layer_colors.get(layer, "#333"),
                        "color"          : "#ffffff",
                        "fontSize"       : "12px",
                        "fontWeight"     : "700",
                        "padding"        : "4px 12px",
                        "borderRadius"   : "12px",
                        "marginRight"    : "4px",
                        "fontFamily"     : "monospace",
                    }
                )
            )
            if i < len(layers_unique) - 1:
                layer_pills.append(
                    html.Span(
                        " → ",
                        style={
                            "color"     : "#444444",
                            "fontSize"  : "14px",
                            "fontWeight": "700",
                        }
                    )
                )

        elements.append(
            html.Div([
                html.Span(
                    "Layers affected",
                    style={
                        "color"        : "#64748b",
                        "fontSize"     : "11px",
                        "fontWeight"   : "700",
                        "textTransform": "uppercase",
                        "letterSpacing": "1px",
                        "display"      : "block",
                        "marginBottom" : "8px",
                    }
                ),
                html.Div(layer_pills),
            ], style={"marginBottom": "20px"})
        )

    # ── Tables involved ────────────────────────────────────────────────────
    if tables_found:
        elements.append(
            html.Div([
                html.Span(
                    "Tables involved",
                    style={
                        "color"        : "#64748b",
                        "fontSize"     : "11px",
                        "fontWeight"   : "700",
                        "textTransform": "uppercase",
                        "letterSpacing": "1px",
                        "display"      : "block",
                        "marginBottom" : "8px",
                    }
                ),
                html.Div([
                    html.Span(
                        t,
                        style={
                            "backgroundColor": "#0a1520",
                            "color"          : "#4a9edd",
                            "fontSize"       : "11px",
                            "padding"        : "3px 8px",
                            "borderRadius"   : "4px",
                            "marginRight"    : "6px",
                            "marginBottom"   : "4px",
                            "display"        : "inline-block",
                            "fontFamily"     : "monospace",
                            "border"         : "1px solid #1e3a5f",
                        }
                    )
                    for t in tables_found[:6]
                ])
            ])
        )

    return html.Div(
        elements,
        style={
            "backgroundColor": severity_bg,
            "border"         : f"1px solid {severity_border}",
            "borderRadius"   : "8px",
            "padding"        : "20px 24px",
        }
    )


# ── Narrative renderer ─────────────────────────────────────────────────────

def render_narrative(
    parsed        : dict,
    business_date : str,
    gold_tables   : list = None,
    overall_status: str  = None,
) -> html.Div:
    """
    Renders the parsed AI narrative as a structured UI.
    Executive summary uses structured renderer.
    All other sections use section_card.
    """

    def safe_str(val):
        if val is None:
            return "Not available."
        if isinstance(val, list):
            return "\n".join(str(item) for item in val if item)
        if isinstance(val, dict):
            return "\n".join(f"{k}: {v}" for k, v in val.items())
        return str(val).strip() or "Not available."

    executive_summary       = safe_str(parsed.get("executive_summary"))
    what_went_wrong         = safe_str(parsed.get("what_went_wrong"))
    root_cause              = safe_str(parsed.get("root_cause"))
    cross_agent_correlation = safe_str(parsed.get("cross_agent_correlation"))
    recommended_actions     = safe_str(parsed.get("recommended_actions"))
    watch_tomorrow          = safe_str(parsed.get("watch_tomorrow"))

    return html.Div([

        dbc.Alert([
            html.H4(f"🤖 AI Pipeline Narrative — {business_date}", className="mb-1"),
            html.P(
                "Generated by databricks-gpt-oss-20b based on "
                "live data from all four validation agents.",
                className="mb-0 small"
            )
        ], color="dark", className="mb-4"),

        html.Div([
            html.H5(
                "📋 Executive Summary",
                style={"color": "#ffffff", "fontSize": "16px",
                       "fontWeight": "600", "marginBottom": "12px"}
            ),
            _render_executive_summary(
                executive_summary,
                business_date,
                gold_tables=gold_tables or [],
                overall_status = overall_status,
            ),
        ], className="mb-4"),

        section_card("❌", "What Went Wrong",     what_went_wrong,         "#5a0000", "#ffcccc"),
        section_card("🔍", "Root Cause",          root_cause,              "#5a3000", "#ffd9a0"),
        section_card("🔗", "Cross-Agent Correlation", cross_agent_correlation, "#2d6a4f"),
        section_card("✅", "Recommended Actions", recommended_actions,     "#1a5276", "#a9cce3"),
        section_card("👁", "Watch Tomorrow",      watch_tomorrow,          "#4a235a"),

        html.Hr(style={"borderColor": "#444"}),
        html.Small(
            f"Generated for business date {business_date}. "
            "This narrative is AI-generated from deterministic "
            "check results and should be reviewed by the "
            "data engineering team before acting.",
            className="text-muted"
        )
    ])


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("insights-alert",            "children"),
    Output("insights-summary-section",  "children"),
    Output("insights-narrative-section","children"),
    Input("generate-insights-btn",      "n_clicks"),
    State("insights-date-input",        "value"),
    prevent_initial_call=True
)
def generate_insights(n_clicks, business_date):
    if not n_clicks:
        return "", html.Div(), html.Div()

    # ── Validate date ──────────────────────────────────────────────────────
    if not business_date or not business_date.strip():
        return (
            error_alert("Please enter a business date."),
            html.Div(),
            html.Div()
        )

    business_date = business_date.strip()

    try:
        from datetime import datetime
        datetime.strptime(business_date, "%Y-%m-%d")
    except ValueError:
        return (
            error_alert(
                "Invalid date format. Please use YYYY-MM-DD "
                "e.g. 2026-06-21"
            ),
            html.Div(),
            html.Div()
        )

    # ── Load agent data ────────────────────────────────────────────────────
    a1 = load_agent1_data(business_date)
    a2 = load_agent2_data(business_date)
    a3 = load_agent3_data()
    a4 = load_agent4_data(business_date)

    any_data = (
        a1.get("available") or
        a2.get("available") or
        a3.get("available") or
        a4.get("available")
    )

    if not any_data:
        return (
            "",
            html.Div(),
            dbc.Alert(
                f"No validation data found for {business_date}. "
                "Check that the agents have been run for this date.",
                color="warning"
            )
        )

    # ── Compute overall status from agent data ─────────────────────────────
    # Used by _render_executive_summary as the authoritative severity source.
    # The AI text may not always say "critical" even when status is CRITICAL.
    any_critical = (
        (a1.get("available") and
         any(r["total_checks_critical"] > 0
             for r in a1.get("runs", [])))
        or
        (a2.get("available") and
         any(r["total_checks_critical"] > 0
             for r in a2.get("runs", [])))
        or
        (a4.get("available") and
         any(r["total_kpis_critical"] > 0
             for r in a4.get("runs", [])))
    )
    any_warning = (
        (a1.get("available") and
         any(r["total_checks_warned"] > 0
             for r in a1.get("runs", [])))
        or
        (a2.get("available") and
         any(r["total_checks_warned"] > 0
             for r in a2.get("runs", [])))
        or
        (a4.get("available") and
         any(r["total_kpis_warned"] > 0
             for r in a4.get("runs", [])))
    )

    overall_status = (
        "CRITICAL" if any_critical
        else "WARNING" if any_warning
        else "PASS"
    )

    # ── Extract Gold table FQNs from A4 evidence ───────────────────────────
    # Used by _render_executive_summary to supplement table name extraction.
    # No hardcoding — straight from the database.
    gold_table_fqns = [
        run.get("gold_fully_qualified_name", "")
        for run in a4.get("runs", [])
        if run.get("gold_fully_qualified_name")
    ]

    # ── Build summary section ──────────────────────────────────────────────
    summary = build_summary_section(business_date, a1, a2, a3, a4)

    # ── Build prompt ───────────────────────────────────────────────────────
    prompt = build_insights_prompt(business_date, a1, a2, a3, a4)

    # ── Call AI model ──────────────────────────────────────────────────────
    try:
        import os
        workspace_host  = os.environ.get(
            "DATABRICKS_HOST", ""
        ).replace("https://", "")
        workspace_token = os.environ.get("DATABRICKS_TOKEN", "")

        if not workspace_host or not workspace_token:
            return (
                error_alert(
                    "DATABRICKS_HOST or DATABRICKS_TOKEN not set "
                    "in environment variables."
                ),
                summary,
                html.Div()
            )

        model_url = (
            f"https://{workspace_host}"
            f"/serving-endpoints/{MODEL_ENDPOINT}/invocations"
        )

        headers = {
            "Authorization": f"Bearer {workspace_token}",
            "Content-Type" : "application/json"
        }

        payload = {
            "messages": [
                {
                    "role"   : "system",
                    "content": (
                        "You are a senior data engineering lead "
                        "for a retail data platform. "
                        "Always respond with valid JSON only. "
                        "All field values must be plain strings — "
                        "never lists or nested objects. "
                        "Never include markdown or text outside the JSON."
                    )
                },
                {
                    "role"   : "user",
                    "content": prompt
                }
            ],
            "max_tokens" : MAX_TOKENS,
            "temperature": TEMPERATURE
        }

        response = requests.post(
            model_url,
            headers  = headers,
            json     = payload,
            timeout  = 180
        )

        if response.status_code != 200:
            return (
                error_alert(
                    f"AI model call failed: HTTP {response.status_code}"
                ),
                summary,
                dbc.Alert(
                    f"Model error: {response.text[:300]}",
                    color="danger"
                )
            )

        raw_content = extract_content(response.json())

        if not raw_content or not raw_content.strip():
            return (
                error_alert("AI returned empty response."),
                summary,
                html.Div()
            )

        # ── Parse JSON response ────────────────────────────────────────────
        content = raw_content.strip()

        if "```json" in content:
            content = content.split("```json")[1]
            if "```" in content:
                content = content.split("```")[0]
        elif "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]

        content = content.strip()
        start   = content.find("{")
        end     = content.rfind("}") + 1

        if start == -1:
            return (
                error_alert("Could not find JSON in AI response."),
                summary,
                dbc.Alert(
                    f"Raw response preview: {raw_content[:500]}",
                    color="warning"
                )
            )

        json_str = (
            content[start:] + '"}'
            if end == 0
            else content[start:end]
        )

        # ── Inner try: JSON parse with field-extraction fallback ───────────
        try:
            parsed = json.loads(json_str)

        except json.JSONDecodeError as je:
            logger.warning(
                f"JSON parse failed: {je}. "
                "Attempting field extraction."
            )

            def extract_field(raw_text: str, field_name: str) -> str:
                marker    = f'"{field_name}":'
                idx       = raw_text.find(marker)
                if idx == -1:
                    return ""
                val_start = raw_text.find('"', idx + len(marker))
                if val_start == -1:
                    return ""
                val_start += 1
                val_end   = val_start
                while val_end < len(raw_text):
                    if (raw_text[val_end] == '"'
                            and raw_text[val_end - 1] != '\\'):
                        break
                    val_end += 1
                return raw_text[val_start:val_end]

            raw_text = content[start:]
            parsed   = {
                "executive_summary"      : (
                    extract_field(raw_text, "executive_summary")
                    or "See raw agent data for details."
                ),
                "what_went_wrong"        : (
                    extract_field(raw_text, "what_went_wrong")
                    or "Response truncated. Check individual agent pages."
                ),
                "root_cause"             : (
                    extract_field(raw_text, "root_cause")
                    or "Response truncated."
                ),
                "cross_agent_correlation": (
                    extract_field(raw_text, "cross_agent_correlation")
                    or "Response truncated."
                ),
                "recommended_actions"    : (
                    extract_field(raw_text, "recommended_actions")
                    or "Check individual agent pages."
                ),
                "watch_tomorrow"         : (
                    extract_field(raw_text, "watch_tomorrow")
                    or "Monitor same tables on next pipeline run."
                )
            }

        # ── Render narrative ───────────────────────────────────────────────
        # parsed is guaranteed defined here — either from json.loads
        # or from the field-extraction fallback above.
        # render_narrative is inside the outer try block so any
        # rendering errors are caught by the outer except clauses.
        narrative = render_narrative(
            parsed,
            business_date,
            gold_tables    = gold_table_fqns,
            overall_status = overall_status,
        )
        return "", summary, narrative

    except requests.exceptions.Timeout:
        return (
            error_alert(
                "AI model timed out after 180 seconds. "
                "Please try again."
            ),
            summary,
            html.Div()
        )
    except Exception as e:
        logger.error(f"Failed to generate insights: {str(e)}")
        import traceback
        traceback.print_exc()
        return (
            error_alert(f"Unexpected error: {str(e)}"),
            summary,
            html.Div()
        )


@callback(
    Output("insights-date-input", "value"),
    Input("ai-insights-location", "search"),
    prevent_initial_call=False,
)
def prefill_date_from_url(search):
    if not search:
        return "2026-07-20"
    import urllib.parse
    params   = urllib.parse.parse_qs(search.lstrip("?"))
    date_val = params.get("date", ["2026-07-20"])[0]
    return date_val