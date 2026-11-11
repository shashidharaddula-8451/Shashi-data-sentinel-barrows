# pages/baseline_explorer.py
import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import math
import logging
from db.connection import execute_query, validate_identifier
from db.queries import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import error_alert, info_alert, fmt_number
from components.nested_columns import nested_sql_source, is_nested_path, path_root


def _root_dtype(safe_fqn: str, column_name: str):
    """Type string of the root column of a nested path (schema-aware resolve)."""
    if not is_nested_path(column_name):
        return None
    try:
        root = path_root(column_name)
        d = execute_query(f"DESCRIBE TABLE {safe_fqn}")
        for _, r in d.iterrows():
            if str(r.iloc[0]).strip() == root:
                return str(r.iloc[1])
    except Exception as e:
        logger.warning(f"_root_dtype({column_name}) failed: {e}")
    return None

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/baseline-explorer",
    name="Baseline Explorer"
)

# ── Table References ───────────────────────────────────────────────────────

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

A1_BASELINES  = f"{CATALOG}.{SCHEMA}.uc1_baseline_metrics_b"
A4_BASELINES  = f"{CATALOG}.{SCHEMA}.uc4_kpi_baseline_metrics_b"
A1_VALIDATION = f"{CATALOG}.{SCHEMA}.uc1_column_validation_registry_b"
A1_TABLE_VAL  = f"{CATALOG}.{SCHEMA}.uc1_table_validation_registry_b"
A4_KPI_REG    = f"{CATALOG}.{SCHEMA}.uc4_kpi_registry_b"

# ── Chart colours ──────────────────────────────────────────────────────────

COLOR_MEAN   = "#1976d2"
COLOR_LINE   = "#0d47a1"
COLOR_WARN   = "#ff9800"
COLOR_CRIT   = "#f44336"

# ── Metric labels per check type ───────────────────────────────────────────

METRIC_LABEL = {
    "VOLUME_ANOMALY"          : "Daily Row Count",
    "NULL_SPIKE"              : "Daily Null Rate (%)",
    "NUMERIC_RANGE"           : "Daily Violation Rate (%)",
    "CATEGORICAL_DOMAIN"      : "Daily Invalid Value Rate (%)",
    "CARDINALITY_DRIFT"       : "Daily Distinct Value Count",
    "MALFORMED_RECORDS"       : "Daily Malformed Rate (%)",
    "SCHEMA_CONFORMANCE"      : "Column Count",
    "CROSS_COLUMN_CONSISTENCY": "Daily Violation Rate (%)",
    "ANOMALY"                 : "Average KPI Value",
}

# ── Source table config ────────────────────────────────────────────────────

