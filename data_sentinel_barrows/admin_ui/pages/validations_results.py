# pages/validations_results.py

import os
import logging
from datetime import datetime, timezone, date

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html, Input, Output, State, callback, ctx, no_update
from databricks.sdk import WorkspaceClient
from flask import request as flask_request

from config.settings import (
    DATABRICKS_HOST,
    DATABRICKS_TOKEN,
    TARGET_CATALOG,
    TARGET_SCHEMA,
)
from db.connection import execute_query
from db.queries import (
    get_validation_run_summary,
    get_validation_results_for_run,
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

dash.register_page(
    __name__,
    path="/validation-results",
    name="Validation Results",
)

DS_AGENT1_VALIDATION_JOB_ID = os.environ.get("DS_AGENT1_VALIDATION_JOB_ID", "").strip()
TABLE_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_table_registry_b"
BASELINE_METRICS = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_baseline_metrics_b"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _workspace_client_pat() -> WorkspaceClient:
    return WorkspaceClient(
        host=DATABRICKS_HOST,
        token=DATABRICKS_TOKEN,
        auth_type="pat",
    )


def _host_base() -> str:
    host = (DATABRICKS_HOST or "").strip().rstrip("/")
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"https://{host}"


def _safe_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _active_table_meta() -> pd.DataFrame:
    query = f"""
        SELECT
            fully_qualified_name,
            COALESCE(validation_lag_days, 1) AS validation_lag_days
        FROM {TABLE_REGISTRY}
        WHERE is_active = true
        ORDER BY fully_qualified_name
    """
    return execute_query(query)


def _status_display(status: str) -> str:
    s = (status or "").upper()
    if s == "CRITICAL":
        return "🔴 CRITICAL"
    if s == "WARNING":
        return "🟡 WARNING"
    if s == "PASS":
        return "🟢 PASS"
    if s == "NO_BASELINE":
        return "🟠 NO_BASELINE"
    if s == "ERROR":
        return "⚫ ERROR"
    return s


def _run_link(run_id) -> str:
    if not run_id or pd.isna(run_id):
        return ""
    host = _host_base()
    if not host or not DS_AGENT1_VALIDATION_JOB_ID:
        return ""
    return f"{host}/jobs/{DS_AGENT1_VALIDATION_JOB_ID}/runs/{run_id}"


def _select_dates(mode: str, single_date, start_date, end_date):
    if (mode or "single") == "single":
        d = _safe_date(single_date)
        return [d] if d else []

    d1 = _safe_date(start_date)
    d2 = _safe_date(end_date)
    if not d1 or not d2:
        return []
    if d1 > d2:
        d1, d2 = d2, d1

    out = []
    cur = d1
    while cur <= d2:
        out.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return out


def _baseline_preview_for_dates(fqn: str, selected_dates: list[date]) -> tuple[list[dict], list[str]]:
    if not fqn or not selected_dates:
        return [], []

    max_date = max(selected_dates)
    df = execute_query(
        f"""
        SELECT
            baseline_version_id,
            window_start,
            window_end,
            baseline_status,
            effective_date,
            computed_timestamp
        FROM {BASELINE_METRICS}
        WHERE fully_qualified_name = :fqn
          AND baseline_version_id IS NOT NULL
          AND baseline_status IN ('VALID', 'INSUFFICIENT_DATA')
          AND effective_date <= :max_date
          AND window_end < :max_date
        """,
        {"fqn": fqn, "max_date": max_date.isoformat()},
    )

    if not df.empty:
        for col in ["window_start", "window_end", "effective_date", "computed_timestamp"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

    preview = []
    missing = []
    for d in sorted(selected_dates):
        chosen = None
        if not df.empty:
            cand = df[
                (df["effective_date"].dt.date <= d)
                & (df["window_end"].dt.date < d)
            ]
            if not cand.empty:
                cand = cand.sort_values(["effective_date", "computed_timestamp"], ascending=[False, False])
                chosen = cand.iloc[0]

        if chosen is None:
            preview.append({
                "date": d.isoformat(),
                "baseline": "",
                "window": "",
                "status": "MISSING",
            })
            missing.append(d.isoformat())
        else:
            bid = str(chosen.get("baseline_version_id") or "")
            ws = chosen.get("window_start")
            we = chosen.get("window_end")
            ws_s = ws.date().isoformat() if pd.notna(ws) else ""
            we_s = we.date().isoformat() if pd.notna(we) else ""
            preview.append({
                "date": d.isoformat(),
                "baseline": bid[:8],
                "window": f"{ws_s} -> {we_s}",
                "status": str(chosen.get("baseline_status") or ""),
            })

    return preview, missing


layout = dbc.Container([

    html.H2("Validation Agent — Raw Ingestion", className="mt-4 mb-2"),
    html.P(
        "Run targeted validations and inspect run history."
        " Select a run to see individual check results and AI analysis.",
        className="text-muted mb-4",
    ),

    html.Div(id="val-results-alert"),

    dbc.Card([
        dbc.CardHeader(html.H5("Run Validation", className="mb-0 text-white")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Table", className="text-white"),
                    dcc.Dropdown(id="val-run-table-filter", placeholder="Select active table...", clearable=False),
                ], md=5),
                dbc.Col([
                    dbc.Label("Mode", className="text-white"),
                    dbc.RadioItems(
                        id="val-run-mode",
                        options=[
                            {"label": "Single date", "value": "single"},
                            {"label": "Date range", "value": "range"},
                        ],
                        value="single",
                        inline=True,
                    ),
                ], md=4),
                dbc.Col([
                    dbc.Label(" ", className="text-white"),
                    dbc.Button("Validate", id="val-run-submit-btn", color="primary", className="d-block w-100"),
                ], md=3),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    html.Div(id="val-run-single-wrap", children=[
                        dbc.Label("Date", className="text-white"),
                        dcc.DatePickerSingle(id="val-run-single-date", display_format="YYYY-MM-DD", clearable=False),
                    ]),
                    html.Div(id="val-run-range-wrap", children=[
                        dbc.Label("Date Range", className="text-white"),
                        dcc.DatePickerRange(id="val-run-range-date", display_format="YYYY-MM-DD", clearable=False),
                    ], style={"display": "none"}),
                ], md=5),
                dbc.Col([
                    html.Div(id="val-run-range-warning", className="mt-4"),
                    html.Div(id="val-run-dates-summary", className="text-muted mt-2"),
                ], md=7),
            ]),

            html.Hr(),
            html.H6("Baseline Preview", className="text-white"),
            html.Div(id="val-run-baseline-missing", className="mb-2"),
            html.Div(id="val-run-baseline-preview"),
            html.Hr(),
            html.Div(id="val-run-submit-summary", className="mb-2"),
            html.Div(id="val-run-submitted-table"),
        ]),
    ], className="mb-4"),

    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Status", className="text-white"),
                    dcc.Dropdown(
                        id="val-status-filter",
                        options=[
                            {"label": "All", "value": "ALL"},
                            {"label": "🔴 Critical", "value": "CRITICAL"},
                            {"label": "🟡 Warning", "value": "WARNING"},
                            {"label": "🟢 Pass", "value": "PASS"},
                            {"label": "🟠 No Baseline", "value": "NO_BASELINE"},
                            {"label": "⚫ Error", "value": "ERROR"},
                        ],
                        value="ALL",
                        clearable=False,
                        style={"backgroundColor": "#2b2b2b", "color": "#ffffff"},
                    ),
                ], md=2),
                dbc.Col([
                    dbc.Label("Table", className="text-white"),
                    dcc.Dropdown(id="val-table-filter", placeholder="All tables...", clearable=True),
                ], md=3),
                dbc.Col([
                    dbc.Label("Date", className="text-white"),
                    dcc.DatePickerSingle(id="val-date-filter", display_format="YYYY-MM-DD", clearable=True),
                ], md=2),
                dbc.Col([
                    dbc.Label("History", className="text-white"),
                    dbc.Checklist(
                        id="val-show-all-runs",
                        options=[{"label": "Show all runs", "value": "all"}],
                        value=[],
                        switch=True,
                    ),
                ], md=3),
                dbc.Col([
                    dbc.Label(" ", className="text-white"),
                    dbc.Button("Refresh", id="refresh-val-runs-btn", color="secondary", className="d-block w-100"),
                ], md=2),
            ]),
        ]),
    ], className="mb-4"),

    dbc.Card([
        dbc.CardHeader(html.H5("Validation Run History", className="mb-0 text-white")),
        dbc.CardBody([
            html.Div(
                dag.AgGrid(
                    **ag_grid_props(
                        grid_id="val-runs-table",
                        row_data=[],
                        col_defs=[
                            {"field": "business_date", "headerName": "Date", "minWidth": 120},
                            {"field": "table_name", "headerName": "Table", "flex": 2, "minWidth": 220},
                            {"field": "status_display", "headerName": "Status", "minWidth": 170,
                             "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                            {"field": "baseline_version_short", "headerName": "Baseline Version", "minWidth": 150},
                            {"field": "triggered_by", "headerName": "Triggered By", "minWidth": 180},
                            {"field": "job_run_link", "headerName": "Job Run", "minWidth": 180, "cellRenderer": "markdown"},
                            {"field": "total_checks_run", "headerName": "Checks", "width": 90},
                            {"field": "total_checks_passed", "headerName": "Passed", "width": 90},
                            {"field": "total_checks_warned", "headerName": "Warned", "width": 90},
                            {"field": "total_checks_critical", "headerName": "Critical", "width": 95},
                            {"field": "total_checks_errored", "headerName": "Errored", "width": 95},
                            {"field": "ai_enrichment_status", "headerName": "AI", "minWidth": 150},
                            {"field": "alert_fired", "headerName": "Alert", "width": 90},
                        ],
                        page_size=12,
                        selection="single",
                        status_col="overall_status",
                    )
                ),
                style={"padding": "0 16px 16px"},
            ),
            html.Div(
                dbc.Button(
                    "👁 Preview Teams Alert",
                    id="a1-preview-btn",
                    color="info",
                    outline=True,
                    size="sm",
                    n_clicks=0,
                    style={"display": "none"},
                ),
                className="mt-2",
            ),
        ]),
    ], className="mb-4"),

    dcc.Loading(
        id="val-results-loading",
        type="circle",
        color="#00c851",
        children=[
            dbc.Card([
                dbc.CardHeader(html.H5("Check Results Detail", className="mb-0", id="check-detail-header")),
                dbc.CardBody([
                    html.Div(
                        "Select a run above to see check details.",
                        id="check-detail-container",
                        className="text-muted",
                    )
                ]),
            ], className="mb-4"),
            dbc.Card([
                dbc.CardHeader(html.H5("🤖 AI Analysis", className="mb-0")),
                dbc.CardBody([
                    html.Div(
                        "AI analysis appears here when a run with AI enrichment is selected.",
                        id="ai-analysis-panel",
                        className="text-muted",
                    )
                ]),
            ], className="mb-4"),
        ],
    ),

    dcc.Interval(id="val-run-poll-interval", interval=5000, disabled=True),
    dcc.Store(id="val-run-submitted-store", data={"runs": [], "polling_active": False}, storage_type="session"),
    dcc.Store(id="val-run-selected-dates-store", data=[]),
    dcc.Store(id="val-history-refresh-store", data=None),
    dcc.Store(id="a1-alert-store", data=None),
    build_alert_modal(modal_id="a1-alert-modal"),

], fluid=True)


