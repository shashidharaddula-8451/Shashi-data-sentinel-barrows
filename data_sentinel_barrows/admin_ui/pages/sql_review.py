# pages/sql_review.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import json
import logging
from db.connection import execute_query, execute_write
from db.queries import (
    get_all_transformations,
    insert_transformation,
    toggle_transformation_active,
    get_review_history,
    get_all_registered_tables,
    get_silver_layer_tables,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import (
    success_alert,
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
    add_status_code,
    ag_grid_props,
    AG_STATUS_ROW_STYLE_JS,
    AG_STATUS_CELL_STYLE_JS,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/sql-review",
    name="SQL Review"
)

# ── Constants ──────────────────────────────────────────────────────────────

CHECKS_OPTIONS = [
    {"label": "Join Fan-out Detection",        "value": "JOIN_FANOUT"},
    {"label": "Missing Null Filter Detection", "value": "NULL_FILTER"},
    {"label": "Aggregation Before Filter",     "value": "AGGREGATION_ORDER"},
    {"label": "Row Count Ratio Validation",    "value": "ROW_COUNT_RATIO"},
]

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2("Transformation Agent — Silver SQL Review", className="mt-4 mb-2"),
    html.P(
        "Register Silver transformation notebooks for automated code review. "
        "Transformation Agent checks for join fan-outs, missing null filters, "
        "aggregation ordering issues, and row count ratio anomalies. "
        "Select a review to preview the Teams alert.",
        className="text-muted mb-4"
    ),

    html.Div(id="sql-review-alert"),

    # ── Summary Cards ──────────────────────────────────────────────────────
    dbc.Row(id="agent3-summary-cards", className="mb-4"),

    # ── Registered Transformations Grid ───────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            dbc.Row([
                dbc.Col(
                    html.H5(
                        "Registered Transformations",
                        className="mb-0"
                    ),
                    width="auto"
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh",
                        id="refresh-transformations-btn",
                        color="secondary",
                        size="sm"
                    ),
                    width="auto",
                    className="ms-auto"
                )
            ], align="center")
        ),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="transformations-grid",
                    col_defs=[
                        {"field": "transformation_id",      "headerName": "ID",         "minWidth": 150},
                        {"field": "target_table",           "headerName": "Target Table",  "flex": 2, "minWidth": 220},
                        {"field": "function_name",          "headerName": "Function",      "flex": 2, "minWidth": 220},
                        {"field": "source_table",           "headerName": "Source Table",  "flex": 2, "minWidth": 220},
                        {"field": "notebook_path",          "headerName": "Notebook Path", "flex": 3, "minWidth": 220},
                        {"field": "expected_survival_rate", "headerName": "Survival %",    "width": 110},
                        {"field": "last_review_status",     "headerName": "Last Review",   "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "last_reviewed_timestamp","headerName": "Last Reviewed", "minWidth": 180},
                        {"field": "is_active",              "headerName": "Active",        "width": 90},
                    ],
                    page_size=10,
                    selection="single",
                    status_col="last_review_status",
                )
            )
        ])
    ], className="mb-4"),

    # ── Manage Selected Transformation ─────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5(
                "Manage Selected Transformation",
                className="mb-0"
            )
        ),
        dbc.CardBody([
            html.P(
                "Select a row above to manage it.",
                className="text-muted",
                id="selected-transformation-label"
            ),
            dbc.ButtonGroup([
                dbc.Button(
                    "Deactivate",
                    id="deactivate-transformation-btn",
                    color="warning",
                    n_clicks=0,
                    disabled=True
                ),
                dbc.Button(
                    "Activate",
                    id="activate-transformation-btn",
                    color="success",
                    n_clicks=0,
                    disabled=True
                )
            ])
        ])
    ], className="mb-4"),

    # ── Review History Panel ───────────────────────────────────────────────
    dcc.Loading(
        id    = "sqlrev-history-loading",
        type  = "circle",
        color = "#00c851",
        children =
            dbc.Card([
                dbc.CardHeader(
                    html.H5(
                        "Review History — Click a row above to filter",
                        className="mb-0",
                        id="review-history-header"
                    )
                ),
                dbc.CardBody([
                    html.Div(id="review-history-container"),
            html.Div(
                dbc.Button(
                    "👁 Preview Teams Alert",
                    id="a3-preview-btn",
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
    ),

    # ── Failed Check Detail Panel ──────────────────────────────────────────
    dcc.Loading(
        id    = "sqlrev-detail-loading",
        type  = "circle",
        color = "#00c851",
        children = [
            dbc.Card([
                dbc.CardHeader(
                    html.H5(
                        "🔍 Failed Check Detail",
                        className="mb-0"
                    )
                ),
                dbc.CardBody([
                    html.Div(
                        html.P(
                            "Select a review row above to see "
                            "individual check results.",
                            className="text-muted small mb-0"
                        ),
                        id="failed-check-detail-panel"
                    )
                ])
            ], className="mb-4",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            }),

            # ── AI Summary Detail Panel ────────────────────────────────────
            dbc.Card([
                dbc.CardHeader(
                    html.H5("🤖 AI Review Summary", className="mb-0")
                ),
                dbc.CardBody([
                    html.Div(
                        "Select a review from the history table above to see "
                        "the AI-generated summary and recommended fix.",
                        id="ai-summary-panel",
                        className="text-muted"
                    )
                ])
            ], className="mb-4"),
        ]
    ),

    # ── Shared components ──────────────────────────────────────────────────
    dcc.Store(id="a3-alert-store", data=None),
    dcc.Store(id="a3-layer-store", data=None),
    build_alert_modal(modal_id="a3-alert-modal")

], fluid=True)


# ── Helper: build row dict for transformations grid ────────────────────────

def _build_txfm_row(row) -> dict:
    """
    Centralised row builder for the transformations grid.
    """
    s = row.get("expected_survival_rate")
    return {
        "transformation_id"      : str(row.get("transformation_id", "")),
        "target_table"           : str(row.get("target_table", "")),
        "function_name"          : str(row.get("function_name", "")),
        "source_table"           : str(row.get("source_table", "")),
        "notebook_path"          : str(row.get("notebook_path", "")),
        "expected_survival_rate" : (
            f"{float(s)*100:.0f}%"
            if s is not None else "N/A"
        ),
        "last_review_status"     : str(
            row.get("last_review_status", "NOT_REVIEWED")
        ),
        "last_reviewed_timestamp": str(
            row.get("last_reviewed_timestamp", "Never")
        ),
        "is_active"              : str(row.get("is_active", True))
    }


# ── Helper: parse check_results JSON ──────────────────────────────────────

def _parse_check_results(raw_cr) -> tuple:
    """
    Parses the check_results JSON field from uc3_review_results_b.

    Returns:
        (failed_checks_summary, failed_checks_detail, parsed_failed_list)

        failed_checks_summary : string for grid cell display
        failed_checks_detail  : string for detail panel (with newlines)
        parsed_failed_list    : list of dicts for rich panel rendering
    """
    failed_checks_summary = "—"
    failed_checks_detail  = ""
    parsed_failed_list    = []

    try:
        if not raw_cr or str(raw_cr).strip() in (
            "", "None", "null", "[]"
        ):
            return "—", "No check results stored.", []

        check_results = json.loads(str(raw_cr))

        if not isinstance(check_results, list):
            return "—", "Unexpected check_results format.", []

        failed = [
            c for c in check_results
            if c.get("check_status") in ("CRITICAL", "WARNING")
        ]

        if not failed:
            return "✅ All passed", "All checks passed.", []

        summary_parts = []
        detail_parts  = []

        for c in failed:
            c_status  = c.get("check_status", "")
            c_name    = c.get("check_name", "UNKNOWN")
            c_level   = c.get("check_level", "")
            findings  = c.get("findings", [])
            rec       = c.get("recommendation", "")
            c_emoji   = "🔴" if c_status == "CRITICAL" else "🟡"

            summary_parts.append(f"{c_emoji} {c_name}")

            # Take the last meaningful finding — Agent 3 always puts
            # the most descriptive summary as the final finding
            top_finding = ""
            if findings and isinstance(findings, list):
                for f in reversed(findings):
                    if isinstance(f, str) and len(f.strip()) > 10:
                        top_finding = f.strip()
                        break

            detail_parts.append(
                f"{c_emoji} {c_name}"
                f"{f' [{c_level}]' if c_level else ''}"
                f"{f': {top_finding}' if top_finding else ''}"
            )

            parsed_failed_list.append({
                "check_name"  : c_name,
                "check_status": c_status,
                "check_level" : c_level,
                "top_finding" : top_finding,
                "recommendation": rec,
                "all_findings": findings,
                "emoji"       : c_emoji
            })

        failed_checks_summary = " | ".join(summary_parts)
        failed_checks_detail  = "\n\n".join(detail_parts)

    except Exception as e:
        logger.warning(f"Failed to parse check_results: {e}")
        failed_checks_summary = "⚠ Parse error"
        failed_checks_detail  = str(e)[:200]

    return failed_checks_summary, failed_checks_detail, parsed_failed_list


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("agent3-summary-cards", "children"),
    Output("transformations-grid", "rowData"),
    Input("refresh-transformations-btn", "n_clicks"),
    prevent_initial_call=False
)
def load_transformations(n_clicks):
    # ── Summary cards ──────────────────────────────────────────────────────
    try:
        from db.queries import get_agent3_dashboard_summary
        summary_df = execute_query(get_agent3_dashboard_summary())

        if not summary_df.empty:
            row = summary_df.iloc[0]

            def safe_int(val):
                try:
                    return int(val) if val is not None else 0
                except (TypeError, ValueError):
                    return 0

            total    = safe_int(row.get("transformations_registered"))
            active   = safe_int(row.get("active_transformations"))
            critical = safe_int(row.get("critical_last_review"))
            warning  = safe_int(row.get("warning_last_review"))
            passing  = safe_int(row.get("pass_last_review"))
            not_rev  = safe_int(row.get("not_reviewed"))

            def make_card(value, label, bg_color, text_color):
                return dbc.Col(dbc.Card([
                    dbc.CardBody([
                        html.H3(
                            str(value),
                            className="text-center fw-bold mb-0",
                            style={"color": text_color}
                        ),
                        html.P(
                            label,
                            className="text-center small mb-0",
                            style={"color": "#cccccc"}
                        )
                    ])
                ], style={
                    "backgroundColor": bg_color,
                    "border"         : f"1px solid {text_color}"
                }), md=2)

            cards = dbc.Row([
                make_card(total,   "Transformations", "#375a7f", "#ffffff"),
                make_card(active,  "Active",          "#375a7f", "#87ceeb"),
                make_card(critical, "Critical",
                          "#3d0000" if critical > 0 else "#2b2b2b",
                          "#ff6b6b" if critical > 0 else "#ffffff"),
                make_card(warning,  "Warning",
                          "#3d2600" if warning > 0 else "#2b2b2b",
                          "#ffa500" if warning > 0 else "#ffffff"),
                make_card(passing,  "Passing",
                          "#003d00" if passing > 0 else "#2b2b2b",
                          "#00c851" if passing > 0 else "#ffffff"),
                make_card(not_rev,  "Not Reviewed", "#2b2b2b", "#aaaaaa"),
            ])
        else:
            cards = dbc.Alert(
                "No transformations registered yet.",
                color="info"
            )

    except Exception as e:
        logger.error(f"Failed to load Agent 3 summary: {str(e)}")
        cards = dbc.Alert(
            f"Could not load summary: {str(e)}",
            color="danger"
        )

    # ── Transformations grid ───────────────────────────────────────────────
    try:
        df   = execute_query(get_all_transformations())
        rows = [_build_txfm_row(row) for _, row in df.iterrows()]
        rows = add_status_code(rows, "last_review_status")
        return cards, rows
    except Exception as e:
        logger.error(f"Failed to load transformations: {str(e)}")
        return cards, []


@callback(
    Output("selected-transformation-label", "children"),
    Output("deactivate-transformation-btn", "disabled"),
    Output("activate-transformation-btn", "disabled"),
    Output("review-history-header", "children"),
    Output("review-history-container", "children"),
    Input("transformations-grid", "selectedRows"),
    prevent_initial_call=True
)
def on_transformation_selected(selected_rows):
    if not selected_rows:
        return (
            "Select a row above to manage it.",
            True, True,
            "Review History — Click a row above to filter",
            dbc.Alert(
                "Select a transformation above to see its review history.",
                color="info"
            )
        )

    row          = selected_rows[0]
    txfm_id      = row.get("transformation_id", "")
    target_table = row.get("target_table", "")
    last_status  = row.get("last_review_status", "NOT_REVIEWED")
    emoji        = STATUS_EMOJI.get(last_status, "⚪")

    label = (
        f"Selected: {target_table} — "
        f"Last review: {emoji} {last_status}"
    )

    header = f"Review History — {target_table}"

    # ── Safe default ───────────────────────────────────────────────────────
    history_table = dbc.Alert(
        "Select a transformation above to see its review history.",
        color="info"
    )

    try:
        history_df = execute_query(*get_review_history(txfm_id))

        if history_df.empty:
            history_table = dbc.Alert(
                "No review history for this transformation yet. "
                "Run the SQL review agent notebook to generate a review.",
                color="info"
            )
        else:
            def safe_val(v):
                return str(v) if v is not None else ""

            history_rows = []

            for _, r in history_df.iterrows():
                status = str(r.get("overall_status", ""))

                # ── Business date — proper column ─────────────────────────────
                bd_raw = r.get("business_date")
                if bd_raw is not None:
                    business_date_str = str(bd_raw)[:10]
                else:
                    business_date_str = "—"

                # ── Parse check_results for failed check display ───────────────
                failed_checks_summary = "—"
                failed_checks_detail  = ""

                try:
                    check_results_list = json.loads(
                        r.get("check_results") or "[]"
                    )
                    failed = [
                        c for c in check_results_list
                        if c.get("check_status") in ("CRITICAL", "WARNING")
                    ]

                    if failed:
                        summary_parts = []
                        detail_parts  = []

                        for c in failed:
                            c_status = c.get("check_status", "")
                            c_name   = c.get("check_name", "")
                            c_level  = c.get("check_level", "")
                            findings = c.get("findings", [])
                            c_emoji  = "🔴" if c_status == "CRITICAL" else "🟡"

                            summary_parts.append(f"{c_emoji} {c_name}")

                            # For ROW_COUNT_RATIO include data date in detail
                            if (
                                c_name == "ROW_COUNT_RATIO"
                                and business_date_str != "—"
                            ):
                                findings = list(findings) + [
                                    f"Data date evaluated: {business_date_str}"
                                ]

                            top_finding = ""
                            for f in findings:
                                if any(kw in f for kw in [
                                    "Found", "WARNING", "CRITICAL",
                                    "No ", "Survival", "survival",
                                    "Data date"
                                ]):
                                    top_finding = f
                                    break
                            if not top_finding and findings:
                                top_finding = findings[0]

                            detail_parts.append(
                                f"{c_emoji} {c_name} [{c_level}]: {top_finding}"
                            )

                        failed_checks_summary = " | ".join(summary_parts)
                        failed_checks_detail  = "\n".join(detail_parts)

                except Exception as parse_err:
                    logger.warning(
                        f"Could not parse check_results: {parse_err}"
                    )

                history_rows.append({
                    "review_id"                  : safe_val(r.get("review_id")),
                    "review_timestamp"           : safe_val(r.get("review_timestamp")),
                    "business_date"              : business_date_str,
                    "overall_status"             : status,
                    "total_checks_run"           : str(r.get("total_checks_run", 0)),
                    "total_checks_passed"        : str(r.get("total_checks_passed", 0)),
                    "total_checks_warned"        : str(r.get("total_checks_warned", 0)),
                    "total_checks_critical"      : str(r.get("total_checks_critical", 0)),
                    "failed_checks"              : failed_checks_summary,
                    "failed_checks_detail"       : failed_checks_detail,
                    "ai_failure_category"        : safe_val(r.get("ai_failure_category")),
                    "ai_confidence"              : safe_val(r.get("ai_confidence")),
                    "ai_summary"                 : safe_val(r.get("ai_summary")),
                    "ai_recommended_action"      : safe_val(r.get("ai_recommended_action")),
                    "alert_sent"                 : "YES" if r.get("alert_sent") else "NO",
                    "check_results"              : safe_val(r.get("check_results")),
                    "target_fully_qualified_name": safe_val(
                        r.get("target_fully_qualified_name", "")
                    )
                })

                history_rows = add_status_code(history_rows, "overall_status")

            history_table = dag.AgGrid(
                **ag_grid_props(
                    grid_id="review-history-table",
                    row_data=history_rows,
                    col_defs=[
                        {"field": "review_timestamp",     "headerName": "Review Time",   "minWidth": 175},
                        {"field": "business_date",        "headerName": "Data Date",  "minWidth": 120},
                        {"field": "overall_status",       "headerName": "Status",     "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "total_checks_run",     "headerName": "Checks",        "width": 90},
                        {"field": "total_checks_passed",  "headerName": "Passed",        "width": 90},
                        {"field": "total_checks_warned",  "headerName": "Warned",        "width": 90},
                        {"field": "total_checks_critical","headerName": "Critical",      "width": 90},
                        {"field": "failed_checks",        "headerName": "Failed Checks", "flex": 2, "minWidth": 280},
                        {"field": "ai_failure_category",  "headerName": "AI Category",   "minWidth": 150},
                        {"field": "ai_confidence",        "headerName": "Confidence",    "width": 110},
                        {"field": "alert_sent",           "headerName": "Alert Sent",    "width": 90},
                    ],
                    page_size=5,
                    selection="single",
                    status_col="overall_status",
                )
            )

    except Exception as e:
        logger.error(f"Failed to load review history: {str(e)}")
        history_table = dbc.Alert(
            f"Could not load review history: {str(e)}",
            color="danger"
        )

    return label, False, False, header, history_table


@callback(
    Output("failed-check-detail-panel", "children"),
    Output("ai-summary-panel", "children"),
    Output("a3-preview-btn", "style"),
    Output("a3-alert-store", "data"),
    Input("review-history-table", "selectedRows"),
    prevent_initial_call=True
)
def show_review_detail(selected_rows):
    """
    Populates both the Failed Check Detail panel and
    the AI Summary panel when a review history row is selected.
    Replaces the old tooltip approach entirely.
    """
    hidden  = {"display": "none"}
    visible = {"display": "inline-block"}

    default_detail = html.P(
        "Select a review row above to see individual check results.",
        className="text-muted small mb-0"
    )

    default_ai = html.P(
        "Select a review row above to see AI summary.",
        className="text-muted"
    )

    if not selected_rows:
        return default_detail, default_ai, hidden, None

    row         = selected_rows[0]
    status      = row.get("overall_status", "")
    alerted     = row.get("alert_sent", "NO")
    raw_cr      = row.get("check_results", "")
    ai_summary  = row.get("ai_summary", "")
    ai_action   = row.get("ai_recommended_action", "")
    ai_category = row.get("ai_failure_category", "")
    confidence  = row.get("ai_confidence", "")

    # ── Failed Check Detail Panel ──────────────────────────────────────────
    _, _, parsed_failed = _parse_check_results(raw_cr)

    if not parsed_failed:
        detail_content = dbc.Alert(
            "All checks passed for this review. No issues found.",
            color="success",
            className="mb-0 small"
        )
    else:
        check_cards = []

        for c in parsed_failed:
            c_name    = c.get("check_name", "")
            c_status  = c.get("check_status", "")
            c_level   = c.get("check_level", "")
            c_emoji   = c.get("emoji", "⚪")
            top_find  = c.get("top_finding", "")
            rec       = c.get("recommendation", "")
            all_finds = c.get("all_findings", [])

            is_crit    = c_status == "CRITICAL"
            bg_color   = "#3d0000" if is_crit else "#3d2600"
            text_color = "#ff6b6b" if is_crit else "#ffa500"

            # Show all findings not just the top one
            findings_content = []
            for f in all_finds:
                if isinstance(f, str) and f.strip():
                    findings_content.append(
                        html.Li(
                            f.strip(),
                            className="small",
                            style={"color": "#cccccc"}
                        )
                    )

            check_cards.append(
                dbc.Card([
                    dbc.CardHeader(
                        dbc.Row([
                            dbc.Col([
                                html.Span(
                                    f"{c_emoji} {c_name}",
                                    className="fw-bold",
                                    style={"color": text_color}
                                ),
                                dbc.Badge(
                                    c_status,
                                    color=(
                                        "danger"
                                        if is_crit
                                        else "warning"
                                    ),
                                    className="ms-2"
                                ),
                                html.Span(
                                    f"  [{c_level}]",
                                    className="small text-muted ms-2"
                                )
                            ])
                        ]),
                        style={
                            "backgroundColor": bg_color,
                            "border"         : "none",
                            "padding"        : "8px 12px"
                        }
                    ),
                    dbc.CardBody([
                        # All findings
                        html.P(
                            "Findings:",
                            className="small fw-bold mb-1",
                            style={"color": "#aaaaaa"}
                        ),
                        html.Ul(
                            findings_content,
                            className="mb-2 ps-3"
                        ) if findings_content else html.Div(),

                        # Recommendation
                        html.Hr(
                            style={"borderColor": "#444"}
                        ) if rec else html.Div(),
                        html.P(
                            [
                                html.Strong(
                                    "Recommendation: ",
                                    style={"color": "#87ceeb"}
                                ),
                                html.Span(
                                    rec,
                                    style={"color": "#cccccc"}
                                )
                            ],
                            className="small mb-0"
                        ) if rec else html.Div()
                    ], style={
                        "backgroundColor": "#2b2b2b",
                        "padding"        : "10px 12px"
                    })
                ], className="mb-3",
                style={
                    "border"         : f"1px solid {text_color}",
                    "backgroundColor": "#2b2b2b"
                })
            )

        detail_content = html.Div(check_cards)

    # ── AI Summary Panel ───────────────────────────────────────────────────
    if not ai_summary or ai_summary in ("", "None"):
        ai_panel = dbc.Alert(
            "No AI summary available for this review. "
            "AI is only generated when checks fail.",
            color="info"
        )
    else:
        emoji = STATUS_EMOJI.get(status, "⚪")

        try:
            confidence_pct = f"{float(confidence):.0%}"
        except (TypeError, ValueError):
            confidence_pct = "N/A"

        ai_panel = dbc.Container([
            dbc.Row([
                dbc.Col([
                    dbc.Badge(
                        f"{emoji} {status}",
                        color=(
                            "danger"  if status == "CRITICAL"
                            else "warning" if status == "WARNING"
                            else "success"
                        ),
                        className="me-2 mb-2 fs-6"
                    ),
                    dbc.Badge(
                        ai_category or "N/A",
                        color="secondary",
                        className="me-2 mb-2 fs-6"
                    ),
                    dbc.Badge(
                        f"Confidence: {confidence_pct}",
                        color="info",
                        className="mb-2 fs-6"
                    )
                ])
            ]),
            dbc.Row([
                dbc.Col([
                    html.H6(
                        "AI Summary",
                        className="text-info mt-2"
                    ),
                    html.P(
                        ai_summary,
                        className="border-start border-info ps-3"
                    )
                ], md=6),
                dbc.Col([
                    html.H6(
                        "Recommended Fix",
                        className="text-warning mt-2"
                    ),
                    html.P(
                        ai_action or "No specific action recommended.",
                        className="border-start border-warning ps-3"
                    )
                ], md=6)
            ])
        ], fluid=True)

    btn_style  = visible if alerted == "YES" else hidden
    store_data = row if alerted == "YES" else None

    return detail_content, ai_panel, btn_style, store_data


# ── Target dropdown: Silver tables from uc2_layer_registry_b ─────────────────

@callback(
    Output("reg-target-table-dropdown", "options"),
    Output("a3-layer-store", "data"),
    Input("reg-target-table-dropdown", "id")
)
def load_target_table_options(_):
    try:
        df = execute_query(get_silver_layer_tables())
        if df.empty:
            logger.warning(
                "No Silver layers found in uc2_layer_registry_b."
            )
            return [], []

        options = [
            {
                "label": str(
                    row["layer_fully_qualified_name"]
                ).split(".")[-1],
                "value": str(row["layer_fully_qualified_name"])
            }
            for _, row in df.iterrows()
        ]
        store_data = df.to_dict("records")
        logger.info(f"Silver tables loaded: {len(options)}")
        return options, store_data

    except Exception as e:
        logger.error(f"Failed to load Silver table options: {str(e)}")
        return [], []


# ── Source dropdown: Raw tables from uc1_table_registry_b ────────────────────

@callback(
    Output("reg-source-table-dropdown", "options"),
    Input("reg-source-table-dropdown", "id")
)
def load_source_table_options(_):
    try:
        df = execute_query(get_all_registered_tables())
        if df.empty:
            return []

        options = [
            {
                "label": str(
                    row["fully_qualified_name"]
                ).split(".")[-1],
                "value": str(row["fully_qualified_name"])
            }
            for _, row in df.iterrows()
        ]
        logger.info(f"Raw tables loaded: {len(options)}")
        return options

    except Exception as e:
        logger.error(f"Failed to load Raw table options: {str(e)}")
        return []


# ── Auto-populate Source and Survival Rate when Target selected ─────────────

@callback(
    Output("reg-source-table-dropdown", "value"),
    Output("reg-survival-rate-input", "value"),
    Input("reg-target-table-dropdown", "value"),
    State("a3-layer-store", "data"),
    prevent_initial_call=True
)
def auto_populate_from_target(target_fqn, layer_store):
    if not target_fqn or not layer_store:
        return None, None

    matching = [
        r for r in layer_store
        if r.get("layer_fully_qualified_name") == target_fqn
    ]

    if not matching:
        return None, None

    row    = matching[0]
    source = row.get("source_fully_qualified_name")

    survival_raw = row.get("expected_survival_rate")
    try:
        survival_pct = (
            round(float(survival_raw) * 100, 0)
            if survival_raw else None
        )
    except (TypeError, ValueError):
        survival_pct = None

    return source, survival_pct


# ── Register Transformation ────────────────────────────────────────────────

@callback(
    Output("sql-review-alert", "children"),
    Output("transformations-grid", "rowData", allow_duplicate=True),
    Input("register-transformation-btn", "n_clicks"),
    State("reg-target-table-dropdown", "value"),
    State("reg-source-table-dropdown", "value"),
    State("reg-notebook-path-input", "value"),
    State("reg-language-dropdown", "value"),
    State("reg-function-name-input", "value"),
    State("reg-survival-rate-input", "value"),
    State("reg-registered-by-input", "value"),
    State("reg-description-input", "value"),
    State("reg-checks-checklist", "value"),
    prevent_initial_call=True
)
def register_transformation(
    n_clicks,
    target_fqn,
    source_fqn,
    notebook_path,
    language,
    function_name,
    survival_rate,
    registered_by,
    description,
    checks_enabled
):
    if not n_clicks:
        return "", []

    required = {
        "Target Table"  : target_fqn,
        "Source Table"  : source_fqn,
        "Notebook Path" : notebook_path,
        "Survival Rate" : survival_rate,
        "Registered By" : registered_by
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        return error_alert(
            f"Please fill in: {', '.join(missing)}"
        ), []

    if not checks_enabled:
        return error_alert(
            "Please select at least one check to enable."
        ), []

    try:
        survival = float(survival_rate)
        if survival > 1.0:
            survival = survival / 100.0
    except (TypeError, ValueError):
        return error_alert(
            "Survival rate must be a number (e.g. 92 or 0.92)"
        ), []

    txfm_id     = str(uuid.uuid4())[:13]
    checks_json = json.dumps(checks_enabled)

    try:
        query = insert_transformation(
            transformation_id           = txfm_id,
            target_fully_qualified_name = target_fqn,
            target_layer                = "SILVER",
            notebook_path               = notebook_path.strip(),
            notebook_language           = language or "PYTHON",
            function_name               = (function_name or "").strip(),
            source_fully_qualified_name = source_fqn,
            transformation_description  = (description or "").strip(),
            checks_enabled              = checks_json,
            expected_survival_rate      = survival,
            registered_by               = registered_by.strip()
        )
        execute_write(*query)

        df   = execute_query(get_all_transformations())
        rows = [_build_txfm_row(row) for _, row in df.iterrows()]

        return (
            success_alert(
                f"Transformation registered successfully. ID: {txfm_id}"
            ),
            rows
        )

    except Exception as e:
        logger.error(f"Failed to register transformation: {str(e)}")
        return error_alert(f"Registration failed: {str(e)}"), []


# ── Toggle Transformation Active Status ────────────────────────────────────

@callback(
    Output("sql-review-alert", "children", allow_duplicate=True),
    Output("transformations-grid", "rowData", allow_duplicate=True),
    Input("deactivate-transformation-btn", "n_clicks"),
    Input("activate-transformation-btn", "n_clicks"),
    State("transformations-grid", "selectedRows"),
    prevent_initial_call=True
)
def toggle_transformation_status(
    deactivate_clicks,
    activate_clicks,
    selected_rows
):
    if not selected_rows:
        return "", []

    triggered = ctx.triggered_id
    row       = selected_rows[0]
    txfm_id   = row.get("transformation_id", "")
    is_active = triggered == "activate-transformation-btn"

    try:
        execute_write(*toggle_transformation_active(txfm_id, is_active))

        df   = execute_query(get_all_transformations())
        rows = [_build_txfm_row(r) for _, r in df.iterrows()]

        action = "activated" if is_active else "deactivated"
        return (
            success_alert(
                f"Transformation {txfm_id} {action} successfully."
            ),
            rows
        )

    except Exception as e:
        logger.error(f"Failed to toggle transformation: {str(e)}")
        return error_alert(f"Toggle failed: {str(e)}"), []


# ── Agent 3 Alert Modal ────────────────────────────────────────────────────

@callback(
    Output("a3-alert-modal", "is_open"),
    Output("a3-alert-modal-title", "children"),
    Output("a3-alert-modal-body", "children"),
    Input("a3-preview-btn", "n_clicks"),
    Input("a3-alert-modal-close-btn", "n_clicks"),
    State("a3-alert-store", "data"),
    State("a3-alert-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_a3_modal(open_clicks, close_clicks, store_data, is_open):
    triggered = ctx.triggered_id

    if triggered == "a3-alert-modal-close-btn":
        return False, "", []

    if triggered == "a3-preview-btn" and store_data:
        review_id  = store_data.get("review_id", "")
        status     = store_data.get("overall_status", "")
        table      = store_data.get("target_table", "")
        raw_ts     = store_data.get("review_timestamp", "")
        date       = str(raw_ts)[:10] if raw_ts else "N/A"
        emoji      = STATUS_EMOJI.get(status, "⚪")

        ai_summary  = store_data.get("ai_summary", "")  or None
        ai_action   = store_data.get("ai_recommended_action", "") or None
        ai_category = store_data.get("ai_failure_category", "") or None
        ai_conf_raw = store_data.get("ai_confidence")

        try:
            ai_confidence = float(ai_conf_raw) if ai_conf_raw else None
        except (TypeError, ValueError):
            ai_confidence = None

        # Parse failed checks from check_results JSON
        raw_cr = store_data.get("check_results", "[]")
        _, _, parsed_failed = _parse_check_results(raw_cr)

        failed_checks = [
            {
                "check_type"        : c.get("check_name", ""),
                "column_name"       : c.get("check_level", "STATIC"),
                "check_status"      : c.get("check_status", ""),
                "observed_value"    : None,
                "deviation_pct"     : None,
                "threshold_warning" : None,
                "threshold_critical": None
            }
            for c in parsed_failed
        ]

        title = f"{emoji} {status}: {table} SQL Review — {date}"

        body = build_alert_card_body(
            agent_name      = "Transformation Agent — Silver SQL Review",
            table_name      = table,
            fqn             = store_data.get(
                "target_fully_qualified_name", ""
            ),
            business_date   = date,
            status          = status,
            checks_run      = int(store_data.get("total_checks_run", 0)),
            checks_passed   = int(store_data.get("total_checks_passed", 0)),
            checks_warned   = int(store_data.get("total_checks_warned", 0)),
            checks_critical = int(
                store_data.get("total_checks_critical", 0)
            ),
            failed_checks   = failed_checks,
            ai_summary      = ai_summary,
            ai_action       = ai_action,
            ai_category     = ai_category,
            ai_confidence   = ai_confidence,
            run_id          = review_id
        )

        return True, title, body

    return False, "", []