SOURCE_TABLE_CONFIG = {
    "uc1_raw_store_transactions"       : {"date_col": "transaction_date"},
    "uc1_raw_inventory_movements"      : {"date_col": "business_date"},
    "uc2_gold_daily_store_metrics"     : {"date_col": "business_date"},
    "uc2_gold_daily_inventory_summary" : {"date_col": "business_date"},
}

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.H2("Baseline Explorer", className="mt-4 mb-2"),
    html.P(
        "Explore what normal looks like for any validation check or KPI. "
        "Select an agent and table on the left, then click a baseline "
        "metric to view the full distribution chart and time series.",
        className="text-muted mb-4"
    ),

    html.Div(id="bex-alert"),

    dbc.Row([

        # ── LEFT SIDEBAR ───────────────────────────────────────────────────
        dbc.Col([

            # Agent selector
            dbc.Card([
                dbc.CardHeader(html.H6("Select Agent", className="mb-0")),
                dbc.CardBody([
                    dcc.RadioItems(
                        id="bex-agent-selector",
                        options=[
                            {
                                "label": "🔍 Validation Agent — Raw Validation",
                                "value": "A1"
                            },
                            {
                                "label": "📊 KPI Assurance Agent — KPI Validation",
                                "value": "A4"
                            },
                        ],
                        value="A1",
                        inputStyle={
                            "marginRight": "8px",
                            "cursor"     : "pointer"
                        },
                        labelStyle={
                            "display"      : "flex",
                            "alignItems"   : "center",
                            "color"        : "#ffffff",
                            "fontSize"     : "14px",
                            "marginBottom" : "8px",
                            "cursor"       : "pointer"
                        }
                    )
                ])
            ], className="mb-3",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            }),

            # Table selector — RadioItems (reliable with dynamic options)
            dbc.Card([
                dbc.CardHeader(html.H6("Select Table", className="mb-0")),
                dbc.CardBody([
                    dcc.RadioItems(
                        id="bex-table-selector",
                        options=[],
                        value=None,
                        inputStyle={
                            "marginRight": "8px",
                            "cursor"     : "pointer"
                        },
                        labelStyle={
                            "display"      : "flex",
                            "alignItems"   : "center",
                            "padding"      : "6px 4px",
                            "cursor"       : "pointer",
                            "borderRadius" : "4px",
                            "marginBottom" : "2px",
                            "color"        : "#ffffff",
                            "fontSize"     : "13px",
                            "borderBottom" : "1px solid #333"
                        }
                    ),
                    html.Div(id="bex-table-info", className="mt-1")
                ])
            ], className="mb-3",
            style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            }),

            # Baseline list — RadioItems
            dbc.Card([
                dbc.CardHeader(
                    html.H6("Select Baseline", className="mb-0")
                ),
                dbc.CardBody([
                    html.Div(
                        id="bex-baseline-list",
                        children=html.P(
                            "Select a table above.",
                            className="text-muted small mb-0"
                        )
                    )
                ])
            ], style={
                "backgroundColor": "#2b2b2b",
                "border"         : "1px solid #444"
            }),

        ], md=3),

        # ── RIGHT PANEL ────────────────────────────────────────────────────
        dbc.Col([
            html.Div(
                id="bex-main-content",
                children=dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.H4(
                                "📊 Select a baseline to explore",
                                className="text-center mt-4",
                                style={"color": "#aaaaaa"}
                            ),
                            html.P(
                                "Choose an agent → table → baseline metric "
                                "from the left panel.",
                                className="text-center text-muted mt-2"
                            )
                        ], className="py-4")
                    ])
                ], style={
                    "backgroundColor": "#2b2b2b",
                    "border"         : "1px solid #444",
                    "minHeight"      : "500px"
                })
            )
        ], md=9),

    ]),

    # ── Stores ─────────────────────────────────────────────────────────────
    dcc.Store(id="bex-baselines-store", data=[]),
    dcc.Store(id="bex-show-thresholds", data=True),

], fluid=True)


# ── Helper functions ───────────────────────────────────────────────────────

def load_tables_with_baselines(agent: str) -> list:
    if agent == "A1":
        query = f"""
            SELECT DISTINCT
                fully_qualified_name,
                SUBSTRING_INDEX(
                    fully_qualified_name, '.', -1
                )               AS table_short,
                COUNT(*)        AS baseline_count
            FROM {A1_BASELINES}
            GROUP BY fully_qualified_name
            ORDER BY fully_qualified_name
        """
    else:
        query = f"""
            SELECT DISTINCT
                gold_fully_qualified_name   AS fully_qualified_name,
                SUBSTRING_INDEX(
                    gold_fully_qualified_name, '.', -1
                )               AS table_short,
                COUNT(*)        AS baseline_count
            FROM {A4_BASELINES}
            GROUP BY gold_fully_qualified_name
            ORDER BY fully_qualified_name
        """
    try:
        df = execute_query(query)
        return df.to_dict("records") if not df.empty else []
    except Exception as e:
        logger.error(f"load_tables_with_baselines failed: {str(e)}")
        return []


