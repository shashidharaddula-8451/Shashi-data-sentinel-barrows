# pages/kpi_baselines.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import logging
from db.connection import execute_query
from db.queries import get_all_kpis
from components.alerts import (
    error_alert,
    info_alert,
    fmt_optional,
    ag_grid_props,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/kpi-baselines",
    name="KPI Baselines"
)

# ── Table References ───────────────────────────────────────────────────────

from config.settings import TARGET_CATALOG, TARGET_SCHEMA

KPI_BASELINE_METRICS = (
    f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_baseline_metrics_b"
)
KPI_REGISTRY = (
    f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_registry_b"
)

GOLD_TABLES = [
    {
        "label": "uc2_gold_daily_store_metrics",
        "value": (
            f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
            f".uc2_gold_daily_store_metrics"
        )
    },
    {
        "label": "uc2_gold_daily_inventory_summary",
        "value": (
            f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
            f".uc2_gold_daily_inventory_summary"
        )
    },
]

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2("KPI Assurance Agent — KPI Baselines", className="mt-4 mb-2"),
    html.P(
        "View computed baseline statistics for Gold KPIs. "
        "Baselines are used by the ANOMALY check to detect "
        "when a KPI deviates significantly from its historical norm. "
        "Only KPIs with ANOMALY checks enabled have baselines.",
        className="text-muted mb-4"
    ),

    html.Div(id="kpi-baselines-alert"),

    # ── Summary Cards ──────────────────────────────────────────────────────
    dcc.Loading(
        id    = "kpibl-summary-loading",
        type  = "circle",
        color = "#00c851",
        children = dbc.Row(id="kpi-baselines-summary-cards", className="mb-4"),
    ),

    # ── Filters ────────────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Filter Baselines", className="mb-0")
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Gold Table", className="text-white"),
                    dcc.Dropdown(
                        id="kpi-baseline-table-dropdown",
                        options=GOLD_TABLES,
                        placeholder="Select Gold table...",
                        clearable=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=5),
                dbc.Col([
                    dbc.Label("KPI Name", className="text-white"),
                    dcc.Dropdown(
                        id="kpi-baseline-kpi-dropdown",
                        placeholder="Select KPI...",
                        clearable=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=5),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "Load Baselines",
                        id="kpi-baselines-load-btn",
                        color="primary",
                        className="d-block w-100"
                    )
                ], md=2)
            ])
        ])
    ], className="mb-4"),

    # ── Baselines Grid ─────────────────────────────────────────────────────
    dcc.Loading(
        id    = "kpibl-grid-loading",
        type  = "circle",
        color = "#00c851",
        children =
            dbc.Card([
                dbc.CardHeader(
                    html.H5("Baseline Metrics", className="mb-0")
                ),
                dbc.CardBody([
                    html.Div(
                        "Select a Gold table and click Load Baselines.",
                        id="kpi-baselines-grid-container",
                        className="text-muted"
                    )
                ])
            ], className="mb-4"),
    ),

    # ── Detail Panel ───────────────────────────────────────────────────────
    dcc.Loading(
        id    = "kpibl-detail-loading",
        type  = "circle",
        color = "#00c851",
        children =
            dbc.Card([
                dbc.CardHeader(
                    html.H5(
                        "📊 Baseline Detail",
                        className="mb-0"
                    )
                ),
                dbc.CardBody([
                    html.Div(
                        "Select a baseline row above to see full statistics.",
                        id="kpi-baseline-detail-panel",
                        className="text-muted"
                    )
                ])
            ], className="mb-4"),
    ),

], fluid=True)


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_baselines_query(
    gold_fqn : str = None,
    kpi_name : str = None
) -> tuple:
    """
    Builds the baseline query with optional filters.

    Returns (query, params).
    """
    where_clauses = []
    params: dict  = {}

    if gold_fqn:
        where_clauses.append(
            "gold_fully_qualified_name = :gold_fqn"
        )
        params["gold_fqn"] = gold_fqn
    if kpi_name:
        where_clauses.append(
            "kpi_name = :kpi_name"
        )
        params["kpi_name"] = kpi_name

    where = (
        "WHERE " + " AND ".join(where_clauses)
        if where_clauses else ""
    )

    return f"""
        SELECT
            baseline_id,
            SUBSTRING_INDEX(
                gold_fully_qualified_name, '.', -1
            )                               AS gold_table,
            gold_fully_qualified_name,
            kpi_name,
            kpi_column,
            baseline_date,
            baseline_window_days,
            ROUND(mean_value, 6)            AS mean_value,
            ROUND(stddev_value, 6)          AS stddev_value,
            ROUND(min_value, 6)             AS min_value,
            ROUND(max_value, 6)             AS max_value,
            ROUND(p25_value, 6)             AS p25_value,
            ROUND(p50_value, 6)             AS p50_value,
            ROUND(p75_value, 6)             AS p75_value,
            ROUND(p95_value, 6)             AS p95_value,
            sample_count,
            is_sufficient_data,
            baseline_status,
            computed_timestamp,
            computed_by
        FROM {KPI_BASELINE_METRICS}
        {where}
        ORDER BY
            gold_fully_qualified_name,
            kpi_name
    """, params


