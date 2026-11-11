# pages/validations.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import json
import logging
from db.connection import execute_query, execute_write
from db.queries import (
    get_all_registered_tables,
    get_columns_for_table,
    get_column_validations_for_table,
    get_table_validations,
    insert_column_validation,
    insert_table_validation
)
from config.settings import (
    TABLE_LEVEL_VALIDATIONS,
    COLUMN_LEVEL_VALIDATIONS,
    THRESHOLD_UNITS
)
from components.alerts import success_alert, error_alert, ag_grid_props

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/validations", name="Validations")

layout = dbc.Container([

    html.H2("Validation Configuration", className="mt-4 mb-2"),
    html.P(
        "Assign and configure validations for registered tables and their columns.",
        className="text-muted mb-4"
    ),

    html.Div(id="validation-alert"),

    # ── Select Table ──
    dbc.Card([
        dbc.CardHeader(html.H5("Select Table", className="mb-0")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dcc.Dropdown(
                        id="val-table-dropdown",
                        placeholder="Select a registered table...",
                        clearable=False
                    )
                ], md=8),
                dbc.Col([
                    dbc.Button(
                        "Load Validations",
                        id="load-validations-btn",
                        color="primary",
                        className="w-100"
                    )
                ], md=4)
            ])
        ])
    ], className="mb-4"),

    # ── Tabs ──
    dbc.Tabs([

        # ── Table-Level Tab ──
        dbc.Tab(
            label="Table-Level Validations",
            tab_id="tab-table-val",
            children=[
                dcc.Loading(id="table-val-loading", type="circle", color="#00c851", children=[
                dbc.Card([
                    dbc.CardBody([

                        html.H6("Existing Table Validations", className="mb-3"),
                        dag.AgGrid(
                            **ag_grid_props(
                                grid_id="table-validations-grid",
                                col_defs=[
                                    {"field": "validation_name",   "headerName": "Validation",  "flex": 2, "minWidth": 200},
                                    {"field": "is_active",         "headerName": "Active",      "width": 90},
                                    {"field": "warning_threshold", "headerName": "Warning",     "width": 110},
                                    {"field": "critical_threshold","headerName": "Critical",    "width": 110},
                                    {"field": "threshold_unit",    "headerName": "Unit",     "minWidth": 150},
                                    {"field": "custom_parameters", "headerName": "Parameters",  "flex": 2, "minWidth": 220},
                                    {"field": "created_by",        "headerName": "Created By",  "flex": 1, "minWidth": 220},
                                ],
                                page_size=10,
                            )
                        ),

                        html.Hr(),
                        html.H6("Add Table-Level Validation", className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Validation"),
                                dcc.Dropdown(
                                    id="table-val-name-dropdown",
                                    options=[
                                        {"label": v, "value": v}
                                        for v in TABLE_LEVEL_VALIDATIONS
                                    ],
                                    placeholder="Select validation...",
                                    clearable=False
                                )
                            ], md=4),
                            dbc.Col([
                                dbc.Label("Warning Threshold"),
                                dbc.Input(
                                    id="table-val-warning-input",
                                    type="number",
                                    placeholder="e.g. 20"
                                )
                            ], md=2),
                            dbc.Col([
                                dbc.Label("Critical Threshold"),
                                dbc.Input(
                                    id="table-val-critical-input",
                                    type="number",
                                    placeholder="e.g. 40"
                                )
                            ], md=2),
                            dbc.Col([
                                dbc.Label("Threshold Unit"),
                                dcc.Dropdown(
                                    id="table-val-unit-dropdown",
                                    options=[
                                        {"label": u, "value": u}
                                        for u in THRESHOLD_UNITS
                                    ],
                                    placeholder="Select unit...",
                                    clearable=False
                                )
                            ], md=4),
                        ], className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Custom Parameters (JSON)"),
                                dbc.Textarea(
                                    id="table-val-params-input",
                                    placeholder='e.g. {"baseline_window_days": 30}',
                                    rows=3
                                )
                            ], md=8),
                            dbc.Col([
                                dbc.Label("Created By"),
                                dbc.Input(
                                    id="table-val-created-by-input",
                                    type="text",
                                    placeholder="Your name or email..."
                                )
                            ], md=4),
                        ], className="mb-3"),

                        dbc.Button(
                            "Add Table Validation",
                            id="add-table-val-btn",
                            color="success",
                            n_clicks=0
                        )
                    ])
                ], className="mt-3")
                ]),  # end Loading
            ]
        ),

        # ── Column-Level Tab ──
        dbc.Tab(
            label="Column-Level Validations",
            tab_id="tab-col-val",
            children=[
                dcc.Loading(id="col-val-loading", type="circle", color="#00c851", children=[
                dbc.Card([
                    dbc.CardBody([

                        html.H6("Existing Column Validations", className="mb-3"),
                        dag.AgGrid(
                            **ag_grid_props(
                                grid_id="column-validations-grid",
                                col_defs=[
                                    {"field": "column_name",       "headerName": "Column",      "flex": 1, "minWidth": 220},
                                    {"field": "validation_name",   "headerName": "Validation",  "flex": 2, "minWidth": 200},
                                    {"field": "is_active",         "headerName": "Active",      "width": 90},
                                    {"field": "warning_threshold", "headerName": "Warning",     "width": 110},
                                    {"field": "critical_threshold","headerName": "Critical",    "width": 110},
                                    {"field": "threshold_unit",    "headerName": "Unit",     "minWidth": 150},
                                    {"field": "custom_parameters", "headerName": "Parameters",  "flex": 2, "minWidth": 220},
                                    {"field": "created_by",        "headerName": "Created By",  "flex": 1, "minWidth": 220},
                                ],
                                page_size=10,
                            )
                        ),

                        html.Hr(),
                        html.H6("Add Column-Level Validation", className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Column"),
                                dcc.Dropdown(
                                    id="col-val-column-dropdown",
                                    placeholder="Select enrolled column...",
                                    clearable=False
                                )
                            ], md=4),
                            dbc.Col([
                                dbc.Label("Validation"),
                                dcc.Dropdown(
                                    id="col-val-name-dropdown",
                                    options=[
                                        {"label": v, "value": v}
                                        for v in COLUMN_LEVEL_VALIDATIONS
                                    ],
                                    placeholder="Select validation...",
                                    clearable=False
                                )
                            ], md=4),
                            dbc.Col([
                                dbc.Label("Threshold Unit"),
                                dcc.Dropdown(
                                    id="col-val-unit-dropdown",
                                    options=[
                                        {"label": u, "value": u}
                                        for u in THRESHOLD_UNITS
                                    ],
                                    placeholder="Select unit...",
                                    clearable=False
                                )
                            ], md=4),
                        ], className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Warning Threshold"),
                                dbc.Input(
                                    id="col-val-warning-input",
                                    type="number",
                                    placeholder="e.g. 20"
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label("Critical Threshold"),
                                dbc.Input(
                                    id="col-val-critical-input",
                                    type="number",
                                    placeholder="e.g. 40"
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label("Created By"),
                                dbc.Input(
                                    id="col-val-created-by-input",
                                    type="text",
                                    placeholder="Your name or email..."
                                )
                            ], md=6),
                        ], className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Custom Parameters (JSON)"),
                                dbc.Textarea(
                                    id="col-val-params-input",
                                    placeholder='e.g. {"min_value": 0, "max_value": 10000}',
                                    rows=3
                                )
                            ], md=12),
                        ], className="mb-3"),

                        dbc.Button(
                            "Add Column Validation",
                            id="add-col-val-btn",
                            color="success",
                            n_clicks=0
                        )
                    ])
                ], className="mt-3")
                ]),  # end Loading
            ]
        )

    ], id="validation-tabs", active_tab="tab-table-val"),

], fluid=True)


# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

@callback(
    Output("val-table-dropdown", "options"),
    Input("val-table-dropdown", "id")
)
def load_val_table_options(_):
    try:
        df = execute_query(get_all_registered_tables())

        if df.empty:
            return []

        active = df[df["is_active"] == True]

        options = [
            {
                "label": row["fully_qualified_name"],
                "value": row["fully_qualified_name"]
            }
            for _, row in active.iterrows()
        ]

        logger.info(f"Active tables for validations: {len(options)}")
        return options

    except Exception as e:
        logger.error(f"Failed to load table options: {str(e)}")
        return []


@callback(
    Output("table-validations-grid", "rowData"),
    Output("column-validations-grid", "rowData"),
    Output("col-val-column-dropdown", "options"),
    Input("load-validations-btn", "n_clicks"),
    State("val-table-dropdown", "value"),
    prevent_initial_call=True
)
def load_validation_data(n_clicks, fqn):
    if not fqn:
        return [], [], []

    table_vals = []
    col_vals = []
    col_options = []

    try:
        df = execute_query(*get_table_validations(fqn))
        if not df.empty:
            table_vals = df.to_dict("records")
    except Exception as e:
        logger.error(f"Failed to load table validations: {str(e)}")

    try:
        df = execute_query(*get_column_validations_for_table(fqn))
        if not df.empty:
            col_vals = df.to_dict("records")
    except Exception as e:
        logger.error(f"Failed to load column validations: {str(e)}")

    try:
        df = execute_query(*get_columns_for_table(fqn))
        active = df[df["is_active"] == True]
        col_options = [
            {"label": r["column_name"], "value": r["column_name"]}
            for _, r in active.iterrows()
        ]
    except Exception as e:
        logger.error(f"Failed to load column options: {str(e)}")

    return table_vals, col_vals, col_options


