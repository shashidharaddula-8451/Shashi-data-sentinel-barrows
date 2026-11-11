# pages/transformation_registry.py

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
    get_all_registered_tables,
    get_silver_layer_tables,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import (
    success_alert, error_alert, ag_grid_props,
    AG_STATUS_ROW_STYLE_JS, AG_STATUS_CELL_STYLE_JS,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/transformation-registry",
    name="Transformation Registry"
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

    html.H2("Transformation Agent — Transformation Registry", className="mt-4 mb-2"),
    html.P(
        "Register and manage Silver transformation notebooks for "
        "automated code review. Each registered transformation will "
        "be reviewed by Transformation Agent for risky SQL patterns and row count "
        "ratio anomalies.",
        className="text-muted mb-4"
    ),

    html.Div(id="txfm-reg-alert"),

    # ── Registered Transformations Grid ─
    dcc.Loading(id="txfm-loading", type="circle", color="#00c851", children=[
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
                        id="txfm-reg-refresh-btn",
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
                    grid_id="txfm-reg-grid",
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
    ]),  # end Loading

    # ── Manage Selected Transformation ─────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Manage Selected Transformation", className="mb-0")
        ),
        dbc.CardBody([
            html.P(
                "Select a row above to manage it.",
                className="text-muted",
                id="txfm-reg-selected-label"
            ),
            dbc.ButtonGroup([
                dbc.Button(
                    "Deactivate",
                    id="txfm-reg-deactivate-btn",
                    color="warning",
                    n_clicks=0,
                    disabled=True
                ),
                dbc.Button(
                    "Activate",
                    id="txfm-reg-activate-btn",
                    color="success",
                    n_clicks=0,
                    disabled=True
                )
            ])
        ])
    ], className="mb-4"),

    # ── Register New Transformation ────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Register New Transformation", className="mb-0")
        ),
        dbc.CardBody([

            # ── Info banner ────────────────────────────────────────────────
            dbc.Alert([
                html.Strong("Target Table "),
                "shows Silver tables from the Layer Registry. ",
                html.Strong("Source Table "),
                "shows Raw tables from the Table Registry. ",
                "Selecting a Target will auto-populate the Source "
                "and Survival Rate."
            ],
            color="info",
            className="mb-3 small"
            ),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Target Silver Table",
                        className="text-white"
                    ),
                    dcc.Dropdown(
                        id="txfm-reg-target-dropdown",
                        placeholder="Select Silver target table...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    ),
                    dbc.FormText(
                        "Silver tables from Reconciliation Agent Layer Registry.",
                        className="text-muted"
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label(
                        "Source Raw Table",
                        className="text-white"
                    ),
                    dcc.Dropdown(
                        id="txfm-reg-source-dropdown",
                        placeholder="Select Raw source table...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    ),
                    dbc.FormText(
                        "Raw tables from Validation Agent Table Registry.",
                        className="text-muted"
                    )
                ], md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Notebook Path (full workspace path)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="txfm-reg-notebook-path-input",
                        type="text",
                        placeholder=(
                            "/Users/s819534@8451.com/"
                            "data_trust_layer/..."
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=8),
                dbc.Col([
                    dbc.Label(
                        "Notebook Language",
                        className="text-white"
                    ),
                    dcc.Dropdown(
                        id="txfm-reg-language-dropdown",
                        options=[
                            {"label": "Python", "value": "PYTHON"},
                            {"label": "SQL",    "value": "SQL"},
                            {"label": "Scala",  "value": "SCALA"}
                        ],
                        value="PYTHON",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Function Name (leave blank for entire notebook)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="txfm-reg-function-name-input",
                        type="text",
                        placeholder=(
                            "e.g. transform_raw_to_silver_transactions"
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label(
                        "Expected Survival Rate (%)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="txfm-reg-survival-rate-input",
                        type="number",
                        placeholder="e.g. 92",
                        min=1,
                        max=100,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "Auto-populated when Target is selected.",
                        className="text-muted"
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label(
                        "Registered By",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="txfm-reg-registered-by-input",
                        type="text",
                        placeholder="Your name or email...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=3),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Description", className="text-white"),
                    dbc.Textarea(
                        id="txfm-reg-description-input",
                        placeholder=(
                            "Describe what this transformation does..."
                        ),
                        rows=3,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=8),
                dbc.Col([
                    dbc.Label(
                        "Checks to Enable",
                        className="text-white"
                    ),
                    dcc.Checklist(
                        id="txfm-reg-checks-checklist",
                        options=CHECKS_OPTIONS,
                        value=[
                            "JOIN_FANOUT",
                            "NULL_FILTER",
                            "AGGREGATION_ORDER",
                            "ROW_COUNT_RATIO"
                        ],
                        inputStyle={"marginRight": "8px"},
                        labelStyle={
                            "display"     : "block",
                            "color"       : "#ffffff",
                            "marginBottom": "4px"
                        }
                    )
                ], md=4),
            ], className="mb-4"),

            dbc.Button(
                "Register Transformation",
                id="txfm-reg-register-btn",
                color="primary",
                n_clicks=0
            )
        ])
    ]),

    # ── Store for layer data ───────────────────────────────────────────────
    dcc.Store(id="txfm-reg-layer-store", data=None)

], fluid=True)


