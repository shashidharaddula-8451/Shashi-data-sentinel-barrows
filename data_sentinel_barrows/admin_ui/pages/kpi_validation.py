# pages/kpi_validation.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_ag_grid as dag

import dash_bootstrap_components as dbc
import json
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from db.queries import (
    get_all_kpis,
    get_kpi_validation_run_summary,
    get_kpi_validation_results_for_run,
    get_agent4_dashboard_summary
)
from components.alerts import (
    error_alert,
    info_alert,
    build_alert_modal,
    build_alert_card_body,
    STATUS_EMOJI,
    STATUS_COLOR,
    fmt_optional,
    fmt_number,
    fmt_deviation,
    fmt_threshold,
    compute_signed_deviation,
    add_status_code,
    ag_grid_props,
    AG_STATUS_ROW_STYLE_JS,
    AG_STATUS_CELL_STYLE_JS,
)

import plotly.graph_objects as go
from datetime import date

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/kpi-validation",
    name="KPI Validation"
)

layout = dbc.Container([

    html.H2("KPI Assurance Agent — Gold KPI Validation", className="mt-4 mb-2"),
    html.P(
        "Monitor Gold layer KPI health. "
        "Click YES in the Alert column to preview the Teams alert.",
        className="text-muted mb-4"
    ),

    html.Div(id="kpi-alert"),

    dcc.Loading(
        id    = "kpiv-summary-loading",
        type  = "circle",
        color = "#00c851",
        children = dbc.Row(id="agent4-summary-cards", className="mb-4"),
    ),

    dcc.Loading(
        id    = "kpiv-tabs-loading",
        type  = "circle",
        color = "#00c851",
        children =
            dbc.Tabs([

        dbc.Tab(
            label="Validation History",
            tab_id="tab-history",
            children=[
                dbc.Card([
                    dbc.CardBody([

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Filter by Status", className="text-white"),
                                dcc.Dropdown(
                                    id="kpi-status-filter",
                                    options=[
                                        {"label": "All",        "value": "ALL"},
                                        {"label": "🔴 Critical","value": "CRITICAL"},
                                        {"label": "🟡 Warning", "value": "WARNING"},
                                        {"label": "🟢 Pass",    "value": "PASS"}
                                    ],
                                    value="ALL",
                                    clearable=False,
                                    style={
                                        "backgroundColor": "#2b2b2b",
                                        "color"          : "#ffffff"
                                    }
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label("\u00a0", className="text-white"),
                                dbc.Button(
                                    "Refresh",
                                    id="refresh-kpi-runs-btn",
                                    color="secondary",
                                    className="d-block w-100"
                                )
                            ], md=2)
                        ], className="mb-3"),

                        dag.AgGrid(
                            **ag_grid_props(
                                grid_id="kpi-runs-table",
                                col_defs=[
                                    {"field": "business_date",       "headerName": "Date",  "minWidth": 120},
                                    {"field": "gold_table",          "headerName": "Table",    "flex": 2, "minWidth": 220},
                                    {"field": "overall_status",      "headerName": "Status",   "minWidth": 150,
                                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                                    {"field": "total_kpis_checked",  "headerName": "KPIs",     "width": 90},
                                    {"field": "total_kpis_passed",   "headerName": "Passed",   "width": 90},
                                    {"field": "total_kpis_warned",   "headerName": "Warning",  "width": 90},
                                    {"field": "total_kpis_critical", "headerName": "Critical", "width": 95},
                                    {"field": "ai_enrichment_status","headerName": "AI",    "minWidth": 150},
                                    {"field": "alert_fired",         "headerName": "Alert",    "width": 90},
                                ],
                                page_size=12,
                                selection="single",
                                status_col="overall_status",
                            )
                        )
                    ])
                ], className="mt-3")
            ]
        ),

        dbc.Tab(
            label="KPI Check Detail",
            tab_id="tab-detail",
            children=[
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id="kpi-check-detail-container")
                    ])
                ], className="mt-3")
            ]
        ),

        dbc.Tab(
            label="🤖 AI Analysis",
            tab_id="tab-ai",
            children=[
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id="kpi-ai-panel")
                    ])
                ], className="mt-3")
            ]
        ),

        dbc.Tab(
            label="Registered KPIs",
            tab_id="tab-kpis",
            children=[
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id="kpi-registry-container")
                    ])
                ], className="mt-3")
            ]
        ),

        dbc.Tab(
            label="🔗 Lineage",
            tab_id="tab-lineage",
            children=[
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id="kpi-lineage-container")
                    ])
                ], className="mt-3")
            ]
        ),

    ], id="kpi-tabs", active_tab="tab-history"),
    ),

    dcc.Store(id="a4-alert-store", data=None),
    build_alert_modal(modal_id="a4-alert-modal")

], fluid=True)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("agent4-summary-cards", "children"),
    Input("agent4-summary-cards", "id")
)
def load_summary(_):
    try:
        df = execute_query(get_agent4_dashboard_summary())
        if df.empty:
            return dbc.Alert("No KPI validation runs yet.", color="info")

        row      = df.iloc[0]
        tables   = int(row.get("kpis_tables_monitored") or 0)
        dates    = int(row.get("dates_validated") or 0)
        checks   = int(row.get("total_kpi_checks") or 0)
        critical = int(row.get("critical_runs") or 0)
        passing  = int(row.get("pass_runs") or 0)
        latest   = str(row.get("latest_date", "N/A"))

        def card(title, value, color_style=None):
            return dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H3(
                        str(value),
                        className="text-center fw-bold mb-0",
                        style=color_style or {"color": "#ffffff"}
                    ),
                    html.P(
                        title,
                        className="text-center small mb-0",
                        style={"color": "#aaaaaa"}
                    )
                ])
            ], style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            }), md=2)

        return dbc.Row([
            card("Gold Tables",   tables),
            card("Dates Checked", dates),
            card("KPI Checks",    checks),
            card("Critical Runs", critical,
                 {"color": "#ff6b6b"} if critical > 0 else None),
            card("Pass Runs",     passing,
                 {"color": "#00c851"} if passing > 0 else None),
            card("Latest Date",   latest),
        ])

    except Exception as e:
        logger.error(f"Failed to load Agent 4 summary: {str(e)}")
        return dbc.Alert(f"Could not load summary: {str(e)}", color="danger")


@callback(
    Output("kpi-runs-table", "rowData"),
    Input("refresh-kpi-runs-btn", "n_clicks"),
    Input("kpi-status-filter", "value"),
    prevent_initial_call=False
)
def load_kpi_runs(n_clicks, status_filter):
    try:
        df = execute_query(get_kpi_validation_run_summary())
        if df.empty:
            return []

        if status_filter and status_filter != "ALL":
            df = df[df["overall_status"] == status_filter]

        def safe_int(v):
            try:
                return int(v) if v is not None else 0
            except (TypeError, ValueError):
                return 0

        rows = []
        for _, row in df.iterrows():
            alerted = row.get("alert_fired", "NO")
            alert_display = (
                "✅ YES (click to preview)"
                if alerted == "YES"
                else "NO"
            )
            rows.append({
                "business_date"            : str(row.get("business_date", "")),
                "gold_table"               : str(row.get("gold_table", "")),
                "gold_fully_qualified_name": str(
                    row.get("gold_fully_qualified_name", "")
                ),
                "overall_status"           : str(row.get("overall_status", "")),
                "total_kpis_checked"       : safe_int(row.get("total_kpis_checked")),
                "total_kpis_passed"        : safe_int(row.get("total_kpis_passed")),
                "total_kpis_warned"        : safe_int(row.get("total_kpis_warned")),
                "total_kpis_critical"      : safe_int(row.get("total_kpis_critical")),
                "ai_enrichment_status"     : str(row.get("ai_enrichment_status", "")),
                "alert_fired"              : alert_display,
                "validation_run_id"        : str(row.get("validation_run_id", ""))
            })

        rows = add_status_code(rows, "overall_status")

        return rows

    except Exception as e:
        logger.error(f"Failed to load KPI runs: {str(e)}")
        return []