@callback(
    Output("val-run-table-filter", "options"),
    Output("val-run-table-filter", "value"),
    Input("refresh-val-runs-btn", "n_clicks"),
    State("val-run-table-filter", "value"),
    prevent_initial_call=False,
)
def load_run_table_options(_n, current_value):
    try:
        df = _active_table_meta()
        if df.empty:
            return [], None
        options = [
            {
                "label": f"{str(r['fully_qualified_name']).split('.')[-1]} ({r['fully_qualified_name']})",
                "value": str(r["fully_qualified_name"]),
            }
            for _, r in df.iterrows()
        ]
        valid_values = {o["value"] for o in options}
        if current_value in valid_values:
            return options, current_value
        return options, options[0]["value"]
    except Exception as e:
        logger.error(f"Failed to load active tables: {e}")
        return [], None


@callback(
    Output("val-run-single-wrap", "style"),
    Output("val-run-range-wrap", "style"),
    Output("val-run-single-date", "max_date_allowed"),
    Output("val-run-single-date", "date"),
    Output("val-run-range-date", "max_date_allowed"),
    Output("val-run-range-date", "start_date"),
    Output("val-run-range-date", "end_date"),
    Output("val-run-range-warning", "children"),
    Output("val-run-dates-summary", "children"),
    Output("val-run-baseline-preview", "children"),
    Output("val-run-baseline-missing", "children"),
    Output("val-run-submit-btn", "disabled"),
    Output("val-run-selected-dates-store", "data"),
    Input("val-run-table-filter", "value"),
    Input("val-run-mode", "value"),
    Input("val-run-single-date", "date"),
    Input("val-run-range-date", "start_date"),
    Input("val-run-range-date", "end_date"),
    Input("val-run-submitted-store", "data"),
    prevent_initial_call=False,
)
def update_run_selector_and_preview(fqn, mode, single_date, start_date, end_date, submitted_store):
    mode = mode or "single"
    run_active = any(not bool(r.get("terminal", False)) for r in (submitted_store or {}).get("runs", []))

    if not fqn:
        return (
            {"display": "block"},
            {"display": "none"},
            None,
            None,
            None,
            None,
            None,
            "",
            "Select a table first.",
            html.Div(),
            html.Div(),
            True,
            [],
        )

    meta = _active_table_meta()
    row = meta[meta["fully_qualified_name"] == fqn]
    lag = 1
    if not row.empty:
        try:
            lag = max(1, int(row.iloc[0]["validation_lag_days"]))
        except Exception:
            lag = 1

    max_day = _utc_today() - pd.Timedelta(days=lag)
    max_day = max_day.date() if hasattr(max_day, "date") else max_day
    max_day_s = max_day.isoformat()

    sd = _safe_date(single_date) or max_day
    if sd > max_day:
        sd = max_day

    rs = _safe_date(start_date) or max_day
    re = _safe_date(end_date) or max_day
    if rs > re:
        rs, re = re, rs
    if re > max_day:
        re = max_day
    if rs > re:
        rs = re

    selected_dates = _select_dates(mode, sd.isoformat(), rs.isoformat(), re.isoformat())

    warning = ""
    disabled = run_active
    if mode == "range" and len(selected_dates) > 10:
        warning = dbc.Alert(f"Max 10 dates (selected {len(selected_dates)})", color="danger", className="py-1")
        disabled = True

    missing_dates = []
    preview_rows = []
    if selected_dates and (mode != "range" or len(selected_dates) <= 10):
        preview_rows, missing_dates = _baseline_preview_for_dates(fqn, selected_dates)

    if missing_dates:
        disabled = True

    if not selected_dates:
        disabled = True

    summary = ""
    if selected_dates:
        summary = f"{len(selected_dates)} dates: {selected_dates[0].isoformat()} → {selected_dates[-1].isoformat()}"

    preview_table = html.Div()
    if preview_rows:
        header = html.Thead(html.Tr([
            html.Th("Date"),
            html.Th("Baseline"),
            html.Th("Window"),
            html.Th("Status"),
        ]))
        body = html.Tbody([
            html.Tr([
                html.Td(r["date"]),
                html.Td(r["baseline"]),
                html.Td(r["window"]),
                html.Td(r["status"]),
            ])
            for r in preview_rows
        ])
        preview_table = dbc.Table([header, body], bordered=True, hover=True, size="sm", striped=True)

    missing_msg = html.Div()
    if missing_dates:
        missing_msg = dbc.Alert(
            "Missing baseline for: " + ", ".join(missing_dates),
            color="warning",
            className="py-1",
        )

    single_style = {"display": "block"} if mode == "single" else {"display": "none"}
    range_style = {"display": "block"} if mode == "range" else {"display": "none"}

    return (
        single_style,
        range_style,
        max_day_s,
        sd.isoformat(),
        max_day_s,
        rs.isoformat(),
        re.isoformat(),
        warning,
        summary,
        preview_table,
        missing_msg,
        disabled,
        [d.isoformat() for d in selected_dates],
    )