def load_baselines_for_table(fqn: str, agent: str) -> list:
    try:
        if agent == "A1":
            query = f"""
                SELECT
                    baseline_id,
                    fully_qualified_name,
                    column_name,
                    check_type,
                    metric_name,
                    baseline_date,
                    baseline_window_days,
                    ROUND(mean_value, 6)    AS mean_value,
                    ROUND(stddev_value, 6)  AS stddev_value,
                    ROUND(min_value, 6)     AS min_value,
                    ROUND(max_value, 6)     AS max_value,
                    ROUND(p25_value, 6)     AS p25_value,
                    ROUND(p50_value, 6)     AS p50_value,
                    ROUND(p75_value, 6)     AS p75_value,
                    ROUND(p95_value, 6)     AS p95_value,
                    sample_count,
                    baseline_status
                FROM {A1_BASELINES}
                WHERE fully_qualified_name = :fqn
                ORDER BY check_type, column_name
            """
        else:
            query = f"""
                SELECT
                    baseline_id,
                    gold_fully_qualified_name   AS fully_qualified_name,
                    kpi_name                    AS column_name,
                    'ANOMALY'                   AS check_type,
                    kpi_column                  AS metric_name,
                    baseline_date,
                    baseline_window_days,
                    ROUND(mean_value, 6)        AS mean_value,
                    ROUND(stddev_value, 6)      AS stddev_value,
                    ROUND(min_value, 6)         AS min_value,
                    ROUND(max_value, 6)         AS max_value,
                    ROUND(p25_value, 6)         AS p25_value,
                    ROUND(p50_value, 6)         AS p50_value,
                    ROUND(p75_value, 6)         AS p75_value,
                    ROUND(p95_value, 6)         AS p95_value,
                    sample_count,
                    baseline_status
                FROM {A4_BASELINES}
                WHERE gold_fully_qualified_name = :fqn
                ORDER BY kpi_name
            """
        df = execute_query(query, {"fqn": fqn})
        return df.to_dict("records") if not df.empty else []
    except Exception as e:
        logger.error(f"load_baselines_for_table failed: {str(e)}")
        return []


def load_thresholds(fqn: str, check_type: str,
                    column_name: str, agent: str) -> dict:
    try:
        if agent == "A1":
            if check_type in ("VOLUME_ANOMALY", "MALFORMED_RECORDS",
                               "SCHEMA_CONFORMANCE"):
                query = f"""
                    SELECT warning_threshold, critical_threshold
                    FROM {A1_TABLE_VAL}
                    WHERE fully_qualified_name = :fqn
                      AND validation_name = :validation_name
                    LIMIT 1
                """
                params = {"fqn": fqn, "validation_name": check_type}
            else:
                query = f"""
                    SELECT warning_threshold, critical_threshold
                    FROM {A1_VALIDATION}
                    WHERE fully_qualified_name = :fqn
                      AND column_name = :column_name
                      AND validation_name = :validation_name
                    LIMIT 1
                """
                params = {
                    "fqn"            : fqn,
                    "column_name"    : column_name,
                    "validation_name": check_type,
                }
        else:
            query = f"""
                SELECT
                    warning_deviation_pct   AS warning_threshold,
                    critical_deviation_pct  AS critical_threshold
                FROM {A4_KPI_REG}
                WHERE gold_fully_qualified_name = :fqn
                  AND kpi_name = :kpi_name
                LIMIT 1
            """
            params = {"fqn": fqn, "kpi_name": column_name}
        df = execute_query(query, params)
        if df.empty:
            return {"warn": None, "crit": None}
        return {
            "warn": float(df.iloc[0]["warning_threshold"] or 0),
            "crit": float(df.iloc[0]["critical_threshold"] or 0)
        }
    except Exception as e:
        logger.warning(f"load_thresholds failed: {str(e)}")
        return {"warn": None, "crit": None}