@callback(
    Output("kpi-check-detail-container", "children"),
    Output("kpi-ai-panel", "children"),
    Output("a4-alert-store", "data"),
    Input("kpi-runs-table", "selectedRows"),
    Input("kpi-runs-table", "cellClicked"),
    prevent_initial_call=True
)
def load_run_detail(selected_rows, cell_clicked):
    placeholder = html.P(
        "Select a validation run from the History tab.",
        className="text-muted"
    )

    if not selected_rows:
        return placeholder, placeholder, None

    row     = selected_rows[0]
    run_id  = row.get("validation_run_id", "")
    alerted = row.get("alert_fired", "NO")

    if not run_id:
        return error_alert("No run ID."), html.Div(), None

    try:
        df = execute_query(*get_kpi_validation_results_for_run(run_id))

        if df.empty:
            return (
                info_alert("No check results found."),
                html.Div(),
                None
            )

        def safe_float(v):
            try:
                return round(float(v), 4) if v is not None else None
            except (TypeError, ValueError):
                return None

        table_rows = []
        for _, r in df.iterrows():
            check_type   = str(r.get("check_type", ""))
            check_status = str(r.get("check_status", ""))
            obs_raw      = r.get("observed_value")
            exp_raw      = r.get("expected_value")

            # Compute signed deviation for ANOMALY checks
            signed_dev = compute_signed_deviation(obs_raw, exp_raw, check_type)

            table_rows.append({
                "kpi_name"       : str(r.get("kpi_name", "")),
                "kpi_column"     : str(r.get("kpi_column", "")),
                "check_type"     : check_type,
                "check_status"   : check_status,
                "observed_value" : fmt_number(obs_raw),
                "expected_value" : fmt_number(exp_raw),
                "deviation_pct"  : fmt_deviation(signed_dev, check_type),
                "warn_threshold" : fmt_threshold(r.get("threshold_warning")),
                "crit_threshold" : fmt_threshold(r.get("threshold_critical")),
            })

        detail_table = dag.AgGrid(
            **ag_grid_props(
                grid_id="kpi-check-detail-grid",
                row_data=table_rows,
                col_defs=[
                    {"field": "kpi_name",       "headerName": "KPI Name",    "flex": 2, "minWidth": 220},
                    {"field": "kpi_column",     "headerName": "Column",   "minWidth": 150},
                    {"field": "check_type",     "headerName": "Check Type",  "minWidth": 200},
                    {"field": "check_status",   "headerName": "Status",   "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "observed_value", "headerName": "Observed",    "width": 110},
                    {"field": "expected_value", "headerName": "Expected",    "width": 110},
                    {"field": "deviation_pct",  "headerName": "Deviation %", "width": 110},
                    {"field": "warn_threshold", "headerName": "Warn",        "width": 110},
                    {"field": "crit_threshold", "headerName": "Critical",    "width": 110},
                ],
                page_size=20,
                status_col="check_status",
            )
        )

        ai_rows = df[df["ai_summary"].notna()]
        status  = row.get("overall_status", "")

        if ai_rows.empty:
            ai_panel = dbc.Alert(
                "No AI enrichment available for this run.",
                color="info"
            )
        else:
            first         = ai_rows.iloc[0]
            ai_summary    = first.get("ai_summary", "")
            ai_action     = first.get("ai_recommended_action", "")
            ai_category   = first.get("ai_failure_category", "")
            ai_confidence = first.get("ai_confidence_score")

            try:
                confidence_pct = f"{float(ai_confidence):.0%}"
            except (TypeError, ValueError):
                confidence_pct = "N/A"

            ai_panel = dbc.Container([
                dbc.Row([
                    dbc.Col([
                        dbc.Badge(
                            ai_category or "N/A",
                            color=STATUS_COLOR.get(status, "secondary"),
                            className="me-2 mb-2 fs-6"
                        ),
                        dbc.Badge(
                            f"Confidence: {confidence_pct}",
                            color="secondary",
                            className="mb-2 fs-6"
                        )
                    ])
                ]),
                dbc.Row([
                    dbc.Col([
                        html.H6("AI Summary", className="text-info mt-2"),
                        html.P(
                            ai_summary,
                            className="border-start border-info ps-3"
                        )
                    ], md=6),
                    dbc.Col([
                        html.H6(
                            "Recommended Action",
                            className="text-success mt-2"
                        ),
                        html.P(
                            ai_action or "No specific action.",
                            className="border-start border-success ps-3"
                        )
                    ], md=6)
                ])
            ], fluid=True)

        store_data = {
            "validation_run_id"        : run_id,
            "business_date"            : row.get("business_date", ""),
            "gold_table"               : row.get("gold_table", ""),
            "gold_fully_qualified_name": row.get("gold_fully_qualified_name", ""),
            "overall_status"           : status,
            "total_kpis_checked"       : row.get("total_kpis_checked", 0),
            "total_kpis_passed"        : row.get("total_kpis_passed", 0),
            "total_kpis_warned"        : row.get("total_kpis_warned", 0),
            "total_kpis_critical"      : row.get("total_kpis_critical", 0),
            "ai_enrichment_status"     : row.get("ai_enrichment_status", "")
        }

        return detail_table, ai_panel, store_data

    except Exception as e:
        logger.error(f"Failed to load run detail: {str(e)}")
        return error_alert(str(e)), html.Div(), None


@callback(
    Output("kpi-registry-container", "children"),
    Input("kpi-tabs", "active_tab")
)
def load_kpi_registry(active_tab):
    if active_tab != "tab-kpis":
        return html.Div()

    try:
        df = execute_query(get_all_kpis())
        if df.empty:
            return info_alert("No KPIs registered yet.")

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "kpi_id"               : str(row.get("kpi_id", "")),
                "gold_table"           : str(row.get("gold_table", "")),
                "kpi_name"             : str(row.get("kpi_name", "")),
                "kpi_column"           : str(row.get("kpi_column", "")),
                "formula_expression"   : fmt_optional(row.get("formula_expression")),
                "min_value"            : fmt_optional(row.get("min_value")),
                "max_value"            : fmt_optional(row.get("max_value")),
                "warning_deviation_pct": fmt_optional(
                    row.get("warning_deviation_pct")
                ),
                "critical_deviation_pct": fmt_optional(
                    row.get("critical_deviation_pct")
                ),
                "checks_enabled"       : str(row.get("checks_enabled", "")),
                "is_active"            : str(row.get("is_active", True))
            })

        return dag.AgGrid(
            **ag_grid_props(
                grid_id="kpi-registry-display-grid",
                row_data=rows,
                col_defs=[
                    {"field": "kpi_id",                "headerName": "ID",    "minWidth": 150},
                    {"field": "gold_table",            "headerName": "Table",    "flex": 2, "minWidth": 220},
                    {"field": "kpi_name",              "headerName": "KPI Name", "flex": 2, "minWidth": 220},
                    {"field": "kpi_column",            "headerName": "Column",   "minWidth": 150},
                    {"field": "formula_expression",    "headerName": "Formula",  "flex": 2, "minWidth": 280},
                    {"field": "min_value",             "headerName": "Min",      "width": 110},
                    {"field": "max_value",             "headerName": "Max",      "width": 110},
                    {"field": "warning_deviation_pct", "headerName": "Warn %",   "width": 110},
                    {"field": "critical_deviation_pct","headerName": "Crit %",   "width": 110},
                    {"field": "checks_enabled",        "headerName": "Checks",   "flex": 1, "minWidth": 220},
                    {"field": "is_active",             "headerName": "Active",   "width": 90},
                ],
                page_size=15,
            )
        )

    except Exception as e:
        logger.error(f"Failed to load KPI registry: {str(e)}")
        return error_alert(f"Could not load KPI registry: {str(e)}")


