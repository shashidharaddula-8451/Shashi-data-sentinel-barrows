# pages/onboarding_history.py

import dash
from dash import dcc, html, Input, Output, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import error_alert, info_alert, ag_grid_props, AG_GRID_DEFAULT_COL_DEF, AG_GRID_THEME
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path  = "/onboarding-history",
    name  = "Onboarding History"
)

PREFIX = f"{TARGET_CATALOG}.{TARGET_SCHEMA}."

# ── Layout ─────────────────────────────────────────────────────────────────

def layout():
    return dbc.Container([

        # Header
        dbc.Row([
            dbc.Col([
                html.H2(
                    "📋 Onboarding History",
                    className="mb-1",
                    style={"color": "#ffffff", "fontWeight": "700"}
                ),
                html.P(
                    "All tables registered in DataSentinel via the "
                    "Table Onboarding Wizard.",
                    className="text-muted mb-3"
                ),
            ])
        ]),

        # Refresh button
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "🔄 Refresh",
                    id    = "oh-refresh-btn",
                    color = "primary",
                    size  = "sm",
                    n_clicks = 0,
                )
            ], width="auto"),
        ], className="mb-3"),

        # Summary cards
        dcc.Loading(
            id       = "oh-summary-loading",
            type     = "circle",
            color    = "#00c851",
            children = html.Div(id="oh-summary-cards")
        ),

        # History table
        dcc.Loading(
            id       = "oh-table-loading",
            type     = "circle",
            color    = "#00c851",
            children = html.Div(id="oh-history-table")
        ),

    ], fluid=True, style={"paddingTop": "24px"})


# ── Data loader ────────────────────────────────────────────────────────────

def _load_history() -> dict:
    """
    Loads all registered tables from uc1_table_registry_b
    with joined counts from child tables.
    """
    try:
        df = execute_query(f"""
            SELECT
                t.table_name,
                t.fully_qualified_name,
                t.source_type,
                t.ingestion_pattern,
                t.ingestion_frequency,
                t.business_date_column,
                t.registered_timestamp,
                t.registered_by,
                t.is_active,
                COUNT(DISTINCT c.column_name)      AS col_count,
                COUNT(DISTINCT cv.column_name)     AS val_count,
                COUNT(DISTINCT tv.validation_name) AS tval_count,
                COUNT(DISTINCT b.metric_name)      AS bl_count
            FROM {PREFIX}uc1_table_registry_b t
            LEFT JOIN {PREFIX}uc1_column_registry_b c
                   ON c.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_column_validation_registry_b cv
                   ON cv.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_table_validation_registry_b tv
                   ON tv.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_baseline_metrics_b b
                   ON b.fully_qualified_name = t.fully_qualified_name
            GROUP BY
                t.table_name,
                t.fully_qualified_name,
                t.source_type,
                t.ingestion_pattern,
                t.ingestion_frequency,
                t.business_date_column,
                t.registered_timestamp,
                t.registered_by,
                t.is_active
            ORDER BY t.registered_timestamp DESC
        """)
        return {"ok": True, "df": df}
    except Exception as e:
        logger.error(f"_load_history failed: {e}")
        return {"ok": False, "error": str(e), "df": None}


# ── Summary cards ──────────────────────────────────────────────────────────

def _build_summary_cards(df) -> dbc.Row:
    today     = date.today()
    this_week = today - timedelta(days=7)
    this_month= today - timedelta(days=30)

    total = len(df)

    # Active vs inactive
    active   = int(df["is_active"].sum()) \
               if "is_active" in df.columns else total
    inactive = total - active

    # This week
    try:
        df["registered_timestamp"] = df["registered_timestamp"].astype(str)
        week_count = len(df[
            df["registered_timestamp"] >= str(this_week)
        ])
    except Exception:
        week_count = 0

    # This month
    try:
        month_count = len(df[
            df["registered_timestamp"] >= str(this_month)
        ])
    except Exception:
        month_count = 0

    # Average columns per table
    try:
        avg_cols = (
            int(df["col_count"].mean())
            if "col_count" in df.columns and total > 0
            else 0
        )
    except Exception:
        avg_cols = 0

    def card(icon, label, value, sub=None, border="#375a7f"):
        return dbc.Col(
            html.Div([
                html.Div([
                    html.Span(
                        icon,
                        style={"fontSize": "20px",
                               "marginRight": "8px"}
                    ),
                    html.Span(
                        label,
                        style={"color"    : "#aaaaaa",
                               "fontSize" : "12px",
                               "fontWeight": "500"}
                    ),
                ], style={"marginBottom": "8px"}),
                html.Div(
                    str(value),
                    style={
                        "color"     : "#ffffff",
                        "fontSize"  : "32px",
                        "fontWeight": "800",
                        "fontFamily": "monospace",
                        "lineHeight": "1",
                    }
                ),
                html.Div(
                    sub or "",
                    style={
                        "color"    : "#64748b",
                        "fontSize" : "12px",
                        "marginTop": "4px",
                    }
                ) if sub else html.Div(),
            ], style={
                "backgroundColor": "#1a1a2e",
                "border"         : f"1px solid {border}",
                "borderLeft"     : f"4px solid {border}",
                "borderRadius"   : "8px",
                "padding"        : "16px 20px",
            }),
            md=2, className="mb-3"
        )

    return dbc.Row([
        card("📦", "Total Tables",   total,
             f"{active} active",    "#375a7f"),
        card("✅", "Active",         active,
             f"{inactive} inactive","#198754"),
        card("📅", "This Week",      week_count,
             "Last 7 days",         "#0d6efd"),
        card("📆", "This Month",     month_count,
             "Last 30 days",        "#6f42c1"),
        card("🔢", "Avg Columns",    avg_cols,
             "Per table",           "#fd7e14"),
    ], className="mb-4")


