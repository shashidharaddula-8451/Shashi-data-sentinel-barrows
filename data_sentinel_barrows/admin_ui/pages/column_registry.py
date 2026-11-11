# pages/column_registry.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
import logging
from db.connection import execute_query, execute_write, execute_many, validate_identifier
from db.queries import (
    get_all_registered_tables,
    get_columns_for_table,
    insert_column_registry
)
from components.alerts import success_alert, error_alert, ag_grid_props
from components.nested_columns import explode_describe_rows

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/column-registry", name="Column Registry")

layout = dbc.Container([

    html.H2("Column Registry", className="mt-4 mb-2"),
    html.P(
        "Select which columns of a registered table should be enrolled for validation. "
        "Columns are fetched live from Unity Catalog.",
        className="text-muted mb-4"
    ),

    html.Div(id="column-registry-alert"),

    # ── Step 1: Select Table ──
    dbc.Card([
        dbc.CardHeader(html.H5("Step 1: Select Registered Table", className="mb-0")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Registered Table"),
                    dcc.Dropdown(
                        id="col-reg-table-dropdown",
                        placeholder="Select a registered table...",
                        clearable=False
                    )
                ], md=8),
                dbc.Col([
                    dbc.Label("\u00a0"),
                    dbc.Button(
                        "Load Columns",
                        id="load-columns-btn",
                        color="primary",
                        className="d-block w-100"
                    )
                ], md=4)
            ])
        ])
    ], className="mb-4"),

    # ── Enrolled Columns ──
    dcc.Loading(id="enrolled-cols-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(html.H5("Currently Enrolled Columns", className="mb-0")),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="enrolled-columns-grid",
                    col_defs=[
                        {"field": "column_name",       "headerName": "Column Name",   "flex": 2, "minWidth": 220},
                        {"field": "expected_data_type","headerName": "Expected Type", "minWidth": 150},
                        {"field": "is_nullable",       "headerName": "Nullable",      "width": 100},
                        {"field": "is_business_key",   "headerName": "Business Key",  "width": 110},
                        {"field": "is_active",         "headerName": "Active",        "width": 90},
                        {"field": "created_by",        "headerName": "Enrolled By",   "flex": 1, "minWidth": 220},
                        {"field": "created_timestamp", "headerName": "Enrolled At",   "minWidth": 175},
                    ],
                    page_size=10,
                    selection="multiple",
                )
            )
        ])
    ], className="mb-4"),
    ]),  # end Loading

    # ── Enroll from Unity Catalog ──
    dcc.Loading(id="uc-cols-loading", type="circle", color="#00c851", children=[
    dbc.Card([
        dbc.CardHeader(
            html.H5("Step 2: Enroll Columns from Unity Catalog", className="mb-0")
        ),
        dbc.CardBody([
            html.P(
                "Columns below are fetched live from the table schema in Unity Catalog. "
                "STRUCT / ARRAY columns are exploded into their nested leaf fields "
                "(e.g. touchpoint.id, accounts[].brands[].name) so each field can be "
                "enrolled and validated individually. "
                "Select the columns you want to enroll for validation.",
                className="text-muted"
            ),
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="uc-columns-grid",
                    col_defs=[
                        {"field": "col_name",      "headerName": "Column Name", "flex": 2, "minWidth": 260},
                        {"field": "data_type",     "headerName": "Data Type",   "minWidth": 150},
                        {"field": "field_level",   "headerName": "Level",       "width": 110},
                        {"field": "parent_column", "headerName": "Parent",      "minWidth": 140},
                        {"field": "comment",       "headerName": "Comment",     "flex": 3, "minWidth": 240},
                    ],
                    page_size=15,
                    selection="multiple",
                )
            ),

            html.Hr(),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Enrolled By"),
                    dbc.Input(
                        id="col-enrolled-by-input",
                        type="text",
                        placeholder="Your name or email..."
                    )
                ], md=6)
            ], className="mb-3"),

            dbc.Button(
                "Enroll Selected Columns",
                id="enroll-columns-btn",
                color="success",
                n_clicks=0,
                className="mt-2"
            )
        ])
    ])
    ]),  # end Loading

], fluid=True)


# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

@callback(
    Output("col-reg-table-dropdown", "options"),
    Input("col-reg-table-dropdown", "id")
)
def load_table_options(_):
    try:
        df = execute_query(get_all_registered_tables())

        if df.empty:
            return []

        # Only show active tables
        active = df[df["is_active"] == True]

        options = [
            {
                "label": row["fully_qualified_name"],
                "value": row["fully_qualified_name"]
            }
            for _, row in active.iterrows()
        ]

        logger.info(f"Active tables for column registry: {len(options)}")
        return options

    except Exception as e:
        logger.error(f"Failed to load table options: {str(e)}")
        return []


@callback(
    Output("enrolled-columns-grid", "rowData"),
    Output("uc-columns-grid", "rowData"),
    Input("load-columns-btn", "n_clicks"),
    State("col-reg-table-dropdown", "value"),
    prevent_initial_call=True
)
def load_column_data(n_clicks, fqn):
    if not fqn:
        return [], []

    enrolled = []
    uc_columns = []

    try:
        enrolled_df = execute_query(*get_columns_for_table(fqn))
        if not enrolled_df.empty:
            enrolled = enrolled_df.to_dict("records")
    except Exception as e:
        logger.error(f"Failed to load enrolled columns: {str(e)}")

    try:
        validate_identifier(fqn)
        uc_df = execute_query(f"DESCRIBE TABLE {fqn}")
        col_field = "col_name" if "col_name" in uc_df.columns else uc_df.columns[0]
        # DESCRIBE output: stop at the first '#' section (partition info etc.)
        # so partition columns are not listed twice.
        top_rows = []
        for rec in uc_df.to_dict("records"):
            name = str(rec.get(col_field, "")).strip()
            if name.startswith("#"):
                break
            if name:
                top_rows.append(rec)
        uc_columns = explode_describe_rows(top_rows, name_key=col_field)
    except Exception as e:
        logger.error(f"Failed to load UC columns: {str(e)}")

    return enrolled, uc_columns


@callback(
    Output("column-registry-alert", "children"),
    Output("enrolled-columns-grid", "rowData", allow_duplicate=True),
    Input("enroll-columns-btn", "n_clicks"),
    State("uc-columns-grid", "selectedRows"),
    State("col-reg-table-dropdown", "value"),
    State("col-enrolled-by-input", "value"),
    prevent_initial_call=True
)
def enroll_columns(n_clicks, selected_rows, fqn, enrolled_by):
    if not n_clicks:
        return "", []

    if not fqn:
        return error_alert("Please select a table first."), []

    if not selected_rows:
        return error_alert("Please select at least one column to enroll."), []

    if not enrolled_by:
        return error_alert("Please enter your name or email in the Enrolled By field."), []

    queries = []
    enrolled_names = []

    for row in selected_rows:
        col_name = row.get("col_name", "")
        col_type = row.get("data_type", "STRING")

        if not col_name:
            continue

        query = insert_column_registry(
            column_id=str(uuid.uuid4()),
            fully_qualified_name=fqn,
            column_name=col_name,
            expected_data_type=col_type,
            is_nullable=True,
            is_business_key=False,
            created_by=enrolled_by
        )
        queries.append(query)
        enrolled_names.append(col_name)

    if not queries:
        return error_alert("No valid columns selected."), []

    try:
        execute_many(queries)
        df = execute_query(*get_columns_for_table(fqn))
        return (
            success_alert(
                f"Successfully enrolled {len(enrolled_names)} column(s): "
                f"{', '.join(enrolled_names)}"
            ),
            df.to_dict("records")
        )
    except Exception as e:
        logger.error(f"Failed to enroll columns: {str(e)}")
        return error_alert(f"Enrollment failed: {str(e)}"), []