def reconstruct_daily_values(fqn: str, check_type: str,
                              column_name: str, agent: str,
                              window_days: int = 30) -> pd.DataFrame:
    table_short = fqn.split(".")[-1]
    config      = SOURCE_TABLE_CONFIG.get(table_short, {})
    date_col    = config.get("date_col", "business_date")

    try:
        safe_fqn   = validate_identifier(fqn)
        row_limit  = int(window_days) + 10
        params     = {}

        if agent == "A1":
            if check_type == "VOLUME_ANOMALY":
                query = f"""
                    SELECT {date_col} AS date, COUNT(*) AS metric_value
                    FROM {safe_fqn}
                    GROUP BY {date_col}
                    ORDER BY {date_col}
                    LIMIT {row_limit}
                """
            elif check_type == "NULL_SPIKE":
                src, safe_col = nested_sql_source(safe_fqn, column_name, _root_dtype(safe_fqn, column_name))
                query = f"""
                    SELECT
                        {date_col} AS date,
                        ROUND(
                            SUM(CASE WHEN {safe_col} IS NULL
                                THEN 1 ELSE 0 END) /
                            NULLIF(COUNT(*), 0) * 100, 4
                        ) AS metric_value
                    FROM {src}
                    GROUP BY {date_col}
                    ORDER BY {date_col}
                    LIMIT {row_limit}
                """
            elif check_type == "CARDINALITY_DRIFT":
                src, safe_col = nested_sql_source(safe_fqn, column_name, _root_dtype(safe_fqn, column_name))
                query = f"""
                    SELECT
                        {date_col} AS date,
                        COUNT(DISTINCT {safe_col}) AS metric_value
                    FROM {src}
                    GROUP BY {date_col}
                    ORDER BY {date_col}
                    LIMIT {row_limit}
                """
            elif check_type == "MALFORMED_RECORDS":
                query = f"""
                    SELECT
                        {date_col} AS date,
                        ROUND(
                            SUM(CASE WHEN _rescued_data IS NOT NULL
                                THEN 1 ELSE 0 END) /
                            NULLIF(COUNT(*), 0) * 100, 4
                        ) AS metric_value
                    FROM {safe_fqn}
                    GROUP BY {date_col}
                    ORDER BY {date_col}
                    LIMIT {row_limit}
                """
            else:
                return pd.DataFrame()
        else:
            src, safe_col = nested_sql_source(safe_fqn, column_name, _root_dtype(safe_fqn, column_name))
            query = f"""
                SELECT
                    {date_col} AS date,
                    ROUND(AVG({safe_col}), 6) AS metric_value
                FROM {src}
                WHERE {safe_col} IS NOT NULL
                GROUP BY {date_col}
                ORDER BY {date_col}
                LIMIT {row_limit}
            """

        df = execute_query(query, params)
        if df.empty:
            return pd.DataFrame()
        df["date"]         = pd.to_datetime(df["date"])
        df["metric_value"] = pd.to_numeric(
            df["metric_value"], errors="coerce"
        )
        return df.dropna(subset=["metric_value"])

    except Exception as e:
        logger.warning(f"reconstruct_daily_values failed: {str(e)}")
        return pd.DataFrame()


