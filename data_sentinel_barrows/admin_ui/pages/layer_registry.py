# pages/layer_registry.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import json
import logging
from db.connection import execute_query, execute_write
from db.queries import (
    get_all_registered_tables,
    get_all_layers,
    insert_layer,
    update_layer,
    toggle_layer_active,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import success_alert, error_alert, ag_grid_props

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/layer-registry", name="Layer Registry")

LAYER_NAMES = ["BRONZE", "SILVER", "GOLD"]

layout = dbc.Container([

    html.H2("Reconciliation Agent — Layer Registry", className="mt-4 mb-2"),
    html.P(
        "Register Raw, Silver, and Gold layers for each source table. "
        "Reconciliation Agent uses this configuration to run cross-layer reconciliation checks.",
        className="text-muted mb-4"
    ),

    html.Div(id="layer-registry-alert"),

    # ── All Registered Layers ──
    # Wrapped in Loading spinner
    dcc.Loading(id="layers-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(
            dbc.Row([
                dbc.Col(
                    html.H5("Registered Layers", className="mb-0"),
                    width="auto"
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh",
                        id="refresh-layers-btn",
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
                    grid_id="layers-grid",
                    col_defs=[
                        {"field": "source_fully_qualified_name", "headerName": "Source Table",  "flex": 2, "minWidth": 220},
                        {"field": "layer_name",                 "headerName": "Layer",      "minWidth": 150,
                         "cellStyle": {"function": """
                             function(params) {
                                 var v = (params.value || '').toUpperCase();
                                 if (v === 'BRONZE') return {color: '#aaaaaa'};
                                 if (v === 'SILVER') return {color: '#87ceeb'};
                                 if (v === 'GOLD')   return {color: '#ffd700'};
                                 return null;
                             }
                         """}},
                        {"field": "layer_fully_qualified_name",  "headerName": "Layer Table",   "flex": 2, "minWidth": 220},
                        {"field": "business_date_column",        "headerName": "Date Column",   "minWidth": 150},
                        {"field": "expected_survival_pct",       "headerName": "Survival %",    "width": 110},
                        {"field": "expected_latency_minutes",    "headerName": "Latency (min)", "width": 120},
                        {"field": "is_active",                   "headerName": "Active",        "width": 90},
                        {"field": "registered_by",               "headerName": "Registered By", "flex": 1, "minWidth": 220},
                    ],
                    page_size=12,
                    selection="single",
                )
            )
        ])
    ], className="mb-4"),
    ]),  # end Loading

    # ── Register or Edit Layer ─────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(html.H5("Register / Edit Layer", className="mb-0")),
        dbc.CardBody([

            dbc.Row([
                dbc.Col([
                    dbc.Label("Source Table (from Validation Agent Registry)",
                              className="text-white"),
                    dcc.Dropdown(
                        id="layer-source-table-dropdown",
                        placeholder="Select source table...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label("Layer", className="text-white"),
                    dcc.Dropdown(
                        id="layer-name-dropdown",
                        options=[
                            {"label": l, "value": l}
                            for l in LAYER_NAMES
                        ],
                        placeholder="Select layer...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Layer Table (fully qualified name)",
                              className="text-white"),
                    dbc.Input(
                        id="layer-table-input",
                        type="text",
                        placeholder=(
                            "e.g. learning_dev.s819534"
                            ".uc2_silver_store_transactions"
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=8),
                dbc.Col([
                    dbc.Label("Business Date Column",
                              className="text-white"),
                    dbc.Input(
                        id="layer-date-col-input",
                        type="text",
                        placeholder="e.g. transaction_date",
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
                        "Expected Survival Rate % (Silver: 92, Gold: leave blank)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="layer-survival-input",
                        type="number",
                        placeholder="e.g. 92",
                        min=0,
                        max=100,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label(
                        "Expected Latency (minutes)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="layer-latency-input",
                        type="number",
                        placeholder="e.g. 120",
                        min=0,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Registered By", className="text-white"),
                    dbc.Input(
                        id="layer-registered-by-input",
                        type="text",
                        placeholder="Your name or email...",
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
                        "Reconciliation Metrics (comma separated column names)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="layer-metrics-input",
                        type="text",
                        placeholder=(
                            "e.g. net_amount, gross_amount, discount_amount"
                        ),
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "These columns will be summed and compared between layers.",
                        className="text-muted"
                    )
                ], md=12),
            ], className="mb-4"),

            # Hidden field to track edit mode
            dcc.Store(id="layer-edit-id", data=None),

            dbc.ButtonGroup([
                dbc.Button(
                    "Save Layer",
                    id="save-layer-btn",
                    color="primary",
                    n_clicks=0
                ),
                dbc.Button(
                    "Clear Form",
                    id="clear-layer-form-btn",
                    color="secondary",
                    n_clicks=0
                )
            ])
        ])
    ], className="mb-4"),

    # ── Manage Selected Layer ──────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(
            html.H5("Manage Selected Layer", className="mb-0")
        ),
        dbc.CardBody([
            html.P(
                "Select a row above to manage it.",
                className="text-muted",
                id="selected-layer-label"
            ),
            dbc.ButtonGroup([
                dbc.Button(
                    "Edit Selected",
                    id="edit-layer-btn",
                    color="info",
                    n_clicks=0,
                    disabled=True
                ),
                dbc.Button(
                    "Deactivate",
                    id="deactivate-layer-btn",
                    color="warning",
                    n_clicks=0,
                    disabled=True
                ),
                dbc.Button(
                    "Activate",
                    id="activate-layer-btn",
                    color="success",
                    n_clicks=0,
                    disabled=True
                )
            ])
        ])
    ])

], fluid=True)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("layers-grid", "rowData"),
    Input("refresh-layers-btn", "n_clicks"),
    prevent_initial_call=False
)
def load_layers(n_clicks):
    try:
        df = execute_query(get_all_layers())
        return df.to_dict("records")
    except Exception as e:
        logger.error(f"Failed to load layers: {str(e)}")
        return []


