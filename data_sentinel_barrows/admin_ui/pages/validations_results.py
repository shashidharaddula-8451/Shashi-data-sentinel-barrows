# pages/validations_results.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import logging
from db.connection import execute_query
from db.queries import (
    get_validation_run_summary,
    get_validation_results_for_run
)
from components.alerts import (
    error_alert,
    info_alert,
    build_alert_modal,
    build_alert_card_body,
    STATUS_EMOJI,
    STATUS_COLOR,
    fmt_number,
    fmt_deviation,
    fmt_threshold,
    compute_signed_deviation,
    ag_grid_props,
    AG_STATUS_CELL_STYLE_JS,
    status_badge,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/validation-results",
    name="Validation Results"
)

layout = dbc.Container([

    html.H2("Validation Agent — Raw Ingestion", className="mt-4 mb-2"),
    html.P(
        "View raw ingestion validation history. "
        "Select a run to see individual check results and AI analysis. "
        "Click Preview Teams Alert to see what was sent to the channel.",
        className="text-muted mb-4"
    ),

    html.Div(id="val-results-alert"),

    # ── Filters ────────────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Status", className="text-white"),
                    dcc.Dropdown(
                        id="val-status-filter",
                        options=[
                            {"label": "All",        "value": "ALL"},
                            {"label": "🔴 Critical","value": "CRITICAL"},
                            {"label": "🟡 Warning", "value": "WARNING"},
                            {"label": "🟢 Pass",    "value": "PASS"}
                        ],
                        value="ALL",
                        clearable=False,
                        style={"backgroundColor": "#2b2b2b", "color": "#ffffff"}
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("Table", className="text-white"),
                    dcc.Dropdown(
                        id="val-table-filter",
                        placeholder="All tables...",
                        clearable=True,
                        style={"backgroundColor": "#2b2b2b", "color": "#ffffff"}
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Date", className="text-white"),
                    dbc.Input(
                        id="val-date-filter",
                        type="text",
                        placeholder="e.g. 2026-06-24",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "Refresh",
                        id="refresh-val-runs-btn",
                        color="secondary",
                        className="d-block w-100"
                    )
                ], md=2)
            ])
        ])
    ], className="mb-4"),

    # ── Validation Run History (AG Grid) ────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Validation Run History", className="mb-0 text-white")
        ),
        dbc.CardBody([
            html.Div(
                dag.AgGrid(
                    **ag_grid_props(
                        grid_id="val-runs-table",
                        row_data=[],
                        col_defs=[
                            {"field": "business_date",         "headerName": "Date",  "minWidth": 120},
                            {"field": "table_name",            "headerName": "Table",    "flex": 2, "minWidth": 220},
                            {"field": "overall_status",        "headerName": "Status",   "minWidth": 150,
                             "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                            {"field": "total_checks_run",      "headerName": "Checks",   "width": 90},
                            {"field": "total_checks_passed",   "headerName": "Passed",   "width": 90},
                            {"field": "total_checks_warned",   "headerName": "Warned",   "width": 90},
                            {"field": "total_checks_critical", "headerName": "Critical", "width": 95},
                            {"field": "ai_enrichment_status",  "headerName": "AI",    "minWidth": 150},
                            {"field": "alert_fired",           "headerName": "Alert",    "width": 90},
                        ],
                        page_size=12,
                        selection="single",
                        status_col="overall_status",
                    )
                ),
                style={"padding": "0 16px 16px"},
            ),
            # Preview button — visible only when alerted run is selected
            html.Div(
                dbc.Button(
                    "👁 Preview Teams Alert",
                    id="a1-preview-btn",
                    color="info",
                    outline=True,
                    size="sm",
                    n_clicks=0,
                    style={"display": "none"}
                ),
                className="mt-2",
            ),
        ]),
    ], className="mb-4"),

    # ── Check Results Detail ───────────────────────────────────────────────
    dcc.Loading(
        id    = "val-results-loading",
        type  = "circle",
        color = "#00c851",
        children = [
            dbc.Card([
                dbc.CardHeader(
                    html.H5("Check Results Detail", className="mb-0",
                            id="check-detail-header")
                ),
                dbc.CardBody([
                    html.Div(
                        "Select a run above to see check details.",
                        id="check-detail-container",
                        className="text-muted"
                    )
                ])
            ], className="mb-4"),

            # ── AI Analysis ────────────────────────────────────────────────
            dbc.Card([
                dbc.CardHeader(html.H5("🤖 AI Analysis", className="mb-0")),
                dbc.CardBody([
                    html.Div(
                        "AI analysis appears here when a run with "
                        "AI enrichment is selected.",
                        id="ai-analysis-panel",
                        className="text-muted"
                    )
                ])
            ], className="mb-4"),
        ]
    ),

    # ── Shared components ──────────────────────────────────────────────────
    dcc.Store(id="a1-alert-store", data=None),
    build_alert_modal(modal_id="a1-alert-modal")

], fluid=True)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("val-runs-table", "rowData"),
    Output("val-table-filter", "options"),
    Input("refresh-val-runs-btn", "n_clicks"),
    Input("val-status-filter", "value"),
    Input("val-table-filter", "value"),
    Input("val-date-filter", "value"),
    prevent_initial_call=False
)
def load_validation_runs(n_clicks, status_filter, table_filter, date_filter):
    try:
        df = execute_query(get_validation_run_summary())
        if df.empty:
            return [], []

        table_options = [
            {"label": t, "value": t}
            for t in sorted(df["table_name"].dropna().unique().tolist())
        ]

        def safe_int(val, default=0):
            try:
                return int(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        if status_filter and status_filter != "ALL":
            df = df[df["overall_status"] == status_filter]
        if table_filter:
            df = df[df["table_name"] == table_filter]
        if date_filter and date_filter.strip():
            df = df[
                df["business_date"].astype(str).str.contains(
                    date_filter.strip(), na=False
                )
            ]

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "validation_run_id"    : str(row.get("validation_run_id", "")),
                "business_date"        : str(row.get("business_date", "")),
                "table_name"           : str(row.get("table_name", "")),
                "fully_qualified_name" : str(row.get("fully_qualified_name", "")),
                "overall_status"       : str(row.get("overall_status", "")),
                "total_checks_run"     : safe_int(row.get("total_checks_run")),
                "total_checks_passed"  : safe_int(row.get("total_checks_passed")),
                "total_checks_warned"  : safe_int(row.get("total_checks_warned")),
                "total_checks_critical": safe_int(row.get("total_checks_critical")),
                "ai_enrichment_status" : str(row.get("ai_enrichment_status", "")),
                "alert_fired"          : str(row.get("alert_fired", "NO"))
            })

        return rows, table_options

    except Exception as e:
        logger.error(f"Failed to load validation runs: {str(e)}")
        return [], []