def build_chart(baseline: dict, daily_df: pd.DataFrame,
                thresholds: dict, show_thresholds: bool,
                agent: str) -> go.Figure:

    check_type   = baseline.get("check_type", "")
    column_name  = baseline.get("column_name", "")
    mean_val     = float(baseline.get("mean_value") or 0)
    min_val      = float(baseline.get("min_value") or 0)
    max_val      = float(baseline.get("max_value") or 0)
    p25_val      = float(baseline.get("p25_value") or 0)
    p50_val      = float(baseline.get("p50_value") or 0)
    p75_val      = float(baseline.get("p75_value") or 0)
    p95_val      = float(baseline.get("p95_value") or 0)
    metric_label = METRIC_LABEL.get(check_type, "Value")

    warn = thresholds.get("warn")
    crit = thresholds.get("crit")

    has_thresholds = show_thresholds and warn is not None and crit is not None
    has_daily      = not daily_df.empty

    # Compute zone bounds for Agent 4
    if agent == "A4" and has_thresholds and mean_val:
        warn_lower = mean_val * (1 - float(warn) / 100)
        warn_upper = mean_val * (1 + float(warn) / 100)
        crit_lower = mean_val * (1 - float(crit) / 100)
        crit_upper = mean_val * (1 + float(crit) / 100)
    else:
        warn_lower = warn_upper = warn
        crit_lower = crit_upper = crit

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.14,
        subplot_titles=[
            f"Daily Values — {column_name} ({check_type})",
            "Statistical Distribution"
        ]
    )

    # ── Top: Time Series ───────────────────────────────────────────────────

    if has_daily:
        dates  = daily_df["date"].tolist()
        values = daily_df["metric_value"].tolist()

        # Mean line
        fig.add_hline(
            y=mean_val,
            line_dash="dash",
            line_color=COLOR_MEAN,
            line_width=1.5,
            annotation_text=f"Mean: {fmt_number(mean_val)}",
            annotation_position="bottom right",
            row=1, col=1
        )

        # Threshold lines
        if has_thresholds:
            if agent == "A4":
                for val, lbl, clr in [
                    (warn_lower, "⚠ Warn low",  COLOR_WARN),
                    (warn_upper, "⚠ Warn high", COLOR_WARN),
                    (crit_lower, "🔴 Crit low",  COLOR_CRIT),
                    (crit_upper, "🔴 Crit high", COLOR_CRIT),
                ]:
                    fig.add_hline(
                        y=val,
                        line_dash="dot",
                        line_color=clr,
                        line_width=1,
                        annotation_text=lbl,
                        annotation_position="bottom left",
                        row=1, col=1
                    )
            else:
                fig.add_hline(
                    y=warn,
                    line_dash="dot",
                    line_color=COLOR_WARN,
                    line_width=1,
                    annotation_text=f"⚠ Warn: {fmt_number(warn)}",
                    row=1, col=1
                )
                fig.add_hline(
                    y=crit,
                    line_dash="dot",
                    line_color=COLOR_CRIT,
                    line_width=1,
                    annotation_text=f"🔴 Crit: {fmt_number(crit)}",
                    row=1, col=1
                )

        # Colour points by status
        point_colors = []
        for v in values:
            if has_thresholds:
                if agent == "A4":
                    if v < crit_lower or v > crit_upper:
                        point_colors.append(COLOR_CRIT)
                    elif v < warn_lower or v > warn_upper:
                        point_colors.append(COLOR_WARN)
                    else:
                        point_colors.append(COLOR_MEAN)
                else:
                    if crit is not None and v >= crit:
                        point_colors.append(COLOR_CRIT)
                    elif warn is not None and v >= warn:
                        point_colors.append(COLOR_WARN)
                    else:
                        point_colors.append(COLOR_MEAN)
            else:
                point_colors.append(COLOR_MEAN)

        fig.add_trace(
            go.Scatter(
                x=dates,
                y=values,
                mode="lines+markers",
                name=metric_label,
                line=dict(color=COLOR_LINE, width=2),
                marker=dict(
                    color=point_colors,
                    size=7,
                    line=dict(color="#ffffff", width=1)
                ),
                hovertemplate=(
                    "<b>%{x|%Y-%m-%d}</b><br>"
                    f"{metric_label}: %{{y:.4f}}<extra></extra>"
                )
            ),
            row=1, col=1
        )
    else:
        fig.add_annotation(
            text="Daily time series not available for this check type.",
            xref="paper", yref="paper",
            x=0.5, y=0.75,
            showarrow=False,
            font=dict(color="#888888", size=13)
        )

    # ── Bottom: Box Plot ───────────────────────────────────────────────────

    fig.add_trace(
        go.Box(
            q1=[p25_val],
            median=[p50_val],
            q3=[p75_val],
            mean=[mean_val],
            lowerfence=[min_val],
            upperfence=[p95_val],
            name="Distribution",
            marker_color=COLOR_MEAN,
            fillcolor="rgba(25, 118, 210, 0.15)",
            line=dict(color=COLOR_MEAN, width=2),
            boxmean=True,
            orientation="h",
            showlegend=False
        ),
        row=2, col=1
    )

    # Threshold markers on box plot
    if has_thresholds:
        if agent == "A4":
            for val, lbl, clr in [
                (warn_lower, "⚠ WL", COLOR_WARN),
                (warn_upper, "⚠ WH", COLOR_WARN),
                (crit_lower, "🔴 CL", COLOR_CRIT),
                (crit_upper, "🔴 CH", COLOR_CRIT),
            ]:
                fig.add_vline(
                    x=val,
                    line_dash="dot",
                    line_color=clr,
                    line_width=1.5,
                    annotation_text=lbl,
                    annotation_position="top",
                    row=2, col=1
                )
        else:
            if warn is not None:
                fig.add_vline(
                    x=warn,
                    line_dash="dot",
                    line_color=COLOR_WARN,
                    line_width=1.5,
                    annotation_text="⚠",
                    annotation_position="top",
                    row=2, col=1
                )
            if crit is not None:
                fig.add_vline(
                    x=crit,
                    line_dash="dot",
                    line_color=COLOR_CRIT,
                    line_width=1.5,
                    annotation_text="🔴",
                    annotation_position="top",
                    row=2, col=1
                )

    fig.update_layout(
        height        = 600,
        paper_bgcolor = "#2b2b2b",
        plot_bgcolor  = "#2b2b2b",
        font          = dict(color="#ffffff", size=12),
        showlegend    = False,
        margin        = dict(l=60, r=40, t=60, b=40),
        hovermode     = "x unified",
    )
    fig.update_xaxes(
        gridcolor="#444", tickcolor="#888",
        linecolor="#444", tickfont=dict(color="#ccc")
    )
    fig.update_yaxes(
        gridcolor="#444", tickcolor="#888",
        linecolor="#444", tickfont=dict(color="#ccc"),
        title_text=metric_label, row=1, col=1
    )
    for ann in fig["layout"]["annotations"]:
        ann["font"] = dict(color="#ffffff", size=12)

    return fig