@callback(
    Output("layer-source-table-dropdown", "options"),
    Input("layer-source-table-dropdown", "id")
)
def load_source_tables(_):
    try:
        df = execute_query(get_all_registered_tables())
        if df.empty:
            return []
        return [
            {
                "label": row["fully_qualified_name"],
                "value": row["fully_qualified_name"]
            }
            for _, row in df.iterrows()
        ]
    except Exception as e:
        logger.error(f"Failed to load source tables: {str(e)}")
        return []


@callback(
    Output("selected-layer-label", "children"),
    Output("edit-layer-btn", "disabled"),
    Output("deactivate-layer-btn", "disabled"),
    Output("activate-layer-btn", "disabled"),
    Input("layers-grid", "selectedRows"),
)
def update_selected_layer(selected_rows):
    if not selected_rows:
        return "Select a row above to manage it.", True, True, True

    row    = selected_rows[0]
    source = row.get("source_fully_qualified_name", "").split(".")[-1]
    layer  = row.get("layer_name", "")
    active = row.get("is_active", True)

    label = (
        f"Selected: {source} → {layer} "
        f"({'Active' if active else 'Inactive'})"
    )
    return label, False, False, False


@callback(
    Output("layer-source-table-dropdown", "value"),
    Output("layer-name-dropdown", "value"),
    Output("layer-table-input", "value"),
    Output("layer-date-col-input", "value"),
    Output("layer-survival-input", "value"),
    Output("layer-latency-input", "value"),
    Output("layer-metrics-input", "value"),
    Output("layer-registered-by-input", "value"),
    Output("layer-edit-id", "data"),
    Input("edit-layer-btn", "n_clicks"),
    Input("clear-layer-form-btn", "n_clicks"),
    State("layers-grid", "selectedRows"),
    prevent_initial_call=True
)
def populate_form_for_edit(edit_clicks, clear_clicks, selected_rows):
    triggered = ctx.triggered_id

    if triggered == "clear-layer-form-btn":
        return None, None, "", "", None, None, "", "", None

    if triggered == "edit-layer-btn" and selected_rows:
        row = selected_rows[0]

        # Parse metrics back from JSON array to comma-separated string
        metrics_raw = row.get("reconciliation_metrics", "[]")
        try:
            metrics_list = json.loads(metrics_raw)
            metrics_str  = ", ".join(metrics_list)
        except Exception:
            metrics_str = metrics_raw

        survival = row.get("expected_survival_pct")
        if survival:
            survival = float(survival)

        return (
            row.get("source_fully_qualified_name"),
            row.get("layer_name"),
            row.get("layer_fully_qualified_name", ""),
            row.get("business_date_column", ""),
            survival,
            row.get("expected_latency_minutes"),
            metrics_str,
            "",
            row.get("layer_id")
        )

    return None, None, "", "", None, None, "", "", None