@callback(
    Output("validation-alert", "children"),
    Output("table-validations-grid", "rowData", allow_duplicate=True),
    Input("add-table-val-btn", "n_clicks"),
    State("val-table-dropdown", "value"),
    State("table-val-name-dropdown", "value"),
    State("table-val-warning-input", "value"),
    State("table-val-critical-input", "value"),
    State("table-val-unit-dropdown", "value"),
    State("table-val-params-input", "value"),
    State("table-val-created-by-input", "value"),
    prevent_initial_call=True
)
def add_table_validation(
    n_clicks, fqn, val_name,
    warning, critical, unit, params, created_by
):
    if not n_clicks:
        return "", []

    if not all([fqn, val_name, warning is not None, critical is not None, unit, created_by]):
        return error_alert(
            "Please fill in all required fields: "
            "Table, Validation, Warning Threshold, Critical Threshold, Unit, Created By."
        ), []

    if params:
        try:
            json.loads(params)
        except json.JSONDecodeError:
            return error_alert(
                "Custom Parameters must be valid JSON. "
                'Example: {"baseline_window_days": 30}'
            ), []

    try:
        query = insert_table_validation(
            table_validation_id=str(uuid.uuid4()),
            fully_qualified_name=fqn,
            validation_name=val_name,
            warning_threshold=float(warning),
            critical_threshold=float(critical),
            threshold_unit=unit,
            custom_parameters=params or "",
            created_by=created_by
        )
        execute_write(*query)
        df = execute_query(*get_table_validations(fqn))
        return (
            success_alert(f"Table validation '{val_name}' added successfully."),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to add table validation: {str(e)}")
        return error_alert(f"Failed to add validation: {str(e)}"), []


@callback(
    Output("validation-alert", "children", allow_duplicate=True),
    Output("column-validations-grid", "rowData", allow_duplicate=True),
    Input("add-col-val-btn", "n_clicks"),
    State("val-table-dropdown", "value"),
    State("col-val-column-dropdown", "value"),
    State("col-val-name-dropdown", "value"),
    State("col-val-warning-input", "value"),
    State("col-val-critical-input", "value"),
    State("col-val-unit-dropdown", "value"),
    State("col-val-params-input", "value"),
    State("col-val-created-by-input", "value"),
    prevent_initial_call=True
)
def add_column_validation(
    n_clicks, fqn, col_name, val_name,
    warning, critical, unit, params, created_by
):
    if not n_clicks:
        return "", []

    if not all([fqn, col_name, val_name, warning is not None, critical is not None, unit, created_by]):
        return error_alert(
            "Please fill in all required fields: "
            "Table, Column, Validation, Warning Threshold, Critical Threshold, Unit, Created By."
        ), []

    if params:
        try:
            json.loads(params)
        except json.JSONDecodeError:
            return error_alert(
                "Custom Parameters must be valid JSON. "
                'Example: {"min_value": 0, "max_value": 10000}'
            ), []

    try:
        query = insert_column_validation(
            column_validation_id=str(uuid.uuid4()),
            fully_qualified_name=fqn,
            column_name=col_name,
            validation_name=val_name,
            warning_threshold=float(warning),
            critical_threshold=float(critical),
            threshold_unit=unit,
            custom_parameters=params or "",
            created_by=created_by
        )
        execute_write(*query)
        df = execute_query(*get_column_validations_for_table(fqn))
        return (
            success_alert(
                f"Column validation '{val_name}' added for column '{col_name}'."
            ),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to add column validation: {str(e)}")
        return error_alert(f"Failed to add validation: {str(e)}"), []