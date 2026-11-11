# pages/sentinel_investigation.py

import dash
import re
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import pandas as pd
import math
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
import dash_ag_grid as dag
from components.alerts import ag_grid_props, AG_STATUS_CELL_STYLE_JS

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path = "/sentinel-investigation",
    name = "DataSentinel Investigation"
)

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

STATUS_COLOR = {
    "CRITICAL": "#ff6b6b",
    "WARNING" : "#ffa500",
    "PASS"    : "#00c851",
    "ERROR"   : "#888888",
}

STATUS_BG = {
    "CRITICAL": "#3d0000",
    "WARNING" : "#3d2000",
    "PASS"    : "#002800",
    "ERROR"   : "#1a1a1a",
}

STATUS_EMOJI = {
    "CRITICAL": "🔴",
    "WARNING" : "🟡",
    "PASS"    : "🟢",
    "ERROR"   : "⚫",
}

# ── Violation-rate check types ─────────────────────────────────────────────
# These checks measure a rate of bad records — always positive.
# All other checks use signed deviation (negative = drop).

UNSIGNED_CHECKS = {
    "FORMULA",
    "CROSS_KPI",
    "CATEGORICAL_DOMAIN",
    "SCHEMA_CONFORMANCE",
    "MALFORMED_RECORDS",
    "DUPLICATE_INGESTION",
    "NUMERIC_RANGE",
    "CROSS_COLUMN_CONSISTENCY",
}

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    dcc.Location(id="si-location", refresh=False),

    # ── Date selector ──────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Business Date",
                        className="text-white fw-bold"
                    ),
                    dcc.Dropdown(
                        id          = "si-date-dropdown",
                        options     = [],
                        value       = None,
                        clearable   = False,
                        placeholder = "Select a date...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                        }
                    ),
                ], md=5),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "View Investigation",
                        id        = "si-load-btn",
                        color     = "primary",
                        size      = "lg",
                        className = "d-block w-100",
                        n_clicks  = 0
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Alert(
                        "Shows what DataSentinel detected across "
                        "all three agents for the selected date.",
                        color     = "info",
                        className = "mb-0 small"
                    )
                ], md=4),
            ])
        ])
    ], className="mt-4 mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),

    html.Div(id="si-alert"),

    dbc.Spinner(
        html.Div(id="si-page-content"),
        color         = "primary",
        type          = "border",
        spinner_style = {"width": "3rem", "height": "3rem"}
    ),

], fluid=True)


# ── Text cleanup ───────────────────────────────────────────────────────────

def _clean_ai_text(text: str) -> str:
    """
    Cleans AI explanation text for display.

    1. Rounds numbers with more than 2 decimal places to 2
       e.g. 815.732174 → 815.73
    2. Adds thousands separators to large numbers
       e.g. 5483.11 → 5,483.11
    3. Converts decimal rate thresholds to percentages
       e.g. "maximum of 0.3" → "maximum of 30%"
    """
    if not text:
        return text

    def round_match(m):
        num_str = m.group(0)
        has_pct = num_str.endswith('%')
        clean   = num_str.rstrip('%')
        try:
            val = float(clean.replace(',', ''))
            if '.' in clean and len(clean.split('.')[1]) > 2:
                formatted = f"{val:,.2f}"
                return formatted + ('%' if has_pct else '')
            return num_str
        except (TypeError, ValueError):
            return num_str

    text = re.sub(r'[\d,]+\.\d{3,}%?', round_match, text)

    def convert_threshold(m):
        prefix = m.group(1)
        val    = float(m.group(2))
        if 0 < val < 1:
            return f"{prefix}{val * 100:.0f}%"
        return m.group(0)

    text = re.sub(
        r'((?:maximum|minimum|max|min) of )(0\.\d+)',
        convert_threshold,
        text,
        flags=re.IGNORECASE
    )

    return text


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _signed_deviation(
    observed   : float,
    baseline   : float,
    check_type : str,
    stored_dev : float,
) -> float:
    """
    Returns correctly-signed deviation percentage.

    For violation-rate checks (FORMULA, CATEGORICAL_DOMAIN etc):
      always positive — measures rate of bad records.

    For all other checks:
      negative when observed < baseline (a drop)
      positive when observed > baseline (a spike)
    """
    if stored_dev is None:
        return None

    if check_type.upper() in UNSIGNED_CHECKS:
        return abs(stored_dev)

    if observed is not None and baseline is not None and baseline != 0:
        if observed < baseline:
            return -abs(stored_dev)
        else:
            return abs(stored_dev)

    return stored_dev