def _stat_card(label: str, value: str):
    return dbc.Card([
        dbc.CardBody([
            html.P(
                label,
                className="mb-0",
                style={"color": "#aaaaaa", "fontSize": "11px"}
            ),
            html.Strong(
                value,
                style={"color": "#ffffff", "fontSize": "14px"}
            )
        ], style={"padding": "8px 12px"})
    ], style={
        "backgroundColor": "#1e1e1e",
        "border"         : "1px solid #444",
        "minWidth"       : "95px"
    })


# ── Callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("bex-table-selector", "options"),
    Output("bex-table-selector", "value"),
    Input("bex-agent-selector", "value"),
    prevent_initial_call=False
)
def update_table_options(agent):
    """
    Loads table options for the selected agent.
    Uses RadioItems — reliable with dynamic content.
    """
    tables = load_tables_with_baselines(agent)
    if not tables:
        return [], None

    options = [
        {
            "label": (
                f"  {t['table_short']}  "
                f"({t['baseline_count']} baselines)"
            ),
            "value": t["fully_qualified_name"]
        }
        for t in tables
    ]

    return options, None    # None = no default selection


@callback(
    Output("bex-baseline-list", "children"),
    Output("bex-baselines-store", "data"),
    Output("bex-table-info", "children"),
    Input("bex-table-selector", "value"),
    State("bex-agent-selector", "value"),
    prevent_initial_call=True
)
def load_baseline_list(selected_fqn, agent):
    """
    Loads baselines for the selected table as RadioItems.
    Stores full baseline data for use in chart rendering.
    """
    if not selected_fqn:
        return (
            html.P("Select a table above.", className="text-muted small mb-0"),
            [],
            html.Div()
        )

    baselines = load_baselines_for_table(selected_fqn, agent)

    if not baselines:
        return (
            html.P("No baselines found.", className="text-muted small mb-0"),
            [],
            html.Div()
        )

    options = []
    for i, b in enumerate(baselines):
        check_type  = b.get("check_type", "")
        column_name = b.get("column_name", "")
        status      = b.get("baseline_status", "")
        mean_val    = b.get("mean_value")

        status_emoji = "✅" if status == "VALID" else "⚠️"
        label = (
            f"{column_name} — {check_type}"
            if column_name not in ("__table__", None, "")
            else check_type
        )

        options.append({
            "label": html.Div([
                html.Span(
                    f"{status_emoji} {label}",
                    style={
                        "color"   : "#ffffff",
                        "fontSize": "12px",
                        "display" : "block"
                    }
                ),
                html.Span(
                    f"Mean: {fmt_number(mean_val)}",
                    style={
                        "color"   : "#aaaaaa",
                        "fontSize": "11px"
                    }
                )
            ]),
            "value": str(i)    # use index as value
        })

    table_short = selected_fqn.split(".")[-1]
    info = html.Small(
        f"✅ {len(baselines)} baselines for {table_short}",
        style={"color": "#00c851"}
    )

    radio = dcc.RadioItems(
        id="bex-baseline-selector",
        options=options,
        value=None,
        inputStyle={
            "marginRight": "8px",
            "cursor"     : "pointer"
        },
        labelStyle={
            "display"      : "flex",
            "alignItems"   : "flex-start",
            "padding"      : "6px 4px",
            "cursor"       : "pointer",
            "borderBottom" : "1px solid #333",
            "marginBottom" : "2px"
        }
    )

    return radio, baselines, info


