# pages/cost.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.graph_objects as go
import pandas as pd
import math
import logging
from datetime import date, datetime, timedelta
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import ag_grid_props, AG_STATUS_CELL_STYLE_JS

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path  = "/cost",
    name  = "Cost"
)

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

# ── Defaults ───────────────────────────────────────────────────────────────

DEFAULT_DBU_PRICE    = 0.30   # $ per DBU — PREMIUM_JOBS_COMPUTE
DEFAULT_DBU_PER_HOUR = 4.0    # Standard_E8as_v4 minimum node config
DEFAULT_APP_COST     = 0.50   # $ per hour — DataSentinel App (fallback only)
DEFAULT_DAYS         = 30

# ── App billing constants ──────────────────────────────────────────────────
# All known app_ids for DataSentinel across name changes
# agent1-admin-ui → data-trust-layer-admin-ui → data-sentinel

APP_IDS = (
    "'8a0ce546-fdb4-4e85-b6b4-427e8bbb3e0d'",   # data-sentinel
    "'e15a21dc-48c9-4eba-bdcf-3b0ce8a99a74'",   # data-trust-layer-admin-ui
    "'e6a6665d-48e8-43ba-bd2d-161f2df39725'",   # agent1-admin-ui
)
APP_IDS_SQL   = ", ".join(APP_IDS)
APP_SKU_PRICE = 0.95   # PREMIUM_ALL_PURPOSE_SERVERLESS_COMPUTE_US_EAST_2

# ── Agent definitions ──────────────────────────────────────────────────────

