# pages/table_registry.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import logging
import pandas as pd
from db.connection import execute_query, execute_write, validate_identifier
from db.queries import (
    get_all_registered_tables,
    get_table_by_fqn,
    insert_table_registry,
    toggle_table_active_status
)
from config.settings import (
    SOURCE_TYPES,
    INGESTION_PATTERNS,
    INGESTION_FREQUENCIES,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import (
    success_alert, error_alert,
    AG_GRID_DEFAULT_COL_DEF, AG_GRID_THEME,
)

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/table-registry", name="Table Registry")


# ── Layout ────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2("Table Registry", className="mt-4 mb-2"),
    html.P(
        "Register tables for validation. Only explicitly registered "
        "and active tables will be picked up by the validation agent.",
        className="text-muted mb-4"
    ),

    html.Div(id="table-registry-alert"),

    # ── Registered Tables ──
    dcc.Loading(id="table-reg-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(
            dbc.Row([
                dbc.Col(
                    html.H5("Registered Tables", className="mb-0"),
                    width="auto"
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh",
                        id="refresh-table-registry",
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
                id="table-registry-grid",
                columnDefs=[
                    {"field": "fully_qualified_name",            "headerName": "Table",          "flex": 2},
                    {"field": "source_type",                     "headerName": "Source Type",    "width": 110},
                    {"field": "ingestion_pattern",               "headerName": "Pattern",        "width": 120},
                    {"field": "ingestion_frequency",             "headerName": "Frequency",      "width": 110},
                    {"field": "partition_column",                "headerName": "Partition Col",  "width": 130},
                    {"field": "business_date_column",            "headerName": "Biz Date Col",   "width": 130},
                    {"field": "expected_arrival_window_minutes", "headerName": "Arrival (min)",  "width": 110},
                    {"field": "is_active",                       "headerName": "Active",         "width": 85},
                    {"field": "registered_by",                   "headerName": "Registered By",  "width": 120},
                    {"field": "registered_timestamp",            "headerName": "Registered",     "width": 160},
                ],
                rowData=[],
                defaultColDef=AG_GRID_DEFAULT_COL_DEF,
                className=AG_GRID_THEME,
                dashGridOptions={
                    "pagination": True,
                    "paginationPageSize": 10,
                    "animateRows": True,
                    "rowSelection": "single",
                    "rowHeight": 40,
                    "headerHeight": 42,
                    "domLayout": "autoHeight",
                },
            )
        ])
    ], className="mb-4"),
    ]),  # end Loading

    # ── Register New Table ────────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(html.H5("Register New Table", className="mb-0")),
        dbc.CardBody([

            dbc.Row([
                dbc.Col([
                    dbc.Label("Catalog", className="text-white"),
                    dcc.Dropdown(
                        id="catalog-dropdown",
                        placeholder="Loading...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Schema", className="text-white"),
                    dcc.Dropdown(
                        id="schema-dropdown",
                        placeholder="Select schema...",
                        clearable=False,
                        disabled=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Table", className="text-white"),
                    dcc.Dropdown(
                        id="table-dropdown",
                        placeholder="Select table...",
                        clearable=False,
                        disabled=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Source Type", className="text-white"),
                    dcc.Dropdown(
                        id="source-type-dropdown",
                        options=[
                            {"label": s, "value": s}
                            for s in SOURCE_TYPES
                        ],
                        placeholder="Select source type...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Ingestion Pattern", className="text-white"),
                    dcc.Dropdown(
                        id="ingestion-pattern-dropdown",
                        options=[
                            {"label": p, "value": p}
                            for p in INGESTION_PATTERNS
                        ],
                        placeholder="Select pattern...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Ingestion Frequency", className="text-white"),
                    dcc.Dropdown(
                        id="ingestion-frequency-dropdown",
                        options=[
                            {"label": f, "value": f}
                            for f in INGESTION_FREQUENCIES
                        ],
                        placeholder="Select frequency...",
                        clearable=False,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Partition Column", className="text-white"),
                    dcc.Dropdown(
                        id="partition-column-dropdown",
                        placeholder="Select partition column (optional)...",
                        clearable=True,
                        disabled=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label("Business Date Column", className="text-white"),
                    dcc.Dropdown(
                        id="business-date-column-dropdown",
                        placeholder="Select business date column...",
                        clearable=True,
                        disabled=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff"
                        }
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label(
                        "Expected Arrival Window (minutes)",
                        className="text-white"
                    ),
                    dbc.Input(
                        id="arrival-window-input",
                        type="number",
                        placeholder="e.g. 60",
                        min=1,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff",
                            "borderColor": "#555"
                        }
                    )
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Registered By", className="text-white"),
                    dbc.Input(
                        id="registered-by-input",
                        type="text",
                        placeholder="Your name or email...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff",
                            "borderColor": "#555"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label("Reason / Notes", className="text-white"),
                    dbc.Input(
                        id="change-reason-input",
                        type="text",
                        placeholder="Why is this table being registered...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color": "#ffffff",
                            "borderColor": "#555"
                        }
                    )
                ], md=6),
            ], className="mb-4"),

            dbc.Button(
                "Register Table",
                id="register-table-btn",
                color="primary",
                n_clicks=0
            )
        ])
    ], className="mb-4"),

    # ── Manage Selected Table ─────────────────────────────────────────────
    dbc.Card([
        dbc.CardHeader(html.H5("Manage Selected Table", className="mb-0")),
        dbc.CardBody([
            html.P(
                "Select a row in the table above to manage it.",
                className="text-muted",
                id="selected-table-label"
            ),
            dbc.ButtonGroup([
                dbc.Button(
                    "Deactivate Selected",
                    id="deactivate-table-btn",
                    color="warning",
                    n_clicks=0,
                    disabled=True
                ),
                dbc.Button(
                    "Activate Selected",
                    id="activate-table-btn",
                    color="success",
                    n_clicks=0,
                    disabled=True
                )
            ])
        ])
    ])

], fluid=True)


