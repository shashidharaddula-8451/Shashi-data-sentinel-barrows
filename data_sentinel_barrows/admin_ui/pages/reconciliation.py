# pages/reconciliation.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import logging
from db.connection import execute_query
from db.queries import (
    get_reconciliation_run_summary,
    get_reconciliation_results_for_run
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
)

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/reconciliation", name="Reconciliation")

layout = dbc.Container([

    html.H2("Reconciliation Agent — Cross-Layer Reconciliation", className="mt-4 mb-2"),
    html.P(
        "View cross-layer reconciliation history. "
        "Select a run to see individual check results. "
        "Click Preview Teams Alert to see what was sent.",
        className="text-muted mb-4"
    ),

    html.Div(id="recon-alert"),

    # ── Filters ────────────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Status", className="text-white"),
                    dcc.Dropdown(
                        id="recon-status-filter",
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
                ], md=4),
                dbc.Col([
                    dbc.Label("Table", className="text-white"),
                    dcc.Dropdown(
                        id="recon-table-filter",
                        placeholder="All tables...",
                        clearable=True,
                        style={"backgroundColor": "#2b2b2b", "color": "#ffffff"}
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "Refresh",
                        id="refresh-recon-btn",
                        color="secondary",
                        className="d-block w-100"
                    )
                ], md=4)
            ])
        ])
    ], className="mb-4"),

    # ── Reconciliation Run History ─
    dcc.Loading(id="recon-runs-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(html.H5("Reconciliation Runs", className="mb-0")),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="recon-runs-table",
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
            html.Div(
                dbc.Button(
                    "👁 Preview Teams Alert",
                    id="a2-preview-btn",
                    color="info",
                    outline=True,
                    size="sm",
                    n_clicks=0,
                    style={"display": "none"}
                ),
                className="mt-3"
            )
        ])
    ], className="mb-4"),
    ]),  # end Loading

    # ── Check Results ──────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Check Results Detail", className="mb-0",
                    id="recon-detail-header")
        ),
        dbc.CardBody([
            html.Div(
                "Select a run above to see check details.",
                id="recon-detail-container",
                className="text-muted"
            )
        ])
    ], className="mb-4"),

    # ── AI Analysis ────────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(html.H5("🤖 AI Analysis", className="mb-0")),
        dbc.CardBody([
            html.Div(
                "AI analysis appears here when a run with "
                "AI enrichment is selected.",
                id="recon-ai-panel",
                className="text-muted"
            )
        ])
    ], className="mb-4"),

    dcc.Store(id="a2-alert-store", data=None),
    build_alert_modal(modal_id="a2-alert-modal")

], fluid=True)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("recon-runs-table", "rowData"),
    Output("recon-table-filter", "options"),
    Input("refresh-recon-btn", "n_clicks"),
    Input("recon-status-filter", "value"),
    Input("recon-table-filter", "value"),
    prevent_initial_call=False
)
def load_recon_runs(n_clicks, status_filter, table_filter):
    try:
        df = execute_query(get_reconciliation_run_summary())
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

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "reconciliation_run_id"      : str(row.get("reconciliation_run_id", "")),
                "business_date"              : str(row.get("business_date", "")),
                "table_name"                 : str(row.get("table_name", "")),
                "source_fully_qualified_name": str(row.get("source_fully_qualified_name", "")),
                "overall_status"             : str(row.get("overall_status", "")),
                "total_checks_run"           : safe_int(row.get("total_checks_run")),
                "total_checks_passed"        : safe_int(row.get("total_checks_passed")),
                "total_checks_warned"        : safe_int(row.get("total_checks_warned")),
                "total_checks_critical"      : safe_int(row.get("total_checks_critical")),
                "ai_enrichment_status"       : str(row.get("ai_enrichment_status", "")),
                "alert_fired"                : str(row.get("alert_fired", "NO")),
                "agent1_validation_run_id"   : str(row.get("agent1_validation_run_id", "") or "")
            })

        return rows, table_options

    except Exception as e:
        logger.error(f"Failed to load recon runs: {str(e)}")
        return [], []