AGENTS = [
    {
        "key"         : "agent1",
        "label"       : "Validation Agent — Raw Ingestion",
        "icon"        : "🔍",
        "color"       : "#375a7f",
        "color_light" : "#4a9edd",
        "table"       : f"{CATALOG}.{SCHEMA}.uc1_validation_run_b",
        "date_col"    : "business_date",
        "duration_col": "validation_duration_seconds",
        "status_col"  : "overall_status",
        "run_id_col"  : "validation_run_id",
        "checks_col"  : "total_checks_run",
    },
    {
        "key"         : "agent2",
        "label"       : "Reconciliation Agent — Reconciliation",
        "icon"        : "🔄",
        "color"       : "#2d6a4f",
        "color_light" : "#00c851",
        "table"       : f"{CATALOG}.{SCHEMA}.uc2_reconciliation_run_b",
        "date_col"    : "business_date",
        "duration_col": "reconciliation_duration_seconds",
        "status_col"  : "overall_status",
        "run_id_col"  : "reconciliation_run_id",
        "checks_col"  : "total_checks_run",
    },
    {
        "key"         : "agent3",
        "label"       : "Transformation Agent — SQL Review",
        "icon"        : "🧪",
        "color"       : "#6b3a7d",
        "color_light" : "#c084fc",
        "table"       : f"{CATALOG}.{SCHEMA}.uc3_review_results_b",
        "date_col"    : "business_date",
        "duration_col": None,              # no duration column — use NULL
        "status_col"  : "overall_status",
        "run_id_col"  : "review_id",
        "checks_col"  : "total_checks_run",
    },
    {
        "key"         : "agent4",
        "label"       : "KPI Assurance Agent — KPI Validation",
        "icon"        : "📊",
        "color"       : "#7d4a1a",
        "color_light" : "#ffa500",
        "table"       : f"{CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b",
        "date_col"    : "business_date",
        "duration_col": "validation_duration_seconds",
        "status_col"  : "overall_status",
        "run_id_col"  : "validation_run_id",
        "checks_col"  : "total_kpis_checked",
    },
]

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.Div([
        html.Span("💰", style={"fontSize": "28px", "marginRight": "12px"}),
        html.Div([
            html.H2("Pipeline Cost Analysis", className="mb-0 text-white"),
            html.P(
                "Estimated compute cost for all DataSentinel pipelines and the Admin App.",
                className="text-muted mb-0 small",
            ),
        ]),
    ], className="d-flex align-items-center mt-4 mb-4"),

    # ── Controls ───────────────────────────────────────────────────────────
    dbc.Card([
        dbc.CardBody([
            dbc.Row([

                # Date range
                dbc.Col([
                    dbc.Label("Date Range", className="text-white fw-bold"),
                    dcc.DatePickerRange(
                        id            = "cost-date-range",
                        start_date    = str(
                            date.today() - timedelta(days=DEFAULT_DAYS)
                        ),
                        end_date      = str(date.today()),
                        display_format= "YYYY-MM-DD",
                        style         = {"fontSize": "13px"}
                    ),
                ], md=4),

                # DBU price
                dbc.Col([
                    dbc.Label(
                        "DBU Price ($/DBU)",
                        className="text-white fw-bold"
                    ),
                    dbc.Input(
                        id    = "cost-dbu-price",
                        type  = "number",
                        value = DEFAULT_DBU_PRICE,
                        min   = 0.01,
                        max   = 10.0,
                        step  = 0.01,
                        style = {
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "PREMIUM_JOBS_COMPUTE list price",
                        className="text-muted"
                    )
                ], md=2),

                # DBU per hour
                dbc.Col([
                    dbc.Label(
                        "DBU/Hour (per node)",
                        className="text-white fw-bold"
                    ),
                    dbc.Input(
                        id    = "cost-dbu-per-hour",
                        type  = "number",
                        value = DEFAULT_DBU_PER_HOUR,
                        min   = 0.5,
                        max   = 32.0,
                        step  = 0.5,
                        style = {
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "Standard_E8as_v4 = 4 DBU/hr",
                        className="text-muted"
                    )
                ], md=2),

                # App cost per hour
                dbc.Col([
                    dbc.Label(
                        "App Cost Fallback ($/hr)",
                        className="text-white fw-bold"
                    ),
                    dbc.Input(
                        id    = "cost-app-per-hour",
                        type  = "number",
                        value = DEFAULT_APP_COST,
                        min   = 0.0,
                        max   = 100.0,
                        step  = 0.01,
                        style = {
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                            "borderColor"    : "#555"
                        }
                    ),
                    dbc.FormText(
                        "Used only if billing data unavailable",
                        className="text-muted"
                    )
                ], md=2),

                # Calculate button
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white fw-bold"),
                    dbc.Button(
                        "Calculate Cost",
                        id        = "cost-calculate-btn",
                        color     = "primary",
                        size      = "lg",
                        className = "d-block w-100",
                        n_clicks  = 0
                    )
                ], md=2),

            ], className="g-3"),

            # Quick date presets
            html.Div([
                html.Small("Quick select: ", className="text-muted me-2"),
                dbc.Button("Last 7 days",  id="cost-preset-7",  color="link",
                           size="sm", className="text-muted p-0 me-3"),
                dbc.Button("Last 30 days", id="cost-preset-30", color="link",
                           size="sm", className="text-muted p-0 me-3"),
                dbc.Button("Last 90 days", id="cost-preset-90", color="link",
                           size="sm", className="text-muted p-0"),
            ], className="mt-3"),

        ])
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),

    html.Div(id="cost-alert"),

    # ── Main content with spinner ───────────────────────────────────────────
    dcc.Loading(
        id    = "cost-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="cost-main-content")
    ),

], fluid=True)


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _fmt_currency(val) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        if f >= 1000:
            return f"${f:,.2f}"
        return f"${f:.4f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_number(val, decimals=2) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        return f"{f:,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _compute_cost(
    duration_seconds : float,
    dbu_per_hour     : float,
    dbu_price        : float
) -> dict:
    """
    Computes DBU consumption and cost from duration.
    Returns dict with hours, dbus, cost.
    """
    if duration_seconds is None or duration_seconds <= 0:
        return {"hours": 0.0, "dbus": 0.0, "cost": 0.0}

    hours = duration_seconds / 3600
    dbus  = hours * dbu_per_hour
    cost  = dbus * dbu_price

    return {
        "hours": round(hours, 6),
        "dbus" : round(dbus, 4),
        "cost" : round(cost, 6),
    }


# ── Data loading ───────────────────────────────────────────────────────────

def _load_agent_runs(
    agent        : dict,
    date_from    : str,
    date_to      : str,
    dbu_per_hour : float,
    dbu_price    : float
) -> pd.DataFrame:
    """
    Loads all runs for an agent within the date range.
    Computes cost per run.
    Agent 3 has no duration column — uses 0 duration.
    """
    table       = agent["table"]
    date_col    = agent["date_col"]
    dur_col     = agent["duration_col"]
    status_col  = agent["status_col"]
    run_id_col  = agent["run_id_col"]
    checks_col  = agent["checks_col"]

    # Agent 3 has no duration column
    dur_expr = (
        f"ROUND({dur_col}, 2) AS duration_seconds"
        if dur_col
        else "CAST(NULL AS DOUBLE) AS duration_seconds"
    )

    try:
        df = execute_query(f"""
            SELECT
                {run_id_col}            AS run_id,
                {date_col}              AS business_date,
                {dur_expr},
                {status_col}            AS overall_status,
                COALESCE({checks_col}, 0) AS checks_run
            FROM {table}
            WHERE {date_col} BETWEEN :date_from AND :date_to
            ORDER BY {date_col} DESC
        """, {"date_from": date_from, "date_to": date_to})

        if df.empty:
            return pd.DataFrame()

        df["agent_key"]   = agent["key"]
        df["agent_label"] = agent["label"]
        df["agent_icon"]  = agent["icon"]
        df["agent_color"] = agent["color_light"]

        # Compute cost per run
        df["duration_seconds"] = pd.to_numeric(
            df["duration_seconds"], errors="coerce"
        ).fillna(0)

        df["duration_hours"] = df["duration_seconds"] / 3600
        df["dbus_consumed"]  = df["duration_hours"] * dbu_per_hour
        df["cost_usd"]       = df["dbus_consumed"] * dbu_price

        return df

    except Exception as e:
        logger.error(f"Failed to load runs for {agent['key']}: {e}")
        return pd.DataFrame()


def _load_all_runs(
    date_from    : str,
    date_to      : str,
    dbu_per_hour : float,
    dbu_price    : float
) -> pd.DataFrame:
    """Loads and combines runs from all four agents."""
    frames = []
    for agent in AGENTS:
        df = _load_agent_runs(
            agent, date_from, date_to, dbu_per_hour, dbu_price
        )
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def _compute_app_cost(
    date_from    : str,
    date_to      : str,
    app_per_hour : float   # kept as parameter for fallback only
) -> dict:
    """
    Computes DataSentinel App cost from system.billing.usage.
    Covers all three app name iterations:
      agent1-admin-ui          (2026-06-24 to 2026-07-01)
      data-trust-layer-admin-ui (2026-07-02 to 2026-07-21)
      data-sentinel             (2026-07-21 onwards)

    Uses actual DBU consumption × APP_SKU_PRICE ($0.95/DBU).
    Falls back to hourly estimate if system tables unavailable.
    """
    try:
        df = execute_query(f"""
            SELECT
                usage_metadata.app_name          AS app_name,
                usage_date,
                SUM(usage_quantity)              AS dbus,
                MIN(usage_start_time)            AS first_usage,
                MAX(usage_end_time)              AS last_usage
            FROM system.billing.usage
            WHERE record_type              = 'ORIGINAL'
              AND billing_origin_product   = 'APPS'
              AND usage_metadata.app_id   IN ({APP_IDS_SQL})
              AND usage_date BETWEEN :date_from AND :date_to
            GROUP BY
                usage_metadata.app_name,
                usage_date
            ORDER BY usage_date DESC
        """, {"date_from": date_from, "date_to": date_to})

        if df.empty:
            # Fallback — no billing data yet for this period
            logger.warning(
                "No app billing data found in system.billing.usage "
                "for date range. Using hourly estimate fallback."
            )
            start = date.fromisoformat(date_from)
            end   = date.fromisoformat(date_to)
            days  = (end - start).days + 1
            hours = days * 24
            cost  = hours * app_per_hour
            return {
                "days"       : days,
                "hours"      : hours,
                "total_dbus" : 0.0,
                "cost"       : round(cost, 2),
                "source"     : "estimate",
                "daily_df"   : None,
            }

        total_dbus = float(df["dbus"].sum())
        cost       = total_dbus * APP_SKU_PRICE
        days_active= df["usage_date"].nunique()

        # Compute hours from DBUs
        # PREMIUM_ALL_PURPOSE_SERVERLESS_COMPUTE: 1 DBU = 1 hour
        # (serverless apps bill at 1 DBU/hr per compute unit)
        hours = total_dbus  # 1 DBU ≈ 1 compute-hour for Apps SKU

        return {
            "days"       : days_active,
            "hours"      : round(hours, 2),
            "total_dbus" : round(total_dbus, 4),
            "cost"       : round(cost, 4),
            "source"     : "billing",
            "daily_df"   : df,
        }

    except Exception as e:
        logger.error(f"App cost from billing failed: {e}. Using estimate.")
        try:
            start = date.fromisoformat(date_from)
            end   = date.fromisoformat(date_to)
            days  = (end - start).days + 1
            hours = days * 24
            cost  = hours * app_per_hour
        except Exception:
            days, hours, cost = 0, 0, 0.0

        return {
            "days"       : days,
            "hours"      : hours,
            "total_dbus" : 0.0,
            "cost"       : round(cost, 2),
            "source"     : "estimate",
            "daily_df"   : None,
        }


# ── Summary card ───────────────────────────────────────────────────────────

def _summary_card(
    icon       : str,
    label      : str,
    runs       : int,
    hours      : float,
    dbus       : float,
    cost       : float,
    border_color: str,
    bg_color   : str = "#0a1520",
) -> dbc.Col:
    return dbc.Col(
        html.Div([
            html.Div([
                html.Span(icon, style={"fontSize": "20px", "marginRight": "8px"}),
                html.Span(
                    label,
                    style={
                        "color"    : "#ffffff",
                        "fontSize" : "13px",
                        "fontWeight": "600",
                    }
                ),
            ], style={"marginBottom": "12px"}),

            # Cost — large number
            html.Div(
                _fmt_currency(cost),
                style={
                    "color"     : "#ffffff",
                    "fontSize"  : "28px",
                    "fontWeight": "800",
                    "fontFamily": "monospace",
                    "marginBottom": "8px",
                }
            ),

            # Stats row
            html.Div([
                html.Div([
                    html.Span(
                        str(runs),
                        style={"color": "#4a9edd", "fontWeight": "700",
                               "fontSize": "14px"}
                    ),
                    html.Span(
                        " runs",
                        style={"color": "#64748b", "fontSize": "12px"}
                    ),
                ], style={"marginBottom": "4px"}),
                html.Div([
                    html.Span(
                        f"{hours:,.2f}",
                        style={"color": "#aaaaaa", "fontSize": "12px",
                               "fontFamily": "monospace"}
                    ),
                    html.Span(
                        " hrs",
                        style={"color": "#64748b", "fontSize": "12px"}
                    ),
                ], style={"marginBottom": "4px"}),
                html.Div([
                    html.Span(
                        f"{dbus:,.2f}",
                        style={"color": "#aaaaaa", "fontSize": "12px",
                               "fontFamily": "monospace"}
                    ),
                    html.Span(
                        " DBUs",
                        style={"color": "#64748b", "fontSize": "12px"}
                    ),
                ]),
            ]),
        ], style={
            "backgroundColor": bg_color,
            "border"         : f"1px solid {border_color}",
            "borderLeft"     : f"4px solid {border_color}",
            "borderRadius"   : "8px",
            "padding"        : "16px 20px",
            "height"         : "100%",
        }),
        md=2, className="mb-3"
    )


# ── Trend chart ────────────────────────────────────────────────────────────

def _build_trend_chart(
    all_runs : pd.DataFrame,
    app_cost : dict = None
) -> dcc.Graph:
    """
    Stacked bar chart — daily cost by agent + app.
    """
    # ── Build agent daily costs ────────────────────────────────────────────
    agent_daily_cost = {}   # {date_str: {agent_label: cost}}

    if not all_runs.empty:
        runs = all_runs.copy()
        runs["business_date"] = pd.to_datetime(
            runs["business_date"]
        ).dt.date.astype(str)

        daily = (
            runs.groupby(["business_date", "agent_label"])["cost_usd"]
            .sum()
            .reset_index()
        )

        for _, row in daily.iterrows():
            d = str(row["business_date"])
            if d not in agent_daily_cost:
                agent_daily_cost[d] = {}
            agent_daily_cost[d][row["agent_label"]] = float(row["cost_usd"])

    # ── Build app daily costs ──────────────────────────────────────────────
    app_daily_cost = {}   # {date_str: cost}

    if app_cost and app_cost.get("daily_df") is not None:
        app_df = app_cost["daily_df"].copy()
        app_df["usage_date"] = app_df["usage_date"].astype(str)
        for _, row in app_df.iterrows():
            d    = str(row["usage_date"])
            dbus = float(row["dbus"] or 0)
            cost = dbus * APP_SKU_PRICE
            app_daily_cost[d] = app_daily_cost.get(d, 0) + cost

    # ── Combine all dates ──────────────────────────────────────────────────
    all_dates = sorted(
        set(agent_daily_cost.keys()) | set(app_daily_cost.keys())
    )

    if not all_dates:
        return html.P(
            "No data available for the selected date range.",
            className="text-muted"
        )

    # ── Build figure ───────────────────────────────────────────────────────
    fig = go.Figure()

    # Agent bars
    for agent in AGENTS:
        label  = agent["label"]
        color  = agent["color_light"]
        costs  = [
            round(agent_daily_cost.get(d, {}).get(label, 0), 6)
            for d in all_dates
        ]

        # Skip agents with all-zero costs to keep chart clean
        if sum(costs) == 0:
            continue

        fig.add_trace(go.Bar(
            name          = f"{agent['icon']} {label}",
            x             = all_dates,
            y             = costs,
            marker_color  = color,
            hovertemplate = (
                f"<b>{agent['icon']} {label}</b><br>"
                f"Date: %{{x}}<br>"
                f"Cost: $%{{y:.6f}}<extra></extra>"
            )
        ))

    # App bar
    if app_daily_cost:
        app_costs = [
            round(app_daily_cost.get(d, 0), 4)
            for d in all_dates
        ]

        # Only add if any non-zero
        if sum(app_costs) > 0:
            fig.add_trace(go.Bar(
                name          = "⚡ DataSentinel App",
                x             = all_dates,
                y             = app_costs,
                marker_color  = "#87ceeb",
                hovertemplate = (
                    "<b>⚡ DataSentinel App</b><br>"
                    "Date: %{x}<br>"
                    "Cost: $%{y:.4f} (actual DBUs)<extra></extra>"
                )
            ))

    fig.update_layout(
        barmode       = "stack",
        height        = 320,
        paper_bgcolor = "#2b2b2b",
        plot_bgcolor  = "#2b2b2b",
        font          = dict(color="#aaaaaa", size=12),
        legend        = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.02,
            xanchor     = "left",
            x           = 0,
            font        = dict(size=11)
        ),
        margin        = dict(l=60, r=20, t=60, b=60),
        xaxis         = dict(
            gridcolor = "#333333",
            tickcolor = "#555555",
            linecolor = "#444444",
            tickangle = -45,
            tickfont  = dict(color="#aaaaaa", size=10),
            type      = "category",   # treat dates as categories
                                      # avoids gaps for missing dates
        ),
        yaxis         = dict(
            gridcolor  = "#333333",
            tickcolor  = "#555555",
            linecolor  = "#444444",
            tickprefix = "$",
            tickfont   = dict(color="#aaaaaa", size=10),
            title_text = "Cost (USD)"
        ),
        hovermode = "x unified",
    )

    return dcc.Graph(
        figure = fig,
        config = {"displayModeBar": False}
    )