def _get_kpi_options_query(gold_fqn: str) -> tuple:
    """
    Returns distinct KPI names that have baselines
    for the selected Gold table.

    Returns (query, params).
    """
    return f"""
        SELECT DISTINCT kpi_name
        FROM {KPI_BASELINE_METRICS}
        WHERE gold_fully_qualified_name = :gold_fqn
        ORDER BY kpi_name
    """, {"gold_fqn": gold_fqn}


def _get_summary_query() -> str:
    """
    Returns summary statistics about all baselines.
    """
    return f"""
        SELECT
            COUNT(*)                                    AS total_baselines,
            COUNT(DISTINCT gold_fully_qualified_name)   AS gold_tables,
            COUNT(DISTINCT kpi_name)                    AS kpis_with_baselines,
            SUM(CASE WHEN baseline_status = 'VALID'
                THEN 1 ELSE 0 END)                      AS valid_baselines,
            SUM(CASE WHEN baseline_status = 'INSUFFICIENT_DATA'
                THEN 1 ELSE 0 END)                      AS insufficient_baselines,
            MAX(baseline_date)                          AS latest_baseline_date
        FROM {KPI_BASELINE_METRICS}
    """


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("kpi-baselines-summary-cards", "children"),
    Input("kpi-baselines-summary-cards", "id")
)
def load_summary_cards(_):
    """
    Loads summary cards on page load.
    """
    try:
        df = execute_query(_get_summary_query())

        if df.empty:
            return dbc.Alert(
                "No baselines computed yet. "
                "Run KPI Assurance Agent → Baseline Computation notebook first.",
                color="info"
            )

        row = df.iloc[0]

        def safe_int(v):
            try:
                return int(v) if v is not None else 0
            except (TypeError, ValueError):
                return 0

        total        = safe_int(row.get("total_baselines"))
        tables       = safe_int(row.get("gold_tables"))
        kpis         = safe_int(row.get("kpis_with_baselines"))
        valid        = safe_int(row.get("valid_baselines"))
        insufficient = safe_int(row.get("insufficient_baselines"))
        latest_date  = str(row.get("latest_baseline_date", "N/A"))

        def card(title, value, color_style=None):
            return dbc.Col(
                dbc.Card([
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
                }),
                md=2
            )

        return dbc.Row([
            card("Total Baselines",  total),
            card("Gold Tables",      tables),
            card("KPIs Baselined",   kpis),
            card("Valid",            valid,
                 {"color": "#00c851"} if valid > 0 else None),
            card("Insufficient Data", insufficient,
                 {"color": "#ffa500"} if insufficient > 0 else None),
            card("Latest Date",      latest_date),
        ])

    except Exception as e:
        logger.error(f"Failed to load KPI baseline summary: {str(e)}")
        return dbc.Alert(
            f"Could not load summary: {str(e)}",
            color="danger"
        )