def _fmt_deviation(dev: float, check_type: str) -> str:
    if dev is None:
        return "—"
    if check_type.upper() in UNSIGNED_CHECKS:
        return f"{abs(dev):+.2f}%"
    if dev > 0:
        return f"+{dev:.2f}%"
    return f"{dev:.2f}%"


def _status_pill(status: str) -> html.Span:
    color = STATUS_COLOR.get(status, "#888888")
    bg    = STATUS_BG.get(status, "#1a1a1a")
    emoji = STATUS_EMOJI.get(status, "⚪")
    return html.Span(
        f"{emoji} {status}",
        style={
            "backgroundColor": bg,
            "color"          : color,
            "border"         : f"1px solid {color}",
            "borderRadius"   : "12px",
            "padding"        : "3px 10px",
            "fontSize"       : "12px",
            "fontWeight"     : "700",
        }
    )


def _agent_header(
    icon      : str,
    agent_name: str,
    table_name: str,
    status    : str,
    checks_run: int,
    critical  : int,
    warned    : int,
    alert_sent: str,
) -> html.Div:
    status_color = STATUS_COLOR.get(status, "#888888")
    status_bg    = STATUS_BG.get(status, "#1a1a1a")

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Span(
                        f"{icon}  {agent_name}",
                        style={
                            "color"    : "#ffffff",
                            "fontSize" : "15px",
                            "fontWeight": "700",
                        }
                    ),
                    html.Span(
                        f"  ·  {table_name}",
                        style={
                            "color"     : "#64748b",
                            "fontSize"  : "13px",
                            "fontFamily": "monospace",
                        }
                    ),
                ]),
            ], md=7),
            dbc.Col([
                html.Div([
                    _status_pill(status),
                    html.Span(
                        f"  {checks_run} checks  "
                        f"🔴{critical}  🟡{warned}",
                        style={
                            "color"     : "#475569",
                            "fontSize"  : "12px",
                            "marginLeft": "8px",
                        }
                    ),
                    html.Span(
                        "  📣 Alerted" if alert_sent == "YES" else "",
                        style={
                            "color"   : "#00c851",
                            "fontSize": "12px",
                        }
                    ),
                ], style={"textAlign": "right"})
            ], md=5),
        ], align="center"),
    ], style={
        "backgroundColor": status_bg,
        "border"         : f"1px solid {status_color}40",
        "borderRadius"   : "8px 8px 0 0",
        "padding"        : "14px 18px",
    })


def _ai_block(ai_text: str) -> html.Div:
    """Renders the AI explanation block."""
    if not ai_text:
        return html.Div()
    return html.Div([
        html.Span(
            "🤖 AI Explanation",
            style={
                "color"       : "#4a9edd",
                "fontSize"    : "12px",
                "fontWeight"  : "700",
                "display"     : "block",
                "marginBottom": "6px",
            }
        ),
        html.P(
            _clean_ai_text(ai_text),
            style={
                "color"       : "#94a3b8",
                "fontSize"    : "13px",
                "lineHeight"  : "1.6",
                "marginBottom": "0",
            }
        ),
    ], style={
        "backgroundColor": "#070d14",
        "borderLeft"     : "3px solid #1e3a5f",
        "padding"        : "12px 16px",
        "marginTop"      : "12px",
    })


def _table_header(headers: list) -> html.Thead:
    return html.Thead(
        html.Tr([
            html.Th(h, style={
                "color"          : "#334155",
                "fontSize"       : "11px",
                "fontWeight"     : "600",
                "textTransform"  : "uppercase",
                "letterSpacing"  : "0.5px",
                "padding"        : "8px 12px",
                "borderBottom"   : "1px solid #0f2035",
                "backgroundColor": "#070d14",
            })
            for h in headers
        ])
    )