@callback(
    Output("val-run-submitted-store", "data"),
    Input("val-run-submit-btn", "n_clicks"),
    State("val-run-table-filter", "value"),
    State("val-run-selected-dates-store", "data"),
    State("val-run-submitted-store", "data"),
    prevent_initial_call=True,
)
def submit_validation_runs(n_clicks, fqn, selected_dates, submitted_store):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    store = submitted_store or {"runs": [], "polling_active": False}
    if not fqn or not selected_dates:
        return store
    if not DS_AGENT1_VALIDATION_JOB_ID:
        store["runs"] = [{
            "date": "",
            "status": "FAILED",
            "terminal": True,
            "run_id": None,
            "run_url": "",
            "message": "DS_AGENT1_VALIDATION_JOB_ID is not configured.",
        }]
        store["polling_active"] = False
        return store

    try:
        email = flask_request.headers.get("X-Forwarded-Email")
    except Exception:
        email = None
    triggered_by = f"UI:{email}" if email else "UI:unknown"

    client = _workspace_client_pat()
    runs = []
    for d in sorted(selected_dates):
        try:
            run_now = client.jobs.run_now(
                job_id=int(DS_AGENT1_VALIDATION_JOB_ID),
                job_parameters={
                    "business_date": d,
                    "table_filter": fqn,
                    "triggered_by": triggered_by,
                },
            )
            run_id = getattr(run_now, "run_id", None) or getattr(getattr(run_now, "response", None), "run_id", None)
            if run_id is None:
                raise RuntimeError("run_now returned no run_id")
            runs.append({
                "date": d,
                "status": "SUBMITTED",
                "terminal": False,
                "run_id": int(run_id),
                "run_url": _run_link(run_id),
                "message": "Submitted",
            })
        except Exception as e:
            runs.append({
                "date": d,
                "status": "FAILED",
                "terminal": True,
                "run_id": None,
                "run_url": "",
                "message": str(e),
            })

    return {
        "runs": runs,
        "polling_active": any(not r.get("terminal", False) for r in runs),
    }