@callback(
    Output("a4-alert-modal", "is_open"),
    Output("a4-alert-modal-title", "children"),
    Output("a4-alert-modal-body", "children"),
    Input("kpi-runs-table", "cellClicked"),
    Input("a4-alert-modal-close-btn", "n_clicks"),
    State("kpi-runs-table", "rowData"),
    State("a4-alert-store", "data"),
    State("a4-alert-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_a4_modal(active_cell, close_clicks, data, store_data, is_open):
    triggered = ctx.triggered_id

    if triggered == "a4-alert-modal-close-btn":
        return False, "", []

    if triggered == "kpi-runs-table" and active_cell and data:
        col_id    = active_cell.get("colId", "")
        row_index = active_cell.get("rowIndex", 0)

        if col_id != "alert_fired":
            return False, "", []

        if row_index >= len(data):
            return False, "", []

        row     = data[row_index]
        alerted = row.get("alert_fired", "NO")

        if "YES" not in alerted:
            return False, "", []

        run_id  = row.get("validation_run_id", "")
        status  = row.get("overall_status", "")
        table   = row.get("gold_table", "")
        date    = str(row.get("business_date", ""))
        fqn     = row.get("gold_fully_qualified_name", "")
        emoji   = STATUS_EMOJI.get(status, "⚪")

        failed_checks = []
        ai_summary = ai_action = ai_category = None
        ai_confidence = None

        try:
            df = execute_query(*get_kpi_validation_results_for_run(run_id))

            if not df.empty:
                for _, r in df.iterrows():
                    if r.get("check_status") in ("CRITICAL", "WARNING"):
                        failed_checks.append({
                            "check_type"        : (
                                f"{r.get('kpi_name', '')} "
                                f"[{r.get('check_type', '')}]"
                            ),
                            "column_name"        : str(r.get("kpi_column", "")),
                            "check_status"       : str(r.get("check_status", "")),
                            "observed_value"     : r.get("observed_value"),
                            "deviation_pct"      : r.get("deviation_percentage"),
                            "threshold_warning"  : r.get("threshold_warning"),
                            "threshold_critical" : r.get("threshold_critical")
                        })

                ai_rows = df[
                    df["ai_summary"].notna() & (df["ai_summary"] != "")
                ]
                if not ai_rows.empty:
                    first         = ai_rows.iloc[0]
                    ai_summary    = str(first.get("ai_summary", ""))
                    ai_action     = str(first.get("ai_recommended_action", ""))
                    ai_category   = str(first.get("ai_failure_category", ""))
                    ai_confidence = first.get("ai_confidence_score")

        except Exception as e:
            logger.error(f"A4 modal error: {str(e)}")

        title = f"{emoji} {status}: {table} KPIs — {date}"

        body = build_alert_card_body(
            agent_name     = "KPI Assurance Agent — Gold KPI Validation",
            table_name     = table,
            fqn            = fqn,
            business_date  = date,
            status         = status,
            checks_run     = int(row.get("total_kpis_checked", 0)),
            checks_passed  = int(row.get("total_kpis_passed", 0)),
            checks_warned  = int(row.get("total_kpis_warned", 0)),
            checks_critical= int(row.get("total_kpis_critical", 0)),
            failed_checks  = failed_checks,
            ai_summary     = ai_summary,
            ai_action      = ai_action,
            ai_category    = ai_category,
            ai_confidence  = float(ai_confidence) if ai_confidence else None,
            run_id         = run_id
        )

        return True, title, body

    return False, "", []


# ══════════════════════════════════════════════════════════════════════════
# LINEAGE DATA LOADING
# ══════════════════════════════════════════════════════════════════════════

def _load_lineage_data(
    gold_fqn      : str,
    business_date : str,
    kpi_name      : str = None
) -> dict:
    """
    Loads all data needed to render the lineage diagram for one
    Gold table on one business date.

    Returns a dict with keys:
      kpi          : dict from uc4_kpi_registry_b
      gold         : dict — A4 status for this table/date
      silver       : dict — A2 RAW→SILVER survival for source table
      raw          : dict — A1 worst check for source table
      source_system: dict — from uc1_table_registry_b
      layers       : dict — from uc2_layer_registry_b
    """
    result = {
        "kpi"          : {},
        "gold"         : {},
        "silver"       : {},
        "raw"          : {},
        "source_system": {},
        "layers"       : {},
    }

    CATALOG = TARGET_CATALOG
    SCHEMA  = TARGET_SCHEMA

    # ── KPI definition ─────────────────────────────────────────────────────
    try:
        kpi_params = {"gold_fqn": gold_fqn}
        kpi_filter = ""
        if kpi_name:
            kpi_filter = "AND kpi_name = :kpi_name"
            kpi_params["kpi_name"] = kpi_name
        df = execute_query(f"""
            SELECT
                kpi_id, kpi_name, kpi_column,
                kpi_description, formula_expression,
                checks_enabled, gold_fully_qualified_name
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_registry_b
            WHERE gold_fully_qualified_name = :gold_fqn
              AND is_active = true
              {kpi_filter}
            ORDER BY kpi_id
            LIMIT 1
        """, kpi_params)
        if not df.empty:
            result["kpi"] = df.iloc[0].to_dict()
    except Exception as e:
        logger.error(f"Lineage: KPI load failed: {e}")

    # ── Gold node: A4 status for this run ──────────────────────────────────
    try:
        gold_params = {
            "gold_fqn"     : gold_fqn,
            "business_date": business_date,
        }
        gold_kpi_filter = ""
        if kpi_name:
            gold_kpi_filter = "AND r.kpi_name = :kpi_name"
            gold_params["kpi_name"] = kpi_name
        df = execute_query(f"""
            SELECT
                r.kpi_name,
                r.check_type,
                r.check_status,
                ROUND(r.observed_value, 4)      AS observed_value,
                ROUND(r.expected_value, 4)      AS expected_value,
                ROUND(r.deviation_percentage, 2) AS deviation_pct,
                r.ai_failure_category
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b run
              ON r.validation_run_id = run.validation_run_id
            WHERE run.gold_fully_qualified_name = :gold_fqn
              AND run.business_date = :business_date
              {gold_kpi_filter}
            ORDER BY
                CASE r.check_status
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'WARNING'  THEN 2
                    ELSE 3
                END,
                r.kpi_name
            LIMIT 1
        """, gold_params)
        if not df.empty:
            result["gold"] = df.iloc[0].to_dict()
    except Exception as e:
        logger.error(f"Lineage: Gold node load failed: {e}")

    # ── Layer registry: find source (raw) table for this gold table ────────
    try:
        df = execute_query(f"""
            SELECT
                layer_name,
                source_fully_qualified_name,
                layer_fully_qualified_name,
                expected_survival_rate
            FROM {CATALOG}.{SCHEMA}.uc2_layer_registry_b
            WHERE is_active = true
              AND (
                  layer_fully_qualified_name = :gold_fqn
                  OR source_fully_qualified_name IN (
                      SELECT source_fully_qualified_name
                      FROM {CATALOG}.{SCHEMA}.uc2_layer_registry_b
                      WHERE layer_fully_qualified_name = :gold_fqn
                        AND is_active = true
                  )
              )
            ORDER BY
                CASE layer_name
                    WHEN 'BRONZE' THEN 1
                    WHEN 'SILVER' THEN 2
                    WHEN 'GOLD'   THEN 3
                END
        """, {"gold_fqn": gold_fqn})
        if not df.empty:
            for _, row in df.iterrows():
                result["layers"][row["layer_name"]] = row.to_dict()
    except Exception as e:
        logger.error(f"Lineage: Layer registry load failed: {e}")

    source_fqn  = None
    silver_fqn  = None

    if "BRONZE" in result["layers"]:
        source_fqn = result["layers"]["BRONZE"]["source_fully_qualified_name"]
    if "SILVER" in result["layers"]:
        silver_fqn = result["layers"]["SILVER"]["layer_fully_qualified_name"]

    # ── Silver node: A2 RAW→SILVER survival ───────────────────────────────
    if source_fqn:
        try:
            df = execute_query(f"""
                SELECT
                    r.check_type,
                    r.check_status,
                    ROUND(r.source_value, 0)        AS raw_count,
                    ROUND(r.target_value, 0)        AS silver_count,
                    ROUND(r.deviation_percentage, 2) AS deviation_pct,
                    r.metric_name
                FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b r
                JOIN {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b run
                  ON r.reconciliation_run_id = run.reconciliation_run_id
                WHERE run.source_fully_qualified_name = :source_fqn
                  AND run.business_date = :business_date
                  AND r.check_type = 'BRONZE_TO_SILVER_ROW_COUNT'
                ORDER BY
                    CASE r.check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END
                LIMIT 1
            """, {
                "source_fqn"   : source_fqn,
                "business_date": business_date,
            })
            if not df.empty:
                row = df.iloc[0].to_dict()
                # Compute actual survival pct from counts
                raw_count    = float(row.get("raw_count") or 0)
                silver_count = float(row.get("silver_count") or 0)
                survival_pct = (
                    round(silver_count / raw_count * 100, 1)
                    if raw_count > 0 else 0.0
                )
                row["survival_pct"] = survival_pct
                result["silver"] = row
        except Exception as e:
            logger.error(f"Lineage: Silver node load failed: {e}")

    # ── Raw node: A1 worst check ───────────────────────────────────────────
    if source_fqn:
        try:
            df = execute_query(f"""
                SELECT
                    r.check_type,
                    r.check_level,
                    r.column_name,
                    r.check_status,
                    ROUND(r.observed_value, 4)       AS observed_value,
                    ROUND(r.deviation_percentage, 2) AS deviation_pct
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
                JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
                  ON r.validation_run_id = run.validation_run_id
                WHERE run.fully_qualified_name = :source_fqn
                  AND run.business_date = :business_date
                ORDER BY
                    CASE r.check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END,
                    ABS(r.deviation_percentage) DESC
                LIMIT 1
            """, {
                "source_fqn"   : source_fqn,
                "business_date": business_date,
            })
            if not df.empty:
                result["raw"] = df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Lineage: Raw node load failed: {e}")

    # ── Source system: from table registry ────────────────────────────────
    if source_fqn:
        try:
            df = execute_query(f"""
                SELECT
                    source_type,
                    ingestion_pattern,
                    ingestion_frequency,
                    table_name
                FROM {CATALOG}.{SCHEMA}.uc1_table_registry_b
                WHERE fully_qualified_name = :source_fqn
                LIMIT 1
            """, {"source_fqn": source_fqn})
            if not df.empty:
                result["source_system"] = df.iloc[0].to_dict()
        except Exception as e:
            logger.error(f"Lineage: Source system load failed: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════
# LINEAGE DIAGRAM BUILDER
# ══════════════════════════════════════════════════════════════════════════

_NODE_COLORS = {
    "CRITICAL": {
        "bg"    : "#3d0000",
        "border": "#ff6b6b",
        "text"  : "#ff6b6b",
        "badge" : "#ff4444",
    },
    "WARNING": {
        "bg"    : "#3d2000",
        "border": "#ffa500",
        "text"  : "#ffa500",
        "badge" : "#ffa500",
    },
    "PASS": {
        "bg"    : "#002800",
        "border": "#00c851",
        "text"  : "#00c851",
        "badge" : "#00c851",
    },
    "UNKNOWN": {
        "bg"    : "#1a1a1a",
        "border": "#555555",
        "text"  : "#aaaaaa",
        "badge" : "#666666",
    },
}

_STATUS_EMOJI = {
    "CRITICAL": "🔴",
    "WARNING" : "🟡",
    "PASS"    : "🟢",
    "UNKNOWN" : "⚪",
}


def _node_colors(status: str) -> dict:
    return _NODE_COLORS.get(
        status if status in _NODE_COLORS else "UNKNOWN",
        _NODE_COLORS["UNKNOWN"]
    )


# ── Replace _build_lineage_figure entirely ────────────────────────────────

def _build_lineage_figure(
    lineage      : dict,
    gold_fqn     : str,
    bdate        : str
) -> go.Figure:
    """
    Builds a clean vertical lineage diagram.

    5 layers stacked top-to-bottom:
      KPI      y=4.0
      Gold     y=3.0
      Silver   y=2.0
      Raw      y=1.0
      Source   y=0.0

    Each node: rounded rect 6 units wide, 0.55 units tall.
    Arrows: solid, with proper arrowheads.
    Left accent bar per node shows status colour.
    """

    kpi    = lineage.get("kpi", {})
    gold   = lineage.get("gold", {})
    silver = lineage.get("silver", {})
    raw    = lineage.get("raw", {})
    src    = lineage.get("source_system", {})
    layers = lineage.get("layers", {})

    gold_table   = gold_fqn.split(".")[-1]
    silver_table = (
        layers.get("SILVER", {})
              .get("layer_fully_qualified_name", "uc2_silver_*")
              .split(".")[-1]
    )
    raw_table = (
        layers.get("BRONZE", {})
              .get("source_fully_qualified_name", "uc1_raw_*")
              .split(".")[-1]
    )
    source_type  = src.get("source_type", "External System")
    ingestion    = src.get("ingestion_pattern", "")
    source_label = f"{source_type} / {ingestion}" if ingestion else source_type

    # ── Compute statuses ───────────────────────────────────────────────────

    kpi_name     = kpi.get("kpi_name") or gold.get("kpi_name") or "KPI"
    kpi_formula  = kpi.get("formula_expression") or ""
    kpi_status   = str(gold.get("check_status", "UNKNOWN"))
    kpi_dev      = gold.get("deviation_pct")
    kpi_check    = gold.get("check_type", "")

    gold_status  = kpi_status
    gold_detail  = (
        f"{kpi_check}  {kpi_dev:+.1f}%"
        if kpi_dev is not None else kpi_check or "No data"
    )

    silver_status = (
        str(silver.get("check_status", "UNKNOWN"))
        if silver else "UNKNOWN"
    )
    survival_pct  = silver.get("survival_pct")
    silver_detail = (
        f"Survival: {survival_pct:.1f}%"
        if survival_pct is not None
        else "No Reconciliation Agent data for this date"
    )

    raw_status     = (
        str(raw.get("check_status", "UNKNOWN"))
        if raw else "UNKNOWN"
    )
    raw_check_type = raw.get("check_type", "")
    raw_dev        = raw.get("deviation_pct")
    raw_col        = raw.get("column_name") or ""
    raw_detail     = (
        f"{raw_check_type}"
        + (f" · {raw_col}" if raw_col and raw_col != "None" else "")
        + (f"  {raw_dev:.1f}%" if raw_dev is not None else "")
        if raw_check_type
        else "No Validation Agent data for this date"
    )

    # ── Node definitions ───────────────────────────────────────────────────
    # Each tuple:
    # (y_center, layer_label, main_label, detail_text, status, click_tag)

    nodes = [
        (
            4.0,
            "KPI DEFINITION",
            kpi_name,
            kpi_formula or kpi_detail_str(kpi_check, kpi_dev),
            kpi_status,
            "kpi"
        ),
        (
            3.0,
            "GOLD LAYER  ·  KPI Assurance Agent",
            gold_table,
            gold_detail,
            gold_status,
            "gold"
        ),
        (
            2.0,
            "SILVER LAYER  ·  Reconciliation Agent",
            silver_table,
            silver_detail,
            silver_status,
            "silver"
        ),
        (
            1.0,
            "RAW LAYER  ·  Validation Agent",
            raw_table,
            raw_detail,
            raw_status,
            "raw"
        ),
        (
            0.0,
            "SOURCE SYSTEM",
            source_label,
            f"{src.get('ingestion_frequency','')}"
            .strip(" /") or "External data source",
            "UNKNOWN",
            "source"
        ),
    ]

    # ── Canvas ─────────────────────────────────────────────────────────────

    fig = go.Figure()

    fig.update_layout(
        height        = 620,
        paper_bgcolor = "#1a1a1a",
        plot_bgcolor  = "#1a1a1a",
        margin        = dict(l=10, r=10, t=10, b=10),
        showlegend    = False,
        xaxis = dict(
            visible    = False,
            range      = [0, 10],
            fixedrange = True,
        ),
        yaxis = dict(
            visible    = False,
            range      = [-0.55, 4.55],
            fixedrange = True,
        ),
        hovermode = "closest",
            hoverlabel = dict(
            bgcolor   = "#2b2b2b",
            bordercolor = "#555555",
            font_size = 13,
            font_color = "#ffffff",
        ),
        # Plotly respects this for cursor
        dragmode = False,
    )

    shapes      = []
    annotations = []

    NODE_W  = 7.2    # total width
    NODE_H  = 0.38   # half-height
    X_LEFT  = (10 - NODE_W) / 2        # = 1.4
    X_RIGHT = X_LEFT + NODE_W          # = 8.6
    X_MID   = 5.0
    ACCENT  = 0.18   # accent bar width

    # ── Draw connector arrows ──────────────────────────────────────────────
    ARROW_COLOR = "#444444"

    for i in range(len(nodes) - 1):
        y_top    = nodes[i][0] - NODE_H - 0.04       # bottom of upper node
        y_bottom = nodes[i + 1][0] + NODE_H + 0.04   # top of lower node

        # Connector line
        shapes.append(dict(
            type      = "line",
            x0=X_MID, y0=y_top,
            x1=X_MID, y1=y_bottom,
            line      = dict(color=ARROW_COLOR, width=2),
            layer     = "below",
        ))

        # Arrowhead pointing UP (child feeds parent)
        # Drawn as a small triangle annotation at top of connector
        mid_y = (y_top + y_bottom) / 2 + 0.02
        annotations.append(dict(
            x         = X_MID,
            y         = y_bottom + 0.01,   # tip of arrow at TOP (pointing up)
            xref="x", yref="y",
            axref="x", ayref="y",
            ax        = X_MID,
            ay        = y_bottom + 0.14,   # tail BELOW tip → arrow points UP
            text      = "",
            showarrow = True,
            arrowhead = 2,
            arrowsize = 1.4,
            arrowwidth= 2,
            arrowcolor= ARROW_COLOR,
        ))


        # "↑ feeds into" label on connector
        annotations.append(dict(
            x         = X_MID + 0.25,
            y         = mid_y,
            xref="x", yref="y",
            text      = "↑ feeds into",
            showarrow = False,
            font      = dict(color="#444444", size=10, family="monospace"),
            xanchor   = "left",
            yanchor   = "middle",
        ))

    # ── Draw nodes ─────────────────────────────────────────────────────────

    for (yc, layer_label, main_label, detail_text, status, tag) in nodes:
        colors = _node_colors(status)
        emoji  = _STATUS_EMOJI.get(
            status if status in _STATUS_EMOJI else "UNKNOWN", "⚪"
        )

        y0 = yc - NODE_H
        y1 = yc + NODE_H

        # ── Node background ────────────────────────────────────────────────
        shapes.append(dict(
            type      = "rect",
            x0=X_LEFT, y0=y0,
            x1=X_RIGHT, y1=y1,
            fillcolor = "#252525",
            line      = dict(color="#3a3a3a", width=1),
            layer     = "above",
        ))

        # ── Left accent bar (status colour) ───────────────────────────────
        shapes.append(dict(
            type      = "rect",
            x0=X_LEFT, y0=y0,
            x1=X_LEFT + ACCENT, y1=y1,
            fillcolor = colors["border"],
            line      = dict(width=0),
            layer     = "above",
        ))

        # ── Status emoji + dot at right edge ──────────────────────────────
        shapes.append(dict(
            type      = "circle",
            x0=X_RIGHT - 0.32, y0=yc - 0.10,
            x1=X_RIGHT - 0.08, y1=yc + 0.10,
            fillcolor = colors["bg"],
            line      = dict(color=colors["border"], width=1.5),
            layer     = "above",
        ))

        # ── Layer label (top-left, small caps) ────────────────────────────
        annotations.append(dict(
            x         = X_LEFT + ACCENT + 0.18,
            y         = y1 - 0.07,
            xref="x", yref="y",
            text      = f"<b>{layer_label}</b>",
            showarrow = False,
            font      = dict(
                color  = colors["text"],
                size   = 9,
                family = "monospace",
            ),
            xanchor   = "left",
            yanchor   = "top",
        ))

        # ── Main label (table / KPI name) ─────────────────────────────────
        annotations.append(dict(
            x         = X_LEFT + ACCENT + 0.18,
            y         = yc + 0.04,
            xref="x", yref="y",
            text      = f"<b>{main_label}</b>",
            showarrow = False,
            font      = dict(
                color  = "#ffffff",
                size   = 13,
                family = "sans-serif",
            ),
            xanchor   = "left",
            yanchor   = "middle",
        ))

        # ── Detail text (status metric) ───────────────────────────────────
        annotations.append(dict(
            x         = X_LEFT + ACCENT + 0.18,
            y         = y0 + 0.10,
            xref="x", yref="y",
            text      = f"{emoji}  {detail_text}",
            showarrow = False,
            font      = dict(
                color  = colors["text"],
                size   = 11,
            ),
            xanchor   = "left",
            yanchor   = "bottom",
        ))

        # ── Status emoji text in circle ───────────────────────────────────
        annotations.append(dict(
            x         = X_RIGHT - 0.20,
            y         = yc,
            xref="x", yref="y",
            text      = emoji,
            showarrow = False,
            font      = dict(size=12),
            xanchor   = "center",
            yanchor   = "middle",
        ))

        annotations.append(dict(
            x         = 5,
            y         = -0.48,
            xref      = "x",
            yref      = "y",
            text      = "↓  Click a card below to navigate to that agent's page",
            showarrow = False,
            font      = dict(
                color  = "#555555",
                size   = 11,
                family = "monospace",
            ),
            xanchor   = "center",
            yanchor   = "bottom",
        ))


    fig.update_layout(shapes=shapes, annotations=annotations)
    return fig


def kpi_detail_str(check_type: str, deviation) -> str:
    """Helper to format KPI detail string."""
    if not check_type:
        return "No data"
    return (
        f"{check_type}  {deviation:+.1f}%"
        if deviation is not None
        else check_type
    )


def _nav_url_for_tag(
    tag          : str,
    gold_fqn     : str,
    business_date: str,
    lineage      : dict
) -> str:
    """Returns the navigation URL for a clicked lineage node."""
    source_fqn = (
        lineage.get("layers", {})
               .get("BRONZE", {})
               .get("source_fully_qualified_name", "")
    )

    if tag == "kpi" or tag == "gold":
        return "/kpi-validation"
    elif tag == "silver":
        return "/reconciliation"
    elif tag == "raw":
        return "/validation-results"
    else:
        return "/table-registry"


# ══════════════════════════════════════════════════════════════════════════
# LINEAGE CALLBACKS
# ══════════════════════════════════════════════════════════════════════════
def _build_lineage_diagram_area(
    lineage      : dict,
    gold_fqn     : str,
    business_date: str,
) -> list:
    """
    Builds the graph + status strip + legend + summary.
    Called on initial render and on every KPI selector change.
    Kept separate from the selector so the dropdown value
    is never reset when the diagram updates.
    """
    layers = lineage.get("layers", {})

    gold_status   = str(lineage.get("gold", {})
                        .get("check_status", "UNKNOWN"))
    silver_status = (str(lineage.get("silver", {})
                         .get("check_status", "UNKNOWN"))
                     if lineage.get("silver") else "UNKNOWN")
    raw_status    = (str(lineage.get("raw", {})
                         .get("check_status", "UNKNOWN"))
                     if lineage.get("raw") else "UNKNOWN")

    def _status_pill(label: str, status: str) -> html.Span:
        colors = _node_colors(status)
        emoji  = _STATUS_EMOJI.get(
            status if status in _STATUS_EMOJI else "UNKNOWN", "⚪"
        )
        return html.Span(
            f"{emoji} {label}",
            style={
                "backgroundColor": colors["bg"],
                "border"         : f"1px solid {colors['border']}",
                "borderRadius"   : "12px",
                "padding"        : "3px 10px",
                "fontSize"       : "12px",
                "color"          : colors["text"],
                "marginRight"    : "8px",
            }
        )

    status_strip = html.Div([
        html.Span(
            "Pipeline health: ",
            style={"color": "#aaaaaa", "fontSize": "12px",
                   "marginRight": "8px"}
        ),
        _status_pill("Raw",    raw_status),
        html.Span("→", style={"color": "#555", "marginRight": "8px",
                               "fontSize": "12px"}),
        _status_pill("Silver", silver_status),
        html.Span("→", style={"color": "#555", "marginRight": "8px",
                               "fontSize": "12px"}),
        _status_pill("Gold",   gold_status),
    ], style={"marginBottom": "16px"})

    legend = html.Div([
        html.Span("Legend: ",
                  style={"color": "#aaaaaa", "fontSize": "12px"}),
        html.Span("🔴 Critical  ",
                  style={"color": "#ff6b6b", "fontSize": "12px"}),
        html.Span("🟡 Warning  ",
                  style={"color": "#ffa500", "fontSize": "12px"}),
        html.Span("🟢 Pass  ",
                  style={"color": "#00c851", "fontSize": "12px"}),
        html.Span("⚪ No data",
                  style={"color": "#aaaaaa", "fontSize": "12px"}),
    ], style={"marginBottom": "8px"})

    fig = _build_lineage_figure(lineage, gold_fqn, business_date)

    summary_rows = _build_lineage_summary(lineage, gold_fqn, business_date)

    return [
        status_strip,
        legend,
        dcc.Graph(
            id     = "kpi-lineage-graph",
            figure = fig,
            config = {
                "displayModeBar": False,
                "scrollZoom"    : False,
            },
            style  = {
                "borderRadius": "8px",
                "cursor"      : "default",
            }
        ),
        html.P(
            "The diagram above shows data flow. "
            "Use the cards below to navigate to each agent's results.",
            style={
                "color"    : "#555555",
                "fontSize" : "12px",
                "textAlign": "center",
                "marginTop": "8px",
            }
        ),
        html.Hr(style={"borderColor": "#333", "margin": "20px 0"}),
        html.H6(
            "Layer-by-Layer Detail",
            style={"color": "#ffffff", "fontSize": "14px",
                   "fontWeight": "600", "marginBottom": "12px"}
        ),
        *summary_rows,
    ]

@callback(
    Output("kpi-lineage-container", "children"),
    Input("kpi-tabs", "active_tab"),
    Input("kpi-runs-table", "selectedRows"),
    Input("kpi-runs-table", "cellClicked"),
    State("kpi-runs-table", "rowData"),
    prevent_initial_call=True,
)
def render_lineage_tab(active_tab, selected_rows, active_cell, data):
    """
    Renders the lineage diagram when the Lineage tab is active
    and a run is selected.
    """
    if active_tab != "tab-lineage":
        return html.Div()

    placeholder = html.P(
        "Select a validation run from the History tab to view lineage.",
        className="text-muted"
    )

    if not data:
        return placeholder

    row = None
    if active_cell:
        row_index = active_cell.get("rowIndex")
        if row_index is not None and row_index < len(data):
            row = data[row_index]
    elif selected_rows:
        row = selected_rows[0]

    if row is None:
        return placeholder
    gold_fqn     = row.get("gold_fully_qualified_name", "")
    business_date= str(row.get("business_date", ""))
    gold_table   = row.get("gold_table", gold_fqn.split(".")[-1])

    if not gold_fqn or not business_date:
        return placeholder

    # Load the worst-status KPI for this run to anchor the lineage
    try:
        df_kpi = execute_query("""
            SELECT kpi_name
            FROM learning_dev.s819534.uc4_kpi_validation_results_b
            WHERE validation_run_id = :validation_run_id
            ORDER BY
                CASE check_status
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'WARNING'  THEN 2
                    ELSE 3
                END,
                kpi_name
            LIMIT 1
        """, {"validation_run_id": row.get("validation_run_id", "")})
        anchor_kpi = df_kpi.iloc[0]["kpi_name"] if not df_kpi.empty else None
    except Exception as e:
        logger.error(f"Lineage: anchor KPI load failed: {e}")
        anchor_kpi = None

    # Load all lineage data
    lineage = _load_lineage_data(gold_fqn, business_date, anchor_kpi)

    # Build selector for which KPI to show lineage for
    try:
        df_kpis = execute_query("""
            SELECT DISTINCT kpi_name, check_status
            FROM learning_dev.s819534.uc4_kpi_validation_results_b
            WHERE validation_run_id = :validation_run_id
            ORDER BY
                CASE check_status
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'WARNING'  THEN 2
                    ELSE 3
                END,
                kpi_name
        """, {"validation_run_id": row.get("validation_run_id", "")})
        kpi_options = [
            {
                "label": f"{r['kpi_name']} ({r['check_status']})",
                "value": r["kpi_name"]
            }
            for _, r in df_kpis.iterrows()
        ] if not df_kpis.empty else []
    except Exception:
        kpi_options = []

    fig = _build_lineage_figure(lineage, gold_fqn, business_date)

    # ── Legend ─────────────────────────────────────────────────────────────
    legend = html.Div([
        html.Span("Legend: ", style={"color": "#aaaaaa", "fontSize": "12px"}),
        html.Span("🔴 Critical  ",
                  style={"color": "#ff6b6b", "fontSize": "12px"}),
        html.Span("🟡 Warning  ",
                  style={"color": "#ffa500", "fontSize": "12px"}),
        html.Span("🟢 Pass  ",
                  style={"color": "#00c851", "fontSize": "12px"}),
        html.Span("⚪ No data",
                  style={"color": "#aaaaaa", "fontSize": "12px"}),
    ], style={"marginBottom": "8px"})

    # ── Status summary strip ───────────────────────────────────────────────
    gold_status   = str(lineage.get("gold", {}).get("check_status", "UNKNOWN"))
    silver_status = str(lineage.get("silver", {}).get("check_status", "UNKNOWN")) \
                    if lineage.get("silver") else "UNKNOWN"
    raw_status    = str(lineage.get("raw", {}).get("check_status", "UNKNOWN")) \
                    if lineage.get("raw") else "UNKNOWN"

    def _status_pill(label: str, status: str) -> html.Span:
        colors = _node_colors(status)
        emoji  = _STATUS_EMOJI.get(
            status if status in _STATUS_EMOJI else "UNKNOWN", "⚪"
        )
        return html.Span(
            f"{emoji} {label}",
            style={
                "backgroundColor": colors["bg"],
                "border"         : f"1px solid {colors['border']}",
                "borderRadius"   : "12px",
                "padding"        : "3px 10px",
                "fontSize"       : "12px",
                "color"          : colors["text"],
                "marginRight"    : "8px",
            }
        )

    status_strip = html.Div([
        html.Span(
            "Pipeline health: ",
            style={"color": "#aaaaaa", "fontSize": "12px",
                   "marginRight": "8px"}
        ),
        _status_pill("Raw",    raw_status),
        html.Span(
            "→",
            style={"color": "#555", "marginRight": "8px", "fontSize": "12px"}
        ),
        _status_pill("Silver", silver_status),
        html.Span(
            "→",
            style={"color": "#555", "marginRight": "8px", "fontSize": "12px"}
        ),
        _status_pill("Gold",   gold_status),
    ], style={"marginBottom": "16px"})

    # ── KPI selector (only shown when multiple KPIs exist) ─────────────────
    kpi_selector = html.Div()
    if len(kpi_options) > 1:
        from dash import dcc as _dcc
        kpi_selector = html.Div([
            html.Label(
                "Select KPI to trace:",
                style={"color": "#aaaaaa", "fontSize": "13px",
                       "marginBottom": "4px", "display": "block"}
            ),
            _dcc.Dropdown(
                id      = "kpi-lineage-kpi-selector",
                options = kpi_options,
                value   = anchor_kpi,
                clearable   = False,
                style={
                    "backgroundColor": "#2b2b2b",
                    "color"          : "#ffffff",
                    "fontSize"       : "13px",
                    "marginBottom"   : "16px",
                    "maxWidth"       : "400px",
                }
            ),
        ])

    # ── Navigation hint ────────────────────────────────────────────────────
    nav_hint = html.P(
        "Click any node to navigate to that agent's results page.",
        style={"color": "#555555", "fontSize": "12px",
               "textAlign": "center", "marginTop": "8px"}
    )

    # ── Summary table below diagram ────────────────────────────────────────
    summary_rows = _build_lineage_summary(lineage, gold_fqn, business_date)

    return html.Div([
        # Header — static
        html.Div([
            html.H6(
                f"Data Lineage — {gold_table} on {business_date}",
                style={"color": "#ffffff", "fontSize": "15px",
                    "fontWeight": "600", "marginBottom": "4px"}
            ),
            html.P(
                "Traces this KPI from its Gold table back through "
                "Silver transformation and Raw ingestion to the "
                "source system. Click any node to navigate to that "
                "agent's results page.",
                style={"color": "#888888", "fontSize": "13px",
                    "marginBottom": "16px"}
            ),
        ]),

        # KPI selector — static, drives the diagram below
        kpi_selector,

        # Everything below the selector is in its own Div
        # so the selector callback can update it without
        # re-rendering and resetting the dropdown value
        html.Div(
            id = "kpi-lineage-diagram-area",
            children = _build_lineage_diagram_area(
                lineage, gold_fqn, business_date
            )
        ),
    ])


@callback(
    Output("kpi-lineage-diagram-area", "children"),
    Input("kpi-lineage-kpi-selector", "value"),
    State("kpi-runs-table", "selectedRows"),
    State("kpi-runs-table", "cellClicked"),
    State("kpi-runs-table", "rowData"),
    prevent_initial_call=True,
)
def update_lineage_on_kpi_change(kpi_name, selected_rows, active_cell, data):
    """
    Updates graph + summary when user picks a different KPI.
    Selector div is not touched so dropdown value is preserved.
    """
    if not kpi_name or not data:
        return dash.no_update

    row = None
    if active_cell:
        row_index = active_cell.get("rowIndex")
        if row_index is not None and row_index < len(data):
            row = data[row_index]
    elif selected_rows:
        row = selected_rows[0]

    if row is None:
        return dash.no_update
    gold_fqn      = row.get("gold_fully_qualified_name", "")
    business_date = str(row.get("business_date", ""))

    if not gold_fqn or not business_date:
        return dash.no_update

    lineage = _load_lineage_data(gold_fqn, business_date, kpi_name)
    return _build_lineage_diagram_area(lineage, gold_fqn, business_date)


# ══════════════════════════════════════════════════════════════════════════
# LINEAGE SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════

def _build_lineage_summary(
    lineage      : dict,
    gold_fqn     : str,
    business_date: str
) -> list:
    """
    Builds a set of detail cards below the diagram —
    one per layer — showing the specific check results
    that contributed to that layer's status.
    """
    elements = []

    layers = lineage.get("layers", {})
    gold   = lineage.get("gold", {})
    silver = lineage.get("silver", {})
    raw    = lineage.get("raw", {})
    src    = lineage.get("source_system", {})
    kpi    = lineage.get("kpi", {})

    gold_table   = gold_fqn.split(".")[-1]
    silver_table = (layers.get("SILVER", {})
                    .get("layer_fully_qualified_name", "Silver")
                    .split(".")[-1])
    raw_table    = (layers.get("BRONZE", {})
                    .get("source_fully_qualified_name", "Bronze")
                    .split(".")[-1])

    def _detail_card(
        layer_label : str,
        table_name  : str,
        status      : str,
        facts       : list,
        nav_href    : str,
        nav_label   : str,
    ) -> html.A:
        colors = _node_colors(status)
        emoji  = _STATUS_EMOJI.get(
            status if status in _STATUS_EMOJI else "UNKNOWN", "⚪"
        )

        fact_elements = []
        for name, value in facts:
            fact_elements.append(
                dbc.Row([
                    dbc.Col(
                        html.Small(
                            name,
                            style={"color": "#888888"}
                        ),
                        width=5
                    ),
                    dbc.Col(
                        html.Small(
                            str(value),
                            style={
                                "color"     : colors["text"],
                                "fontWeight": "500"
                            }
                        ),
                        width=7
                    ),
                ], className="mb-1")
            )

        card_content = dbc.Row([
            dbc.Col([
                html.Span(
                    layer_label,
                    style={
                        "color"        : colors["text"],
                        "fontSize"     : "11px",
                        "textTransform": "uppercase",
                        "letterSpacing": "1px",
                        "display"      : "block",
                        "fontFamily"   : "monospace",
                    }
                ),
                html.Span(
                    f"{emoji}  {table_name}",
                    style={
                        "color"     : "#ffffff",
                        "fontSize"  : "14px",
                        "fontWeight": "600",
                    }
                ),
            ], md=4),
            dbc.Col(fact_elements, md=6),
            dbc.Col([
                html.Div(
                    "Open →",
                    style={
                        "fontSize"       : "13px",
                        "color"          : "#4a9edd",
                        "fontWeight"     : "600",
                        "textAlign"      : "center",
                        "padding"        : "6px 12px",
                        "borderRadius"   : "6px",
                        "backgroundColor": "#1a1a1a",
                        "border"         : "1px solid #3a3a3a",
                        "whiteSpace"     : "nowrap",
                    }
                ),
                html.Div(
                    nav_label,
                    style={
                        "fontSize" : "11px",
                        "color"    : "#aaaaaa",
                        "textAlign": "center",
                        "marginTop": "2px",
                    }
                ),
            ], md=2,
            className="d-flex flex-column align-items-center justify-content-center"),
        ], align="center")

        # Entire card is wrapped in html.A — clicking anywhere navigates.
        # No Dash callback, no dcc.Location, no Plotly clickData needed.
        return html.A(
            html.Div(
                card_content,
                className = "lineage-card",
                style={
                    "backgroundColor": colors["bg"],
                    "borderLeft"     : f"3px solid {colors['border']}",
                    "borderRadius"   : "6px",
                    "padding"        : "12px 16px",
                    "marginBottom"   : "8px",
                    "transition"     : "filter 0.15s ease",
                }
            ),
            href  = nav_href,
            style = {
                "textDecoration": "none",
                "display"       : "block",
                "cursor"        : "pointer",
            }
        )

    # ── Gold card ──────────────────────────────────────────────────────────
    gold_status  = str(gold.get("check_status", "UNKNOWN"))
    gold_dev     = gold.get("deviation_pct")
    gold_check   = gold.get("check_type", "—")
    gold_obs     = gold.get("observed_value")
    gold_exp     = gold.get("expected_value")
    gold_cat     = gold.get("ai_failure_category", "—")

    gold_facts = [
        ("KPI",          kpi.get("kpi_name", "—")),
        ("Check type",   gold_check),
        ("Observed",     f"{gold_obs}" if gold_obs is not None else "—"),
        ("Expected",     f"{gold_exp}" if gold_exp is not None else "—"),
        ("Deviation",    f"{gold_dev:+.1f}%" if gold_dev is not None else "—"),
        ("AI category",  gold_cat or "—"),
    ]
    elements.append(_detail_card(
        "Gold Layer", gold_table,
        gold_status, gold_facts,
        "/kpi-validation", "View in KPI Assurance Agent →"
    ))

    # ── Silver card ────────────────────────────────────────────────────────
    silver_status  = str(silver.get("check_status", "UNKNOWN")) \
                     if silver else "UNKNOWN"
    survival_pct   = silver.get("survival_pct")
    raw_count      = silver.get("raw_count")
    silver_count   = silver.get("silver_count")
    expected_surv  = (layers.get("SILVER", {})
                      .get("expected_survival_rate", 0.92))

    silver_facts = [
        ("Check type",        "RAW → SILVER row count"),
        ("Raw records",       f"{int(raw_count):,}"
                              if raw_count is not None else "—"),
        ("Silver records",    f"{int(silver_count):,}"
                              if silver_count is not None else "—"),
        ("Actual survival",   f"{survival_pct:.1f}%"
                              if survival_pct is not None else "—"),
        ("Expected survival", f"{float(expected_surv)*100:.0f}%"
                              if expected_surv else "—"),
    ]
    elements.append(_detail_card(
        "Silver Layer", silver_table,
        silver_status, silver_facts,
        "/reconciliation", "View in Reconciliation Agent →"
    ))

    # ── Raw card ───────────────────────────────────────────────────────────
    raw_status     = str(raw.get("check_status", "UNKNOWN")) \
                     if raw else "UNKNOWN"
    raw_check_type = raw.get("check_type", "—")
    raw_col        = raw.get("column_name", "") or ""
    raw_dev        = raw.get("deviation_pct")
    raw_obs        = raw.get("observed_value")

    raw_facts = [
        ("Worst check",   raw_check_type),
        ("Column",        raw_col if raw_col and raw_col != "None" else "table-level"),
        ("Observed",      f"{raw_obs}" if raw_obs is not None else "—"),
        ("Deviation",     f"{raw_dev:.1f}%"
                          if raw_dev is not None else "—"),
        ("Ingestion",     src.get("ingestion_pattern", "—")),
        ("Frequency",     src.get("ingestion_frequency", "—")),
    ]
    elements.append(_detail_card(
        "Raw Layer", raw_table,
        raw_status, raw_facts,
        "/validation-results", "View in Validation Agent →"
    ))

    # ── Source system card ─────────────────────────────────────────────────
    src_facts = [
        ("Source type",  src.get("source_type", "—")),
        ("Pattern",      src.get("ingestion_pattern", "—")),
        ("Frequency",    src.get("ingestion_frequency", "—")),
    ]
    elements.append(_detail_card(
        "Source System",
        src.get("source_type", "External System"),
        "UNKNOWN", src_facts,
        "/table-registry", "View in Table Registry →"
    ))

    return elements