# ── Callbacks ─────────────────────────────────────────────────────────────

@callback(
    Output("table-registry-grid", "rowData"),
    Input("refresh-table-registry", "n_clicks"),
    prevent_initial_call=False
)
def load_registered_tables(n_clicks):
    try:
        df = execute_query(get_all_registered_tables())
        return df.to_dict("records")
    except Exception as e:
        logger.error(f"Failed to load registered tables: {str(e)}")
        return []


@callback(
    Output("catalog-dropdown", "options"),
    Output("catalog-dropdown", "value"),
    Input("catalog-dropdown", "id")
)
def load_catalogs(_):
    """
    Hardcoded to TARGET_CATALOG for PoC.
    SHOW CATALOGS returns 63 catalogs across the workspace
    but we only want admins registering tables in learning_dev.
    """
    options = [{"label": TARGET_CATALOG, "value": TARGET_CATALOG}]
    return options, TARGET_CATALOG


@callback(
    Output("schema-dropdown", "options"),
    Output("schema-dropdown", "disabled"),
    Output("schema-dropdown", "value"),
    Input("catalog-dropdown", "value")
)
def load_schemas(catalog):
    if not catalog:
        return [], True, None

    try:
        validate_identifier(catalog)
        df = execute_query(f"SHOW SCHEMAS IN {catalog}")

        # Confirmed column name from debug: "databaseName"
        schemas = df["databaseName"].tolist()
        schemas = [str(s) for s in schemas if s is not None]

        # Filter system schemas
        system_schemas = {"information_schema", "default"}
        schemas = [s for s in schemas if s not in system_schemas]

        logger.info(f"Schemas loaded: {schemas}")

        options = [{"label": s, "value": s} for s in schemas]

        default_value = (
            TARGET_SCHEMA
            if TARGET_SCHEMA in schemas
            else None
        )

        return options, False, default_value

    except Exception as e:
        logger.error(f"Failed to load schemas: {str(e)}")
        return [], True, None


@callback(
    Output("table-dropdown", "options"),
    Output("table-dropdown", "disabled"),
    Input("schema-dropdown", "value"),
    State("catalog-dropdown", "value")
)
def load_tables(schema, catalog):
    if not schema or not catalog:
        return [], True

    try:
        validate_identifier(catalog)
        validate_identifier(schema)
        df = execute_query(f"SHOW TABLES IN {catalog}.{schema}")

        # Confirmed column name from debug: "tableName"
        tables = df["tableName"].tolist()
        tables = [str(t) for t in tables if t is not None]

        # Hide metadata tables
        metadata_tables = {
            "uc1_table_registry_b",
            "uc1_column_registry_b",
            "uc1_column_validation_registry_b",
            "uc1_table_validation_registry_b",
            "uc1_baseline_metrics_b",
            "uc1_validation_run_b",
            "uc1_validation_results_b"
        }
        tables = [t for t in tables if t not in metadata_tables]

        logger.info(f"Tables loaded: {tables}")

        return [{"label": t, "value": t} for t in tables], False

    except Exception as e:
        logger.error(f"Failed to load tables: {str(e)}")
        return [], True