@callback(
    Output("val-run-submitted-store", "data", allow_duplicate=True),
    Output("val-history-refresh-store", "data"),
    Input("val-run-poll-interval", "n_intervals"),
    State("val-run-submitted-store", "data"),
    prevent_initial_call=True,
)
def poll_submitted_runs(_n, submitted_store):
    store = submitted_store or {"runs": [], "polling_active": False}
    runs = store.get("runs", [])
    if not runs or not store.get("polling_active"):
        raise dash.exceptions.PreventUpdate

    client = _workspace_client_pat()
    transitioned_terminal = False

    for r in runs:
        if r.get("terminal") or not r.get("run_id"):
            continue
        try:
            info = client.jobs.get_run(run_id=int(r["run_id"]))
            state = getattr(info, "state", None)
            life_raw = getattr(state, "life_cycle_state", None) if state is not None else None
            res_raw = getattr(state, "result_state", None) if state is not None else None
            life = getattr(life_raw, "value", str(life_raw or ""))
            res = getattr(res_raw, "value", str(res_raw or ""))
            r["run_url"] = getattr(info, "run_page_url", r.get("run_url") or "")

            if life in {"TERMINATED", "INTERNAL_ERROR", "SKIPPED"}:
                r["terminal"] = True
                transitioned_terminal = True
                if res == "SUCCESS":
                    r["status"] = "SUCCESS"
                    r["message"] = "Completed"
                else:
                    r["status"] = "FAILED"
                    r["message"] = getattr(state, "state_message", "Run failed") or "Run failed"
            elif life in {"RUNNING", "PENDING", "QUEUED", "BLOCKED"}:
                r["status"] = life
            else:
                r["status"] = life or r.get("status", "UNKNOWN")
        except Exception as e:
            r["terminal"] = True
            r["status"] = "FAILED"
            r["message"] = str(e)
            transitioned_terminal = True

    store["runs"] = runs
    store["polling_active"] = any(not r.get("terminal", False) for r in runs)
    refresh_token = (
        datetime.now(timezone.utc).isoformat()
        if transitioned_terminal and not store.get("polling_active", False)
        else no_update
    )
    return store, refresh_token


