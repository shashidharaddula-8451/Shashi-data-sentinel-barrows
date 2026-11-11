# pages/dashboard.py

import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from db.queries import (
    get_validation_coverage,
    get_combined_dashboard_summary,
    get_reconciliation_run_summary,
    get_review_history,
    get_kpi_validation_run_summary,
    get_validation_run_summary 
)

import dash_ag_grid as dag
from components.alerts import (
    fmt_number,
    fmt_deviation,
    fmt_threshold,
    compute_signed_deviation,
    ag_grid_props,
    AG_STATUS_CELL_STYLE_JS,
)

from dash import ctx, ALL, State
import requests
import json
import os
from datetime import date, datetime, timedelta

import logging

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/", name="Dashboard")

layout = dbc.Container([
    dcc.Interval(
        id          = "dashboard-refresh-interval",
        interval    = 5 * 60 * 1000,
        n_intervals = 0,
        disabled    = True
    ),

    dcc.Store(id="db-refresh-paused", data=True),
    dcc.Store(id="db-initial-load-trigger", data=True),

    dbc.Row([
        dbc.Col([
            html.Div(
                id    = "db-refresh-indicator",
                style = {"color": "#64748b", "fontSize": "12px",
                         "marginTop": "16px", "marginBottom": "4px"}
            )
        ], md=8),
        dbc.Col([
            dbc.Button(
                "⏸ Pause Auto-Refresh",
                id       = "db-refresh-toggle",
                color    = "secondary",
                outline  = True,
                size     = "sm",
                n_clicks = 0,
                style    = {"fontSize": "12px", "marginTop": "16px"}
            )
        ], md=4, className="d-flex justify-content-end"),
    ], className="mb-2"),

    # ── Page Header ────────────────────────────────────────────────────────
    html.H2(
        "Data Sentinel — Overview",
        className="mt-4 mb-1"
    ),
    html.P(
        "Real-time status across all four validation agents.",
        className="text-muted mb-4"
    ),

    # ── Add to dashboard.py layout ─────────────────────────────────────────────
    # Insert this card BEFORE the existing "Agent Summary" section

    dbc.Card([
        dbc.CardBody([
            html.H5(
                "Ask DataSentinel",
                className="mb-1 text-white",
                style={"fontSize": "18px", "fontWeight": "600"}
            ),
            html.P(
                "Ask questions about your data platform in plain English.",
                className="text-muted mb-3",
                style={"fontSize": "14px"}
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Input(
                        id          = "nlq-input",
                        placeholder = (
                            'Try: "Which tables had volume drops last week?" '
                            'or "What caused the KPI failure on June 21st?"'
                        ),
                        type        = "text",
                        debounce    = False,
                        n_submit    = 0,
                        style={
                            "backgroundColor": "#1a1a1a",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555",
                            "fontSize"       : "15px",
                            "height"         : "44px",
                        }
                    ),
                ], md=9),
                dbc.Col([
                    dbc.Button(
                        "Ask →",
                        id        = "nlq-submit-btn",
                        color     = "primary",
                        className = "w-100",
                        n_clicks  = 0,
                        style     = {"height": "44px", "fontSize": "15px"}
                    ),
                ], md=3),
            ], className="mb-3"),

            # Example chips
            html.Div([
                html.Span(
                    "Try: ",
                    style={"color": "#666", "fontSize": "13px",
                        "marginRight": "8px"}
                ),
                *[
                    html.Span(
                        example,
                        id          = {"type": "nlq-example", "index": i},
                        n_clicks    = 0,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "border"         : "1px solid #444",
                            "borderRadius"   : "12px",
                            "padding"        : "4px 12px",
                            "marginRight"    : "8px",
                            "fontSize"       : "12px",
                            "color"          : "#aaaaaa",
                            "cursor"         : "pointer",
                            "display"        : "inline-block",
                            "marginBottom"   : "4px",
                        }
                    )
                    for i, example in enumerate([
                        "Which tables had volume drops last week?",
                        "What caused the KPI failure on June 21st?",
                        "How many CRITICAL alerts this month?",
                        "Is transaction data healthy today?",
                    ])
                ]
            ], className="mb-3"),

            # Answer panel — hidden until a query is made
            dbc.Spinner(
                html.Div(id="nlq-answer-panel"),
                color  = "primary",
                type   = "border",
                spinner_style = {"width": "2rem", "height": "2rem"}
            ),
        ])
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),

    # ── Agent Summary Cards ────────────────────────────────────────────────
    html.H5("Agent Summary", className="mb-3 text-secondary"),
    dcc.Loading(
        id    = "dashboard-main-loading",
        type  = "circle",
        color = "#00c851",
        children = [
            dbc.Row(id="combined-summary-cards", className="mb-4"),

    html.Hr(className="my-4"),

    # ── Agent 1 Section ───────────────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.H5(
                "🔍 Validation Agent — Raw Ingestion Validation",
                className="mb-3"
            ),
            html.P(
                "Validation coverage across registered raw tables.",
                className="text-muted small mb-3"
            )
        ])
    ]),
    dbc.Card([
        dbc.CardBody([
            html.Div(id="agent1-coverage-table")
        ])
    ], className="mb-4"),

    html.Hr(className="my-4"),

    # ── Agent 2 Section ───────────────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.H5(
                "🔄 Reconciliation Agent — Cross-Layer Reconciliation",
                className="mb-3"
            ),
            html.P(
                "Recent reconciliation runs across Raw, Silver, and Gold layers.",
                className="text-muted small mb-3"
            )
        ])
    ]),
    dbc.Card([
        dbc.CardBody([
            html.Div(id="agent2-recent-runs")
        ])
    ], className="mb-4"),

    html.Hr(className="my-4"),

    # ── Agent 3 Section ───────────────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.H5(
                "🧪 Transformation Agent — Silver SQL Review",
                className="mb-3"
            ),
            html.P(
                "Latest transformation review results.",
                className="text-muted small mb-3"
            )
        ])
    ]),
    dbc.Card([
        dbc.CardBody([
            html.Div(id="agent3-recent-reviews")
        ])
    ], className="mb-4"),

    # ── Agent 4 Section ───────────────────────────────────────────────────

    html.Hr(className="my-4"),

    dbc.Row([
        dbc.Col([
            html.H5(
                "📊 KPI Assurance Agent — Gold KPI Validation",
                className="mb-3"
            ),
            html.P(
                "Latest KPI validation results across Gold tables.",
                className="text-muted small mb-3"
            )
        ])
    ]),
    dbc.Card([
        dbc.CardBody([
            html.Div(id="agent4-recent-validations")
        ])
    ], className="mb-4"),
        ]
    ),

], fluid=True)


