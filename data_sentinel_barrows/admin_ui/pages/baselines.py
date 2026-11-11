# pages/baselines.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import logging
from db.connection import execute_query
from db.queries import get_all_registered_tables, get_baselines_for_table
from components.alerts import (
    error_alert,
    info_alert,
    fmt_number,
    ag_grid_props,
)

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/baselines", name="Baselines")

layout = dbc.Container([

    html.H2("Baseline Metrics", className="mt-4 mb-2"),
    html.P(
        "View computed baseline statistics for registered tables. "
        "Baselines are computed by the baseline computation job and used "
        "by the validation agent to detect anomalies.",
        className="text-muted mb-4"
    ),

    html.Div(id="baselines-alert"),

    dbc.Card([
        dbc.CardHeader(html.H5("Select Table", className="mb-0")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dcc.Dropdown(
                        id="baseline-table-dropdown",
                        placeholder="Select a registered table...",
                        clearable=False
                    )
                ], md=8),
                dbc.Col([
                    dbc.Button(
                        "Load Baselines",
                        id="load-baselines-btn",
                        color="primary",
                        className="w-100"
                    )
                ], md=4)
            ])
        ])
    ], className="mb-4"),

    dbc.Card([
        dbc.CardHeader(html.H5("Baseline Metrics", className="mb-0")),
        dbc.CardBody([
            dcc.Loading(
                id    = "baselines-loading",
                type  = "circle",
                color = "#00c851",
                children = html.Div(id="baselines-table-container")
            )
        ])
    ])

], fluid=True)


@callback(
    Output("baseline-table-dropdown", "options"),
    Input("baseline-table-dropdown", "id")
)
def load_baseline_table_options(_):
    try:
        df = execute_query(get_all_registered_tables())
        active = df[df["is_active"] == True]
        return [
            {"label": r["fully_qualified_name"], "value": r["fully_qualified_name"]}
            for _, r in active.iterrows()
        ]
    except Exception as e:
        logger.error(f"Failed to load table options: {str(e)}")
        return []


@callback(
    Output("baselines-alert", "children"),
    Output("baselines-table-container", "children"),
    Input("load-baselines-btn", "n_clicks"),
    State("baseline-table-dropdown", "value"),
    prevent_initial_call=True
)
def load_baselines(n_clicks, fqn):
    if not fqn:
        return error_alert("Please select a table."), []

    try:
        df = execute_query(*get_baselines_for_table(fqn))

        if df.empty:
            return "", info_alert(
                "No baseline metrics found for this table. "
                "Run the baseline computation job to generate baselines."
            )

        # ── Drop any completely empty rows ─────────────────────────────────
        df = df.dropna(how="all")

        # ── Build rows with status code ────────────────────────────────────
        rows = []
        for _, r in df.iterrows():
            status = str(r.get("baseline_status", "") or "")
            rows.append({
                "column_name"       : str(r.get("column_name", "") or "—"),
                "check_type"        : str(r.get("check_type", "") or "—"),
                "metric_name"       : str(r.get("metric_name", "") or "—"),
                "baseline_date"     : str(r.get("baseline_date", "") or "—"),
                "baseline_window_days": str(r.get("baseline_window_days", "") or "—"),
                "mean_value"        : fmt_number(r.get("mean_value")),
                "stddev_value"      : fmt_number(r.get("stddev_value")),
                "min_value"         : fmt_number(r.get("min_value")),
                "max_value"         : fmt_number(r.get("max_value")),
                "p25_value"         : fmt_number(r.get("p25_value")),
                "p50_value"         : fmt_number(r.get("p50_value")),
                "p75_value"         : fmt_number(r.get("p75_value")),
                "p95_value"         : fmt_number(r.get("p95_value")),
                "sample_count"      : str(r.get("sample_count", "") or "—"),
                "is_sufficient_data": str(r.get("is_sufficient_data", "") or "—"),
                "baseline_status"   : status,
                "computed_by"       : str(r.get("computed_by", "") or "—"),
            })

        table = dag.AgGrid(
            **ag_grid_props(
                grid_id="baselines-grid",
                row_data=rows,
                col_defs=[
                    {"field": "column_name",        "headerName": "Column",        "flex": 2, "minWidth": 220},
                    {"field": "check_type",         "headerName": "Check Type", "minWidth": 200},
                    {"field": "metric_name",        "headerName": "Metric",        "flex": 2, "minWidth": 220},
                    {"field": "baseline_date",      "headerName": "Baseline Date", "minWidth": 120},
                    {"field": "baseline_window_days","headerName": "Window",        "width": 90},
                    {"field": "mean_value",         "headerName": "Mean",          "width": 110},
                    {"field": "stddev_value",       "headerName": "Std Dev",       "width": 110},
                    {"field": "min_value",          "headerName": "Min",           "width": 110},
                    {"field": "max_value",          "headerName": "Max",           "width": 110},
                    {"field": "p25_value",          "headerName": "P25",           "width": 110},
                    {"field": "p50_value",          "headerName": "P50",           "width": 110},
                    {"field": "p75_value",          "headerName": "P75",           "width": 110},
                    {"field": "p95_value",          "headerName": "P95",           "width": 110},
                    {"field": "sample_count",       "headerName": "Samples",       "width": 90},
                    {"field": "is_sufficient_data", "headerName": "Sufficient",    "width": 100},
                    {"field": "baseline_status",    "headerName": "Status",     "minWidth": 150,
                     "cellStyle": {"function": """
                         function(params) {
                             var v = (params.value || '').toUpperCase();
                             if (v === 'VALID')             return {color: '#00c851', fontWeight: '600'};
                             if (v === 'INSUFFICIENT_DATA') return {color: '#ffa500', fontWeight: '600'};
                             if (v === 'STALE')             return {color: '#ffa500', fontWeight: '600'};
                             return null;
                         }
                     """}},
                    {"field": "computed_by",        "headerName": "Computed By",   "flex": 1, "minWidth": 220},
                ],
                page_size=15,
            )
        )

        return "", table

    except Exception as e:
        logger.error(f"Failed to load baselines: {str(e)}")
        return error_alert(f"Failed to load baselines: {str(e)}"), []