# ── History table ──────────────────────────────────────────────────────────

def _build_history_table(df) -> html.Div:
    if df.empty:
        return info_alert(
            "No tables registered yet. Use the "
            "Table Onboarding Wizard to register your first table."
        )

    rows = []
    for _, r in df.iterrows():
        ts = str(r.get("registered_timestamp", "—"))
        ts = ts[:19] if len(ts) > 19 else ts

        is_active = r.get("is_active", True)

        rows.append({
            "table_name"       : str(r.get("table_name",         "—")),
            "fully_qualified"  : str(r.get("fully_qualified_name","—")),
            "source_type"      : str(r.get("source_type",        "—")),
            "ingestion_pattern": str(r.get("ingestion_pattern",  "—")),
            "frequency"        : str(r.get("ingestion_frequency","—")),
            "date_column"      : str(r.get("business_date_column","—")),
            "col_count"        : int(r.get("col_count",  0) or 0),
            "val_count"        : int(r.get("val_count",  0) or 0),
            "tval_count"       : int(r.get("tval_count", 0) or 0),
            "bl_count"         : int(r.get("bl_count",   0) or 0),
            "registered_by"    : str(r.get("registered_by",      "—")),
            "registered_ts"    : ts,
            "status"           : "Active" if is_active else "Inactive",
        })

    col_defs = [
        {"field": "table_name",        "headerName": "Table Name",    "flex": 2, "minWidth": 220},
        {"field": "fully_qualified",   "headerName": "FQN",           "flex": 3, "minWidth": 220,
         "tooltipField": "fully_qualified"},
        {"field": "source_type",       "headerName": "Source Type",   "minWidth": 150},
        {"field": "ingestion_pattern", "headerName": "Pattern",    "minWidth": 150},
        {"field": "frequency",         "headerName": "Frequency",  "minWidth": 150},
        {"field": "date_column",       "headerName": "Date Column",   "minWidth": 150},
        {"field": "col_count",         "headerName": "Cols",          "width": 90},
        {"field": "val_count",         "headerName": "Col Rules",     "width": 90},
        {"field": "tval_count",        "headerName": "Tbl Checks",    "width": 95},
        {"field": "bl_count",          "headerName": "Baselines",     "width": 95},
        {"field": "registered_by",     "headerName": "Registered By", "flex": 1, "minWidth": 220},
        {"field": "registered_ts",     "headerName": "Registered At", "minWidth": 175},
        {"field": "status",            "headerName": "Status",     "minWidth": 150,
         "cellStyle": {"function": """
             function(params) {
                 var v = (params.value || '');
                 if (v === 'Active')   return {color: '#00c851', fontWeight: '600'};
                 if (v === 'Inactive') return {color: '#888888', fontWeight: '600'};
                 return null;
             }
         """}},
    ]

    return dbc.Card([
        dbc.CardHeader(
            html.H6(
                f"Registered Tables ({len(rows)})",
                className="mb-0 text-white"
            )
        ),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="oh-table",
                    row_data=rows,
                    col_defs=col_defs,
                    page_size=20,
                )
            )
        ])
    ], style={
        "backgroundColor": "#2b2b2b",
        "border"         : "1px solid #444",
    })


# ── Main callback ──────────────────────────────────────────────────────────

@callback(
    Output("oh-summary-cards", "children"),
    Output("oh-history-table", "children"),
    Input("oh-refresh-btn",    "n_clicks"),
    Input("oh-summary-cards",  "id"),
)
def load_history(n_clicks, _):
    result = _load_history()

    if not result["ok"]:
        alert = error_alert(f"Failed to load history: {result['error']}")
        return alert, html.Div()

    df = result["df"]

    if df is None or df.empty:
        return (
            info_alert("No tables registered yet."),
            html.Div()
        )

    summary = _build_summary_cards(df)
    table   = _build_history_table(df)

    return summary, table