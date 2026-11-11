# pages/kpi_registry.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import json
import logging
from db.connection import execute_query, execute_write
from db.queries import (
    get_all_kpis,
    insert_kpi,
    toggle_kpi_active,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import (
    success_alert,
    error_alert,
    info_alert,
    fmt_optional,
    ag_grid_props,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/kpi-registry",
    name="KPI Registry"
)

# ── Constants ──────────────────────────────────────────────────────────────

CHECK_OPTIONS = [
    {"label": "Formula Validation",    "value": "FORMULA"},
    {"label": "Cross-KPI Consistency", "value": "CROSS_KPI"},
    {"label": "Anomaly Detection",     "value": "ANOMALY"},
    {"label": "Range Validation",      "value": "RANGE"},
]

GOLD_TABLES_OPTIONS = [
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

# ── Helper ─────────────────────────────────────────────────────────────────

def _build_kpi_row(row) -> dict:
    return {
        "kpi_id"                 : str(row.get("kpi_id", "")),
        "gold_table"             : str(row.get("gold_table", "")),
        "gold_fully_qualified_name": str(
            row.get("gold_fully_qualified_name", "")
        ),
        "kpi_name"               : str(row.get("kpi_name", "")),
        "kpi_column"             : str(row.get("kpi_column", "")),
        "formula_expression"     : fmt_optional(
            row.get("formula_expression")
        ),
        "min_value"              : fmt_optional(row.get("min_value")),
        "max_value"              : fmt_optional(row.get("max_value")),
        "warning_deviation_pct"  : fmt_optional(
            row.get("warning_deviation_pct")
        ),
        "critical_deviation_pct" : fmt_optional(
            row.get("critical_deviation_pct")
        ),
        "checks_enabled"         : str(row.get("checks_enabled", "")),
        "has_baseline"           : str(row.get("has_baseline", "NO")),
        "baseline_mean"          : fmt_optional(row.get("baseline_mean")),
        "baseline_stddev"        : fmt_optional(
            row.get("baseline_stddev")
        ),
        "baseline_status"        : fmt_optional(
            row.get("baseline_status")
        ),
        "baseline_samples"       : fmt_optional(
            row.get("baseline_samples")
        ),
        "is_active"              : str(row.get("is_active", True))
    }


# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2("KPI Assurance Agent — KPI Registry", className="mt-4 mb-2"),
    html.P(
        "Register and manage Gold KPI definitions. "
        "Each KPI requires a formula, acceptable range, "
        "and anomaly detection thresholds.",
        className="text-muted mb-4"
    ),

    html.Div(id="kpi-registry-alert"),

    # ── Registered KPIs Grid ──────────────────────────────────────────────
    dcc.Loading(id="kpi-reg-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(
            dbc.Row([
                dbc.Col(
                    html.H5("Registered KPIs", className="mb-0"),
                    width="auto"
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh",
                        id="refresh-kpi-registry-btn",
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
                    grid_id="kpi-registry-grid",
                    col_defs=[
                        {"field": "kpi_id",                "headerName": "KPI ID",      "minWidth": 150},
                        {"field": "gold_table",            "headerName": "Gold Table",     "flex": 2, "minWidth": 220},
                        {"field": "kpi_name",              "headerName": "KPI Name",       "flex": 2, "minWidth": 220},
                        {"field": "kpi_column",            "headerName": "Column",      "minWidth": 160},
                        {"field": "formula_expression",    "headerName": "Formula",        "flex": 2, "minWidth": 280},
                        {"field": "min_value",             "headerName": "Min",            "width": 110},
                        {"field": "max_value",             "headerName": "Max",            "width": 110},
                        {"field": "warning_deviation_pct", "headerName": "Warn %",         "width": 110},
                        {"field": "critical_deviation_pct","headerName": "Crit %",         "width": 110},
                        {"field": "checks_enabled",        "headerName": "Checks",      "minWidth": 200},
                        {"field": "has_baseline",          "headerName": "Has Baseline",   "minWidth": 150,
                         "cellStyle": {"function": """
                             function(params) {
                                 var v = (params.value || '').toUpperCase();
                                 if (v === 'YES') return {color: '#00c851', fontWeight: 'bold'};
                                 if (v === 'NO')  return {color: '#ffa500', fontWeight: 'bold'};
                                 return null;
                             }
                         """}},
                        {"field": "baseline_mean",         "headerName": "Baseline Mean",  "width": 120},
                        {"field": "baseline_stddev",       "headerName": "Baseline StdDev","width": 130},
                        {"field": "baseline_status",       "headerName": "Baseline Status","minWidth": 150,
                         "cellStyle": {"function": """
                             function(params) {
                                 var v = (params.value || '').toUpperCase();
                                 if (v === 'VALID')             return {color: '#00c851'};
                                 if (v === 'INSUFFICIENT_DATA') return {color: '#ffa500'};
                                 return null;
                             }
                         """}},
                        {"field": "baseline_samples",      "headerName": "Samples",        "width": 90},
                        {"field": "is_active",             "headerName": "Active",         "width": 90},
                    ],
                    page_size=10,
                    selection="single",
                )
            )
        ])
    ], className="mb-4"),
    ]),  # end Loading

    # ── Manage Selected KPI ────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Manage Selected KPI", className="mb-0")
        ),
        dbc.CardBody([
            html.P(
                "Select a KPI above to manage it.",
                className="text-muted",
                id="selected-kpi-label"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button(
                            "Deactivate",
                            id="deactivate-kpi-btn",
                            color="warning",
                            n_clicks=0,
                            disabled=True
                        ),
                        dbc.Button(
                            "Activate",
                            id="activate-kpi-btn",
                            color="success",
                            n_clicks=0,
                            disabled=True
                        )
                    ])
                ], width="auto"),
                dbc.Col([
                    dbc.Button(
                        "📊 View Baseline",
                        id="view-baseline-btn",
                        color="info",
                        outline=True,
                        disabled=True,
                        href="/kpi-baselines"
                    )
                ], width="auto")
            ], align="center", className="g-2")
        ])
    ], className="mb-4"),

    # ── Register New KPI ───────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Register New KPI", className="mb-0")
        ),
        dbc.CardBody([

            dbc.Row([
                dbc.Col([
                    dbc.Label("Gold Table", className="text-white"),
                    dcc.Dropdown(
                        id="kpi-gold-table-dropdown",
                        options=GOLD_TABLES_OPTIONS,
                        placeholder="Select Gold table...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label(
                        "Business Date Column",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-date-col-input",
                        type="text",
                        placeholder="e.g. business_date",
                        value="business_date",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("KPI Name", className="text-white"),
                    dbc.Input(
                        id="kpi-name-input",
                        type="text",
                        placeholder="e.g. return_rate",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label("KPI Column", className="text-white"),
                    dbc.Input(
                        id="kpi-column-input",
                        type="text",
                        placeholder="e.g. return_rate",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Description", className="text-white"),
                    dbc.Textarea(
                        id="kpi-description-input",
                        placeholder="Describe what this KPI measures...",
                        rows=2,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=12),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Formula Expression "
                        "(leave blank if no formula check)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-formula-input",
                        type="text",
                        placeholder=(
                            "e.g. return_count / total_transactions"
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "Write the right-hand side of the equation. "
                        "The KPI column must equal this expression.",
                        className="text-muted"
                    )
                ], md=8),
                dbc.Col([
                    dbc.Label(
                        "Formula Columns (JSON array)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-formula-cols-input",
                        type="text",
                        placeholder=(
                            '["return_count", "total_transactions"]'
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Min Value (leave blank for no lower bound)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-min-input",
                        type="number",
                        placeholder="e.g. 0.0",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label(
                        "Max Value (leave blank for no upper bound)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-max-input",
                        type="number",
                        placeholder="e.g. 1.0",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label(
                        "Warning Deviation %",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-warn-pct-input",
                        type="number",
                        placeholder="e.g. 20",
                        min=0,
                        max=100,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "% deviation from baseline to trigger warning",
                        className="text-muted"
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label(
                        "Critical Deviation %",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-crit-pct-input",
                        type="number",
                        placeholder="e.g. 50",
                        min=0,
                        max=100,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "% deviation from baseline to trigger critical",
                        className="text-muted"
                    )
                ], md=3),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Baseline Window Days",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="kpi-baseline-days-input",
                        type="number",
                        placeholder="e.g. 30",
                        value=30,
                        min=7,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("Registered By", className="text-white"),
                    dbc.Input(
                        id="kpi-registered-by-input",
                        type="text",
                        placeholder="Your name or email...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label(
                        "Checks to Enable",
                        className="text-white"
                    ),
                    dcc.Checklist(
                        id="kpi-checks-checklist",
                        options=CHECK_OPTIONS,
                        value=["FORMULA", "RANGE", "ANOMALY"],
                        inputStyle={"marginRight": "8px"},
                        labelStyle={
                            "display"     : "block",
                            "color"       : "#ffffff",
                            "marginBottom": "4px"
                        }
                    )
                ], md=6),
            ], className="mb-4"),

            dbc.Button(
                "Register KPI",
                id="register-kpi-btn",
                color="primary",
                n_clicks=0
            )
        ])
    ]),

], fluid=True)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("kpi-registry-grid", "rowData"),
    Input("refresh-kpi-registry-btn", "n_clicks"),
    prevent_initial_call=False
)
def load_kpi_registry(_):
    try:
        df = execute_query(get_all_kpis())
        if df.empty:
            return []
        return [_build_kpi_row(row) for _, row in df.iterrows()]
    except Exception as e:
        logger.error(f"Failed to load KPI registry: {str(e)}")
        return []