@callback(
    Output("check-detail-header", "children"),
    Output("check-detail-container", "children"),
    Output("ai-analysis-panel", "children"),
    Output("a1-preview-btn", "style"),
    Output("a1-alert-store", "data"),
    Input("val-runs-table", "selectedRows"),
    prevent_initial_call=True
)
def load_check_details(selected_rows):
    hidden  = {"display": "none"}
    visible = {"display": "inline-block"}

    if not selected_rows:
        return (
            "Check Results Detail",
            html.P("Select a run above.", className="text-muted"),
            html.P("AI analysis appears here.", className="text-muted"),
            hidden,
            None
        )

    row     = selected_rows[0]
    run_id  = row.get("validation_run_id", "")
    table   = row.get("table_name", "")
    date    = row.get("business_date", "")
    status  = row.get("overall_status", "")
    alerted = row.get("alert_fired", "NO")
    emoji   = STATUS_EMOJI.get(status, "⚪")

    header  = f"Check Results — {table} on {date}  {emoji} {status}"

    if not run_id:
        return header, error_alert("No run ID."), html.Div(), hidden, None

    try:
        df = execute_query(*get_validation_results_for_run(run_id))

        if df.empty:
            return (
                header,
                info_alert("No check results found."),
                html.Div(),
                hidden,
                None
            )

        def safe_float(val):
            try:
                return round(float(val), 4) if val is not None else None
            except (TypeError, ValueError):
                return None

        table_rows = []
        for _, r in df.iterrows():
            check_type   = str(r.get("check_type", ""))
            check_status = str(r.get("check_status", ""))
            obs_raw      = r.get("observed_value")
            base_raw     = r.get("baseline_value")
            dev_raw      = r.get("deviation_pct")

            # Compute signed deviation
            signed_dev = compute_signed_deviation(obs_raw, base_raw, check_type)

            table_rows.append({
                "check_type"    : check_type,
                "check_level"   : str(r.get("check_level", "")),
                "column_name"   : str(r.get("column_name", "") or "table-level"),
                "check_status"  : check_status,
                "observed_value": fmt_number(obs_raw),
                "baseline_value": fmt_number(base_raw),
                "deviation_pct" : fmt_deviation(signed_dev, check_type),
                "warn_threshold": fmt_threshold(r.get("threshold_warning")),
                "crit_threshold": fmt_threshold(r.get("threshold_critical")),
            })
        
        detail_table = dag.AgGrid(
            **ag_grid_props(
                grid_id="val-check-detail-grid",
                row_data=table_rows,
                col_defs=[
                    {"field": "check_type",     "headerName": "Check Type",  "flex": 1, "minWidth": 200},
                    {"field": "check_level",    "headerName": "Level",    "minWidth": 150},
                    {"field": "column_name",    "headerName": "Column",      "flex": 1, "minWidth": 220},
                    {"field": "check_status",   "headerName": "Status",   "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "observed_value", "headerName": "Observed",    "width": 110},
                    {"field": "baseline_value", "headerName": "Baseline",    "width": 110},
                    {"field": "deviation_pct",  "headerName": "Deviation %", "width": 110},
                    {"field": "warn_threshold", "headerName": "Warn",        "width": 110},
                    {"field": "crit_threshold", "headerName": "Critical",    "width": 110},
                ],
                page_size=20,
                status_col="check_status",
            )
        )

        # AI Panel
        ai_rows = df[df["ai_summary"].notna() & (df["ai_summary"] != "")]
        if ai_rows.empty:
            ai_panel = dbc.Alert(
                "No AI enrichment for this run. "
                "AI triggers when 2+ checks fail with 1+ CRITICAL.",
                color="info"
            )
        else:
            first         = ai_rows.iloc[0]
            ai_summary    = str(first.get("ai_summary", ""))
            ai_action     = str(first.get("ai_recommended_action", ""))
            ai_category   = str(first.get("ai_failure_category", ""))
            ai_confidence = first.get("ai_confidence_score")

            try:
                conf_pct = f"{float(ai_confidence):.0%}"
            except (TypeError, ValueError):
                conf_pct = "N/A"

            ai_panel = dbc.Container([
                dbc.Row([
                    dbc.Col([
                        dbc.Badge(
                            ai_category or "N/A",
                            color=STATUS_COLOR.get(status, "secondary"),
                            className="me-2 mb-2 fs-6"
                        ),
                        dbc.Badge(
                            f"Confidence: {conf_pct}",
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
                        html.H6("Recommended Action", className="text-success mt-2"),
                        html.P(
                            ai_action or "No specific action.",
                            className="border-start border-success ps-3"
                        )
                    ], md=6)
                ])
            ], fluid=True)

        # Store data for modal
        store_data = {
            "validation_run_id"    : run_id,
            "table_name"           : table,
            "fully_qualified_name" : row.get("fully_qualified_name", ""),
            "business_date"        : date,
            "overall_status"       : status,
            "total_checks_run"     : row.get("total_checks_run", 0),
            "total_checks_passed"  : row.get("total_checks_passed", 0),
            "total_checks_warned"  : row.get("total_checks_warned", 0),
            "total_checks_critical": row.get("total_checks_critical", 0),
            "ai_enrichment_status" : row.get("ai_enrichment_status", "")
        }

        btn_style = visible if alerted == "YES" else hidden

        return header, detail_table, ai_panel, btn_style, store_data

    except Exception as e:
        logger.error(f"Failed to load check details: {str(e)}")
        return header, error_alert(str(e)), html.Div(), hidden, None


@callback(
    Output("a1-alert-modal", "is_open"),
    Output("a1-alert-modal-title", "children"),
    Output("a1-alert-modal-body", "children"),
    Input("a1-preview-btn", "n_clicks"),
    Input("a1-alert-modal-close-btn", "n_clicks"),
    State("a1-alert-store", "data"),
    State("a1-alert-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_a1_modal(open_clicks, close_clicks, store_data, is_open):
    triggered = ctx.triggered_id

    if triggered == "a1-alert-modal-close-btn":
        return False, "", []

    if triggered == "a1-preview-btn" and store_data:
        run_id = store_data.get("validation_run_id", "")
        status = store_data.get("overall_status", "")
        table  = store_data.get("table_name", "")
        date   = store_data.get("business_date", "")
        emoji  = STATUS_EMOJI.get(status, "⚪")

        failed_checks = []
        ai_summary = ai_action = ai_category = None
        ai_confidence = None

        try:
            df = execute_query(*get_validation_results_for_run(run_id))
            if not df.empty:
                for _, r in df.iterrows():
                    if r.get("check_status") in ("CRITICAL", "WARNING"):
                        failed_checks.append({
                            "check_type"        : str(r.get("check_type", "")),
                            "column_name"        : str(r.get("column_name", "") or "table-level"),
                            "check_status"       : str(r.get("check_status", "")),
                            "observed_value"     : r.get("observed_value"),
                            "deviation_pct"      : r.get("deviation_pct"),
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
            logger.error(f"A1 modal load error: {str(e)}")

        title = f"{emoji} {status}: {table} — {date}"

        body = build_alert_card_body(
            agent_name     = "Validation Agent — Raw Ingestion Validation",
            table_name     = table,
            fqn            = store_data.get("fully_qualified_name", ""),
            business_date  = date,
            status         = status,
            checks_run     = int(store_data.get("total_checks_run", 0)),
            checks_passed  = int(store_data.get("total_checks_passed", 0)),
            checks_warned  = int(store_data.get("total_checks_warned", 0)),
            checks_critical= int(store_data.get("total_checks_critical", 0)),
            failed_checks  = failed_checks,
            ai_summary     = ai_summary,
            ai_action      = ai_action,
            ai_category    = ai_category,
            ai_confidence  = float(ai_confidence) if ai_confidence else None,
            run_id         = run_id
        )

        return True, title, body

    return False, "", []