@callback(
    Output("combined-summary-cards",    "children"),
    Output("agent1-coverage-table",     "children"),
    Output("agent2-recent-runs",        "children"),
    Output("agent3-recent-reviews",     "children"),
    Output("agent4-recent-validations", "children"),
    Input("db-initial-load-trigger",       "data"),
    Input("dashboard-refresh-interval", "n_intervals"),
)
def load_dashboard(_, n_intervals):

    # ── Agent Summary Cards ────────────────────────────────────────────────
    try:
        df = execute_query(get_combined_dashboard_summary())

        cards = []
        agent_meta = {
            "Agent 1": {"icon": "🔍", "color": "blue",  "gradient": {"from": "blue",   "to": "cyan",   "deg": 45}},
            "Agent 2": {"icon": "🔄", "color": "green", "gradient": {"from": "green",  "to": "teal",   "deg": 45}},
            "Agent 3": {"icon": "🧪", "color": "violet","gradient": {"from": "violet", "to": "grape",  "deg": 45}},
            "Agent 4": {"icon": "📊", "color": "orange","gradient": {"from": "orange", "to": "yellow", "deg": 45}},
        }

        for _, row in df.iterrows():
            agent_raw = str(row.get("agent", ""))
            agent    = AGENT_DISPLAY_NAME.get(agent_raw, agent_raw)
            tables   = int(row.get("tables_monitored") or 0)
            checks   = int(row.get("total_checks_run") or 0)
            critical = int(row.get("critical_runs") or 0)
            passing  = int(row.get("pass_runs") or 0)
            latest   = str(row.get("latest_date", "N/A"))
            meta     = agent_meta.get(agent_raw, {"icon": "⚙️", "color": "gray", "gradient": {"from": "gray", "to": "dark", "deg": 45}})

            crit_color = "#e03131" if critical > 0 else "#ffffff"
            cards.append(
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            # Header row: icon + agent name + date badge
                            html.Div([
                                html.Span(
                                    meta["icon"],
                                    style={"fontSize": "18px", "marginRight": "8px"}
                                ),
                                html.Span(
                                    agent,
                                    style={"fontWeight": "600", "fontSize": "14px",
                                           "color": "#ffffff"}
                                ),
                                html.Span(
                                    f"📅 {latest}",
                                    style={"float": "right", "fontSize": "11px",
                                           "color": "#909296", "border": "1px solid #555",
                                           "borderRadius": "4px", "padding": "2px 8px"}
                                ),
                            ], style={"marginBottom": "12px"}),
                            # Stats row
                            html.Div([
                                html.Div([
                                    html.Div(str(tables), style={"fontWeight": "700",
                                             "fontSize": "22px", "color": "#ffffff",
                                             "textAlign": "center"}),
                                    html.Div("Tables", style={"fontSize": "11px",
                                             "color": "#909296", "textAlign": "center"}),
                                ], style={"flex": "1"}),
                                html.Div([
                                    html.Div(str(checks), style={"fontWeight": "700",
                                             "fontSize": "22px", "color": "#ffffff",
                                             "textAlign": "center"}),
                                    html.Div("Checks", style={"fontSize": "11px",
                                             "color": "#909296", "textAlign": "center"}),
                                ], style={"flex": "1"}),
                                html.Div([
                                    html.Div(str(critical), style={"fontWeight": "700",
                                             "fontSize": "22px", "color": crit_color,
                                             "textAlign": "center"}),
                                    html.Div("Critical", style={"fontSize": "11px",
                                             "color": "#909296", "textAlign": "center"}),
                                ], style={"flex": "1"}),
                            ], style={"display": "flex", "justifyContent": "space-around"}),
                        ])
                    ], style={"backgroundColor": "#25262B", "border": "1px solid #373A40",
                              "borderRadius": "8px"})
                ], md=3)
            )

        summary_cards = dbc.Row(cards)

    except Exception as e:
        logger.error(f"Failed to load combined summary: {str(e)}")
        summary_cards = dbc.Alert(
            f"Could not load summary: {str(e)}",
            color="danger"
        )

    # ── Agent 1 Coverage Table ─────────────────────────────────────────────
    try:
        from db.queries import get_validation_coverage
        coverage_df = execute_query(get_validation_coverage())

        if coverage_df.empty:
            agent1_content = dbc.Alert(
                "No tables registered yet. "
                "Use Validation Agent → Table Registry to onboard tables.",
                color="info"
            )
        else:
            agent1_content = dag.AgGrid(
                **ag_grid_props(
                    grid_id="db-agent1-coverage-grid",
                    row_data=coverage_df.to_dict("records"),
                    col_defs=[
                        {"field": "fully_qualified_name",             "headerName": "Table",      "flex": 2, "minWidth": 220},
                        {"field": "source_type",                     "headerName": "Source Type", "minWidth": 150},
                        {"field": "ingestion_frequency",             "headerName": "Frequency",   "minWidth": 150},
                        {"field": "is_active",                       "headerName": "Active",      "width": 90},
                        {"field": "columns_enrolled",                "headerName": "Columns",     "width": 90},
                        {"field": "column_validations_configured",   "headerName": "Col Checks",  "width": 100},
                        {"field": "table_validations_configured",    "headerName": "Tbl Checks",  "width": 100},
                    ],
                    page_size=5,
                    height=250,
                )
            )

    except Exception as e:
        logger.error(f"Failed to load Agent 1 coverage: {str(e)}")
        agent1_content = dbc.Alert(
            f"Could not load Validation Agent data: {str(e)}",
            color="danger"
        )

    # ── Agent 2 Recent Runs ────────────────────────────────────────────────────
    try:
        recon_df = execute_query(get_reconciliation_run_summary())

        if recon_df.empty:
            agent2_content = dbc.Alert(
                "No reconciliation runs yet.",
                color="info"
            )
        else:
            def safe_int(val, default=0):
                try:
                    return int(val) if val is not None else default
                except (TypeError, ValueError):
                    return default

            def safe_str(val, default=""):
                """
                Converts a value to string safely.
                Handles None, NaN, float NaN from pandas.
                """
                import math
                if val is None:
                    return default
                try:
                    if isinstance(val, float) and math.isnan(val):
                        return default
                except (TypeError, ValueError):
                    pass
                s = str(val).strip()
                if s.lower() in ("none", "nan", ""):
                    return default
                return s

            rows = []
            for _, row in recon_df.head(6).iterrows():

                # table_name — confirmed present in query output
                table_name = safe_str(row.get("table_name"))
                if not table_name:
                    fqn        = safe_str(row.get("source_fully_qualified_name"))
                    table_name = fqn.split(".")[-1] if "." in fqn else fqn

                rows.append({
                    "business_date"        : safe_str(row.get("business_date")),
                    "table_name"           : table_name,
                    "overall_status"       : safe_str(row.get("overall_status")),
                    "total_checks_run"     : safe_int(row.get("total_checks_run")),
                    "total_checks_critical": safe_int(
                        row.get("total_checks_critical")
                    ),
                    "ai_enrichment_status" : safe_str(row.get("ai_enrichment_status")),
                    "alert_fired"          : safe_str(
                        row.get("alert_fired"), default="NO"
                    )
                })

            agent2_content = dag.AgGrid(
                **ag_grid_props(
                    grid_id="db-agent2-runs-grid",
                    row_data=rows,
                    col_defs=[
                        {"field": "business_date",         "headerName": "Date",  "minWidth": 120},
                        {"field": "table_name",            "headerName": "Table",    "flex": 1, "minWidth": 220},
                        {"field": "overall_status",        "headerName": "Status",   "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "total_checks_run",      "headerName": "Checks",   "width": 90},
                        {"field": "total_checks_critical", "headerName": "Critical", "width": 90},
                        {"field": "ai_enrichment_status",  "headerName": "AI",    "minWidth": 150},
                        {"field": "alert_fired",           "headerName": "Alert",    "width": 90},
                    ],
                    page_size=6,
                    status_col="overall_status",
                    height=280,
                )
            )

    except Exception as e:
        logger.error(f"Failed to load Agent 2 runs: {str(e)}")
        agent2_content = dbc.Alert(
            f"Could not load Reconciliation Agent data: {str(e)}",
            color="danger"
        )

    # ── Agent 3 Recent Reviews ─────────────────────────────────────────────
    try:
        reviews_df = execute_query(*get_review_history())

        if reviews_df.empty:
            agent3_content = dbc.Alert(
                "No SQL reviews yet. "
                "Run Transformation Agent → SQL Review Agent notebook to generate reviews.",
                color="info"
            )
        else:
            # Agent 3 row builder
            rows = []
            for _, row in reviews_df.head(6).iterrows():
                target = str(row.get("target_table", ""))
                if not target or target == "None":
                    fqn    = str(row.get("target_fully_qualified_name", ""))
                    target = fqn.split(".")[-1] if "." in fqn else fqn

                # Business date from proper column
                bd_raw = row.get("business_date")
                bdate  = str(bd_raw)[:10] if bd_raw is not None else "—"

                rows.append({
                    "review_timestamp"     : str(row.get("review_timestamp", ""))[:19],
                    "target_table"         : target,
                    "business_date"        : bdate,
                    "overall_status"       : str(row.get("overall_status", "")),
                    "total_checks_run"     : str(row.get("total_checks_run", 0)),
                    "total_checks_critical": str(row.get("total_checks_critical", 0)),
                    "ai_failure_category"  : str(row.get("ai_failure_category", "")),
                    "alert_sent"           : "YES" if row.get("alert_sent") else "NO"
                })

            agent3_content = dag.AgGrid(
                **ag_grid_props(
                    grid_id="db-agent3-reviews-grid",
                    row_data=rows,
                    col_defs=[
                        {"field": "review_timestamp",      "headerName": "Review Time",  "minWidth": 175},
                        {"field": "target_table",          "headerName": "Table",         "flex": 1, "minWidth": 220},
                        {"field": "business_date",         "headerName": "Data Date",  "minWidth": 120},
                        {"field": "overall_status",        "headerName": "Status",     "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "total_checks_run",      "headerName": "Checks",        "width": 90},
                        {"field": "total_checks_critical", "headerName": "Critical",      "width": 90},
                        {"field": "ai_failure_category",   "headerName": "AI Category",   "flex": 1, "minWidth": 150},
                        {"field": "alert_sent",            "headerName": "Alert",          "width": 90},
                    ],
                    page_size=6,
                    status_col="overall_status",
                    height=280,
                )
            )

    except Exception as e:
        logger.error(f"Failed to load Agent 3 reviews: {str(e)}")
        agent3_content = dbc.Alert(
            f"Could not load Transformation Agent data: {str(e)}",
            color="danger"
        )

    # ── Agent 4 Recent KPI Validations ─────────────────────────────────────
    try:
        kpi_df = execute_query(get_kpi_validation_run_summary())

        if kpi_df.empty:
            agent4_content = dbc.Alert(
                "No KPI validations yet. Run KPI Assurance Agent notebook.",
                color="info"
            )
        else:
            def safe_int(v):
                try:
                    return int(v) if v is not None else 0
                except (TypeError, ValueError):
                    return 0

            rows = []
            for _, row in kpi_df.head(6).iterrows():
                rows.append({
                    "business_date"      : str(row.get("business_date", "")),
                    "gold_table"         : str(row.get("gold_table", "")),
                    "overall_status"     : str(row.get("overall_status", "")),
                    "total_kpis_checked" : safe_int(row.get("total_kpis_checked")),
                    "total_kpis_critical": safe_int(row.get("total_kpis_critical")),
                    "ai_enrichment_status": str(row.get("ai_enrichment_status", "")),
                    "alert_fired"        : str(row.get("alert_fired", "NO"))
                })

            agent4_content = dag.AgGrid(
                **ag_grid_props(
                    grid_id="db-agent4-kpi-grid",
                    row_data=rows,
                    col_defs=[
                        {"field": "business_date",        "headerName": "Date",  "minWidth": 120},
                        {"field": "gold_table",           "headerName": "Table",    "flex": 1, "minWidth": 220},
                        {"field": "overall_status",       "headerName": "Status",   "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "total_kpis_checked",   "headerName": "KPIs",     "width": 90},
                        {"field": "total_kpis_critical",  "headerName": "Critical", "width": 90},
                        {"field": "ai_enrichment_status", "headerName": "AI",    "minWidth": 150},
                        {"field": "alert_fired",          "headerName": "Alert",    "width": 90},
                    ],
                    page_size=6,
                    status_col="overall_status",
                    height=280,
                )
            )

    except Exception as e:
        logger.error(f"Failed to load Agent 4 validations: {str(e)}")
        agent4_content = dbc.Alert(
            f"Could not load KPI Assurance Agent data: {str(e)}",
            color="danger"
        )

    return (
        summary_cards,
        agent1_content,
        agent2_content,
        agent3_content,
        agent4_content
    )


@callback(
    Output("dashboard-quality-score-widget", "children"),
    Input("db-initial-load-trigger", "data")
)
def load_dashboard_quality_widget(_):
    try:
        import importlib
        qs = importlib.import_module("pages.quality_score")

        history = qs._load_history(days=90)
        if not history:
            return html.P(
                "Quality score not yet available.",
                className="text-muted small mb-0"
            )

        latest_date = history[-1][0]
        today_dims  = qs._load_dimension_scores_for_date(latest_date)
        trends      = qs._compute_trends(history)
        overall     = qs._weighted_overall(today_dims)
        color       = qs._score_color(overall)

        dim_pills = []
        for key in qs.WEIGHTS.keys():
            score = today_dims.get(key)
            dim_pills.append(
                html.Div([
                    html.Span(
                        qs.DIMENSION_LABELS[key],
                        style={
                            "color"  : "#aaaaaa",
                            "fontSize": "11px",
                            "display": "block"
                        }
                    ),
                    html.Span(
                        f"{score}/100" if score is not None else "—",
                        style={
                            "color"     : qs._score_color(score),
                            "fontSize"  : "14px",
                            "fontWeight": "700"
                        }
                    ),
                ], style={
                    "marginRight" : "24px",
                    "display"     : "inline-block",
                    "verticalAlign": "top",
                })
            )

        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.Span(
                        f"{overall}/100" if overall is not None else "—",
                        style={
                            "color"     : color,
                            "fontSize"  : "36px",
                            "fontWeight": "800",
                            "lineHeight": "1"
                        }
                    ),
                    html.Span(
                        " Quality Score",
                        style={
                            "color"      : "#aaaaaa",
                            "fontSize"   : "14px",
                            "marginLeft" : "8px"
                        }
                    ),
                    html.Div([
                        qs._trend_element("vs last week",  trends.get("vs_week")),
                        qs._trend_element("vs last month", trends.get("vs_month")),
                    ], style={"marginTop": "6px"}),
                ], md=4),
                dbc.Col([
                    html.Div(dim_pills, style={"paddingTop": "4px"})
                ], md=6),
                dbc.Col([
                    dbc.Button(
                        "View Details →",
                        href="/quality-score",
                        color="link",
                        style={
                            "color"    : "#4a9edd",
                            "fontSize" : "14px",
                            "padding"  : "0",
                            "marginTop": "8px"
                        }
                    )
                ], md=2, className="d-flex align-items-center justify-content-end"),
            ], align="center"),
        ])

    except Exception as e:
        logger.error(f"Dashboard quality widget failed: {e}")
        return html.P(
            "Quality score temporarily unavailable.",
            className="text-muted small mb-0"
        )