@callback(
    Output("recon-detail-header", "children"),
    Output("recon-detail-container", "children"),
    Output("recon-ai-panel", "children"),
    Output("a2-preview-btn", "style"),
    Output("a2-alert-store", "data"),
    Input("recon-runs-table", "selectedRows"),
    prevent_initial_call=True
)
def load_recon_details(selected_rows):
    hidden  = {"display": "none"}
    visible = {"display": "inline-block"}

    if not selected_rows:
        return (
            "Check Results Detail",
            html.P("Select a run above.", className="text-muted"),
            html.P("AI analysis appears here.", className="text-muted"),
            hidden, None
        )

    row     = selected_rows[0]
    run_id  = row.get("reconciliation_run_id", "")
    table   = row.get("table_name", "")
    date    = row.get("business_date", "")
    status  = row.get("overall_status", "")
    alerted = row.get("alert_fired", "NO")
    emoji   = STATUS_EMOJI.get(status, "⚪")
    header  = f"Check Results — {table} on {date}  {emoji} {status}"

    if not run_id:
        return header, error_alert("No run ID."), html.Div(), hidden, None

    try:
        df = execute_query(*get_reconciliation_results_for_run(run_id))

        if df.empty:
            return (
                header,
                info_alert("No check results found."),
                html.Div(), hidden, None
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
            src_raw      = r.get("source_value")
            tgt_raw      = r.get("target_value")
            exp_raw      = r.get("expected_value")
            dev_raw      = r.get("deviation_pct")

            # For reconciliation checks deviation sign matters:
            # RAW_TO_SILVER_ROW_COUNT: target < source = negative (drop)
            # SILVER_TO_GOLD_AGGREGATE: target != source = could be either
            signed_dev = compute_signed_deviation(tgt_raw, exp_raw, check_type)
            if signed_dev is None:
                signed_dev = compute_signed_deviation(tgt_raw, src_raw, check_type)

            table_rows.append({
                "from_layer"     : str(r.get("from_layer", "")),
                "to_layer"       : str(r.get("to_layer", "")),
                "check_type"     : check_type,
                "metric_name"    : str(r.get("metric_name", "")),
                "check_status"   : check_status,
                "source_value"   : fmt_number(src_raw),
                "target_value"   : fmt_number(tgt_raw),
                "deviation_pct"  : fmt_deviation(signed_dev, check_type),
                "warn_threshold" : fmt_threshold(r.get("threshold_warning")),
                "crit_threshold" : fmt_threshold(r.get("threshold_critical")),
                "agent1_status"  : str(r.get("agent1_overall_status", ""))
            })

        detail_table = dag.AgGrid(
            **ag_grid_props(
                grid_id="recon-detail-grid",
                row_data=table_rows,
                col_defs=[
                    {"field": "from_layer",      "headerName": "From", "minWidth": 150},
                    {"field": "to_layer",        "headerName": "To",   "minWidth": 150},
                    {"field": "check_type",      "headerName": "Check",   "flex": 1, "minWidth": 200},
                    {"field": "metric_name",     "headerName": "Metric",  "flex": 1, "minWidth": 220},
                    {"field": "check_status",    "headerName": "Status",  "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "source_value",    "headerName": "Source",  "width": 110},
                    {"field": "target_value",    "headerName": "Target",  "width": 110},
                    {"field": "deviation_pct",   "headerName": "Dev %",   "width": 110},
                    {"field": "warn_threshold",  "headerName": "Warn",    "width": 110},
                    {"field": "crit_threshold",  "headerName": "Crit",    "width": 110},
                    {"field": "agent1_status",   "headerName": "Validation Agent", "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                ],
                page_size=20,
                status_col="check_status",
            )
        )

        # AI Panel
        ai_rows = df[df["ai_summary"].notna() & (df["ai_summary"] != "")]
        if ai_rows.empty:
            ai_panel = dbc.Alert(
                "No AI enrichment for this run.",
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

        store_data = {
            "reconciliation_run_id"      : run_id,
            "table_name"                 : table,
            "source_fully_qualified_name": row.get("source_fully_qualified_name", ""),
            "business_date"              : date,
            "overall_status"             : status,
            "total_checks_run"           : row.get("total_checks_run", 0),
            "total_checks_passed"        : row.get("total_checks_passed", 0),
            "total_checks_warned"        : row.get("total_checks_warned", 0),
            "total_checks_critical"      : row.get("total_checks_critical", 0),
            "ai_enrichment_status"       : row.get("ai_enrichment_status", ""),
            "agent1_validation_run_id"   : row.get("agent1_validation_run_id", "")
        }

        btn_style = visible if alerted == "YES" else hidden

        return header, detail_table, ai_panel, btn_style, store_data

    except Exception as e:
        logger.error(f"Failed to load recon details: {str(e)}")
        return header, error_alert(str(e)), html.Div(), hidden, None


@callback(
    Output("a2-alert-modal", "is_open"),
    Output("a2-alert-modal-title", "children"),
    Output("a2-alert-modal-body", "children"),
    Input("a2-preview-btn", "n_clicks"),
    Input("a2-alert-modal-close-btn", "n_clicks"),
    State("a2-alert-store", "data"),
    State("a2-alert-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_a2_modal(open_clicks, close_clicks, store_data, is_open):
    triggered = ctx.triggered_id

    if triggered == "a2-alert-modal-close-btn":
        return False, "", []

    if triggered == "a2-preview-btn" and store_data:
        run_id = store_data.get("reconciliation_run_id", "")
        status = store_data.get("overall_status", "")
        table  = store_data.get("table_name", "")
        date   = store_data.get("business_date", "")
        emoji  = STATUS_EMOJI.get(status, "⚪")
        a1_id  = store_data.get("agent1_validation_run_id", "N/A") or "N/A"

        failed_checks = []
        ai_summary = ai_action = ai_category = None
        ai_confidence = None

        try:
            df = execute_query(*get_reconciliation_results_for_run(run_id))
            if not df.empty:
                for _, r in df.iterrows():
                    if r.get("check_status") in ("CRITICAL", "WARNING"):
                        failed_checks.append({
                            "check_type"       : (
                                f"{r.get('from_layer', '')}→"
                                f"{r.get('to_layer', '')} "
                                f"{r.get('check_type', '')}"
                            ),
                            "column_name"      : str(r.get("metric_name", "")),
                            "check_status"     : str(r.get("check_status", "")),
                            "observed_value"   : r.get("source_value"),
                            "deviation_pct"    : r.get("deviation_pct"),
                            "threshold_warning": r.get("threshold_warning"),
                            "threshold_critical": r.get("threshold_critical")
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
            logger.error(f"A2 modal load error: {str(e)}")

        title = f"{emoji} {status}: {table} — {date}"

        body = build_alert_card_body(
            agent_name     = "Reconciliation Agent — Cross-Layer Reconciliation",
            table_name     = table,
            fqn            = store_data.get("source_fully_qualified_name", ""),
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
            run_id         = run_id,
            extra_facts    = [
                {"name": "Validation Agent Context", "value": a1_id}
            ]
        )

        return True, title, body

    return False, "", []