def _results_wrapper(table_element, ai_text: str = None) -> html.Div:
    return html.Div([
        html.Div(
            table_element,
            style={"overflowX": "auto"}
        ),
        _ai_block(ai_text) if ai_text else html.Div(),
    ], style={
        "backgroundColor": "#0a1520",
        "border"         : "1px solid #0f2035",
        "borderTop"      : "none",
        "borderRadius"   : "0 0 8px 8px",
        "padding"        : "12px",
        "marginBottom"   : "16px",
    })


def _no_results_wrapper(message: str = "No results found.") -> html.Div:
    return html.Div(
        html.P(message, className="text-muted small mb-0"),
        style={
            "backgroundColor": "#0a1520",
            "border"         : "1px solid #0f2035",
            "borderTop"      : "none",
            "borderRadius"   : "0 0 8px 8px",
            "padding"        : "16px",
            "marginBottom"   : "16px",
        }
    )


# ── Data loading ───────────────────────────────────────────────────────────

def _load_a1(business_date: str) -> dict:
    try:
        runs = execute_query(f"""
            SELECT
                validation_run_id,
                SUBSTRING_INDEX(
                    fully_qualified_name, '.', -1
                )                               AS table_name,
                fully_qualified_name,
                overall_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true
                     THEN 'YES' ELSE 'NO'
                END                             AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date = :business_date
            ORDER BY fully_qualified_name
        """, {"business_date": business_date})

        if runs.empty:
            return {"available": False}

        all_tables = []
        for _, run in runs.iterrows():
            run_id = run["validation_run_id"]

            results = execute_query(f"""
                SELECT
                    check_type,
                    check_level,
                    column_name,
                    check_status,
                    ROUND(observed_value, 4)        AS observed_value,
                    ROUND(baseline_value, 4)        AS baseline_value,
                    ROUND(deviation_percentage, 4)  AS deviation_pct,
                    threshold_warning,
                    threshold_critical,
                    ai_summary,
                    ai_failure_category,
                    ROUND(ai_confidence_score, 2)   AS ai_confidence
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
                WHERE validation_run_id = :run_id
                ORDER BY
                    CASE check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END,
                    check_type
            """, {"run_id": run_id})

            all_tables.append({
                "run"    : run.to_dict(),
                "results": results,
            })

        return {"available": True, "tables": all_tables}

    except Exception as e:
        logger.error(f"A1 load failed: {e}")
        return {"available": False, "error": str(e)}


def _load_a2(business_date: str) -> dict:
    try:
        runs = execute_query(f"""
            SELECT
                reconciliation_run_id,
                SUBSTRING_INDEX(
                    source_fully_qualified_name, '.', -1
                )                               AS table_name,
                source_fully_qualified_name,
                overall_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true
                     THEN 'YES' ELSE 'NO'
                END                             AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date = :business_date
            ORDER BY source_fully_qualified_name
        """, {"business_date": business_date})

        if runs.empty:
            return {"available": False}

        all_tables = []
        for _, run in runs.iterrows():
            run_id = run["reconciliation_run_id"]

            results = execute_query(f"""
                SELECT
                    from_layer,
                    to_layer,
                    check_type,
                    metric_name,
                    check_status,
                    ROUND(source_value, 2)          AS source_value,
                    ROUND(target_value, 2)          AS target_value,
                    ROUND(deviation_percentage, 2)  AS deviation_pct,
                    threshold_warning,
                    threshold_critical,
                    agent1_overall_status,
                    ai_summary,
                    ai_failure_category
                FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
                WHERE reconciliation_run_id = :run_id
                ORDER BY
                    CASE check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END,
                    from_layer, check_type
            """, {"run_id": run_id})

            all_tables.append({
                "run"    : run.to_dict(),
                "results": results,
            })

        return {"available": True, "tables": all_tables}

    except Exception as e:
        logger.error(f"A2 load failed: {e}")
        return {"available": False, "error": str(e)}