@callback(
    Output("selected-kpi-label", "children"),
    Output("deactivate-kpi-btn", "disabled"),
    Output("activate-kpi-btn", "disabled"),
    Output("view-baseline-btn", "disabled"),
    Input("kpi-registry-grid", "selectedRows"),
)
def update_selected_kpi(selected_rows):
    if not selected_rows:
        return (
            "Select a KPI above to manage it.",
            True, True, True
        )

    row          = selected_rows[0]
    kpi_name     = row.get("kpi_name", "")
    kpi_id       = row.get("kpi_id", "")
    is_active    = row.get("is_active", "True")
    has_baseline = row.get("has_baseline", "NO")
    checks       = row.get("checks_enabled", "")
    status       = "Active" if is_active == "True" else "Inactive"

    label = (
        f"Selected: {kpi_name} ({kpi_id}) — {status}"
    )

    # View Baseline enabled only when ANOMALY check exists
    # AND baseline has been computed
    baseline_btn_disabled = not (
        has_baseline == "YES" and "ANOMALY" in checks
    )

    return label, False, False, baseline_btn_disabled


@callback(
    Output("kpi-registry-alert", "children"),
    Output("kpi-registry-grid", "rowData", allow_duplicate=True),
    Input("deactivate-kpi-btn", "n_clicks"),
    Input("activate-kpi-btn", "n_clicks"),
    State("kpi-registry-grid", "selectedRows"),
    prevent_initial_call=True
)
def toggle_kpi_status(
    deactivate_clicks, activate_clicks,
    selected_rows
):
    if not selected_rows:
        return "", []

    triggered = ctx.triggered_id
    row       = selected_rows[0]
    kpi_id    = row.get("kpi_id", "")
    kpi_name  = row.get("kpi_name", "")
    is_active = triggered == "activate-kpi-btn"

    try:
        execute_write(*toggle_kpi_active(kpi_id, is_active))
        df     = execute_query(get_all_kpis())
        rows   = [_build_kpi_row(r) for _, r in df.iterrows()]
        action = "activated" if is_active else "deactivated"
        return (
            success_alert(f"KPI '{kpi_name}' {action} successfully."),
            rows
        )
    except Exception as e:
        logger.error(f"Failed to toggle KPI: {str(e)}")
        return error_alert(f"Toggle failed: {str(e)}"), []