# ── Efficiency chart ───────────────────────────────────────────────────────

def _build_efficiency_chart(all_runs: pd.DataFrame) -> dcc.Graph:
    """
    Horizontal bar — cost per check per agent.
    Lower = more efficient.
    """
    if all_runs.empty:
        return html.P("No data.", className="text-muted")

    agent_summary = (
        all_runs.groupby("agent_label")
        .agg(
            total_cost   = ("cost_usd",   "sum"),
            total_checks = ("checks_run", "sum"),
            agent_color  = ("agent_color", "first"),
            agent_icon   = ("agent_icon",  "first"),
        )
        .reset_index()
    )

    agent_summary["cost_per_check"] = (
        agent_summary["total_cost"] /
        agent_summary["total_checks"].replace(0, float("nan"))
    )
    agent_summary = agent_summary.dropna(subset=["cost_per_check"])
    agent_summary = agent_summary.sort_values(
        "cost_per_check", ascending=True
    )

    if agent_summary.empty:
        return html.P("No check data available.", className="text-muted")

    # ── Determine display unit ─────────────────────────────────────────────
    max_cost = float(agent_summary["cost_per_check"].max())

    if max_cost < 0.001:
        unit_symbol = "µ$"
        unit_label  = "µ$ (micro-dollars)"
        multiplier  = 1_000_000
    elif max_cost < 1.0:
        unit_symbol = "¢"
        unit_label  = "¢ (cents)"
        multiplier  = 100
    else:
        unit_symbol = "$"
        unit_label  = "$ (USD)"
        multiplier  = 1

    # ── Scale values ───────────────────────────────────────────────────────
    scaled = [
        float(v) * multiplier
        for v in agent_summary["cost_per_check"]
    ]
    labels = [
        f"{v:,.2f} {unit_symbol}"
        for v in scaled
    ]
    y_labels = [
        f"{row['agent_icon']} {row['agent_label']}"
        for _, row in agent_summary.iterrows()
    ]
    colors = agent_summary["agent_color"].tolist()

    hover_texts = []
    for i, (_, row) in enumerate(agent_summary.iterrows()):
        hover_texts.append(
            f"<b>{row['agent_icon']} {row['agent_label']}</b><br>"
            f"Cost per check: {scaled[i]:,.2f} {unit_symbol}<br>"
            f"Total checks: {int(row['total_checks']):,}<br>"
            f"Total cost: ${float(row['total_cost']):.6f}"
        )

    # ── Build figure using plain numbers on x-axis ─────────────────────────
    # We do NOT use tickvals/ticktext — instead we use tickprefix/ticksuffix
    # on already-scaled data so Plotly renders e.g. "573.65 µ$" naturally

    fig = go.Figure(go.Bar(
        x            = scaled,
        y            = y_labels,
        orientation  = "h",
        marker_color = colors,
        text         = labels,
        textposition = "outside",
        textfont     = dict(
            color  = "#ffffff",
            size   = 13,
            family = "monospace"
        ),
        hovertext    = hover_texts,
        hoverinfo    = "text",
        cliponaxis   = False,
    ))

    max_scaled = max(scaled) if scaled else 1

    fig.update_layout(
        height        = 240,
        paper_bgcolor = "#2b2b2b",
        plot_bgcolor  = "#2b2b2b",
        font          = dict(color="#aaaaaa", size=12),
        margin        = dict(l=220, r=140, t=20, b=60),
        xaxis         = dict(
            gridcolor    = "#333333",
            tickcolor    = "#555555",
            linecolor    = "#444444",
            tickfont     = dict(color="#aaaaaa", size=11),
            title_text   = f"Cost per Check ({unit_label})",
            title_font   = dict(color="#aaaaaa", size=12),
            range        = [0, max_scaled * 1.3],
            tickvals     = [
                round(max_scaled * i / 5, 2)
                for i in range(7)
            ],
            ticktext     = [
                f"{round(max_scaled * i / 5, 0):,.0f} {unit_symbol}"
                for i in range(7)
            ],
            showgrid     = True,
            zeroline     = True,
            zerolinecolor= "#444444",
        ),
        yaxis = dict(
            tickfont  = dict(color="#ffffff", size=13),
            linecolor = "#444444",
            autorange = "reversed",
        ),
        bargap    = 0.3,
        hovermode = "closest",
    )

    return dcc.Graph(
        figure = fig,
        config = {"displayModeBar": False}
    )