@callback(
    Output("val-run-poll-interval", "disabled"),
    Input("val-run-submitted-store", "data"),
    prevent_initial_call=False,
)
def control_poll_interval(submitted_store):
    if not submitted_store:
        return True
    return not bool(submitted_store.get("polling_active", False))


@callback(
    Output("val-run-submit-summary", "children"),
    Output("val-run-submitted-table", "children"),
    Input("val-run-submitted-store", "data"),
    prevent_initial_call=False,
)
def render_submitted_runs(submitted_store):
    runs = (submitted_store or {}).get("runs", [])
    if not runs:
        return "", html.Div()

    total = len(runs)
    done = sum(1 for r in runs if r.get("status") == "SUCCESS")
    failed = sum(1 for r in runs if r.get("status") == "FAILED")
    summary = f"{done} of {total} done, {failed} failed"

    header = html.Thead(html.Tr([
        html.Th("Date"),
        html.Th("Status"),
        html.Th("Run link"),
        html.Th("Message"),
    ]))
    body = html.Tbody([
        html.Tr([
            html.Td(r.get("date", "")),
            html.Td(r.get("status", "")),
            html.Td(html.A("Open", href=r.get("run_url"), target="_blank") if r.get("run_url") else ""),
            html.Td(r.get("message", "")),
        ])
        for r in runs
    ])
    table = dbc.Table([header, body], bordered=True, hover=True, size="sm", striped=True)
    return summary, table