def _load_a4(business_date: str) -> dict:
    try:
        runs = execute_query(f"""
            SELECT
                validation_run_id,
                SUBSTRING_INDEX(
                    gold_fully_qualified_name, '.', -1
                )                               AS gold_table,
                gold_fully_qualified_name,
                overall_status,
                total_kpis_checked,
                total_kpis_passed,
                total_kpis_warned,
                total_kpis_critical,
                ai_enrichment_status,
                CASE WHEN alert_sent = true
                     THEN 'YES' ELSE 'NO'
                END                             AS alert_sent
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date = :business_date
            ORDER BY gold_fully_qualified_name
        """, {"business_date": business_date})

        if runs.empty:
            return {"available": False}

        all_tables = []
        for _, run in runs.iterrows():
            run_id = run["validation_run_id"]

            results = execute_query(f"""
                SELECT
                    kpi_name,
                    kpi_column,
                    check_type,
                    check_status,
                    ROUND(observed_value, 4)        AS observed_value,
                    ROUND(expected_value, 4)        AS expected_value,
                    ROUND(deviation_percentage, 2)  AS deviation_pct,
                    threshold_warning,
                    threshold_critical,
                    ai_summary,
                    ai_failure_category,
                    ROUND(ai_confidence_score, 2)   AS ai_confidence
                FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
                WHERE validation_run_id = :run_id
                ORDER BY
                    CASE check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END,
                    kpi_name, check_type
            """, {"run_id": run_id})

            all_tables.append({
                "run"    : run.to_dict(),
                "results": results,
            })

        return {"available": True, "tables": all_tables}

    except Exception as e:
        logger.error(f"A4 load failed: {e}")
        return {"available": False, "error": str(e)}


# ── Section builders ───────────────────────────────────────────────────────