@callback(
    Output("partition-column-dropdown", "options"),
    Output("partition-column-dropdown", "disabled"),
    Output("business-date-column-dropdown", "options"),   # ← CORRECT: "dropdown"
    Output("business-date-column-dropdown", "disabled"),  # ← CORRECT: "dropdown"
    Input("table-dropdown", "value"),
    State("catalog-dropdown", "value"),
    State("schema-dropdown", "value")
)
def load_table_columns(table, catalog, schema):
    logger.info(
        f"load_table_columns fired: "
        f"table={table}, catalog={catalog}, schema={schema}"
    )

    if not table or not catalog or not schema:
        return [], True, [], True

    try:
        fqn = f"{catalog}.{schema}.{table}"
        validate_identifier(fqn)
        df  = execute_query(f"DESCRIBE TABLE {fqn}")

        logger.info(f"DESCRIBE result: {df.columns.tolist()}, {len(df)} rows")

        col_field = (
            "col_name"
            if "col_name" in df.columns
            else df.columns[0]
        )

        columns = df[col_field].tolist()
        columns = [
            str(c) for c in columns
            if c and
               str(c).strip() != "" and
               not str(c).startswith("#") and
               str(c) != "None"
        ]

        logger.info(f"Columns loaded: {columns}")

        options = [{"label": c, "value": c} for c in columns]
        return options, False, options, False

    except Exception as e:
        logger.error(f"load_table_columns FAILED: {str(e)}")
        return [], True, [], True


@callback(
    Output("table-registry-alert", "children"),
    Output("table-registry-grid", "rowData", allow_duplicate=True),
    Input("register-table-btn", "n_clicks"),
    State("catalog-dropdown", "value"),
    State("schema-dropdown", "value"),
    State("table-dropdown", "value"),
    State("source-type-dropdown", "value"),
    State("ingestion-pattern-dropdown", "value"),
    State("ingestion-frequency-dropdown", "value"),
    State("partition-column-dropdown", "value"),
    State("business-date-column-dropdown", "value"),
    State("arrival-window-input", "value"),
    State("registered-by-input", "value"),
    State("change-reason-input", "value"),
    prevent_initial_call=True
)
def register_table(
    n_clicks, catalog, schema, table,
    source_type, ingestion_pattern, ingestion_frequency,
    partition_column, business_date_column,
    arrival_window, registered_by, change_reason
):
    if not n_clicks:
        return "", []

    required = {
        "Catalog"            : catalog,
        "Schema"             : schema,
        "Table"              : table,
        "Source Type"        : source_type,
        "Ingestion Pattern"  : ingestion_pattern,
        "Ingestion Frequency": ingestion_frequency,
        "Arrival Window"     : arrival_window,
        "Registered By"      : registered_by
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        return error_alert(
            f"Please fill in: {', '.join(missing)}"
        ), []

    fqn = f"{catalog}.{schema}.{table}"

    try:
        existing = execute_query(*get_table_by_fqn(fqn))
        if not existing.empty:
            return error_alert(
                f"Table {fqn} is already registered."
            ), []
    except Exception:
        pass

    try:
        query = insert_table_registry(
            table_id=str(uuid.uuid4()),
            table_catalog=catalog,
            table_schema=schema,
            table_name=table,
            fully_qualified_name=fqn,
            source_type=source_type,
            ingestion_pattern=ingestion_pattern,
            ingestion_frequency=ingestion_frequency,
            partition_column=partition_column or "",
            business_date_column=business_date_column or "",
            expected_arrival_window_minutes=int(arrival_window),
            registered_by=registered_by,
            change_reason=change_reason or ""
        )
        execute_write(*query)
        df = execute_query(get_all_registered_tables())
        return (
            success_alert(f"Table {fqn} registered successfully."),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to register table: {str(e)}")
        return error_alert(f"Registration failed: {str(e)}"), []


@callback(
    Output("selected-table-label", "children"),
    Output("deactivate-table-btn", "disabled"),
    Output("activate-table-btn", "disabled"),
    Input("table-registry-grid", "selectedRows"),
)
def update_selected_label(selected_rows):
    if not selected_rows:
        return "Select a row in the table above to manage it.", True, True
    row         = selected_rows[0]
    fqn         = row.get("fully_qualified_name", "")
    is_active   = row.get("is_active", True)
    status_text = "Active" if is_active else "Inactive"
    return (
        f"Selected: {fqn} — Current status: {status_text}",
        False,
        False
    )


@callback(
    Output("table-registry-alert", "children", allow_duplicate=True),
    Output("table-registry-grid", "rowData", allow_duplicate=True),
    Input("deactivate-table-btn", "n_clicks"),
    Input("activate-table-btn", "n_clicks"),
    State("table-registry-grid", "selectedRows"),
    prevent_initial_call=True
)
def toggle_table_status(
    deactivate_clicks, activate_clicks,
    selected_rows
):
    if not selected_rows:
        return "", []

    triggered = ctx.triggered_id
    row       = selected_rows[0]
    fqn       = row.get("fully_qualified_name", "")
    is_active = triggered == "activate-table-btn"

    try:
        execute_write(*toggle_table_active_status(fqn, is_active))
        df     = execute_query(get_all_registered_tables())
        action = "activated" if is_active else "deactivated"
        return (
            success_alert(f"Table {fqn} {action} successfully."),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to toggle status: {str(e)}")
        return error_alert(f"Status update failed: {str(e)}"), []