# ── Run detail table ───────────────────────────────────────────────────────

def _build_run_table(all_runs: pd.DataFrame) -> dag.AgGrid:
    """
    Detailed run-level cost breakdown table.
    """
    rows = []
    for _, r in all_runs.iterrows():
        status = str(r.get("overall_status", "") or "")
        rows.append({
            "business_date"  : str(r.get("business_date", "")),
            "agent"          : f"{r.get('agent_icon','')} {r.get('agent_label','')}",
            "overall_status" : status,
            "checks_run"     : int(r.get("checks_run") or 0),
            "duration_sec"   : _fmt_number(r.get("duration_seconds"), 1),
            "duration_hrs"   : _fmt_number(r.get("duration_hours"), 4),
            "dbus_consumed"  : _fmt_number(r.get("dbus_consumed"), 4),
            "cost_usd"       : _fmt_currency(r.get("cost_usd")),
        })

    # Sort by date desc then agent
    rows = sorted(rows, key=lambda x: x["business_date"], reverse=True)

    return dag.AgGrid(
        **ag_grid_props(
            grid_id="cost-run-detail-grid",
            row_data=rows,
            col_defs=[
                {"field": "business_date",  "headerName": "Date",       "minWidth": 120},
                {"field": "agent",          "headerName": "Pipeline",      "flex": 2, "minWidth": 220},
                {"field": "overall_status", "headerName": "Status",     "minWidth": 150,
                 "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                {"field": "checks_run",     "headerName": "Checks",        "width": 90},
                {"field": "duration_sec",   "headerName": "Duration (s)",  "width": 110},
                {"field": "duration_hrs",   "headerName": "Duration (hr)", "width": 120},
                {"field": "dbus_consumed",  "headerName": "DBUs",          "width": 110},
                {"field": "cost_usd",       "headerName": "Cost (USD)",    "width": 110},
            ],
            page_size=20,
            status_col="overall_status",
        )
    )


# ── Main page builder ──────────────────────────────────────────────────────

def _build_page(
    date_from    : str,
    date_to      : str,
    dbu_price    : float,
    dbu_per_hour : float,
    app_per_hour : float
) -> html.Div:

    all_runs = _load_all_runs(date_from, date_to, dbu_per_hour, dbu_price)
    app_cost = _compute_app_cost(date_from, date_to, app_per_hour)

    elements = []

    # ── Date range header ──────────────────────────────────────────────────
    elements.append(
        html.Div([
            html.Span(
                f"📅 {date_from}  →  {date_to}",
                style={
                    "color"    : "#4a9edd",
                    "fontSize" : "13px",
                    "fontFamily": "monospace"
                }
            ),
            html.Span(
                f"  ·  DBU price ${dbu_price}/DBU  ·  "
                f"{dbu_per_hour} DBU/hr  ·  "
                f"App ${app_per_hour}/hr",
                style={"color": "#64748b", "fontSize": "12px"}
            ),
        ], style={"marginBottom": "20px"})
    )

    # ── Summary cards ──────────────────────────────────────────────────────
    if all_runs.empty:
        elements.append(
            dbc.Alert(
                f"No pipeline runs found between {date_from} and {date_to}. "
                "Ensure agents have been run for this period.",
                color="warning"
            )
        )
        return html.Div(elements)

    # Per-agent summaries
    summary_cards = []
    total_cost    = 0.0
    total_dbus    = 0.0
    total_hours   = 0.0
    total_runs    = 0

    for agent in AGENTS:
        agent_df = all_runs[all_runs["agent_key"] == agent["key"]]
        if agent_df.empty:
            runs  = 0
            hours = 0.0
            dbus  = 0.0
            cost  = 0.0
        else:
            runs  = len(agent_df)
            hours = float(agent_df["duration_hours"].sum())
            dbus  = float(agent_df["dbus_consumed"].sum())
            cost  = float(agent_df["cost_usd"].sum())

        total_runs  += runs
        total_hours += hours
        total_dbus  += dbus
        total_cost  += cost

        summary_cards.append(
            _summary_card(
                icon         = agent["icon"],
                label        = agent["label"],
                runs         = runs,
                hours        = hours,
                dbus         = dbus,
                cost         = cost,
                border_color = agent["color_light"],
            )
        )

    # App card
    total_cost += app_cost["cost"]
    app_source_label = (
        "from system.billing.usage"
        if app_cost.get("source") == "billing"
        else "estimated (no billing data)"
    )
    summary_cards.append(
        _summary_card(
            icon         = "⚡",
            label        = f"DataSentinel App",
            runs         = app_cost["days"],
            hours        = app_cost["hours"],
            dbus         = app_cost.get("total_dbus", 0.0),
            cost         = app_cost["cost"],
            border_color = "#87ceeb",
        )
    )

    # Total card
    summary_cards.append(
        _summary_card(
            icon         = "💰",
            label        = "Total — All Pipelines",
            runs         = total_runs,
            hours        = total_hours,
            dbus         = total_dbus,
            cost         = total_cost,
            border_color = "#ffffff",
            bg_color     = "#0f2035",
        )
    )

    elements.append(
        html.H5(
            "Cost Summary",
            style={
                "color"       : "#ffffff",
                "fontSize"    : "16px",
                "fontWeight"  : "700",
                "marginBottom": "12px",
            }
        )
    )
    elements.append(
        dbc.Row(summary_cards, className="mb-4")
    )

    # ── Trend chart ────────────────────────────────────────────────────────
    elements.append(
        dbc.Card([
            dbc.CardHeader(
                html.H6("📈 Daily Cost Trend", className="mb-0 text-white")
            ),
            dbc.CardBody([
                _build_trend_chart(all_runs, app_cost)
            ])
        ], className="mb-4",
        style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})
    )

    # ── Efficiency chart ───────────────────────────────────────────────────
    elements.append(
        dbc.Card([
            dbc.CardHeader(
                html.H6(
                    "⚡ Cost Efficiency — Cost per Check by Agent",
                    className="mb-0 text-white"
                )
            ),
            dbc.CardBody([
                html.P(
                    "Lower cost per check = more efficient pipeline. "
                    "Values auto-scaled to most readable unit (µ$, ¢, or $). "
                    "Transformation Agent (SQL Review) shows $0 — no duration column available.",
                    className="text-muted small mb-3"
                ),
                _build_efficiency_chart(all_runs)
            ])
        ], className="mb-4",
        style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})
    )

    # ── Run detail table ───────────────────────────────────────────────────
    elements.append(
        dbc.Card([
            dbc.CardHeader(
                html.H6(
                    f"🔍 Run-Level Detail ({len(all_runs)} runs)",
                    className="mb-0 text-white"
                )
            ),
            dbc.CardBody([
                html.P(
                    "Transformation Agent (SQL Review) shows $0.00 — "
                    "no duration column available in uc3_review_results_b.",
                    className="text-muted small mb-3"
                ),
                _build_run_table(all_runs)
            ])
        ], className="mb-4",
        style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})
    )

    # ── Assumptions footnote ───────────────────────────────────────────────
    app_source_note = (
        f"DataSentinel App cost sourced from system.billing.usage "
        f"(actual DBUs × $0.95/DBU — PREMIUM_ALL_PURPOSE_SERVERLESS_COMPUTE_US_EAST_2). "
        f"Covers app_ids: agent1-admin-ui, data-trust-layer-admin-ui, data-sentinel."
        if app_cost.get("source") == "billing"
        else
        f"DataSentinel App cost is an estimate (${app_per_hour}/hr × hours in period). "
        f"No billing data found in system.billing.usage for this date range."
    )

    elements.append(
        html.Div([
            html.Hr(style={"borderColor": "#333"}),
            html.P([
                html.Strong("Assumptions: ", style={"color": "#aaaaaa"}),
                html.Span(
                    f"Pipeline costs calculated as: (duration_seconds ÷ 3600) × "
                    f"{dbu_per_hour} DBU/hr × ${dbu_price}/DBU. "
                    f"Cluster node type: Standard_E8as_v4. "
                    f"{app_source_note}",
                    style={"color": "#64748b", "fontSize": "12px"}
                )
            ])
        ])
    )

    return html.Div(elements)