@callback(
    Output("kpi-baseline-kpi-dropdown", "options"),
    Output("kpi-baseline-kpi-dropdown", "value"),
    Input("kpi-baseline-table-dropdown", "value"),
    prevent_initial_call=True
)
def update_kpi_dropdown(gold_fqn):
    """
    When a Gold table is selected, populate the KPI dropdown
    with only KPIs that have baselines for that table.
    """
    if not gold_fqn:
        return [], None

    try:
        df = execute_query(*_get_kpi_options_query(gold_fqn))
        if df.empty:
            return [], None

        options = [
            {"label": row["kpi_name"], "value": row["kpi_name"]}
            for _, row in df.iterrows()
        ]
        return options, None

    except Exception as e:
        logger.error(f"Failed to load KPI options: {str(e)}")
        return [], None


@callback(
    Output("kpi-baselines-alert", "children"),
    Output("kpi-baselines-grid-container", "children"),
    Input("kpi-baselines-load-btn", "n_clicks"),
    State("kpi-baseline-table-dropdown", "value"),
    State("kpi-baseline-kpi-dropdown", "value"),
    prevent_initial_call=True
)
def load_baselines(n_clicks, gold_fqn, kpi_name):
    """
    Loads baseline records based on selected filters.
    """
    if not gold_fqn:
        return error_alert(
            "Please select a Gold table."
        ), html.Div()

    try:
        df = execute_query(
            *_get_baselines_query(gold_fqn, kpi_name)
        )

        if df.empty:
            return "", info_alert(
                "No baselines found for the selected filters. "
                "Run the KPI Baseline Computation notebook to "
                "generate baselines."
            )

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "baseline_id"         : str(row.get("baseline_id", "")),
                "gold_table"          : str(row.get("gold_table", "")),
                "gold_fully_qualified_name": str(
                    row.get("gold_fully_qualified_name", "")
                ),
                "kpi_name"            : str(row.get("kpi_name", "")),
                "kpi_column"          : str(row.get("kpi_column", "")),
                "baseline_date"       : str(row.get("baseline_date", "")),
                "baseline_window_days": str(row.get("baseline_window_days", "")),
                "mean_value"          : fmt_optional(row.get("mean_value"),   decimals=6),
                "stddev_value"        : fmt_optional(row.get("stddev_value"), decimals=6),
                "min_value"           : fmt_optional(row.get("min_value"),    decimals=6),
                "max_value"           : fmt_optional(row.get("max_value"),    decimals=6),
                "p25_value"           : fmt_optional(row.get("p25_value"),    decimals=6),
                "p50_value"           : fmt_optional(row.get("p50_value"),    decimals=6),
                "p75_value"           : fmt_optional(row.get("p75_value"),    decimals=6),
                "p95_value"           : fmt_optional(row.get("p95_value"),    decimals=6),
                "sample_count"        : str(row.get("sample_count", "")),
                "is_sufficient_data"  : str(row.get("is_sufficient_data", "")),
                "baseline_status"     : str(row.get("baseline_status", "")),
                "computed_timestamp"  : str(row.get("computed_timestamp", "")),
                "computed_by"         : str(row.get("computed_by", ""))
            })

        grid = dag.AgGrid(
            **ag_grid_props(
                grid_id="kpi-baselines-grid",
                row_data=rows,
                col_defs=[
                    {"field": "kpi_name",            "headerName": "KPI Name",      "flex": 2, "minWidth": 220},
                    {"field": "kpi_column",          "headerName": "Column",     "minWidth": 160},
                    {"field": "baseline_date",       "headerName": "Baseline Date", "minWidth": 120},
                    {"field": "baseline_window_days","headerName": "Window (days)", "width": 110},
                    {"field": "mean_value",          "headerName": "Mean",          "width": 110},
                    {"field": "stddev_value",        "headerName": "Std Dev",       "width": 110},
                    {"field": "min_value",           "headerName": "Min",           "width": 110},
                    {"field": "max_value",           "headerName": "Max",           "width": 110},
                    {"field": "p25_value",           "headerName": "P25",           "width": 110},
                    {"field": "p50_value",           "headerName": "P50 (Median)",  "width": 110},
                    {"field": "p75_value",           "headerName": "P75",           "width": 110},
                    {"field": "p95_value",           "headerName": "P95",           "width": 110},
                    {"field": "sample_count",        "headerName": "Samples",       "width": 90},
                    {"field": "is_sufficient_data",  "headerName": "Sufficient",    "width": 100},
                    {"field": "baseline_status",     "headerName": "Status",     "minWidth": 150,
                     "cellStyle": {"function": """
                         function(params) {
                             var v = (params.value || '').toUpperCase();
                             if (v === 'VALID')             return {color: '#00c851'};
                             if (v === 'INSUFFICIENT_DATA') return {color: '#ffa500'};
                             return null;
                         }
                     """}},
                    {"field": "computed_by",          "headerName": "Computed By",   "flex": 1, "minWidth": 220},
                ],
                page_size=10,
                selection="single",
            )
        )

        return "", grid

    except Exception as e:
        logger.error(f"Failed to load KPI baselines: {str(e)}")
        return error_alert(
            f"Failed to load baselines: {str(e)}"
        ), html.Div()