# ── NLQ: populate input from example chips ─────────────────────────────────

@callback(
    Output("nlq-input", "value"),
    Input({"type": "nlq-example", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def populate_from_example(n_clicks_list):
    """Clicking an example chip fills the search input."""
    if not any(n for n in n_clicks_list if n):
        return dash.no_update

    examples = [
        "Which tables had volume drops last week?",
        "What caused the KPI failure on June 21st?",
        "How many CRITICAL alerts this month?",
        "Is transaction data healthy today?",
    ]

    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        idx = triggered.get("index", 0)
        return examples[idx]

    return dash.no_update


# ── NLQ: main query callback ───────────────────────────────────────────────

@callback(
    Output("nlq-answer-panel", "children"),
    Input("nlq-submit-btn", "n_clicks"),
    Input("nlq-input", "n_submit"),
    State("nlq-input", "value"),
    prevent_initial_call=True,
)
def handle_nlq(n_clicks, n_submit, query):
    """
    Main NLQ handler.
    Step 1: classify intent via AI (small structured call).
    Step 2: fetch data deterministically.
    Step 3: render answer.
    """
    if not query or not query.strip():
        return _nlq_info("Please type a question above.")

    query = query.strip()

    # ── Step 1: Classify intent ────────────────────────────────────────────
    try:
        intent_data = _classify_intent(query)
    except Exception as e:
        logger.error(f"NLQ intent classification failed: {e}")
        return _nlq_error(
            "Could not understand your question. Please try rephrasing."
        )

    intent = intent_data.get("intent", "unknown")
    params = intent_data.get("params", {})

    logger.info(f"NLQ intent={intent} params={params} query='{query}'")

    # ── Step 2 + 3: Fetch and render ──────────────────────────────────────
    try:
        if intent == "volume_drop":
            return _answer_volume_drop(params, query)

        elif intent == "kpi_failure":
            return _answer_kpi_failure(params, query)

        elif intent == "alert_count":
            return _answer_alert_count(params, query)

        elif intent == "table_health":
            return _answer_table_health(params, query)

        elif intent == "critical_checks":
            return _answer_critical_checks(params, query)

        elif intent == "agent_summary":
            return _answer_agent_summary(params, query)

        else:
            return _answer_unknown(query)

    except Exception as e:
        logger.error(f"NLQ answer render failed: {e}")
        return _nlq_error(f"Found the intent but could not fetch data: {str(e)}")


# ── Intent classification ──────────────────────────────────────────────────

def _classify_intent(query: str) -> dict:
    """
    Calls the AI model with a tiny structured prompt.
    Returns dict with intent and params.
    Timeout is short (15s) — this must be fast.
    """
    today     = date.today().isoformat()
    week_ago  = (date.today() - timedelta(days=7)).isoformat()
    month_ago = (date.today() - timedelta(days=30)).isoformat()

    prompt = f"""You are a data platform query classifier.
Today's date is {today}.

Classify the user query into exactly one intent and extract parameters.
Respond with valid JSON only. No markdown. No explanation.

INTENTS:
  volume_drop    - questions about volume drops, missing data, row count issues
  kpi_failure    - questions about KPI failures, Gold layer issues, specific dates
  alert_count    - questions about counting alerts, how many failures, statistics
  table_health   - questions about whether a specific table or dataset is healthy
  critical_checks- questions about CRITICAL checks, worst failures, most severe issues
  agent_summary  - questions about a specific agent's performance
  unknown        - cannot classify

PARAMETER EXTRACTION RULES:
  date_from / date_to: convert relative dates to ISO format (YYYY-MM-DD)
    "today"      → {today}
    "last week"  → date_from={week_ago}, date_to={today}
    "this month" → date_from={month_ago}, date_to={today}
    "June 21st"  → 2026-06-21  (assume 2026 for pilot dates)
    "June 21"    → 2026-06-21
  table_name: extract if mentioned (transactions, inventory, store, kpi)
  agent: extract agent number if mentioned (1, 2, 3, 4)
  status: extract if mentioned (CRITICAL, WARNING, PASS)

RESPONSE FORMAT:
{{
  "intent": "<intent_name>",
  "params": {{
    "date_from": "<YYYY-MM-DD or null>",
    "date_to": "<YYYY-MM-DD or null>",
    "date": "<YYYY-MM-DD or null>",
    "table_name": "<name or null>",
    "agent": "<1|2|3|4 or null>",
    "status": "<CRITICAL|WARNING|PASS or null>"
  }}
}}

USER QUERY: {query}"""

    workspace_host  = os.environ.get("DATABRICKS_HOST", "").replace("https://", "")
    workspace_token = os.environ.get("DATABRICKS_TOKEN", "")

    response = requests.post(
        f"https://{workspace_host}/serving-endpoints/databricks-gpt-oss-20b/invocations",
        headers={
            "Authorization": f"Bearer {workspace_token}",
            "Content-Type" : "application/json"
        },
        json={
            "messages": [
                {
                    "role"   : "system",
                    "content": (
                        "You are a JSON-only query classifier. "
                        "Never output anything except valid JSON."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "max_tokens" : 256,
            "temperature": 0.0
        },
        timeout=20
    )

    if response.status_code != 200:
        raise Exception(f"Model call failed: HTTP {response.status_code}")

    raw = _extract_model_text(response.json())

    # Strip markdown if model wrapped it
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1] if "```json" not in raw \
              else raw.split("```json")[1].split("```")[0]

    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1:
        raise Exception("No JSON in model response")

    return json.loads(raw[start:end])


def _extract_model_text(response_data: dict) -> str:
    """Reuses the same extraction logic as other notebooks."""
    choices = response_data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


# ── Answer renderers ───────────────────────────────────────────────────────

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

# Maps the internal 'Agent N' SQL alias (used to join/group query results)
# to the user-facing agent name for display.
AGENT_DISPLAY_NAME = {
    "Agent 1": "Validation Agent",
    "Agent 2": "Reconciliation Agent",
    "Agent 3": "Transformation Agent",
    "Agent 4": "KPI Assurance Agent",
}


def _answer_volume_drop(params: dict, query: str) -> html.Div:
    """Shows A1 VOLUME_ANOMALY checks that failed in the date range."""
    date_from = params.get("date_from") or \
                (date.today() - timedelta(days=7)).isoformat()
    date_to   = params.get("date_to")   or date.today().isoformat()

    df = execute_query(f"""
        SELECT
            r.business_date,
            SUBSTRING_INDEX(r.fully_qualified_name, '.', -1) AS table_name,
            r.check_status,
            ROUND(r.observed_value, 0)      AS observed_rows,
            ROUND(r.baseline_value, 0)      AS baseline_rows,
            ROUND(r.deviation_percentage, 1) AS deviation_pct,
            r.ai_summary
        FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
        WHERE r.check_type   = 'VOLUME_ANOMALY'
          AND r.check_status IN ('WARNING', 'CRITICAL')
          AND r.business_date BETWEEN :date_from AND :date_to
        ORDER BY r.business_date DESC, r.deviation_percentage ASC
    """, {"date_from": date_from, "date_to": date_to})

    header = _answer_header(
        f"Volume drops between {date_from} and {date_to}",
        len(df) if not df.empty else 0,
        query
    )

    if df.empty:
        return html.Div([
            header,
            _nlq_info(
                f"No volume anomalies found between {date_from} and {date_to}. "
                "All tables were within normal volume range."
            )
        ])

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "business_date" : str(row["business_date"]),
            "table_name"    : str(row["table_name"]),
            "check_status"  : str(row["check_status"]),
            "observed_rows" : str(int(row["observed_rows"] or 0)),
            "baseline_rows" : str(int(row["baseline_rows"] or 0)),
            "deviation_pct" : f"{row['deviation_pct']}%",
            "ai_summary"    : str(row["ai_summary"] or "—"),
        })

    return html.Div([
        header,
        dag.AgGrid(
            **ag_grid_props(
                grid_id="db-nlq-volume-grid",
                row_data=rows,
                col_defs=[
                    {"field": "business_date", "headerName": "Date",    "minWidth": 120},
                    {"field": "table_name",    "headerName": "Table",      "flex": 1, "minWidth": 220},
                    {"field": "check_status",  "headerName": "Status",  "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "observed_rows", "headerName": "Observed",   "width": 100},
                    {"field": "baseline_rows", "headerName": "Baseline",   "width": 100},
                    {"field": "deviation_pct", "headerName": "Deviation",  "width": 110},
                    {"field": "ai_summary",    "headerName": "AI Summary", "flex": 2, "minWidth": 280},
                ],
                page_size=10,
                status_col="check_status",
            )
        )
    ])


def _answer_kpi_failure(params: dict, query: str) -> html.Div:
    """Shows A4 failed KPI checks for a date, plus AI summary."""
    bdate = params.get("date") or date.today().isoformat()

    df = execute_query(f"""
        SELECT
            r.kpi_name,
            r.kpi_column,
            r.check_type,
            r.check_status,
            ROUND(r.observed_value, 4)      AS observed_value,
            ROUND(r.expected_value, 4)      AS expected_value,
            ROUND(r.deviation_percentage, 2) AS deviation_pct,
            r.ai_summary,
            r.ai_recommended_action,
            r.ai_failure_category
        FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b r
        WHERE r.business_date = :bdate
          AND r.check_status IN ('WARNING', 'CRITICAL')
        ORDER BY
            CASE r.check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
            r.kpi_name
    """, {"bdate": bdate})

    header = _answer_header(
        f"KPI failures on {bdate}",
        len(df) if not df.empty else 0,
        query
    )

    if df.empty:
        return html.Div([
            header,
            _nlq_info(
                f"No KPI failures found on {bdate}. "
                "All KPI checks passed on that date."
            ),
            _ai_insights_link(bdate),
        ])

    # Surface the AI summary from the first enriched row
    ai_narrative = None
    ai_action    = None
    ai_category  = None
    for _, row in df.iterrows():
        if row.get("ai_summary"):
            ai_narrative = str(row["ai_summary"])
            ai_action    = str(row.get("ai_recommended_action", "") or "")
            ai_category  = str(row.get("ai_failure_category", "") or "")
            break

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "kpi_name"      : str(row["kpi_name"]),
            "check_type"    : str(row["check_type"]),
            "check_status"  : str(row["check_status"]),
            "observed_value": str(row["observed_value"]),
            "expected_value": str(row["expected_value"]),
            "deviation_pct" : f"{row['deviation_pct']}%",
        })

    elements = [header]

    # AI explanation card
    if ai_narrative:
        elements.append(
            dbc.Card([
                dbc.CardHeader(
                    html.Strong(
                        f"🤖 AI Explanation"
                        + (f" — {ai_category}" if ai_category else ""),
                        style={"color": "#ffffff"}
                    ),
                    style={"backgroundColor": "#343a40"}
                ),
                dbc.CardBody([
                    html.P(ai_narrative,
                           style={"color": "#cccccc", "fontSize": "14px",
                                  "marginBottom": "8px"}),
                    html.P(ai_action,
                           style={"color": "#aaaaaa", "fontSize": "13px",
                                  "fontStyle": "italic", "marginBottom": "0"})
                    if ai_action else html.Div()
                ])
            ], className="mb-3",
            style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})
        )

    elements.append(
        dag.AgGrid(
            **ag_grid_props(
                grid_id="db-nlq-kpi-failure-grid",
                row_data=rows,
                col_defs=[
                    {"field": "kpi_name",       "headerName": "KPI",       "flex": 1, "minWidth": 220},
                    {"field": "check_type",     "headerName": "Check",  "minWidth": 200},
                    {"field": "check_status",   "headerName": "Status", "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "observed_value", "headerName": "Observed",  "width": 110},
                    {"field": "expected_value", "headerName": "Expected",  "width": 110},
                    {"field": "deviation_pct",  "headerName": "Deviation", "width": 110},
                ],
                page_size=10,
                status_col="check_status",
            )
        )
    )

    elements.append(_ai_insights_link(bdate))
    return html.Div(elements)


def _answer_alert_count(params: dict, query: str) -> html.Div:
    """Shows count of alerts by agent and status for a date range."""
    date_from = params.get("date_from") or \
                (date.today() - timedelta(days=30)).isoformat()
    date_to   = params.get("date_to")   or date.today().isoformat()
    status    = params.get("status")

    query_params = {"date_from": date_from, "date_to": date_to}
    if status:
        status_filter = "AND overall_status = :status"
        query_params["status"] = status
    else:
        status_filter = "AND overall_status IN ('CRITICAL', 'WARNING')"

    df = execute_query(f"""
        SELECT agent, overall_status, COUNT(*) AS run_count
        FROM (
            SELECT 'Agent 1' AS agent, overall_status, business_date
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            {status_filter}
            UNION ALL
            SELECT 'Agent 2', overall_status, business_date
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            {status_filter}
            UNION ALL
            SELECT 'Agent 4', overall_status, business_date
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            {status_filter}
        )
        GROUP BY agent, overall_status
        ORDER BY agent, overall_status
    """, query_params)

    header = _answer_header(
        f"Alert summary: {date_from} to {date_to}",
        int(df["run_count"].sum()) if not df.empty else 0,
        query
    )

    if df.empty:
        return html.Div([
            header,
            _nlq_info(
                f"No alerts found between {date_from} and {date_to}."
            )
        ])

    # Build summary cards
    total_critical = int(
        df[df["overall_status"] == "CRITICAL"]["run_count"].sum()
    ) if not df.empty else 0
    total_warning  = int(
        df[df["overall_status"] == "WARNING"]["run_count"].sum()
    ) if not df.empty else 0
    total          = total_critical + total_warning

    summary_cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H3(str(total),
                        style={"color": "#ffffff", "textAlign": "center",
                               "marginBottom": "4px"}),
                html.P("Total Alerts",
                       style={"color": "#aaaaaa", "fontSize": "13px",
                              "textAlign": "center", "marginBottom": "0"})
            ])
        ], style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),
        md=4),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H3(str(total_critical),
                        style={"color": "#ff6b6b", "textAlign": "center",
                               "marginBottom": "4px"}),
                html.P("Critical",
                       style={"color": "#aaaaaa", "fontSize": "13px",
                              "textAlign": "center", "marginBottom": "0"})
            ])
        ], style={"backgroundColor": "#3d0000", "border": "1px solid #ff6b6b"}),
        md=4),
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H3(str(total_warning),
                        style={"color": "#ffa500", "textAlign": "center",
                               "marginBottom": "4px"}),
                html.P("Warning",
                       style={"color": "#aaaaaa", "fontSize": "13px",
                              "textAlign": "center", "marginBottom": "0"})
            ])
        ], style={"backgroundColor": "#3d2000", "border": "1px solid #ffa500"}),
        md=4),
    ], className="mb-3")

    # Breakdown table
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "agent"       : AGENT_DISPLAY_NAME.get(str(row["agent"]), str(row["agent"])),
            "check_status": str(row["overall_status"]),
            "run_count"   : str(int(row["run_count"])),
        })

    return html.Div([
        header,
        summary_cards,
        dag.AgGrid(
            **ag_grid_props(
                grid_id="db-nlq-status-breakdown-grid",
                row_data=rows,
                col_defs=[
                    {"field": "agent",        "headerName": "Agent",  "flex": 1, "minWidth": 220},
                    {"field": "check_status", "headerName": "Status", "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "run_count",    "headerName": "Count",  "width": 100},
                ],
                page_size=20,
                status_col="check_status",
            )
        )
    ])


def _answer_table_health(params: dict, query: str) -> html.Div:
    """
    Shows A1 + A2 + A4 status for a table on a given date.
    Table name matching is fuzzy — checks if the param
    appears anywhere in the fully qualified name.
    """
    bdate      = params.get("date") or date.today().isoformat()
    table_name = params.get("table_name") or ""

    # ── A1 run for this date ───────────────────────────────────────────────
    params_a1 = {"bdate": bdate}
    table_filter_a1 = ""
    if table_name:
        table_filter_a1 = "AND fully_qualified_name LIKE :table_pattern"
        params_a1["table_pattern"] = f"%{table_name}%"

    df_a1 = execute_query(f"""
        SELECT
            SUBSTRING_INDEX(fully_qualified_name, '.', -1) AS table_name,
            overall_status,
            total_checks_run,
            total_checks_passed,
            total_checks_warned,
            total_checks_critical,
            ai_enrichment_status
        FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
        WHERE business_date = :bdate
        {table_filter_a1}
        ORDER BY fully_qualified_name
    """, params_a1)

    # ── A2 run for this date ───────────────────────────────────────────────
    params_a2 = {"bdate": bdate}
    table_filter_a2 = ""
    if table_name:
        table_filter_a2 = "AND source_fully_qualified_name LIKE :table_pattern"
        params_a2["table_pattern"] = f"%{table_name}%"

    df_a2 = execute_query(f"""
        SELECT
            SUBSTRING_INDEX(
                source_fully_qualified_name, '.', -1
            )                           AS table_name,
            overall_status,
            total_checks_run,
            total_checks_passed,
            total_checks_warned,
            total_checks_critical
        FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
        WHERE business_date = :bdate
        {table_filter_a2}
        ORDER BY source_fully_qualified_name
    """, params_a2)

    # ── A4 run for this date ───────────────────────────────────────────────
    params_a4 = {"bdate": bdate}
    table_filter_a4 = ""
    if table_name:
        table_filter_a4 = "AND gold_fully_qualified_name LIKE :table_pattern"
        params_a4["table_pattern"] = f"%{table_name}%"

    df_a4 = execute_query(f"""
        SELECT
            SUBSTRING_INDEX(
                gold_fully_qualified_name, '.', -1
            )                           AS table_name,
            overall_status,
            total_kpis_checked          AS total_checks_run,
            total_kpis_passed           AS total_checks_passed,
            total_kpis_warned           AS total_checks_warned,
            total_kpis_critical         AS total_checks_critical
        FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
        WHERE business_date = :bdate
        {table_filter_a4}
        ORDER BY gold_fully_qualified_name
    """, params_a4)

    title_suffix = f" for '{table_name}'" if table_name else ""
    header = _answer_header(
        f"Data health on {bdate}{title_suffix}",
        None,
        query
    )

    no_data = df_a1.empty and df_a2.empty and df_a4.empty
    if no_data:
        return html.Div([
            header,
            _nlq_info(
                f"No validation runs found for {bdate}"
                + (f" matching '{table_name}'" if table_name else "")
                + ". Check that agents have been run for this date."
            )
        ])

    def _agent_section(label: str, df, emoji: str) -> html.Div:
        if df.empty:
            return html.Div([
                html.H6(f"{emoji} {label}",
                        style={"color": "#aaaaaa", "fontSize": "14px",
                               "marginBottom": "8px", "marginTop": "16px"}),
                html.P("No runs found.",
                       style={"color": "#555", "fontSize": "13px"})
            ])

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "table_name"           : str(row.get("table_name", "")),
                "check_status"         : str(row.get("overall_status", "")),
                "total_checks_run"     : str(int(row.get("total_checks_run") or 0)),
                "total_checks_passed"  : str(int(row.get("total_checks_passed") or 0)),
                "total_checks_warned"  : str(int(row.get("total_checks_warned") or 0)),
                "total_checks_critical": str(int(row.get("total_checks_critical") or 0)),
            })

        return html.Div([
            html.H6(f"{emoji} {label}",
                    style={"color": "#ffffff", "fontSize": "14px",
                           "marginBottom": "8px", "marginTop": "16px"}),
            dag.AgGrid(
                **ag_grid_props(
                    grid_id=f"db-nlq-health-{label.split()[1].lower()}-grid",
                    row_data=rows,
                    col_defs=[
                        {"field": "table_name",            "headerName": "Table",    "flex": 1, "minWidth": 220},
                        {"field": "check_status",          "headerName": "Status",   "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "total_checks_run",      "headerName": "Checks",   "width": 90},
                        {"field": "total_checks_passed",   "headerName": "Passed",   "width": 90},
                        {"field": "total_checks_warned",   "headerName": "Warned",   "width": 90},
                        {"field": "total_checks_critical", "headerName": "Critical", "width": 90},
                    ],
                    page_size=10,
                    status_col="check_status",
                )
            )
        ])

    return html.Div([
        header,
        _agent_section("Validation Agent — Raw Ingestion", df_a1, "🔍"),
        _agent_section("Reconciliation Agent — Reconciliation", df_a2, "🔄"),
        _agent_section("KPI Assurance Agent — KPI Validation", df_a4, "📊"),
        _ai_insights_link(bdate),
    ])


def _answer_critical_checks(params: dict, query: str) -> html.Div:
    """Shows all CRITICAL checks across all agents in the date range."""
    date_from = params.get("date_from") or \
                (date.today() - timedelta(days=7)).isoformat()
    date_to   = params.get("date_to")   or date.today().isoformat()

    df = execute_query(f"""
        SELECT
            'Agent 1'                                           AS agent,
            CAST(business_date AS STRING)                       AS business_date,
            SUBSTRING_INDEX(fully_qualified_name, '.', -1)      AS table_name,
            check_type,
            column_name                                         AS detail,
            ROUND(observed_value, 4)                            AS observed_value,
            ROUND(deviation_percentage, 2)                      AS deviation_pct,
            COALESCE(ai_failure_category, '')                   AS ai_category
        FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
        WHERE check_status  = 'CRITICAL'
          AND business_date BETWEEN :date_from AND :date_to

        UNION ALL

        SELECT
            'Agent 2',
            CAST(business_date AS STRING),
            SUBSTRING_INDEX(
                source_fully_qualified_name, '.', -1
            ),
            check_type,
            metric_name,
            ROUND(source_value, 4),
            ROUND(deviation_percentage, 2),
            COALESCE(ai_failure_category, '')
        FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
        WHERE check_status  = 'CRITICAL'
          AND business_date BETWEEN :date_from AND :date_to

        UNION ALL

        SELECT
            'Agent 4',
            CAST(business_date AS STRING),
            SUBSTRING_INDEX(
                gold_fully_qualified_name, '.', -1
            ),
            check_type,
            kpi_name,
            ROUND(observed_value, 4),
            ROUND(deviation_percentage, 2),
            COALESCE(ai_failure_category, '')
        FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
        WHERE check_status  = 'CRITICAL'
          AND business_date BETWEEN :date_from AND :date_to

        ORDER BY business_date DESC, agent
    """, {"date_from": date_from, "date_to": date_to})

    header = _answer_header(
        f"CRITICAL checks: {date_from} to {date_to}",
        len(df) if not df.empty else 0,
        query
    )

    if df.empty:
        return html.Div([
            header,
            _nlq_info(
                f"No CRITICAL checks found between {date_from} and {date_to}. "
                "The platform was healthy during this period."
            )
        ])

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "agent"         : AGENT_DISPLAY_NAME.get(str(row["agent"]), str(row["agent"])),
            "business_date" : str(row["business_date"]),
            "table_name"    : str(row["table_name"]),
            "check_type"    : str(row["check_type"]),
            "detail"        : str(row["detail"] or "—"),
            "observed_value": str(row["observed_value"]),
            "deviation_pct" : f"{row['deviation_pct']}%",
            "ai_category"   : str(row["ai_category"] or "—"),
            "check_status"  : "CRITICAL",   # all rows are CRITICAL
        })

    return html.Div([
        header,
        dag.AgGrid(
            **ag_grid_props(
                grid_id="db-nlq-critical-checks-grid",
                row_data=rows,
                col_defs=[
                    {"field": "agent",          "headerName": "Agent",  "minWidth": 150},
                    {"field": "business_date",  "headerName": "Date",   "minWidth": 120},
                    {"field": "table_name",     "headerName": "Table",     "flex": 1, "minWidth": 220},
                    {"field": "check_type",     "headerName": "Check",  "minWidth": 200},
                    {"field": "detail",         "headerName": "Detail",    "flex": 1, "minWidth": 280},
                    {"field": "observed_value", "headerName": "Observed",  "width": 110},
                    {"field": "deviation_pct",  "headerName": "Deviation", "width": 110},
                    {"field": "ai_category",    "headerName": "Category",  "flex": 1, "minWidth": 150},
                ],
                page_size=15,
                status_col="check_status",
            )
        )
    ])