def _build_a1_section(a1: dict) -> html.Div:
    if not a1.get("available"):
        return html.Div([
            html.Div([
                html.Span(
                    "🔍 Validation Agent — Raw Ingestion Validation",
                    style={"color": "#ffffff", "fontWeight": "700",
                           "fontSize": "15px"}
                ),
                html.Span(
                    "  No data for this date",
                    style={"color": "#475569", "fontSize": "13px"}
                ),
            ], style={
                "padding"        : "16px",
                "backgroundColor": "#0a1520",
                "borderRadius"   : "8px",
                "marginBottom"   : "12px",
            })
        ])

    elements = []

    for idx, tbl in enumerate(a1["tables"]):
        run     = tbl["run"]
        results = tbl["results"]
        status  = str(run.get("overall_status", "UNKNOWN"))

        elements.append(
            _agent_header(
                icon       = "🔍",
                agent_name = "Validation Agent — Raw Ingestion Validation",
                table_name = str(run.get("table_name", "")),
                status     = status,
                checks_run = int(run.get("total_checks_run") or 0),
                critical   = int(run.get("total_checks_critical") or 0),
                warned     = int(run.get("total_checks_warned") or 0),
                alert_sent = str(run.get("alert_sent", "NO")),
            )
        )

        if not results.empty:
            grid_rows = []
            for _, r in results.iterrows():
                check_status = str(r.get("check_status", ""))
                check_type   = str(r.get("check_type", ""))
                obs          = _safe_float(r.get("observed_value"))
                base_val     = _safe_float(r.get("baseline_value"))
                stored_dev   = _safe_float(r.get("deviation_pct"))
                col_name     = str(r.get("column_name") or "table-level")
                signed_dev   = _signed_deviation(obs, base_val, check_type, stored_dev)

                grid_rows.append({
                    "check_status": check_status,
                    "check_type"  : check_type,
                    "column_name" : col_name,
                    "observed"    : f"{obs:.4f}" if obs is not None else "—",
                    "baseline"    : f"{base_val:.4f}" if base_val is not None else "—",
                    "deviation"   : _fmt_deviation(signed_dev, check_type),
                })

            ai_text = None
            ai_rows = results[
                results["ai_summary"].notna() &
                (results["ai_summary"] != "")
            ]
            if not ai_rows.empty:
                ai_text = str(ai_rows.iloc[0]["ai_summary"])

            a1_grid = dag.AgGrid(
                **ag_grid_props(
                    grid_id=f"si-a1-grid-{idx}",
                    row_data=grid_rows,
                    col_defs=[
                        {"field": "check_status", "headerName": "Status",  "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "check_type",   "headerName": "Check Type", "flex": 1, "minWidth": 200},
                        {"field": "column_name",  "headerName": "Column",     "flex": 1, "minWidth": 220},
                        {"field": "observed",     "headerName": "Observed",   "width": 110},
                        {"field": "baseline",     "headerName": "Baseline",   "width": 110},
                        {"field": "deviation",    "headerName": "Deviation",  "width": 110},
                    ],
                    page_size=25,
                    status_col="check_status",
                    height=min(200 + len(grid_rows) * 32, 500),
                )
            )

            elements.append(
                _results_wrapper(a1_grid, ai_text=ai_text)
            )
        else:
            elements.append(
                _no_results_wrapper("No check results found for this run.")
            )

    return html.Div(elements)


def _build_a2_section(a2: dict) -> html.Div:
    if not a2.get("available"):
        return html.Div([
            html.Div([
                html.Span(
                    "🔄 Reconciliation Agent — Reconciliation",
                    style={"color": "#ffffff", "fontWeight": "700",
                           "fontSize": "15px"}
                ),
                html.Span(
                    "  No data for this date",
                    style={"color": "#475569", "fontSize": "13px"}
                ),
            ], style={
                "padding"        : "16px",
                "backgroundColor": "#0a1520",
                "borderRadius"   : "8px",
                "marginBottom"   : "12px",
            })
        ])

    elements = []

    for idx, tbl in enumerate(a2["tables"]):
        run     = tbl["run"]
        results = tbl["results"]
        status  = str(run.get("overall_status", "UNKNOWN"))

        elements.append(
            _agent_header(
                icon       = "🔄",
                agent_name = "Reconciliation Agent — Cross-Layer Reconciliation",
                table_name = str(run.get("table_name", "")),
                status     = status,
                checks_run = int(run.get("total_checks_run") or 0),
                critical   = int(run.get("total_checks_critical") or 0),
                warned     = int(run.get("total_checks_warned") or 0),
                alert_sent = str(run.get("alert_sent", "NO")),
            )
        )

        if not results.empty:
            grid_rows = []
            for _, r in results.iterrows():
                check_status = str(r.get("check_status", ""))
                src_val      = _safe_float(r.get("source_value"))
                tgt_val      = _safe_float(r.get("target_value"))
                dev          = _safe_float(r.get("deviation_pct"))
                from_layer   = str(r.get("from_layer", ""))
                to_layer     = str(r.get("to_layer", ""))

                grid_rows.append({
                    "check_status": check_status,
                    "layers"      : f"{from_layer} → {to_layer}",
                    "check_type"  : str(r.get("check_type", "")),
                    "metric_name" : str(r.get("metric_name", "")),
                    "source_value": f"{src_val:,.2f}" if src_val is not None else "—",
                    "target_value": f"{tgt_val:,.2f}" if tgt_val is not None else "—",
                    "deviation"   : f"{dev:+.2f}%" if dev is not None else "—",
                })

            ai_text = None
            ai_rows = results[
                results["ai_summary"].notna() &
                (results["ai_summary"] != "")
            ]
            if not ai_rows.empty:
                ai_text = str(ai_rows.iloc[0]["ai_summary"])

            a2_grid = dag.AgGrid(
                **ag_grid_props(
                    grid_id=f"si-a2-grid-{idx}",
                    row_data=grid_rows,
                    col_defs=[
                        {"field": "check_status", "headerName": "Status",  "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "layers",       "headerName": "Layers",  "minWidth": 150},
                        {"field": "check_type",   "headerName": "Check",   "flex": 1, "minWidth": 200},
                        {"field": "metric_name",  "headerName": "Metric",  "flex": 1, "minWidth": 220},
                        {"field": "source_value", "headerName": "Source",  "width": 110},
                        {"field": "target_value", "headerName": "Target",  "width": 110},
                        {"field": "deviation",    "headerName": "Dev %",   "width": 110},
                    ],
                    page_size=25,
                    status_col="check_status",
                    height=min(200 + len(grid_rows) * 32, 500),
                )
            )

            elements.append(
                _results_wrapper(a2_grid, ai_text=ai_text)
            )
        else:
            elements.append(
                _no_results_wrapper("No check results found.")
            )

    return html.Div(elements)


def _build_a4_section(a4: dict) -> html.Div:
    if not a4.get("available"):
        return html.Div([
            html.Div([
                html.Span(
                    "📊 KPI Assurance Agent — KPI Validation",
                    style={"color": "#ffffff", "fontWeight": "700",
                           "fontSize": "15px"}
                ),
                html.Span(
                    "  No data for this date",
                    style={"color": "#475569", "fontSize": "13px"}
                ),
            ], style={
                "padding"        : "16px",
                "backgroundColor": "#0a1520",
                "borderRadius"   : "8px",
                "marginBottom"   : "12px",
            })
        ])

    elements = []

    for idx, tbl in enumerate(a4["tables"]):
        run     = tbl["run"]
        results = tbl["results"]
        status  = str(run.get("overall_status", "UNKNOWN"))

        elements.append(
            _agent_header(
                icon       = "📊",
                agent_name = "KPI Assurance Agent — Gold KPI Validation",
                table_name = str(run.get("gold_table", "")),
                status     = status,
                checks_run = int(run.get("total_kpis_checked") or 0),
                critical   = int(run.get("total_kpis_critical") or 0),
                warned     = int(run.get("total_kpis_warned") or 0),
                alert_sent = str(run.get("alert_sent", "NO")),
            )
        )

        if not results.empty:
            grid_rows = []
            for _, r in results.iterrows():
                check_status = str(r.get("check_status", ""))
                check_type   = str(r.get("check_type", ""))
                obs          = _safe_float(r.get("observed_value"))
                exp          = _safe_float(r.get("expected_value"))
                dev          = _safe_float(r.get("deviation_pct"))

                grid_rows.append({
                    "check_status": check_status,
                    "kpi_name"    : str(r.get("kpi_name", "")),
                    "check_type"  : check_type,
                    "observed"    : f"{obs:.4f}" if obs is not None else "—",
                    "expected"    : f"{exp:.4f}" if exp is not None else "—",
                    "deviation"   : f"{dev:+.2f}%" if dev is not None else "—",
                })

            ai_text = None
            ai_rows = results[
                results["ai_summary"].notna() &
                (results["ai_summary"] != "")
            ]
            if not ai_rows.empty:
                ai_text = str(ai_rows.iloc[0]["ai_summary"])

            a4_grid = dag.AgGrid(
                **ag_grid_props(
                    grid_id=f"si-a4-grid-{idx}",
                    row_data=grid_rows,
                    col_defs=[
                        {"field": "check_status", "headerName": "Status",  "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "kpi_name",     "headerName": "KPI Name",   "flex": 2, "minWidth": 220},
                        {"field": "check_type",   "headerName": "Check Type", "flex": 1, "minWidth": 200},
                        {"field": "observed",     "headerName": "Observed",   "width": 110},
                        {"field": "expected",     "headerName": "Expected",   "width": 110},
                        {"field": "deviation",    "headerName": "Deviation",  "width": 110},
                    ],
                    page_size=25,
                    status_col="check_status",
                    height=min(200 + len(grid_rows) * 32, 500),
                )
            )

            elements.append(
                _results_wrapper(a4_grid, ai_text=ai_text)
            )
        else:
            elements.append(
                _no_results_wrapper("No KPI results found.")
            )

    return html.Div(elements)


# ── Severity banner ────────────────────────────────────────────────────────

def _severity_banner(a1: dict, a2: dict, a4: dict) -> html.Div:
    any_critical = (
        (a1.get("available") and any(
            int(t["run"].get("total_checks_critical") or 0) > 0
            for t in a1.get("tables", [])
        )) or
        (a2.get("available") and any(
            int(t["run"].get("total_checks_critical") or 0) > 0
            for t in a2.get("tables", [])
        )) or
        (a4.get("available") and any(
            int(t["run"].get("total_kpis_critical") or 0) > 0
            for t in a4.get("tables", [])
        ))
    )

    any_warning = (
        (a1.get("available") and any(
            int(t["run"].get("total_checks_warned") or 0) > 0
            for t in a1.get("tables", [])
        )) or
        (a2.get("available") and any(
            int(t["run"].get("total_checks_warned") or 0) > 0
            for t in a2.get("tables", [])
        )) or
        (a4.get("available") and any(
            int(t["run"].get("total_kpis_warned") or 0) > 0
            for t in a4.get("tables", [])
        ))
    )

    if any_critical:
        color  = "#ff6b6b"
        bg     = "#3d0000"
        border = "#ff6b6b"
        emoji  = "🔴"
        label  = "CRITICAL issues detected across multiple agents"
    elif any_warning:
        color  = "#ffa500"
        bg     = "#3d2000"
        border = "#ffa500"
        emoji  = "🟡"
        label  = "WARNING conditions detected — monitoring required"
    else:
        color  = "#00c851"
        bg     = "#002800"
        border = "#00c851"
        emoji  = "🟢"
        label  = "All checks passed — data quality normal"

    return html.Div([
        html.Span(
            f"{emoji}  {label}",
            style={
                "color"    : color,
                "fontSize" : "15px",
                "fontWeight": "700",
            }
        ),
    ], style={
        "backgroundColor": bg,
        "border"         : f"1px solid {border}",
        "borderRadius"   : "8px",
        "padding"        : "14px 20px",
        "marginBottom"   : "24px",
    })


def _agent_section_label(title: str) -> html.H5:
    return html.H5(
        title,
        style={
            "color"        : "#4a9edd",
            "fontSize"     : "14px",
            "fontWeight"   : "700",
            "textTransform": "uppercase",
            "letterSpacing": "1px",
            "marginBottom" : "12px",
        }
    )


# ── Main page builder ──────────────────────────────────────────────────────

def _build_investigation(business_date: str) -> html.Div:

    a1 = _load_a1(business_date)
    a2 = _load_a2(business_date)
    a4 = _load_a4(business_date)

    has_any = (
        a1.get("available") or
        a2.get("available") or
        a4.get("available")
    )

    from datetime import datetime
    try:
        dt  = datetime.strptime(business_date, "%Y-%m-%d")
        day = dt.strftime("%A, %-d %B %Y")
    except Exception:
        day = business_date

    elements = []

    # ── Page header ────────────────────────────────────────────────────────
    elements.append(
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.H2(
                        "🔍 DataSentinel Investigation",
                        className = "mt-4 mb-1",
                        style     = {"color": "#ffffff"}
                    ),
                    html.P(
                        f"What DataSentinel found on {day}",
                        style={
                            "color"       : "#64748b",
                            "fontSize"    : "14px",
                            "marginBottom": "0",
                        }
                    ),
                ], md=8),
                dbc.Col([
                    html.Div([
                        html.A(
                            "🤖 Open AI Insights →",
                            href  = f"/ai-insights?date={business_date}",
                            style = {
                                "color"         : "#87ceeb",
                                "fontSize"      : "13px",
                                "textDecoration": "none",
                                "display"       : "block",
                                "textAlign"     : "right",
                                "marginTop"     : "32px",
                            }
                        ),
                    ])
                ], md=4),
            ]),
            html.Hr(style={
                "borderColor": "#1e3a5f",
                "margin"     : "20px 0 24px",
            }),
        ])
    )

    if not has_any:
        elements.append(
            dbc.Alert(
                f"No validation data found for {business_date}. "
                "Ensure all agents have been run for this date.",
                color="warning"
            )
        )
        return html.Div(elements)

    # ── Severity banner ────────────────────────────────────────────────────
    elements.append(_severity_banner(a1, a2, a4))

    # ── Context explainer ──────────────────────────────────────────────────
    elements.append(
        html.Div([
            html.P([
                html.Strong(
                    "What you are looking at: ",
                    style={"color": "#ffffff"}
                ),
                html.Span(
                    "This is the technical investigation view. "
                    "Every finding below was produced by a deterministic "
                    "check — hard numbers compared against baselines or "
                    "rules. The AI explanations summarise what the checks "
                    "found but did not make any of the detections themselves.",
                    style={"color": "#64748b", "fontSize": "13px"}
                )
            ], style={"marginBottom": "0"}),
        ], style={
            "backgroundColor": "#070d14",
            "border"         : "1px solid #1e3a5f",
            "borderRadius"   : "8px",
            "padding"        : "14px 18px",
            "marginBottom"   : "24px",
        })
    )

    # ── Agent 1 ────────────────────────────────────────────────────────────
    elements.append(
        html.Div([
            _agent_section_label("Validation Agent — Raw Ingestion Validation"),
            _build_a1_section(a1),
        ], className="mb-2")
    )

    # ── Agent 2 ────────────────────────────────────────────────────────────
    elements.append(
        html.Div([
            _agent_section_label("Reconciliation Agent — Cross-Layer Reconciliation"),
            _build_a2_section(a2),
        ], className="mb-2")
    )

    # ── Agent 4 ────────────────────────────────────────────────────────────
    elements.append(
        html.Div([
            _agent_section_label("KPI Assurance Agent — Gold KPI Validation"),
            _build_a4_section(a4),
        ], className="mb-2")
    )

    # ── Bottom navigation ──────────────────────────────────────────────────
    elements.append(
        html.Div([
            html.Hr(style={
                "borderColor": "#1e3a5f",
                "margin"     : "8px 0 20px",
            }),
            dbc.Row([
                dbc.Col([
                    html.A(
                        "📊 Open Financial Report →",
                        href  = f"/financial-report",
                        style = {
                            "color"         : "#4a9edd",
                            "fontSize"      : "13px",
                            "textDecoration": "none",
                        }
                    ),
                ], md=4),
                dbc.Col([
                    html.A(
                        "🤖 Open AI Insights for full narrative →",
                        href  = f"/ai-insights?date={business_date}",
                        style = {
                            "color"         : "#87ceeb",
                            "fontSize"      : "13px",
                            "textDecoration": "none",
                            "display"       : "block",
                            "textAlign"     : "right",
                        }
                    ),
                ], md=8),
            ]),
        ], className="mb-4")
    )

    return html.Div(elements)