@callback(
    Output("kpi-baseline-detail-panel", "children"),
    Input("kpi-baselines-grid", "selectedRows"),
    prevent_initial_call=True
)
def show_baseline_detail(selected_rows):
    """
    Shows a detailed stat panel when a baseline row is selected.
    Displays distribution statistics, anomaly trigger bounds,
    KPI registry configuration, and audit information.
    """
    if not selected_rows:
        return html.P(
            "Select a baseline row above to see full statistics.",
            className="text-muted"
        )

    row = selected_rows[0]

    # ── Extract fields ─────────────────────────────────────────────────────
    kpi_name    = row.get("kpi_name", "")
    kpi_column  = row.get("kpi_column", "")
    gold_table  = row.get("gold_table", "")
    gold_fqn    = row.get("gold_fully_qualified_name", "")
    bdate       = row.get("baseline_date", "")
    window      = row.get("baseline_window_days", "")
    samples     = row.get("sample_count", "")
    status      = row.get("baseline_status", "")
    computed_by = row.get("computed_by", "")
    computed_ts = row.get("computed_timestamp", "")

    # ── Format stat values using shared fmt_optional ───────────────────────
    mean_val   = fmt_optional(row.get("mean_value"),   decimals=4)
    stddev_val = fmt_optional(row.get("stddev_value"), decimals=4)
    min_val    = fmt_optional(row.get("min_value"),    decimals=4)
    max_val    = fmt_optional(row.get("max_value"),    decimals=4)
    p25_val    = fmt_optional(row.get("p25_value"),    decimals=4)
    p50_val    = fmt_optional(row.get("p50_value"),    decimals=4)
    p75_val    = fmt_optional(row.get("p75_value"),    decimals=4)
    p95_val    = fmt_optional(row.get("p95_value"),    decimals=4)

    status_color = "success" if status == "VALID" else "warning"
    status_emoji = "✅" if status == "VALID" else "⚠️"

    # ── Section 1: Anomaly Trigger Bounds ──────────────────────────────────
    # Computes what value would trigger WARNING and CRITICAL today
    # based on the KPI registry thresholds applied to the baseline mean

    threshold_section = html.Div()   # safe default

    try:
        kpi_df = execute_query(f"""
            SELECT
                warning_deviation_pct,
                critical_deviation_pct
            FROM {KPI_REGISTRY}
            WHERE kpi_name                  = :kpi_name
              AND gold_fully_qualified_name  = :gold_fqn
              AND is_active                  = true
            LIMIT 1
        """, {"kpi_name": kpi_name, "gold_fqn": gold_fqn})

        if not kpi_df.empty and mean_val != "—":
            warn_pct  = float(
                kpi_df.iloc[0]["warning_deviation_pct"] or 0
            )
            crit_pct  = float(
                kpi_df.iloc[0]["critical_deviation_pct"] or 0
            )
            mean_f    = float(row.get("mean_value") or 0)

            warn_low  = fmt_optional(
                mean_f * (1 - warn_pct / 100), decimals=4
            )
            warn_high = fmt_optional(
                mean_f * (1 + warn_pct / 100), decimals=4
            )
            crit_low  = fmt_optional(
                mean_f * (1 - crit_pct / 100), decimals=4
            )
            crit_high = fmt_optional(
                mean_f * (1 + crit_pct / 100), decimals=4
            )

            threshold_section = dbc.Card([
                dbc.CardHeader(
                    html.Strong("⚡ Anomaly Trigger Bounds"),
                    style={
                        "backgroundColor": "#343a40",
                        "color"          : "white"
                    }
                ),
                dbc.CardBody([
                    html.P(
                        "These are the values that would trigger "
                        "a WARNING or CRITICAL alert based on the "
                        "configured deviation thresholds applied "
                        "to the baseline mean.",
                        className="text-muted small mb-3"
                    ),
                    dbc.Row([
                        dbc.Col([
                            html.H6(
                                "🟡 Warning Zone",
                                style={"color": "#ffa500"}
                            ),
                            html.P(
                                "Triggers if today's average is outside:",
                                className="small text-muted mb-1"
                            ),
                            html.P(
                                f"[ {warn_low}  →  {warn_high} ]",
                                className="fw-bold font-monospace",
                                style={"color": "#ffa500"}
                            ),
                            html.Small(
                                f"±{warn_pct:.0f}% from "
                                f"baseline mean {mean_val}",
                                className="text-muted"
                            )
                        ], md=6),
                        dbc.Col([
                            html.H6(
                                "🔴 Critical Zone",
                                style={"color": "#ff6b6b"}
                            ),
                            html.P(
                                "Triggers if today's average is outside:",
                                className="small text-muted mb-1"
                            ),
                            html.P(
                                f"[ {crit_low}  →  {crit_high} ]",
                                className="fw-bold font-monospace",
                                style={"color": "#ff6b6b"}
                            ),
                            html.Small(
                                f"±{crit_pct:.0f}% from "
                                f"baseline mean {mean_val}",
                                className="text-muted"
                            )
                        ], md=6)
                    ])
                ])
            ], className="mb-3",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            })

    except Exception as e:
        logger.warning(
            f"Could not compute anomaly trigger bounds: {str(e)}"
        )

    # ── Section 2: KPI Registry Configuration ──────────────────────────────
    # Shows the registry entry for this KPI so user does not
    # need to navigate to a separate page

    registry_section = html.Div()   # safe default

    try:
        reg_df = execute_query(f"""
            SELECT
                kpi_id,
                kpi_description,
                formula_expression,
                checks_enabled,
                min_value,
                max_value,
                warning_deviation_pct,
                critical_deviation_pct,
                is_active,
                registered_by,
                registered_timestamp
            FROM {KPI_REGISTRY}
            WHERE kpi_name                  = :kpi_name
              AND gold_fully_qualified_name  = :gold_fqn
            LIMIT 1
        """, {"kpi_name": kpi_name, "gold_fqn": gold_fqn})

        if not reg_df.empty:
            r = reg_df.iloc[0]

            registry_section = dbc.Card([
                dbc.CardHeader(
                    html.Strong("📋 KPI Registry Configuration"),
                    style={
                        "backgroundColor": "#343a40",
                        "color"          : "white"
                    }
                ),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "KPI ID",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                str(r.get("kpi_id", "—")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Checks Enabled",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                str(r.get("checks_enabled", "—")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Formula",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt_optional(
                                    r.get("formula_expression")
                                ),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Active",
                                className="text-muted d-block"
                            ),
                            dbc.Badge(
                                "✅ Active"
                                if r.get("is_active")
                                else "❌ Inactive",
                                color=(
                                    "success"
                                    if r.get("is_active")
                                    else "danger"
                                )
                            )
                        ], md=3),
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "Range Min",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt_optional(r.get("min_value")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Range Max",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt_optional(r.get("max_value")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Warning Deviation %",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt_optional(
                                    r.get("warning_deviation_pct")
                                ),
                                className="small",
                                style={"color": "#ffa500"}
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Critical Deviation %",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt_optional(
                                    r.get("critical_deviation_pct")
                                ),
                                className="small",
                                style={"color": "#ff6b6b"}
                            )
                        ], md=3),
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "Description",
                                className="text-muted d-block"
                            ),
                            html.P(
                                str(
                                    r.get("kpi_description", "") or "—"
                                ),
                                className="text-white small mb-0"
                            )
                        ])
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "Registered By",
                                className="text-muted d-block mt-2"
                            ),
                            html.Strong(
                                str(r.get("registered_by", "—")),
                                className="text-white small"
                            )
                        ], md=6),
                        dbc.Col([
                            html.Small(
                                "Registered At",
                                className="text-muted d-block mt-2"
                            ),
                            html.Strong(
                                str(r.get("registered_timestamp", "—"))[:19],
                                className="text-white small"
                            )
                        ], md=6),
                    ])
                ])
            ], className="mb-3",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            })

    except Exception as e:
        logger.warning(
            f"Could not load KPI registry config: {str(e)}"
        )

    # ── Assemble full detail panel ─────────────────────────────────────────

    return dbc.Container([

        # ── Header ─────────────────────────────────────────────────────────
        dbc.Row([
            dbc.Col([
                html.H5(
                    kpi_name,
                    className="mb-1 text-white"
                ),
                html.P(
                    f"{gold_table}  →  column: {kpi_column}",
                    className="text-muted small mb-2"
                ),
                dbc.Badge(
                    f"{status_emoji} {status}",
                    color=status_color,
                    className="me-2"
                ),
                dbc.Badge(
                    f"{samples} samples over {window} days",
                    color="secondary",
                    className="me-2"
                ),
                dbc.Badge(
                    f"Baseline date: {bdate}",
                    color="info"
                )
            ])
        ], className="mb-4"),

        # ── Distribution Statistics ─────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Strong("📈 Distribution Statistics"),
                style={
                    "backgroundColor": "#343a40",
                    "color"          : "white"
                }
            ),
            dbc.CardBody([
                dbc.Row([

                    # Central tendency
                    dbc.Col([
                        html.H6(
                            "Central Tendency",
                            className="text-info mb-3"
                        ),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "Mean",
                                    className="text-muted d-block"
                                ),
                                width=5
                            ),
                            dbc.Col(
                                html.Strong(
                                    mean_val,
                                    className="text-white"
                                ),
                                width=7
                            )
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "Median (P50)",
                                    className="text-muted d-block"
                                ),
                                width=5
                            ),
                            dbc.Col(
                                html.Strong(
                                    p50_val,
                                    className="text-white"
                                ),
                                width=7
                            )
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "Std Dev",
                                    className="text-muted d-block"
                                ),
                                width=5
                            ),
                            dbc.Col(
                                html.Strong(
                                    stddev_val,
                                    className="text-white"
                                ),
                                width=7
                            )
                        ], className="mb-2"),
                    ], md=4),

                    # Range
                    dbc.Col([
                        html.H6(
                            "Range",
                            className="text-warning mb-3"
                        ),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "Min",
                                    className="text-muted d-block"
                                ),
                                width=5
                            ),
                            dbc.Col(
                                html.Strong(
                                    min_val,
                                    className="text-white"
                                ),
                                width=7
                            )
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "Max",
                                    className="text-muted d-block"
                                ),
                                width=5
                            ),
                            dbc.Col(
                                html.Strong(
                                    max_val,
                                    className="text-white"
                                ),
                                width=7
                            )
                        ], className="mb-2"),
                    ], md=4),

                    # Percentiles
                    dbc.Col([
                        html.H6(
                            "Percentiles",
                            className="text-success mb-3"
                        ),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "P25",
                                    className="text-muted d-block"
                                ),
                                width=4
                            ),
                            dbc.Col(
                                html.Strong(
                                    p25_val,
                                    className="text-white"
                                ),
                                width=8
                            )
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "P75",
                                    className="text-muted d-block"
                                ),
                                width=4
                            ),
                            dbc.Col(
                                html.Strong(
                                    p75_val,
                                    className="text-white"
                                ),
                                width=8
                            )
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    "P95",
                                    className="text-muted d-block"
                                ),
                                width=4
                            ),
                            dbc.Col(
                                html.Strong(
                                    p95_val,
                                    className="text-white"
                                ),
                                width=8
                            )
                        ], className="mb-2"),
                    ], md=4),

                ])
            ])
        ], className="mb-3",
        style={
            "backgroundColor": "#2b2b2b",
            "border"         : "1px solid #444"
        }),

        # ── Anomaly Trigger Bounds ──────────────────────────────────────────
        threshold_section,

        # ── KPI Registry Configuration ──────────────────────────────────────
        registry_section,

        # ── Audit Info ─────────────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.Strong("🔍 Audit"),
                style={
                    "backgroundColor": "#343a40",
                    "color"          : "white"
                }
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Small(
                            "Computed By",
                            className="text-muted d-block"
                        ),
                        html.Strong(
                            computed_by or "—",
                            className="text-white small"
                        )
                    ], md=4),
                    dbc.Col([
                        html.Small(
                            "Computed At",
                            className="text-muted d-block"
                        ),
                        html.Strong(
                            str(computed_ts)[:19] if computed_ts else "—",
                            className="text-white small"
                        )
                    ], md=4),
                    dbc.Col([
                        html.Small(
                            "Baseline Date",
                            className="text-muted d-block"
                        ),
                        html.Strong(
                            bdate or "—",
                            className="text-white small"
                        )
                    ], md=4)
                ])
            ])
        ], style={
            "backgroundColor": "#2b2b2b",
            "border"         : "1px solid #444"
        })

    ], fluid=True)

    # ── KPI Registry Config ────────────────────────────────────────────────────
    try:
        reg_df = execute_query(f"""
            SELECT
                kpi_id,
                kpi_description,
                formula_expression,
                checks_enabled,
                min_value,
                max_value,
                warning_deviation_pct,
                critical_deviation_pct,
                is_active,
                registered_by,
                registered_timestamp
            FROM {KPI_REGISTRY}
            WHERE kpi_name = :kpi_name
            AND gold_fully_qualified_name = :gold_fqn
            LIMIT 1
        """, {
            "kpi_name": kpi_name,
            "gold_fqn": row.get("gold_fully_qualified_name", ""),
        })

        if not reg_df.empty:
            r = reg_df.iloc[0]

            def fmt(v):
                try:
                    import math
                    if v is None or math.isnan(float(v)):
                        return "—"
                    return str(v)
                except (TypeError, ValueError):
                    return str(v) if v else "—"

            registry_section = dbc.Card([
                dbc.CardHeader(
                    html.Strong("📋 KPI Registry Configuration"),
                    style={
                        "backgroundColor": "#343a40",
                        "color"          : "white"
                    }
                ),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "KPI ID",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                str(r.get("kpi_id", "—")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Checks Enabled",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                str(r.get("checks_enabled", "—")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Formula",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                str(r.get("formula_expression", "") or "—"),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Active",
                                className="text-muted d-block"
                            ),
                            dbc.Badge(
                                "✅ Active" if r.get("is_active") else "❌ Inactive",
                                color="success" if r.get("is_active") else "danger"
                            )
                        ], md=3),
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "Range Min",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt(r.get("min_value")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Range Max",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt(r.get("max_value")),
                                className="text-white small"
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Warning Deviation %",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt(r.get("warning_deviation_pct")),
                                className="text-white small",
                                style={"color": "#ffa500 !important"}
                            )
                        ], md=3),
                        dbc.Col([
                            html.Small(
                                "Critical Deviation %",
                                className="text-muted d-block"
                            ),
                            html.Strong(
                                fmt(r.get("critical_deviation_pct")),
                                className="text-white small",
                                style={"color": "#ff6b6b !important"}
                            )
                        ], md=3),
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                "Description",
                                className="text-muted d-block"
                            ),
                            html.P(
                                str(r.get("kpi_description", "") or "—"),
                                className="text-white small mb-0"
                            )
                        ])
                    ])
                ])
            ], className="mt-3",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            })
        else:
            registry_section = html.Div()

    except Exception as e:
        logger.warning(f"Could not load KPI registry config: {str(e)}")
        registry_section = html.Div()