def _answer_agent_summary(params: dict, query: str) -> html.Div:
    """Shows recent run summary for a specific agent."""
    agent     = params.get("agent") or "1"
    date_from = params.get("date_from") or \
                (date.today() - timedelta(days=7)).isoformat()
    date_to   = params.get("date_to")   or date.today().isoformat()

    agent_queries = {
        "1": (
            f"""
            SELECT
                business_date,
                SUBSTRING_INDEX(
                    fully_qualified_name, '.', -1
                )                       AS table_name,
                overall_status          AS check_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ai_enrichment_status
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            ORDER BY business_date DESC, fully_qualified_name
            """,
            "Validation Agent — Raw Ingestion"
        ),
        "2": (
            f"""
            SELECT
                business_date,
                SUBSTRING_INDEX(
                    source_fully_qualified_name, '.', -1
                )                       AS table_name,
                overall_status          AS check_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ai_enrichment_status
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            ORDER BY business_date DESC, source_fully_qualified_name
            """,
            "Reconciliation Agent — Reconciliation"
        ),
        "4": (
            f"""
            SELECT
                business_date,
                SUBSTRING_INDEX(
                    gold_fully_qualified_name, '.', -1
                )                       AS table_name,
                overall_status          AS check_status,
                total_kpis_checked      AS total_checks_run,
                total_kpis_passed       AS total_checks_passed,
                total_kpis_warned       AS total_checks_warned,
                total_kpis_critical     AS total_checks_critical,
                ai_enrichment_status
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date BETWEEN :date_from AND :date_to
            ORDER BY business_date DESC, gold_fully_qualified_name
            """,
            "KPI Assurance Agent — KPI Validation"
        ),
    }

    if str(agent) not in agent_queries:
        return _nlq_info(
            f"Agent {agent} summary is not available. "
            "Try Validation Agent, Reconciliation Agent, or KPI Assurance Agent."
        )

    sql, agent_label = agent_queries[str(agent)]
    df = execute_query(sql, {"date_from": date_from, "date_to": date_to})

    header = _answer_header(
        f"{agent_label}: {date_from} to {date_to}",
        len(df) if not df.empty else 0,
        query
    )

    if df.empty:
        return html.Div([
            header,
            _nlq_info(f"No runs found for {agent_label} in this date range.")
        ])

    rows = []
    for _, row in df.iterrows():
        rows.append({
            "business_date"        : str(row["business_date"]),
            "table_name"           : str(row["table_name"]),
            "check_status"         : str(row["check_status"]),
            "total_checks_run"     : str(int(row.get("total_checks_run") or 0)),
            "total_checks_passed"  : str(int(row.get("total_checks_passed") or 0)),
            "total_checks_warned"  : str(int(row.get("total_checks_warned") or 0)),
            "total_checks_critical": str(int(row.get("total_checks_critical") or 0)),
            "ai_enrichment_status" : str(row.get("ai_enrichment_status", "")),
        })

    return html.Div([
        header,
        dag.AgGrid(
            **ag_grid_props(
                grid_id="db-nlq-agent-summary-grid",
                row_data=rows,
                col_defs=[
                    {"field": "business_date",        "headerName": "Date",  "minWidth": 120},
                    {"field": "table_name",           "headerName": "Table",    "flex": 1, "minWidth": 220},
                    {"field": "check_status",         "headerName": "Status",   "minWidth": 150,
                     "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                    {"field": "total_checks_run",     "headerName": "Checks",   "width": 90},
                    {"field": "total_checks_passed",  "headerName": "Passed",   "width": 90},
                    {"field": "total_checks_warned",  "headerName": "Warned",   "width": 90},
                    {"field": "total_checks_critical","headerName": "Critical", "width": 90},
                    {"field": "ai_enrichment_status", "headerName": "AI",    "minWidth": 150},
                ],
                page_size=15,
                status_col="check_status",
            )
        )
    ])


def _answer_unknown(query: str) -> html.Div:
    """Friendly fallback when intent cannot be classified."""
    return dbc.Alert([
        html.Strong("I'm not sure how to answer that. "),
        html.Br(),
        html.Span(
            "Try questions like:",
            style={"color": "#cccccc"}
        ),
        html.Ul([
            html.Li("Which tables had volume drops last week?"),
            html.Li("What caused the KPI failure on June 21st?"),
            html.Li("How many CRITICAL alerts did we have this month?"),
            html.Li("Is transaction data healthy today?"),
            html.Li("Show me Reconciliation Agent summary for last week"),
        ], style={"color": "#cccccc", "marginTop": "8px",
                  "fontSize": "14px"}),
    ], color="secondary", className="mt-3")


# ── Shared UI helpers ──────────────────────────────────────────────────────

def _answer_header(title: str, result_count, query: str) -> html.Div:
    """Renders the answer panel header with query echo and result count."""
    count_badge = (
        dbc.Badge(
            f"{result_count} result{'s' if result_count != 1 else ''}",
            color="secondary",
            className="ms-2"
        )
        if result_count is not None else html.Span()
    )

    return html.Div([
        html.Hr(style={"borderColor": "#444", "marginTop": "16px"}),
        html.Div([
            html.Span(
                f'"{query}"',
                style={"color": "#aaaaaa", "fontSize": "13px",
                       "fontStyle": "italic"}
            ),
        ], className="mb-2"),
        html.Div([
            html.H6(
                title,
                style={"color": "#ffffff", "fontSize": "15px",
                       "fontWeight": "600", "display": "inline",
                       "marginBottom": "0"}
            ),
            count_badge,
        ], className="mb-3"),
    ])


def _ai_insights_link(bdate: str) -> html.Div:
    """Renders a link to the AI Insights page for a specific date."""
    return html.Div([
        dbc.Button(
            f"🤖 Open AI Insights for {bdate} →",
            href  = f"/ai-insights?date={bdate}",
            color = "link",
            style = {"color": "#4a9edd", "fontSize": "13px",
                     "padding": "0", "marginTop": "12px"}
        )
    ])


def _nlq_info(message: str) -> dbc.Alert:
    return dbc.Alert(message, color="info", className="mt-3",
                     style={"fontSize": "14px"})


def _nlq_error(message: str) -> dbc.Alert:
    return dbc.Alert(message, color="warning", className="mt-3",
                     style={"fontSize": "14px"})
    

@callback(
    Output("dashboard-refresh-interval", "disabled"),
    Output("db-refresh-toggle",          "children"),
    Output("db-refresh-toggle",          "color"),
    Output("db-refresh-indicator",       "children"),
    Output("db-refresh-paused",          "data"),
    Input("db-refresh-toggle",           "n_clicks"),
    State("db-refresh-paused",           "data"),
    prevent_initial_call=True,
)
def toggle_db_refresh(n_clicks, is_paused):
    new_paused = not is_paused
    if new_paused:
        return (
            True,
            "▶ Resume Auto-Refresh",
            "success",
            "Auto-refresh paused",
            True,
        )
    return (
        False,
        "⏸ Pause Auto-Refresh",
        "secondary",
        "Auto-refreshing every 5 minutes",
        False,
    )