# ── Callback ───────────────────────────────────────────────────────────────
# ── Load date options ──────────────────────────────────────────────────────

@callback(
    Output("si-date-dropdown", "options"),
    Output("si-date-dropdown", "value"),
    Input("si-date-dropdown",  "id"),
    Input("si-location",       "search"),
)
def load_si_date_options(_, search):
    """
    Populates the date dropdown from validation run history.
    If ?date= is in the URL (linked from financial report),
    pre-selects that date automatically.
    """
    try:
        df = execute_query(f"""
            SELECT DISTINCT business_date
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            ORDER BY business_date DESC
            LIMIT 60
        """)
        if df.empty:
            return [], None

        options = [
            {
                "label": str(row["business_date"])[:10],
                "value": str(row["business_date"])[:10]
            }
            for _, row in df.iterrows()
        ]

        available = [o["value"] for o in options]

        # Check if a date was passed via URL query string
        preselect = None
        if search:
            import urllib.parse
            params = urllib.parse.parse_qs(search.lstrip("?"))
            if "date" in params:
                url_date = params["date"][0]
                if url_date in available:
                    preselect = url_date

        # Default priority:
        # 1. URL query param  2. July 20  3. July 19  4. Most recent
        default = (
            preselect
            if preselect
            else "2026-07-20" if "2026-07-20" in available
            else "2026-07-19" if "2026-07-19" in available
            else options[0]["value"] if options else None
        )

        return options, default

    except Exception as e:
        logger.error(f"Failed to load SI date options: {e}")
        return [], None