@callback(
    Output("val-runs-table", "rowData"),
    Output("val-runs-table", "selectedRows"),
    Output("val-table-filter", "options"),
    Input("refresh-val-runs-btn", "n_clicks"),
    Input("val-status-filter", "value"),
    Input("val-table-filter", "value"),
    Input("val-date-filter", "date"),
    Input("val-show-all-runs", "value"),
    Input("val-history-refresh-store", "data"),
    prevent_initial_call=False,
)
def load_validation_runs(_n, status_filter, table_filter, date_filter, show_all_runs, refresh_token):
    try:
        df = execute_query(get_validation_run_summary())
        if df.empty:
            return [], [], []

        for c in ["business_date", "validation_start_timestamp", "created_timestamp"]:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce")

        table_options = [{"label": t, "value": t} for t in sorted(df["table_name"].dropna().unique().tolist())]

        if status_filter and status_filter != "ALL":
            df = df[df["overall_status"] == status_filter]
        if table_filter:
            df = df[df["table_name"] == table_filter]
        if date_filter:
            d = _safe_date(date_filter)
            if d is not None:
                df = df[df["business_date"].dt.date == d]

        show_all = "all" in (show_all_runs or [])
        if not show_all:
            df = df.sort_values(["validation_start_timestamp", "created_timestamp"], ascending=[False, False])
            df = df.drop_duplicates(subset=["fully_qualified_name", "business_date"], keep="first")

        df = df.sort_values(["business_date", "validation_start_timestamp"], ascending=[False, False])

        rows = []
        for _, row in df.iterrows():
            run_link = _run_link(row.get("pipeline_run_id"))
            run_md = f"[Run]({run_link})" if run_link else ""
            bid = str(row.get("baseline_version_id") or "")
            rows.append({
                "validation_run_id": str(row.get("validation_run_id", "")),
                "business_date": row.get("business_date").date().isoformat() if pd.notna(row.get("business_date")) else "",
                "table_name": str(row.get("table_name", "")),
                "fully_qualified_name": str(row.get("fully_qualified_name", "")),
                "overall_status": str(row.get("overall_status", "")),
                "status_display": _status_display(str(row.get("overall_status", ""))),
                "baseline_version_short": bid[:8] if bid else "",
                "triggered_by": str(row.get("triggered_by", "") or ""),
                "job_run_link": run_md,
                "total_checks_run": int(row.get("total_checks_run") or 0),
                "total_checks_passed": int(row.get("total_checks_passed") or 0),
                "total_checks_warned": int(row.get("total_checks_warned") or 0),
                "total_checks_critical": int(row.get("total_checks_critical") or 0),
                "total_checks_errored": int(row.get("total_checks_errored") or 0),
                "ai_enrichment_status": str(row.get("ai_enrichment_status", "")),
                "alert_fired": str(row.get("alert_fired", "NO")),
            })

        selected = [rows[0]] if rows and refresh_token else []
        return rows, selected, table_options

    except Exception as e:
        logger.error(f"Failed to load validation runs: {str(e)}")
        return [], [], []