@callback(
    Output("layer-registry-alert", "children"),
    Output("layers-grid", "rowData", allow_duplicate=True),
    Input("save-layer-btn", "n_clicks"),
    State("layer-source-table-dropdown", "value"),
    State("layer-name-dropdown", "value"),
    State("layer-table-input", "value"),
    State("layer-date-col-input", "value"),
    State("layer-survival-input", "value"),
    State("layer-latency-input", "value"),
    State("layer-metrics-input", "value"),
    State("layer-registered-by-input", "value"),
    State("layer-edit-id", "data"),
    prevent_initial_call=True
)
def save_layer(
    n_clicks,
    source_fqn,
    layer_name,
    layer_table,
    date_col,
    survival_pct,
    latency,
    metrics_str,
    registered_by,
    edit_id
):
    if not n_clicks:
        return "", []

    # Validate required fields
    required = {
        "Source Table"   : source_fqn,
        "Layer"          : layer_name,
        "Layer Table"    : layer_table,
        "Date Column"    : date_col,
        "Latency"        : latency,
        "Metrics"        : metrics_str,
        "Registered By"  : registered_by
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        return error_alert(
            f"Please fill in: {', '.join(missing)}"
        ), []

    # Parse metrics from comma-separated to JSON array
    metrics_list = [m.strip() for m in metrics_str.split(",") if m.strip()]
    metrics_json = json.dumps(metrics_list)

    # Parse layer table into parts
    parts = layer_table.strip().split(".")
    if len(parts) != 3:
        return error_alert(
            "Layer Table must be fully qualified: catalog.schema.table"
        ), []

    layer_catalog = parts[0]
    layer_schema  = parts[1]
    layer_table_name = parts[2]

    survival = float(survival_pct) if survival_pct else 1.0

    try:
        if edit_id:
            # UPDATE existing layer
            query = update_layer(
                layer_id                   = edit_id,
                layer_fully_qualified_name = layer_table.strip(),
                business_date_column       = date_col.strip(),
                expected_survival_rate     = survival,
                expected_latency_minutes   = int(latency),
                reconciliation_metrics     = metrics_json
            )
            execute_write(*query)
            msg = f"Layer updated successfully."

        else:
            # INSERT new layer
            query = insert_layer(
                layer_id                   = str(uuid.uuid4()),
                source_fully_qualified_name= source_fqn,
                layer_name                 = layer_name,
                layer_fully_qualified_name = layer_table.strip(),
                layer_catalog              = layer_catalog,
                layer_schema               = layer_schema,
                layer_table                = layer_table_name,
                business_date_column       = date_col.strip(),
                expected_survival_rate     = survival,
                expected_latency_minutes   = int(latency),
                reconciliation_metrics     = metrics_json,
                registered_by              = registered_by.strip()
            )
            execute_write(*query)
            msg = (
                f"Layer {layer_name} registered for "
                f"{source_fqn.split('.')[-1]} successfully."
            )

        df = execute_query(get_all_layers())
        return success_alert(msg), df.to_dict("records")

    except Exception as e:
        logger.error(f"Failed to save layer: {str(e)}")
        return error_alert(f"Save failed: {str(e)}"), []


@callback(
    Output("layer-registry-alert", "children", allow_duplicate=True),
    Output("layers-grid", "rowData", allow_duplicate=True),
    Input("deactivate-layer-btn", "n_clicks"),
    Input("activate-layer-btn", "n_clicks"),
    State("layers-grid", "selectedRows"),
    prevent_initial_call=True
)
def toggle_layer_status(deactivate_clicks, activate_clicks, selected_rows):
    if not selected_rows:
        return "", []

    triggered = ctx.triggered_id
    row       = selected_rows[0]
    layer_id  = row.get("layer_id", "")
    is_active = triggered == "activate-layer-btn"

    try:
        execute_write(*toggle_layer_active(layer_id, is_active))
        df     = execute_query(get_all_layers())
        action = "activated" if is_active else "deactivated"
        return (
            success_alert(f"Layer {action} successfully."),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to toggle layer: {str(e)}")
        return error_alert(f"Toggle failed: {str(e)}"), []