@callback(
    Output("si-alert",        "children"),
    Output("si-page-content", "children"),
    Input("si-load-btn",      "n_clicks"),
    Input("si-location",      "search"),
    State("si-date-dropdown", "value"),
    prevent_initial_call=False,
)
def render_investigation(n_clicks, search, dropdown_date):
    """
    Renders the investigation for the selected date.

    Fires on:
      - Page load (auto-loads if date in URL or default date)
      - Button click (loads whatever is in the dropdown)

    Priority:
      - Button click → use dropdown value
      - Page load with ?date= URL param → use URL date
      - Page load without URL param → use dropdown default
    """
    from dash import ctx

    triggered = ctx.triggered_id if ctx.triggered_id else None

    # Determine which date to use
    business_date = None

    if triggered == "si-load-btn":
        # User clicked the button — use dropdown selection
        business_date = dropdown_date

    else:
        # Page load — check URL first then fall back to dropdown
        if search:
            import urllib.parse
            params = urllib.parse.parse_qs(search.lstrip("?"))
            if "date" in params:
                business_date = params["date"][0]

        if not business_date:
            business_date = dropdown_date

    if not business_date:
        return "", html.Div()

    try:
        return "", _build_investigation(business_date)
    except Exception as e:
        logger.error(f"Investigation page failed: {e}")
        import traceback
        traceback.print_exc()
        return (
            dbc.Alert(
                f"Could not load investigation: {str(e)}",
                color="danger"
            ),
            html.Div()
        )