@callback(
    Output("check-detail-header", "children"),
    Output("check-detail-container", "children"),
    Output("ai-analysis-panel", "children"),
    Output("a1-preview-btn", "style"),
    Output("a1-alert-store", "data"),
    Input("val-runs-table", "selectedRows"),
    prevent_initial_call=True,
)
def load_check_details(selected_rows):
    hidden = {"display": "none"}
    visible = {"display": "inline-block"}

    if not selected_rows:
        return (
            "Check Results Detail",
            html.P("Select a run above.", className="text-muted"),
            html.P("AI analysis appears here.", className="text-muted"),
            hidden,
            None,
        )

    row = selected_rows[0]
    run_id = row.get("validation_run_id", "")
    table = row.get("table_name", "")
    biz_date = row.get("business_date", "")
    status = row.get("overall_status", "")
    alerted = row.get("alert_fired", "NO")
    emoji = STATUS_EMOJI.get(status, "⚪")

    header = f"Check Results — {table} on {biz_date}  {emoji} {status}"

    if not run_id:
        return header, error_alert("No run ID."), html.Div(), hidden, None

    try:
        df = execute_query(*get_validation_results_for_run(run_id))
        if df.empty:
            return header, info_alert("No check results found."), html.Div(), hidden, None

        table_rows = []
        for _, r in df.iterrows():
            check_type = str(r.get("check_type", ""))
            check_status = str(r.get("check_status", ""))
            obs_raw = r.get("observed_value")
            base_raw = r.get("baseline_value")
            signed_dev = compute_signed_deviation(obs_raw, base_raw, check_type)

            table_rows.append({
                "check_type": check_type,
                "check_level": str(r.get("check_level", "")),
                "column_name": str(r.get("column_name", "") or "table-level"),
                "check_status": check_status,
                "observed_value": fmt_number(obs_raw),
                "baseline_value": fmt_number(base_raw),
                "deviation_pct": fmt_deviation(signed_dev, check_type),
                "warn_threshold": fmt_threshold(r.get("threshold_warning")),
                "crit_threshold": fmt_threshold(r.get("threshold_critical")),
            })

        detail_table = dag.AgGrid(
            **ag_grid_props(
                grid_id="val-check-detail-grid",
                row_data=table_rows,
                col_defs=[
                    {"field": "check_type", "headerName": "Check Type", "flex": 1, "minWidth": 200},
                    {"field": "check_level", "headerName": "Level", "minWidth": 150},
                    {"field": "column_name", "headerName": "Column", "flex": 1, "minWidth": 220},
                    {"field": "check_status", "headerName": "Status", "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "observed_value", "headerName": "Observed", "width": 110},
                    {"field": "baseline_value", "headerName": "Baseline", "width": 110},
                    {"field": "deviation_pct", "headerName": "Deviation %", "width": 110},
                    {"field": "warn_threshold", "headerName": "Warn", "width": 110},
                    {"field": "crit_threshold", "headerName": "Critical", "width": 110},
                ],
                page_size=20,
                status_col="check_status",
            )
        )

        ai_rows = df[df["ai_summary"].notna() & (df["ai_summary"] != "")]
        if ai_rows.empty:
            ai_panel = dbc.Alert(
                "No AI enrichment for this run. "
                "AI triggers when 2+ checks fail with 1+ CRITICAL.",
                color="info",
            )
        else:
            first = ai_rows.iloc[0]
            ai_summary = str(first.get("ai_summary", ""))
            ai_action = str(first.get("ai_recommended_action", ""))
            ai_category = str(first.get("ai_failure_category", ""))
            ai_confidence = first.get("ai_confidence_score")
            try:
                conf_pct = f"{float(ai_confidence):.0%}"
            except (TypeError, ValueError):
                conf_pct = "N/A"

            ai_panel = dbc.Container([
                dbc.Row([
                    dbc.Col([
                        dbc.Badge(ai_category or "N/A", color=STATUS_COLOR.get(status, "secondary"), className="me-2 mb-2 fs-6"),
                        dbc.Badge(f"Confidence: {conf_pct}", color="secondary", className="mb-2 fs-6"),
                    ])
                ]),
                dbc.Row([
                    dbc.Col([
                        html.H6("AI Summary", className="text-info mt-2"),
                        html.P(ai_summary, className="border-start border-info ps-3"),
                    ], md=6),
                    dbc.Col([
                        html.H6("Recommended Action", className="text-success mt-2"),
                        html.P(ai_action or "No specific action.", className="border-start border-success ps-3"),
                    ], md=6),
                ]),
            ], fluid=True)

        store_data = {
            "validation_run_id": run_id,
            "table_name": table,
            "fully_qualified_name": row.get("fully_qualified_name", ""),
            "business_date": biz_date,
            "overall_status": status,
            "total_checks_run": row.get("total_checks_run", 0),
            "total_checks_passed": row.get("total_checks_passed", 0),
            "total_checks_warned": row.get("total_checks_warned", 0),
            "total_checks_critical": row.get("total_checks_critical", 0),
            "ai_enrichment_status": row.get("ai_enrichment_status", ""),
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
    prevent_initial_call=True,
)
def toggle_a1_modal(open_clicks, close_clicks, store_data, is_open):
    triggered = ctx.triggered_id

    if triggered == "a1-alert-modal-close-btn":
        return False, "", []

    if triggered == "a1-preview-btn" and store_data:
        run_id = store_data.get("validation_run_id", "")
        status = store_data.get("overall_status", "")
        table = store_data.get("table_name", "")
        biz_date = store_data.get("business_date", "")
        emoji = STATUS_EMOJI.get(status, "⚪")

        failed_checks = []
        ai_summary = ai_action = ai_category = None
        ai_confidence = None

        try:
            df = execute_query(*get_validation_results_for_run(run_id))
            if not df.empty:
                for _, r in df.iterrows():
                    if r.get("check_status") in ("CRITICAL", "WARNING"):
                        failed_checks.append({
                            "check_type": str(r.get("check_type", "")),
                            "column_name": str(r.get("column_name", "") or "table-level"),
                            "check_status": str(r.get("check_status", "")),
                            "observed_value": r.get("observed_value"),
                            "deviation_pct": r.get("deviation_pct"),
                            "threshold_warning": r.get("threshold_warning"),
                            "threshold_critical": r.get("threshold_critical"),
                        })

                ai_rows = df[df["ai_summary"].notna() & (df["ai_summary"] != "")]
                if not ai_rows.empty:
                    first = ai_rows.iloc[0]
                    ai_summary = str(first.get("ai_summary", ""))
                    ai_action = str(first.get("ai_recommended_action", ""))
                    ai_category = str(first.get("ai_failure_category", ""))
                    ai_confidence = first.get("ai_confidence_score")
        except Exception as e:
            logger.error(f"A1 modal load error: {str(e)}")

        title = f"{emoji} {status}: {table} — {biz_date}"
        body = build_alert_card_body(
            agent_name="Validation Agent — Raw Ingestion Validation",
            table_name=table,
            fqn=store_data.get("fully_qualified_name", ""),
            business_date=biz_date,
            status=status,
            checks_run=int(store_data.get("total_checks_run", 0)),
            checks_passed=int(store_data.get("total_checks_passed", 0)),
            checks_warned=int(store_data.get("total_checks_warned", 0)),
            checks_critical=int(store_data.get("total_checks_critical", 0)),
            failed_checks=failed_checks,
            ai_summary=ai_summary,
            ai_action=ai_action,
            ai_category=ai_category,
            ai_confidence=float(ai_confidence) if ai_confidence else None,
            run_id=run_id,
        )

        return True, title, body

    return False, "", []