@callback(
    Output("bex-main-content", "children"),
    Input("bex-baseline-selector", "value"),
    State("bex-baselines-store", "data"),
    State("bex-table-selector", "value"),
    State("bex-agent-selector", "value"),
    State("bex-show-thresholds", "data"),
    prevent_initial_call=True
)
def render_chart(selected_idx, baselines_store, selected_fqn,
                 agent, show_thresholds):
    """
    Renders the full chart panel when a baseline is selected.
    """
    if selected_idx is None or not baselines_store or not selected_fqn:
        return dash.no_update

    try:
        idx      = int(selected_idx)
        baseline = baselines_store[idx]
    except (ValueError, IndexError, TypeError):
        return dbc.Alert("Could not load baseline.", color="warning")

    check_type  = baseline.get("check_type", "")
    column_name = baseline.get("column_name", "")
    mean_val    = baseline.get("mean_value")
    stddev_val  = baseline.get("stddev_value")
    min_val     = baseline.get("min_value")
    max_val     = baseline.get("max_value")
    p25_val     = baseline.get("p25_value")
    p50_val     = baseline.get("p50_value")
    p75_val     = baseline.get("p75_value")
    p95_val     = baseline.get("p95_value")
    samples     = baseline.get("sample_count")
    status      = baseline.get("baseline_status", "")
    b_date      = baseline.get("baseline_date", "")
    window      = baseline.get("baseline_window_days", 30)

    table_short  = selected_fqn.split(".")[-1]
    metric_label = METRIC_LABEL.get(check_type, "Value")
    label        = (
        f"{column_name} — {check_type}"
        if column_name not in ("__table__", None, "")
        else check_type
    )

    try:
        thresholds = load_thresholds(
            selected_fqn, check_type, column_name, agent
        )
        daily_df = reconstruct_daily_values(
            selected_fqn, check_type, column_name,
            agent, int(window or 30)
        )
        fig = build_chart(
            baseline        = baseline,
            daily_df        = daily_df,
            thresholds      = thresholds,
            show_thresholds = (
                show_thresholds if show_thresholds is not None else True
            ),
            agent           = agent
        )

    except Exception as e:
        logger.error(f"Chart build failed: {str(e)}")
        return dbc.Alert(f"Chart error: {str(e)}", color="danger")

    # Threshold zone display
    warn = thresholds.get("warn")
    crit = thresholds.get("crit")

    if agent == "A4" and mean_val and warn and crit:
        mf         = float(mean_val)
        wl         = mf * (1 - float(warn) / 100)
        wu         = mf * (1 + float(warn) / 100)
        cl         = mf * (1 - float(crit) / 100)
        cu         = mf * (1 + float(crit) / 100)
        thresh_display = dbc.Row([
            dbc.Col([
                html.Small(
                    "🟡 Warning Zone",
                    style={"color": "#ffa500"}
                ),
                html.Br(),
                html.Small(
                    f"[ {fmt_number(wl)} → {fmt_number(wu)} ]  "
                    f"(±{fmt_number(warn)}% from mean)",
                    style={
                        "color"     : "#ffa500",
                        "fontFamily": "monospace"
                    }
                )
            ], md=6),
            dbc.Col([
                html.Small(
                    "🔴 Critical Zone",
                    style={"color": "#ff6b6b"}
                ),
                html.Br(),
                html.Small(
                    f"[ {fmt_number(cl)} → {fmt_number(cu)} ]  "
                    f"(±{fmt_number(crit)}% from mean)",
                    style={
                        "color"     : "#ff6b6b",
                        "fontFamily": "monospace"
                    }
                )
            ], md=6)
        ])
    elif warn is not None and crit is not None:
        thresh_display = dbc.Row([
            dbc.Col([
                html.Small(
                    f"🟡 Warning threshold: ≥ {fmt_number(warn)}",
                    style={"color": "#ffa500"}
                )
            ], md=6),
            dbc.Col([
                html.Small(
                    f"🔴 Critical threshold: ≥ {fmt_number(crit)}",
                    style={"color": "#ff6b6b"}
                )
            ], md=6)
        ])
    else:
        thresh_display = html.Small(
            "No thresholds configured for this check.",
            className="text-muted"
        )

    return dbc.Card([
        dbc.CardBody([

            # Header
            dbc.Row([
                dbc.Col([
                    html.H5(label, className="mb-1 text-white"),
                    html.Small(
                        f"{table_short}  ·  {metric_label}  ·  "
                        f"{samples} samples  ·  {window}-day window  ·  "
                        f"Baseline: {str(b_date)[:10]}",
                        style={"color": "#aaaaaa"}
                    )
                ], md=8),
                dbc.Col([
                    dbc.Switch(
                        id="bex-threshold-toggle",
                        label="Show Thresholds",
                        value=(
                            show_thresholds
                            if show_thresholds is not None else True
                        ),
                        className="mt-1"
                    )
                ], md=4, className="text-end")
            ], className="mb-3"),

            # Threshold zones
            dbc.Card([
                dbc.CardBody([thresh_display])
            ], className="mb-3",
            style={
                "backgroundColor": "#1e1e1e",
                "border"         : "1px solid #444"
            }),

            # Chart
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": True, "scrollZoom": True},
                className="mb-3"
            ),

            # Stats
            html.H6("Distribution Statistics", className="text-white mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        _stat_card("Mean",    fmt_number(mean_val)),
                        _stat_card("Std Dev", fmt_number(stddev_val)),
                        _stat_card("Min",     fmt_number(min_val)),
                        _stat_card("Max",     fmt_number(max_val)),
                    ], className="d-flex flex-wrap gap-2")
                ], md=6),
                dbc.Col([
                    html.Div([
                        _stat_card("P25",          fmt_number(p25_val)),
                        _stat_card("P50 (Median)", fmt_number(p50_val)),
                        _stat_card("P75",          fmt_number(p75_val)),
                        _stat_card("P95",          fmt_number(p95_val)),
                    ], className="d-flex flex-wrap gap-2")
                ], md=6)
            ])

        ])
    ], style={
        "backgroundColor": "#2b2b2b",
        "border"         : "1px solid #444"
    })


@callback(
    Output("bex-show-thresholds", "data"),
    Input("bex-threshold-toggle", "value"),
    prevent_initial_call=True
)
def update_threshold_store(value):
    return value