@callback(
    Output("kpi-registry-alert", "children", allow_duplicate=True),
    Output("kpi-registry-grid", "rowData", allow_duplicate=True),
    Input("register-kpi-btn", "n_clicks"),
    State("kpi-gold-table-dropdown", "value"),
    State("kpi-date-col-input", "value"),
    State("kpi-name-input", "value"),
    State("kpi-column-input", "value"),
    State("kpi-description-input", "value"),
    State("kpi-formula-input", "value"),
    State("kpi-formula-cols-input", "value"),
    State("kpi-min-input", "value"),
    State("kpi-max-input", "value"),
    State("kpi-warn-pct-input", "value"),
    State("kpi-crit-pct-input", "value"),
    State("kpi-baseline-days-input", "value"),
    State("kpi-registered-by-input", "value"),
    State("kpi-checks-checklist", "value"),
    prevent_initial_call=True
)
def register_kpi(
    n_clicks,
    gold_table, date_col, kpi_name, kpi_column,
    description, formula, formula_cols,
    min_val, max_val, warn_pct, crit_pct,
    baseline_days, registered_by, checks_enabled
):
    if not n_clicks:
        return "", []

    required = {
        "Gold Table"   : gold_table,
        "KPI Name"     : kpi_name,
        "KPI Column"   : kpi_column,
        "Warning %"    : warn_pct,
        "Critical %"   : crit_pct,
        "Registered By": registered_by
    }

    missing = [k for k, v in required.items() if not v and v != 0]
    if missing:
        return error_alert(
            f"Please fill in: {', '.join(missing)}"
        ), []

    if not checks_enabled:
        return error_alert(
            "Please select at least one check to enable."
        ), []

    # Validate formula columns JSON
    formula_cols_json = "[]"
    if formula_cols:
        try:
            parsed = json.loads(formula_cols)
            formula_cols_json = json.dumps(parsed)
        except json.JSONDecodeError:
            return error_alert(
                "Formula Columns must be a valid JSON array. "
                'Example: ["col1", "col2"]'
            ), []

    checks_json = json.dumps(checks_enabled)

    table_short = gold_table.split(".")[-1].replace(
        "uc2_gold_daily_", ""
    )
    kpi_id = f"kpi-{table_short[:3]}-{str(uuid.uuid4())[:6]}"

    try:
        query = insert_kpi(
            kpi_id                    = kpi_id,
            gold_fully_qualified_name = gold_table,
            business_date_column      = (date_col or "business_date").strip(),
            kpi_name                  = kpi_name.strip(),
            kpi_column                = kpi_column.strip(),
            kpi_description           = (description or "").strip(),
            formula_expression        = (formula or "").strip(),
            formula_columns           = formula_cols_json,
            min_value                 = float(min_val) if min_val is not None else None,
            max_value                 = float(max_val) if max_val is not None else None,
            baseline_window_days      = int(baseline_days or 30),
            warning_deviation_pct     = float(warn_pct),
            critical_deviation_pct    = float(crit_pct),
            checks_enabled            = checks_json,
            registered_by             = registered_by.strip()
        )
        execute_write(*query)

        df   = execute_query(get_all_kpis())
        rows = [_build_kpi_row(r) for _, r in df.iterrows()]

        return (
            success_alert(
                f"KPI '{kpi_name}' registered successfully. "
                f"ID: {kpi_id}"
            ),
            rows
        )

    except Exception as e:
        logger.error(f"Failed to register KPI: {str(e)}")
        return error_alert(f"Registration failed: {str(e)}"), []