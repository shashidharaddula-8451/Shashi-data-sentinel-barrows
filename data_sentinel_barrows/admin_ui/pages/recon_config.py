# pages/recon_config.py

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import uuid
import json
import logging
from db.connection import execute_query, execute_write
from db.queries import (
    update_layer_check_config,
    get_hierarchy_view,
    get_all_metric_configs,
    insert_metric_config,
    update_metric_config,
    toggle_metric_config_active,
    get_all_registered_tables,
    TARGET_CATALOG,
    TARGET_SCHEMA
)
from components.alerts import success_alert, error_alert, info_alert

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/recon-config",
    name="Reconciliation Config"
)

# ── Constants ──────────────────────────────────────────────────────────────

CHECK_TYPE_COLORS = {
    "ROW_COUNT" : "#0d6efd",   # blue
    "AGGREGATE" : "#ffc107",   # yellow
    "FRESHNESS" : "#198754"    # green
}

CHECK_TYPE_ICONS = {
    "ROW_COUNT" : "📊",
    "AGGREGATE" : "💰",
    "FRESHNESS" : "⏱️"
}

UNIT_OPTIONS = [
    {"label": "PERCENTAGE", "value": "PERCENTAGE"},
    {"label": "COUNT",      "value": "COUNT"},
    {"label": "MINUTES",    "value": "MINUTES"},
]