# ── Preset date callbacks ──────────────────────────────────────────────────

@callback(
    Output("cost-date-range", "start_date"),
    Output("cost-date-range", "end_date"),
    Input("cost-preset-7",  "n_clicks"),
    Input("cost-preset-30", "n_clicks"),
    Input("cost-preset-90", "n_clicks"),
    prevent_initial_call=True,
)
def apply_preset(n7, n30, n90):
    from dash import ctx
    today = date.today()
    triggered = ctx.triggered_id

    if triggered == "cost-preset-7":
        return str(today - timedelta(days=7)),  str(today)
    if triggered == "cost-preset-30":
        return str(today - timedelta(days=30)), str(today)
    if triggered == "cost-preset-90":
        return str(today - timedelta(days=90)), str(today)

    return str(today - timedelta(days=DEFAULT_DAYS)), str(today)


# ── Main callback ──────────────────────────────────────────────────────────

@callback(
    Output("cost-alert",        "children"),
    Output("cost-main-content", "children"),
    Input("cost-calculate-btn", "n_clicks"),
    State("cost-date-range",    "start_date"),
    State("cost-date-range",    "end_date"),
    State("cost-dbu-price",     "value"),
    State("cost-dbu-per-hour",  "value"),
    State("cost-app-per-hour",  "value"),
    prevent_initial_call=True,
)
def calculate_cost(
    n_clicks,
    start_date,
    end_date,
    dbu_price,
    dbu_per_hour,
    app_per_hour
):
    if not n_clicks:
        return "", html.Div()

    # Validate inputs
    if not start_date or not end_date:
        return (
            dbc.Alert("Please select a date range.", color="warning"),
            html.Div()
        )

    try:
        dbu_price    = float(dbu_price    or DEFAULT_DBU_PRICE)
        dbu_per_hour = float(dbu_per_hour or DEFAULT_DBU_PER_HOUR)
        app_per_hour = float(app_per_hour or DEFAULT_APP_COST)
    except (TypeError, ValueError):
        return (
            dbc.Alert("Invalid numeric input.", color="danger"),
            html.Div()
        )

    try:
        return "", _build_page(
            date_from    = start_date,
            date_to      = end_date,
            dbu_price    = dbu_price,
            dbu_per_hour = dbu_per_hour,
            app_per_hour = app_per_hour,
        )
    except Exception as e:
        logger.error(f"Cost page failed: {e}")
        import traceback
        traceback.print_exc()
        return (
            dbc.Alert(f"Error: {str(e)}", color="danger"),
            html.Div()
        )