# ── Helper: build row dict ─────────────────────────────────────────────────

def _build_txfm_row(row) -> dict:
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


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("txfm-reg-grid", "rowData"),
    Input("txfm-reg-refresh-btn", "n_clicks"),
    prevent_initial_call=False
)
def load_transformations(_):
    try:
        df   = execute_query(get_all_transformations())
        rows = [_build_txfm_row(row) for _, row in df.iterrows()]
        return rows
    except Exception as e:
        logger.error(f"Failed to load transformations: {str(e)}")
        return []


@callback(
    Output("txfm-reg-selected-label", "children"),
    Output("txfm-reg-deactivate-btn", "disabled"),
    Output("txfm-reg-activate-btn", "disabled"),
    Input("txfm-reg-grid", "selectedRows"),
)
def update_selected_label(selected_rows):
    if not selected_rows:
        return "Select a row above to manage it.", True, True

    row         = selected_rows[0]
    txfm_id     = row.get("transformation_id", "")
    target      = row.get("target_table", "")
    last_status = row.get("last_review_status", "NOT_REVIEWED")
    is_active   = row.get("is_active", "True")
    status_str  = "Active" if is_active == "True" else "Inactive"

    label = (
        f"Selected: {target} ({txfm_id}) — "
        f"{status_str} | Last review: {last_status}"
    )
    return label, False, False


@callback(
    Output("txfm-reg-alert", "children"),
    Output("txfm-reg-grid", "rowData", allow_duplicate=True),
    Input("txfm-reg-deactivate-btn", "n_clicks"),
    Input("txfm-reg-activate-btn", "n_clicks"),
    State("txfm-reg-grid", "selectedRows"),
    prevent_initial_call=True
)
def toggle_transformation(
    deactivate_clicks, activate_clicks,
    selected_rows
):
    if not selected_rows:
        return "", []

    triggered = ctx.triggered_id
    row       = selected_rows[0]
    txfm_id   = row.get("transformation_id", "")
    is_active = triggered == "txfm-reg-activate-btn"

    try:
        execute_write(*toggle_transformation_active(txfm_id, is_active))
        df     = execute_query(get_all_transformations())
        rows   = [_build_txfm_row(r) for _, r in df.iterrows()]
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


@callback(
    Output("txfm-reg-target-dropdown", "options"),
    Output("txfm-reg-layer-store", "data"),
    Input("txfm-reg-target-dropdown", "id")
)
def load_target_options(_):
    try:
        df = execute_query(get_silver_layer_tables())
        if df.empty:
            logger.warning(
                "No Silver layers found. "
                "Register layers in Agent 2 → Layer Registry first."
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


@callback(
    Output("txfm-reg-source-dropdown", "options"),
    Input("txfm-reg-source-dropdown", "id")
)
def load_source_options(_):
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


@callback(
    Output("txfm-reg-source-dropdown", "value"),
    Output("txfm-reg-survival-rate-input", "value"),
    Input("txfm-reg-target-dropdown", "value"),
    State("txfm-reg-layer-store", "data"),
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

    logger.info(
        f"Auto-populated: source={source}, survival={survival_pct}%"
    )
    return source, survival_pct


@callback(
    Output("txfm-reg-alert", "children", allow_duplicate=True),
    Output("txfm-reg-grid", "rowData", allow_duplicate=True),
    Input("txfm-reg-register-btn", "n_clicks"),
    State("txfm-reg-target-dropdown", "value"),
    State("txfm-reg-source-dropdown", "value"),
    State("txfm-reg-notebook-path-input", "value"),
    State("txfm-reg-language-dropdown", "value"),
    State("txfm-reg-function-name-input", "value"),
    State("txfm-reg-survival-rate-input", "value"),
    State("txfm-reg-registered-by-input", "value"),
    State("txfm-reg-description-input", "value"),
    State("txfm-reg-checks-checklist", "value"),
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
                f"Transformation registered. ID: {txfm_id}"
            ),
            rows
        )

    except Exception as e:
        logger.error(f"Failed to register transformation: {str(e)}")
        return error_alert(f"Registration failed: {str(e)}"), []