METRIC_SUGGESTIONS = {
    ("BRONZE", "SILVER", "ROW_COUNT") : ["row_count_survival_rate"],
    ("SILVER", "GOLD",   "ROW_COUNT") : ["gold_row_count"],
    ("BRONZE", "SILVER", "AGGREGATE") : [
        "net_amount", "gross_amount", "discount_amount",
        "quantity_change", "total_cost_impact"
    ],
    ("SILVER", "GOLD",   "AGGREGATE") : [
        "net_amount_vs_total_net_amount",
        "gross_amount_vs_total_gross_amount",
        "discount_amount_vs_total_discount_amount",
        "quantity_change_vs_net_quantity_change",
        "total_cost_impact_vs_total_cost_impact"
    ],
    ("BRONZE", "SILVER", "FRESHNESS") : ["silver_data_presence"],
    ("SILVER", "GOLD",   "FRESHNESS") : ["gold_data_presence"],
}

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2(
        "Reconciliation Agent — Configuration",
        className="mt-4 mb-2"
    ),
    html.P(
        "Configure check policies and specific metrics for "
        "cross-layer reconciliation. "
        "The hierarchy shows: Source Table → Layer Transition → "
        "Check Type → Individual Metrics.",
        className="text-muted mb-4"
    ),

    html.Div(id="recon-config-alert"),

    # ── Table selector ─────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Source Table", className="text-white"),
                    dcc.Dropdown(
                        id="recon-config-table-filter",
                        placeholder="Select source table...",
                        clearable=True,
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff"
                        }
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "Refresh",
                        id="refresh-recon-config-btn",
                        color="secondary",
                        className="d-block w-100"
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "➕ Add Metric",
                        id="show-add-metric-btn",
                        color="primary",
                        outline=True,
                        className="d-block w-100"
                    )
                ], md=3),
            ])
        ])
    ], className="mb-4"),

    # ── Hierarchy View ─────────────────────────────────────────────────────
    html.Div(id="recon-config-hierarchy"),

    # ── Edit Check Policy Panel ────────────────────────────────────────────
    dbc.Collapse(
        dbc.Card([
            dbc.CardHeader(
                html.H5(
                    "✏️ Edit Check Policy",
                    className="mb-0",
                    id="edit-check-policy-header"
                )
            ),
            dbc.CardBody([
                html.P(
                    "These are the DEFAULT thresholds for all metrics "
                    "under this check type and layer transition. "
                    "Individual metrics can override these values.",
                    className="text-muted small mb-3"
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Default Warning Threshold", className="text-white"),
                        dbc.Input(
                            id="policy-warn-input",
                            type="number",
                            min=0,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label("Default Critical Threshold", className="text-white"),
                        dbc.Input(
                            id="policy-crit-input",
                            type="number",
                            min=0,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label("Unit", className="text-white"),
                        dcc.Dropdown(
                            id="policy-unit-dropdown",
                            options=UNIT_OPTIONS,
                            clearable=False,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label("Updated By", className="text-white"),
                        dbc.Input(
                            id="policy-updated-by-input",
                            type="text",
                            placeholder="Your name...",
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
                        dbc.Label("Description / Rationale", className="text-white"),
                        dbc.Textarea(
                            id="policy-description-input",
                            rows=2,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=12)
                ], className="mb-3"),
                dbc.ButtonGroup([
                    dbc.Button(
                        "Save Policy",
                        id="save-policy-btn",
                        color="primary",
                        n_clicks=0
                    ),
                    dbc.Button(
                        "Cancel",
                        id="cancel-policy-btn",
                        color="secondary",
                        n_clicks=0
                    )
                ])
            ])
        ], className="mb-4"),
        id="edit-check-policy-collapse",
        is_open=False
    ),

    # ── Edit Metric Panel ──────────────────────────────────────────────────
    dbc.Collapse(
        dbc.Card([
            dbc.CardHeader(
                html.H5(
                    "✏️ Add / Edit Metric",
                    className="mb-0",
                    id="edit-metric-panel-header"
                )
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Source Table", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-table-dropdown",
                            placeholder="Select source table...",
                            clearable=False,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=4),
                    dbc.Col([
                        dbc.Label("From Layer", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-from-dropdown",
                            options=[
                                {"label": "BRONZE", "value": "BRONZE"},
                                {"label": "SILVER", "value": "SILVER"},
                            ],
                            clearable=False,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=2),
                    dbc.Col([
                        dbc.Label("To Layer", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-to-dropdown",
                            options=[
                                {"label": "SILVER", "value": "SILVER"},
                                {"label": "GOLD",   "value": "GOLD"},
                            ],
                            clearable=False,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=2),
                    dbc.Col([
                        dbc.Label("Check Type", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-check-dropdown",
                            options=[
                                {"label": "ROW_COUNT", "value": "ROW_COUNT"},
                                {"label": "AGGREGATE", "value": "AGGREGATE"},
                                {"label": "FRESHNESS", "value": "FRESHNESS"},
                            ],
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
                        dbc.Label("Metric Name", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-name-dropdown",
                            placeholder="Select or type metric...",
                            clearable=True,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=4),
                    dbc.Col([
                        dbc.Label("Source Column", className="text-white"),
                        dbc.Input(
                            id="metric-panel-src-col-input",
                            type="text",
                            placeholder="e.g. net_amount",
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=4),
                    dbc.Col([
                        dbc.Label("Target Column", className="text-white"),
                        dbc.Input(
                            id="metric-panel-tgt-col-input",
                            type="text",
                            placeholder="e.g. total_net_amount",
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=4),
                ], className="mb-3"),

                dbc.Alert(
                    id="metric-panel-default-hint",
                    color="info",
                    className="small mb-3"
                ),

                dbc.Row([
                    dbc.Col([
                        dbc.Label(
                            "Override Warning Threshold",
                            className="text-white"
                        ),
                        dbc.Input(
                            id="metric-panel-warn-input",
                            type="number",
                            min=0,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        ),
                        dbc.FormText(
                            "Leave blank to use the check policy default.",
                            className="text-muted"
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label(
                            "Override Critical Threshold",
                            className="text-white"
                        ),
                        dbc.Input(
                            id="metric-panel-crit-input",
                            type="number",
                            min=0,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        ),
                        dbc.FormText(
                            "Leave blank to use the check policy default.",
                            className="text-muted"
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label("Unit", className="text-white"),
                        dcc.Dropdown(
                            id="metric-panel-unit-dropdown",
                            options=UNIT_OPTIONS,
                            value="PERCENTAGE",
                            clearable=False,
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff"
                            }
                        )
                    ], md=3),
                    dbc.Col([
                        dbc.Label("Updated By", className="text-white"),
                        dbc.Input(
                            id="metric-panel-updated-by-input",
                            type="text",
                            placeholder="Your name...",
                            style={
                                "backgroundColor": "#2b2b2b",
                                "color"          : "#ffffff",
                                "borderColor"    : "#555"
                            }
                        )
                    ], md=3),
                ], className="mb-4"),

                dcc.Store(id="metric-panel-edit-id", data=None),

                dbc.ButtonGroup([
                    dbc.Button(
                        "Save Metric",
                        id="save-metric-panel-btn",
                        color="primary",
                        n_clicks=0
                    ),
                    dbc.Button(
                        "Cancel",
                        id="cancel-metric-panel-btn",
                        color="secondary",
                        n_clicks=0
                    )
                ])
            ])
        ], className="mb-4"),
        id="edit-metric-panel-collapse",
        is_open=False
    ),

    # ── Stores ─────────────────────────────────────────────────────────────
    dcc.Store(id="editing-policy-id", data=None),
    dcc.Store(id="hierarchy-data-store", data=None)

], fluid=True)


# ── Helper: Build Hierarchy Cards ──────────────────────────────────────────

def build_hierarchy(df, table_filter=None):
    """
    Builds the visual hierarchy from the joined query result.
    Groups by table → layer transition → check type → metrics.
    """
    if df.empty:
        return info_alert("No configuration found. Run the SQL setup script first.")

    if table_filter:
        df = df[df["source_fully_qualified_name"] == table_filter]

    if df.empty:
        return info_alert("No configuration found for the selected table.")

    elements = []

    tables = df["source_fully_qualified_name"].dropna().unique().tolist()

    for fqn in sorted(tables):
        table_name = fqn.split(".")[-1]
        df_table   = df[df["source_fully_qualified_name"] == fqn]

        # ── Table header ───────────────────────────────────────────────────
        table_card_children = []

        transitions = (
            df_table[["from_layer", "to_layer"]]
            .drop_duplicates()
            .sort_values(["from_layer", "to_layer"])
            .values.tolist()
        )

        for from_layer, to_layer in transitions:
            df_transition = df_table[
                (df_table["from_layer"] == from_layer) &
                (df_table["to_layer"] == to_layer)
            ]

            transition_label = f"{from_layer} → {to_layer}"
            transition_color = "#375a7f" if from_layer == "BRONZE" else "#2d6a4f"

            check_sections = []

            check_types = (
                df_transition["check_type"]
                .dropna().unique().tolist()
            )

            for check_type in sorted(check_types):
                df_check  = df_transition[
                    df_transition["check_type"] == check_type
                ]
                icon      = CHECK_TYPE_ICONS.get(check_type, "")
                color     = CHECK_TYPE_COLORS.get(check_type, "#666")
                first_row = df_check.iloc[0]

                default_warn  = first_row.get("default_warning_threshold")
                default_crit  = first_row.get("default_critical_threshold")
                unit          = first_row.get("threshold_unit", "")
                description   = first_row.get("check_description", "")
                policy_id     = first_row.get("layer_check_config_id", "")

                # ── Check type header with edit button ─────────────────────
                check_header = dbc.Row([
                    dbc.Col([
                        html.Span(
                            f"{icon} {check_type}",
                            style={
                                "color"     : color,
                                "fontWeight": "bold",
                                "fontSize"  : "14px"
                            }
                        ),
                        html.Span(
                            f"  Default: warn {default_warn} | "
                            f"crit {default_crit} {unit}",
                            className="text-muted small ms-2"
                        ),
                    ], width="auto"),
                    dbc.Col([
                        dbc.Button(
                            "✏️ Edit Policy",
                            id={"type": "edit-policy-btn", "index": policy_id},
                            color="link",
                            size="sm",
                            className="p-0 text-muted"
                        )
                    ], width="auto", className="ms-auto")
                ], align="center", className="mb-2")

                if description:
                    check_header_desc = html.P(
                        description,
                        className="text-muted small mb-2 ms-3"
                    )
                else:
                    check_header_desc = html.Div()

                # ── Metrics table ──────────────────────────────────────────
                metrics_df = df_check.dropna(subset=["metric_name"])

                if metrics_df.empty:
                    metrics_content = dbc.Alert(
                        "No metrics configured for this check. "
                        "Use Add Metric to add one.",
                        color="warning",
                        className="small mb-0 ms-3"
                    )
                else:
                    metric_rows = []
                    for _, mrow in metrics_df.iterrows():
                        has_override  = bool(mrow.get("has_override", False))
                        m_warn        = mrow.get("metric_warning")
                        m_crit        = mrow.get("metric_critical")
                        m_active      = bool(mrow.get("metric_active", True))
                        metric_id     = mrow.get("metric_config_id", "")
                        src_col       = mrow.get("source_column") or "—"
                        tgt_col       = mrow.get("target_column") or "—"

                        warn_display  = (
                            html.Span(
                                f"{m_warn}",
                                style={
                                    "color"     : "#ffc107",
                                    "fontWeight": "bold"
                                },
                                title="Overrides policy default"
                            )
                            if has_override
                            else html.Span(f"{m_warn}", className="text-muted")
                        )

                        crit_display  = (
                            html.Span(
                                f"{m_crit}",
                                style={
                                    "color"     : "#ffc107",
                                    "fontWeight": "bold"
                                },
                                title="Overrides policy default"
                            )
                            if has_override
                            else html.Span(f"{m_crit}", className="text-muted")
                        )

                        metric_rows.append(
                            html.Tr([
                                html.Td(
                                    mrow.get("metric_name", ""),
                                    style={"fontSize": "12px", "color": "#ffffff" if m_active else "#888"}
                                ),
                                html.Td(
                                    src_col,
                                    style={"fontSize": "11px", "color": "#aaaaaa"}
                                ),
                                html.Td(
                                    tgt_col,
                                    style={"fontSize": "11px", "color": "#aaaaaa"}
                                ),
                                html.Td(warn_display, style={"fontSize": "12px"}),
                                html.Td(crit_display, style={"fontSize": "12px"}),
                                html.Td(
                                    "✅" if m_active else "❌",
                                    style={"fontSize": "12px", "textAlign": "center"}
                                ),
                                html.Td([
                                    dbc.Button(
                                        "Edit",
                                        id={"type": "edit-metric-btn",
                                            "index": metric_id},
                                        color="link",
                                        size="sm",
                                        className="p-0 me-2 text-info"
                                    ),
                                    dbc.Button(
                                        "Off" if m_active else "On",
                                        id={"type": "toggle-metric-btn",
                                            "index": metric_id},
                                        color="link",
                                        size="sm",
                                        className=(
                                            "p-0 text-warning"
                                            if m_active
                                            else "p-0 text-success"
                                        )
                                    )
                                ], style={"whiteSpace": "nowrap"})
                            ])
                        )

                    override_note = (
                        html.Small(
                            "🟡 = threshold overrides policy default",
                            className="text-muted ms-3"
                        )
                        if any(
                            bool(r.get("has_override", False))
                            for _, r in metrics_df.iterrows()
                        )
                        else html.Div()
                    )

                    metrics_content = html.Div([
                        override_note,
                        html.Table([
                            html.Thead(html.Tr([
                                html.Th("Metric",         style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                                html.Th("Source Column",  style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                                html.Th("Target Column",  style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                                html.Th("Warn",           style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                                html.Th("Critical",       style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                                html.Th("Active",         style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal", "textAlign": "center"}),
                                html.Th("Actions",        style={"fontSize": "11px", "color": "#aaaaaa", "fontWeight": "normal"}),
                            ])),
                            html.Tbody(metric_rows)
                        ], style={
                            "width"          : "100%",
                            "borderCollapse" : "collapse",
                            "marginLeft"     : "16px"
                        })
                    ])

                check_sections.append(
                    html.Div([
                        check_header,
                        check_header_desc,
                        metrics_content,
                        html.Hr(style={"borderColor": "#333", "margin": "12px 0"})
                    ])
                )

            table_card_children.append(
                dbc.Card([
                    dbc.CardHeader(
                        html.Div([
                            html.Span(
                                f"{'⬇️' if from_layer == 'BRONZE' else '⬆️'} "
                                f"{transition_label}",
                                style={
                                    "color"     : "#ffffff",
                                    "fontWeight": "bold"
                                }
                            )
                        ]),
                        style={"backgroundColor": transition_color}
                    ),
                    dbc.CardBody(check_sections)
                ], className="mb-3",
                style={
                    "backgroundColor": "#1e1e1e",
                    "border"         : f"1px solid {transition_color}"
                })
            )

        elements.append(
            dbc.Card([
                dbc.CardHeader(
                    html.H5(
                        f"📋 {table_name}",
                        className="mb-0 text-white"
                    ),
                    style={"backgroundColor": "#343a40"}
                ),
                dbc.CardBody(table_card_children)
            ], className="mb-4",
            style={
                "backgroundColor": "#252525",
                "border"         : "1px solid #555"
            })
        )

    return html.Div(elements)


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("recon-config-hierarchy", "children"),
    Output("recon-config-table-filter", "options"),
    Output("hierarchy-data-store", "data"),
    Input("refresh-recon-config-btn", "n_clicks"),
    Input("recon-config-table-filter", "value"),
    prevent_initial_call=False
)
def load_hierarchy(n_clicks, table_filter):
    try:
        df = execute_query(get_hierarchy_view())

        if df.empty:
            return (
                info_alert("No configuration found."),
                [],
                None
            )

        table_options = [
            {"label": fqn.split(".")[-1], "value": fqn}
            for fqn in sorted(df["source_fully_qualified_name"].dropna().unique())
        ]

        hierarchy = build_hierarchy(df, table_filter)

        # Store raw data for callbacks
        store_data = df.to_dict("records")

        return hierarchy, table_options, store_data

    except Exception as e:
        logger.error(f"Failed to load hierarchy: {str(e)}")
        return error_alert(str(e)), [], None


@callback(
    Output("metric-panel-table-dropdown", "options"),
    Input("metric-panel-table-dropdown", "id")
)
def load_metric_panel_tables(_):
    try:
        df = execute_query(get_all_registered_tables())
        if df.empty:
            return []
        return [
            {
                "label": str(row["fully_qualified_name"]),
                "value": str(row["fully_qualified_name"])
            }
            for _, row in df.iterrows()
        ]
    except Exception as e:
        logger.error(f"Failed to load tables: {str(e)}")
        return []


@callback(
    Output("metric-panel-name-dropdown", "options"),
    Output("metric-panel-unit-dropdown", "value"),
    Output("metric-panel-default-hint", "children"),
    Input("metric-panel-from-dropdown", "value"),
    Input("metric-panel-to-dropdown", "value"),
    Input("metric-panel-check-dropdown", "value"),
    State("metric-panel-table-dropdown", "value"),
    State("hierarchy-data-store", "data"),
)
def update_metric_panel_hints(
    from_layer, to_layer, check_type, table_fqn, store_data
):
    if not from_layer or not to_layer or not check_type:
        return [], "PERCENTAGE", "Select layers and check type."

    key     = (from_layer, to_layer, check_type)
    metrics = METRIC_SUGGESTIONS.get(key, [])
    options = [{"label": m, "value": m} for m in metrics]

    unit_map = {
        "ROW_COUNT" : "PERCENTAGE",
        "AGGREGATE" : "PERCENTAGE",
        "FRESHNESS" : "MINUTES"
    }

    # Find default thresholds from store
    hint = "No policy defaults found for this combination."
    if store_data and table_fqn:
        matching = [
            r for r in store_data
            if (
                r.get("source_fully_qualified_name") == table_fqn and
                r.get("from_layer") == from_layer and
                r.get("to_layer") == to_layer and
                r.get("check_type") == check_type
            )
        ]
        if matching:
            row  = matching[0]
            warn = row.get("default_warning_threshold")
            crit = row.get("default_critical_threshold")
            unit = row.get("threshold_unit", "")
            desc = row.get("check_description", "")
            hint = (
                f"Policy defaults for {from_layer}→{to_layer} {check_type}: "
                f"warn = {warn}, critical = {crit} {unit}. "
                f"{desc}"
            )

    return options, unit_map.get(check_type, "PERCENTAGE"), hint


@callback(
    Output("edit-check-policy-collapse", "is_open"),
    Output("edit-check-policy-header", "children"),
    Output("policy-warn-input", "value"),
    Output("policy-crit-input", "value"),
    Output("policy-unit-dropdown", "value"),
    Output("policy-description-input", "value"),
    Output("editing-policy-id", "data"),
    Input({"type": "edit-policy-btn", "index": dash.ALL}, "n_clicks"),
    State("hierarchy-data-store", "data"),
    prevent_initial_call=True
)
def open_edit_policy_panel(n_clicks_list, store_data):
    if not any(n for n in n_clicks_list if n):
        return False, "", None, None, None, "", None

    triggered = ctx.triggered_id
    if not triggered:
        return False, "", None, None, None, "", None

    policy_id = triggered.get("index", "")
    if not policy_id or not store_data:
        return False, "", None, None, None, "", None

    matching = [
        r for r in store_data
        if r.get("layer_check_config_id") == policy_id
    ]

    if not matching:
        return False, "", None, None, None, "", None

    row        = matching[0]
    from_layer = row.get("from_layer", "")
    to_layer   = row.get("to_layer", "")
    check_type = row.get("check_type", "")
    table      = row.get("source_fully_qualified_name", "").split(".")[-1]
    icon       = CHECK_TYPE_ICONS.get(check_type, "")

    header = (
        f"✏️ Edit Policy: {table} | {from_layer}→{to_layer} | "
        f"{icon} {check_type}"
    )

    return (
        True,
        header,
        row.get("default_warning_threshold"),
        row.get("default_critical_threshold"),
        row.get("threshold_unit"),
        row.get("check_description", ""),
        policy_id
    )


@callback(
    Output("recon-config-alert", "children"),
    Output("edit-check-policy-collapse", "is_open", allow_duplicate=True),
    Output("recon-config-hierarchy", "children", allow_duplicate=True),
    Input("save-policy-btn", "n_clicks"),
    Input("cancel-policy-btn", "n_clicks"),
    State("policy-warn-input", "value"),
    State("policy-crit-input", "value"),
    State("policy-unit-dropdown", "value"),
    State("policy-description-input", "value"),
    State("policy-updated-by-input", "value"),
    State("editing-policy-id", "data"),
    State("recon-config-table-filter", "value"),
    prevent_initial_call=True
)
def save_or_cancel_policy(
    save_clicks, cancel_clicks,
    warn, crit, unit, description, updated_by,
    policy_id, table_filter
):
    triggered = ctx.triggered_id

    if triggered == "cancel-policy-btn":
        return "", False, dash.no_update

    if triggered == "save-policy-btn":
        if not all([warn is not None, crit is not None, unit, updated_by]):
            return error_alert(
                "Please fill in Warning, Critical, Unit and Updated By."
            ), True, dash.no_update

        try:
            warn_val = float(warn)
            crit_val = float(crit)
        except (TypeError, ValueError):
            return error_alert("Thresholds must be numbers."), True, dash.no_update

        if warn_val >= crit_val:
            return error_alert(
                "Warning must be less than Critical."
            ), True, dash.no_update

        try:
            execute_write(*update_layer_check_config(
                layer_check_config_id     = policy_id,
                default_warning_threshold = warn_val,
                default_critical_threshold= crit_val,
                threshold_unit            = unit,
                description               = description or "",
                updated_by                = updated_by.strip()
            ))

            df        = execute_query(get_hierarchy_view())
            hierarchy = build_hierarchy(df, table_filter)

            return (
                success_alert("Policy updated successfully."),
                False,
                hierarchy
            )

        except Exception as e:
            logger.error(f"Failed to save policy: {str(e)}")
            return error_alert(f"Save failed: {str(e)}"), True, dash.no_update

    return "", False, dash.no_update


@callback(
    Output("edit-metric-panel-collapse", "is_open"),
    Output("edit-metric-panel-header", "children"),
    Output("metric-panel-table-dropdown", "value"),
    Output("metric-panel-from-dropdown", "value"),
    Output("metric-panel-to-dropdown", "value"),
    Output("metric-panel-check-dropdown", "value"),
    Output("metric-panel-name-dropdown", "value"),
    Output("metric-panel-src-col-input", "value"),
    Output("metric-panel-tgt-col-input", "value"),
    Output("metric-panel-warn-input", "value"),
    Output("metric-panel-crit-input", "value"),
    Output("metric-panel-unit-dropdown", "value", allow_duplicate=True),
    Output("metric-panel-edit-id", "data"),
    Input({"type": "edit-metric-btn", "index": dash.ALL}, "n_clicks"),
    Input("show-add-metric-btn", "n_clicks"),
    Input("cancel-metric-panel-btn", "n_clicks"),
    State("hierarchy-data-store", "data"),
    prevent_initial_call=True
)
def open_metric_panel(
    edit_clicks, add_clicks, cancel_clicks, store_data
):
    triggered = ctx.triggered_id

    if triggered == "cancel-metric-panel-btn":
        return (
            False, "✏️ Add / Edit Metric",
            None, None, None, None, None,
            "", "", None, None, "PERCENTAGE", None
        )

    if triggered == "show-add-metric-btn":
        return (
            True, "➕ Add New Metric",
            None, None, None, None, None,
            "", "", None, None, "PERCENTAGE", None
        )

    if isinstance(triggered, dict) and triggered.get("type") == "edit-metric-btn":
        metric_id = triggered.get("index", "")

        if not metric_id or not store_data:
            return (
                False, "✏️ Add / Edit Metric",
                None, None, None, None, None,
                "", "", None, None, "PERCENTAGE", None
            )

        matching = [
            r for r in store_data
            if r.get("metric_config_id") == metric_id
        ]

        if not matching:
            return (
                False, "✏️ Add / Edit Metric",
                None, None, None, None, None,
                "", "", None, None, "PERCENTAGE", None
            )

        row        = matching[0]
        from_layer = row.get("from_layer", "")
        to_layer   = row.get("to_layer", "")
        check_type = row.get("check_type", "")
        metric     = row.get("metric_name", "")
        icon       = CHECK_TYPE_ICONS.get(check_type, "")

        header = (
            f"✏️ Edit Metric: {from_layer}→{to_layer} | "
            f"{icon} {check_type} | {metric}"
        )

        src_col = row.get("source_column", "") or ""
        tgt_col = row.get("target_column", "") or ""

        return (
            True,
            header,
            row.get("source_fully_qualified_name"),
            from_layer,
            to_layer,
            check_type,
            metric,
            src_col,
            tgt_col,
            row.get("metric_warning"),
            row.get("metric_critical"),
            row.get("threshold_unit"),
            metric_id
        )

    return (
        False, "✏️ Add / Edit Metric",
        None, None, None, None, None,
        "", "", None, None, "PERCENTAGE", None
    )


@callback(
    Output("recon-config-alert", "children", allow_duplicate=True),
    Output("edit-metric-panel-collapse", "is_open", allow_duplicate=True),
    Output("recon-config-hierarchy", "children", allow_duplicate=True),
    Input("save-metric-panel-btn", "n_clicks"),
    State("metric-panel-table-dropdown", "value"),
    State("metric-panel-from-dropdown", "value"),
    State("metric-panel-to-dropdown", "value"),
    State("metric-panel-check-dropdown", "value"),
    State("metric-panel-name-dropdown", "value"),
    State("metric-panel-src-col-input", "value"),
    State("metric-panel-tgt-col-input", "value"),
    State("metric-panel-warn-input", "value"),
    State("metric-panel-crit-input", "value"),
    State("metric-panel-unit-dropdown", "value"),
    State("metric-panel-updated-by-input", "value"),
    State("metric-panel-edit-id", "data"),
    State("recon-config-table-filter", "value"),
    State("hierarchy-data-store", "data"),
    prevent_initial_call=True
)
def save_metric_panel(
    n_clicks,
    table_fqn, from_layer, to_layer, check_type,
    metric_name, src_col, tgt_col,
    warn, crit, unit, updated_by,
    edit_id, table_filter, store_data
):
    if not n_clicks:
        return "", False, dash.no_update

    required = {
        "Source Table": table_fqn,
        "From Layer"  : from_layer,
        "To Layer"    : to_layer,
        "Check Type"  : check_type,
        "Metric Name" : metric_name,
        "Updated By"  : updated_by
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        return error_alert(
            f"Please fill in: {', '.join(missing)}"
        ), True, dash.no_update

    # Look up policy defaults if warn/crit not provided
    if (warn is None or crit is None) and store_data:
        matching = [
            r for r in store_data
            if (
                r.get("source_fully_qualified_name") == table_fqn and
                r.get("from_layer") == from_layer and
                r.get("to_layer") == to_layer and
                r.get("check_type") == check_type
            )
        ]
        if matching:
            row  = matching[0]
            warn = warn if warn is not None else row.get("default_warning_threshold")
            crit = crit if crit is not None else row.get("default_critical_threshold")

    try:
        warn_val = float(warn)
        crit_val = float(crit)
    except (TypeError, ValueError):
        return error_alert("Thresholds must be numbers."), True, dash.no_update

    if warn_val >= crit_val:
        return error_alert(
            "Warning must be less than Critical."
        ), True, dash.no_update

    try:
        if edit_id:
            execute_write(*update_metric_config(
                metric_config_id   = edit_id,
                warning_threshold  = warn_val,
                critical_threshold = crit_val,
                threshold_unit     = unit,
                source_column      = src_col or "",
                target_column      = tgt_col or "",
                updated_by         = updated_by.strip()
            ))
            msg = f"Metric '{metric_name}' updated successfully."
        else:
            config_id = str(uuid.uuid4())[:13]
            # Determine display order
            existing  = execute_query(get_all_metric_configs())
            order_val = 1
            if not existing.empty:
                subset = existing[
                    (existing["source_fully_qualified_name"] == table_fqn) &
                    (existing["from_layer"] == from_layer) &
                    (existing["to_layer"] == to_layer) &
                    (existing["check_type"] == check_type)
                ]
                if not subset.empty:
                    order_val = int(subset["display_order"].max() or 0) + 1

            execute_write(*insert_metric_config(
                metric_config_id            = config_id,
                source_fully_qualified_name = table_fqn,
                from_layer                  = from_layer,
                to_layer                    = to_layer,
                check_type                  = check_type,
                metric_name                 = metric_name.strip(),
                source_column               = src_col or "",
                target_column               = tgt_col or "",
                warning_threshold           = warn_val,
                critical_threshold          = crit_val,
                threshold_unit              = unit,
                display_order               = order_val,
                created_by                  = updated_by.strip()
            ))
            msg = f"Metric '{metric_name}' added. ID: {config_id}"

        df        = execute_query(get_hierarchy_view())
        hierarchy = build_hierarchy(df, table_filter)

        return success_alert(msg), False, hierarchy

    except Exception as e:
        logger.error(f"Failed to save metric: {str(e)}")
        return error_alert(f"Save failed: {str(e)}"), True, dash.no_update


@callback(
    Output("recon-config-alert", "children", allow_duplicate=True),
    Output("recon-config-hierarchy", "children", allow_duplicate=True),
    Input({"type": "toggle-metric-btn", "index": dash.ALL}, "n_clicks"),
    State("hierarchy-data-store", "data"),
    State("recon-config-table-filter", "value"),
    prevent_initial_call=True
)
def toggle_metric_from_hierarchy(n_clicks_list, store_data, table_filter):
    if not any(n for n in n_clicks_list if n):
        return dash.no_update, dash.no_update

    triggered = ctx.triggered_id
    if not triggered:
        return dash.no_update, dash.no_update

    metric_id = triggered.get("index", "")
    if not metric_id or not store_data:
        return dash.no_update, dash.no_update

    matching = [
        r for r in store_data
        if r.get("metric_config_id") == metric_id
    ]

    if not matching:
        return dash.no_update, dash.no_update

    current_active = bool(matching[0].get("metric_active", True))
    new_active     = not current_active
    metric_name    = matching[0].get("metric_name", "")

    try:
        execute_write(*toggle_metric_config_active(metric_id, new_active))

        df        = execute_query(get_hierarchy_view())
        hierarchy = build_hierarchy(df, table_filter)

        action = "activated" if new_active else "deactivated"
        return (
            success_alert(f"Metric '{metric_name}' {action}."),
            hierarchy
        )

    except Exception as e:
        logger.error(f"Failed to toggle metric: {str(e)}")
        return error_alert(f"Toggle failed: {str(e)}"), dash.no_update