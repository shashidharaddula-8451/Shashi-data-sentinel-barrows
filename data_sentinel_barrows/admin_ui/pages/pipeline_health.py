# pages/pipeline_health.py

import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import date, datetime, timedelta
import math
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
import dash_ag_grid as dag
from components.alerts import ag_grid_props, AG_STATUS_CELL_STYLE_JS

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path  = "/pipeline-health",
    name  = "Pipeline Health"
)

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

# ── Pipeline definitions ───────────────────────────────────────────────────

# ── Baseline window ────────────────────────────────────────────────────────
# The clean historical period used to compute "normal" behaviour.
# Excludes controlled anomaly dates and any dates with injected failures.
# Update these if the pilot data changes.

BASELINE_WINDOW_START = "2026-05-19"
BASELINE_WINDOW_END   = "2026-06-17"

# Fallback colour palette assigned by registration order, since colour is not
# a registry attribute. Cycled if more pipelines are registered than colours.
_COLOR_PALETTE = [
    ("#375a7f", "#4a9edd"),
    ("#2d6a4f", "#00c851"),
    ("#7c4a9e", "#b46eea"),
    ("#9e4a4a", "#ea6e6e"),
    ("#9e8a4a", "#eac86e"),
]

DEFAULT_SLA_MINUTES = 120


def _load_pipelines() -> dict:
    """
    Builds pipeline definitions at runtime from uc1_table_registry_b, so any
    table onboarded through the wizard automatically appears here instead of
    requiring a hardcoded dict entry.
    """
    try:
        df = execute_query(f"""
            SELECT
                table_id,
                table_name,
                fully_qualified_name,
                business_date_column,
                source_type,
                ingestion_pattern,
                ingestion_frequency,
                expected_arrival_window_minutes
            FROM {CATALOG}.{SCHEMA}.uc1_table_registry_b
            WHERE is_active = true
            ORDER BY table_name
        """)
    except Exception as e:
        logger.error(f"Pipeline registry load failed: {e}")
        return {}

    if df.empty:
        return {}

    pipelines = {}
    for i, row in df.reset_index(drop=True).iterrows():
        color, color_light = _COLOR_PALETTE[i % len(_COLOR_PALETTE)]
        table_name = str(row["table_name"])
        sla = row.get("expected_arrival_window_minutes")
        pipelines[str(row["table_id"])] = {
            "fqn"        : row["fully_qualified_name"],
            "label"      : " ".join(w.capitalize() for w in table_name.split("_")) + " Pipeline",
            "date_col"   : row.get("business_date_column") or "business_date",
            "source_type": row.get("source_type") or "—",
            "pattern"    : row.get("ingestion_pattern") or "—",
            "frequency"  : row.get("ingestion_frequency") or "—",
            "sla_minutes": int(sla) if sla is not None and not pd.isna(sla) else DEFAULT_SLA_MINUTES,
            "color"      : color,
            "color_light": color_light,
        }
    return pipelines

STATUS_COLOR = {
    "CRITICAL": "#ff6b6b",
    "WARNING" : "#ffa500",
    "PASS"    : "#00c851",
    "UNKNOWN" : "#aaaaaa",
}

STATUS_BG = {
    "CRITICAL": "#3d0000",
    "WARNING" : "#3d2000",
    "PASS"    : "#002800",
    "UNKNOWN" : "#1a1a1a",
}

STATUS_EMOJI = {
    "CRITICAL": "🔴",
    "WARNING" : "🟡",
    "PASS"    : "🟢",
    "UNKNOWN" : "⚪",
}

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    dcc.Interval(
        id          = "ph-refresh-interval",
        interval    = 5 * 60 * 1000,
        n_intervals = 0,
        disabled    = True
    ),

    dcc.Store(id="ph-refresh-paused", data=True),

    html.H2(
        "Pipeline Health",
        className = "mt-4 mb-1"
    ),
    html.P(
        "Daily ingestion pipeline status, reliability trends, "
        "and failure history for all registered data pipelines.",
        className = "text-muted mb-4",
        style     = {"fontSize": "15px"}
    ),
    dbc.Row([
        dbc.Col([
            html.Div(
                id    = "ph-refresh-indicator",
                style = {"color": "#64748b", "fontSize": "12px",
                        "marginBottom": "8px"}
            )
        ], md=8),
        dbc.Col([
            dbc.Button(
                "⏸ Pause Auto-Refresh",
                id       = "ph-refresh-toggle",
                color    = "secondary",
                outline  = True,
                size     = "sm",
                n_clicks = 0,
                style    = {"fontSize": "12px"}
            )
        ], md=4, className="d-flex justify-content-end mb-2"),
    ]),

    dcc.Loading(
        id    = "ph-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="ph-page-content")
    )

], fluid=True)


# ── Data loading ───────────────────────────────────────────────────────────

def _load_pipeline_runs(fqns: list, days: int = 60) -> pd.DataFrame:
    if not fqns:
        return pd.DataFrame()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    params = {f"fqn_{i}": fqn for i, fqn in enumerate(fqns)}
    params["cutoff"] = cutoff
    in_clause = ", ".join(f":fqn_{i}" for i in range(len(fqns)))
    try:
        df = execute_query(f"""
            SELECT
                validation_run_id,
                fully_qualified_name,
                business_date,
                overall_status,
                total_checks_run,
                total_checks_passed,
                total_checks_warned,
                total_checks_critical,
                ROUND(validation_duration_seconds, 1) AS duration_sec,
                created_timestamp,
                ai_enrichment_status
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE fully_qualified_name IN ({in_clause})
              AND business_date >= :cutoff
            ORDER BY business_date DESC, fully_qualified_name
        """, params)
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Pipeline runs load failed: {e}")
        return pd.DataFrame()


def _load_check_detail(fqns: list, days: int = 60) -> pd.DataFrame:
    if not fqns:
        return pd.DataFrame()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    params = {f"fqn_{i}": fqn for i, fqn in enumerate(fqns)}
    params["cutoff"] = cutoff
    in_clause = ", ".join(f":fqn_{i}" for i in range(len(fqns)))
    try:
        df = execute_query(f"""
            SELECT
                r.fully_qualified_name,
                r.business_date,
                r.check_type,
                r.check_level,
                r.column_name,
                r.check_status,
                ROUND(r.observed_value, 4)       AS observed_value,
                ROUND(r.baseline_value, 4)       AS baseline_value,
                ROUND(r.deviation_percentage, 2) AS deviation_pct,
                r.threshold_warning,
                r.threshold_critical,
                r.ai_summary,
                run.validation_run_id
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
              ON r.validation_run_id = run.validation_run_id
            WHERE r.fully_qualified_name IN ({in_clause})
              AND r.check_status IN ('CRITICAL', 'WARNING')
              AND r.business_date >= :cutoff
            ORDER BY r.business_date DESC, r.check_status
        """, params)
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Check detail load failed: {e}")
        return pd.DataFrame()


def _load_volume_history(cfg: dict, days: int = 30) -> pd.DataFrame:
    """
    Loads daily row counts directly from the raw table.

    Uses the raw table itself as the spine — this captures ALL dates
    including gap dates that have raw data but no agent validation runs.
    Zero-row dates (like July 19) still appear because uc1_validation_run_b
    is used as a supplementary spine for dates where the pipeline ran
    but produced nothing.
    """
    fqn      = cfg["fqn"]
    date_col = cfg["date_col"]

    try:
        df = execute_query(f"""
            SELECT
                all_dates.business_date,
                COALESCE(raw.row_count, 0) AS row_count
            FROM (
                -- Primary spine: actual dates in raw table
                SELECT DISTINCT {date_col} AS business_date
                FROM {fqn}

                UNION

                -- Supplementary spine: dates where agent ran but
                -- raw table had zero rows (e.g. July 19)
                SELECT DISTINCT business_date
                FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
                WHERE fully_qualified_name = :fqn
            ) all_dates
            LEFT JOIN (
                SELECT
                    {date_col}  AS business_date,
                    COUNT(*)    AS row_count
                FROM {fqn}
                GROUP BY {date_col}
            ) raw
              ON all_dates.business_date = raw.business_date
            ORDER BY all_dates.business_date DESC
            LIMIT {int(days) + 30}
        """, {"fqn": fqn})

        if df.empty:
            return pd.DataFrame()

        df["business_date"] = pd.to_datetime(df["business_date"])
        df["row_count"]     = pd.to_numeric(
            df["row_count"], errors="coerce"
        ).fillna(0).astype(int)

        return df.sort_values("business_date")

    except Exception as e:
        logger.error(
            f"Volume history load failed for {fqn}: {e}"
        )
        return pd.DataFrame()


def _load_arrival_times(cfg: dict, days: int = 60) -> pd.DataFrame:
    fqn      = cfg["fqn"]
    date_col = cfg["date_col"]
    cutoff   = (date.today() - timedelta(days=days)).isoformat()

    try:
        df = execute_query(f"""
            SELECT
                {date_col}               AS business_date,
                MIN(ingestion_timestamp) AS first_record,
                MAX(ingestion_timestamp) AS last_record,
                COUNT(*)                 AS row_count
            FROM {fqn}
            WHERE {date_col} >= :cutoff
            GROUP BY {date_col}
            ORDER BY {date_col} DESC
        """, {"cutoff": cutoff})
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Arrival time load failed for {fqn}: {e}")
        return pd.DataFrame()


# ── Computation helpers ────────────────────────────────────────────────────

def _compute_reliability_metrics(
    runs_df  : pd.DataFrame,
    checks_df: pd.DataFrame,
    fqn      : str,
) -> dict:
    """Computes 60-day reliability metrics for one pipeline."""
    pipe_runs   = (
        runs_df[runs_df["fully_qualified_name"] == fqn]
        if not runs_df.empty else pd.DataFrame()
    )
    pipe_checks = (
        checks_df[checks_df["fully_qualified_name"] == fqn]
        if not checks_df.empty else pd.DataFrame()
    )

    total_runs = len(pipe_runs)
    if total_runs == 0:
        return {
            "total_runs"      : 0,
            "success_rate"    : None,
            "most_common_fail": "—",
            "avg_duration"    : None,
        }

    pass_runs    = len(pipe_runs[pipe_runs["overall_status"] == "PASS"])
    success_rate = round(pass_runs / total_runs * 100, 1)

    most_common = "—"
    if not pipe_checks.empty:
        mode = pipe_checks["check_type"].mode()
        most_common = mode.iloc[0] if not mode.empty else "—"

    avg_dur = None
    if "duration_sec" in pipe_runs.columns:
        raw_dur = pipe_runs["duration_sec"].mean()
        try:
            f = float(raw_dur)
            avg_dur = None if math.isnan(f) else round(f, 1)
        except (TypeError, ValueError):
            avg_dur = None

    return {
        "total_runs"      : total_runs,
        "success_rate"    : success_rate,
        "most_common_fail": most_common,
        "avg_duration"    : avg_dur,
    }


def _get_latest_run(runs_df: pd.DataFrame, fqn: str) -> dict:
    """Returns the most recent run record for a pipeline."""
    if runs_df.empty:
        return {}
    pipe = runs_df[runs_df["fully_qualified_name"] == fqn]
    if pipe.empty:
        return {}
    return pipe.sort_values("business_date", ascending=False).iloc[0].to_dict()


def _fmt_timestamp(ts) -> str:
    if ts is None:
        return "—"
    try:
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        now      = datetime.now()
        time_str = ts.strftime("%H:%M")
        if ts.date() == now.date():
            return f"{time_str} today"
        return f"{time_str} on {ts.strftime('%-d %b')}"
    except Exception:
        return str(ts)


def _safe_float(val) -> float:
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ── Section 1: Current status cards ───────────────────────────────────────

def _build_status_card(
    cfg         : dict,
    runs_df     : pd.DataFrame,
    checks_df   : pd.DataFrame,
    arrivals_df : pd.DataFrame,
) -> dbc.Col:

    fqn    = cfg["fqn"]
    latest = _get_latest_run(runs_df, fqn)

    if not latest:
        status      = "UNKNOWN"
        latest_date = "No runs found"
    else:
        status      = str(latest.get("overall_status", "UNKNOWN"))
        latest_date = str(latest.get("business_date", ""))[:10]

    color = STATUS_COLOR.get(status, STATUS_COLOR["UNKNOWN"])
    bg    = STATUS_BG.get(status, STATUS_BG["UNKNOWN"])
    emoji = STATUS_EMOJI.get(status, "⚪")

    # ── Volume info ────────────────────────────────────────────────────────
    volume_obs = None
    volume_dev = None

    if latest_date and latest_date != "No runs found":
        try:
            vol_df = execute_query(f"""
                SELECT
                    ROUND(r.observed_value, 0)       AS observed_value,
                    ROUND(r.deviation_percentage, 1) AS deviation_pct
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
                JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
                  ON r.validation_run_id = run.validation_run_id
                WHERE run.fully_qualified_name = :fqn
                  AND run.business_date        = :latest_date
                  AND r.check_type             = 'VOLUME_ANOMALY'
                ORDER BY
                    CASE r.check_status
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'WARNING'  THEN 2
                        ELSE 3
                    END
                LIMIT 1
            """, {"fqn": fqn, "latest_date": latest_date})
            if not vol_df.empty:
                volume_obs = _safe_float(vol_df.iloc[0]["observed_value"])
                volume_dev = _safe_float(vol_df.iloc[0]["deviation_pct"])
        except Exception as e:
            logger.error(f"Volume query failed for {fqn}: {e}")

    # ── Worst check for latest date ────────────────────────────────────────
    worst_check = "—"
    if not checks_df.empty and latest_date:
        day_checks = checks_df[
            (checks_df["fully_qualified_name"] == fqn) &
            (checks_df["business_date"].astype(str).str[:10] == latest_date)
        ]
        if not day_checks.empty:
            crit = day_checks[day_checks["check_status"] == "CRITICAL"]
            worst_check = (
                str(crit.iloc[0]["check_type"])
                if not crit.empty
                else str(day_checks.iloc[0]["check_type"])
            )

    # ── Arrival time and SLA ───────────────────────────────────────────────
    arrival_str = "—"
    sla_minutes = cfg["sla_minutes"]
    sla_badge   = html.Span(
        "—",
        style={"color": "#555555", "fontSize": "13px"}
    )

    if not arrivals_df.empty:
        try:
            latest_arr = arrivals_df.sort_values(
                "business_date", ascending=False
            ).iloc[0]
            first_rec  = latest_arr.get("first_record")
            last_rec   = latest_arr.get("last_record")

            if first_rec is not None and last_rec is not None:
                arrival_str = _fmt_timestamp(first_rec)

                if hasattr(first_rec, "to_pydatetime"):
                    first_rec = first_rec.to_pydatetime()
                if hasattr(last_rec, "to_pydatetime"):
                    last_rec = last_rec.to_pydatetime()

                # SLA = how many minutes did it take for ALL data
                # to arrive (last record - first record)
                # This is the ingestion window duration.
                # For DAILY batch: should complete within sla_minutes
                # For NEAR_REALTIME: should complete within sla_minutes
                ingestion_window_minutes = (
                    last_rec - first_rec
                ).total_seconds() / 60

                sla_met = ingestion_window_minutes <= sla_minutes

                if sla_met:
                    sla_badge = html.Span(
                        f"✅ completed in "
                        f"{int(ingestion_window_minutes)} min "
                        f"(SLA: {sla_minutes} min)",
                        style={"color": "#00c851", "fontSize": "13px"}
                    )
                else:
                    sla_badge = html.Span(
                        f"⚠️ {int(ingestion_window_minutes)} min "
                        f"(SLA: {sla_minutes} min)",
                        style={"color": "#ffa500", "fontSize": "13px"}
                    )

        except Exception as e:
            logger.error(f"SLA computation failed for {fqn}: {e}")
            sla_badge = html.Span(
                "Could not compute",
                style={"color": "#555555", "fontSize": "13px"}
            )

    # ── Metric row helper ──────────────────────────────────────────────────
    def _metric_row(label: str, value) -> html.Div:
        return html.Div([
            html.Span(
                label,
                style={
                    "color"  : "#888888",
                    "fontSize": "13px",
                    "display": "inline-block",
                    "width"  : "110px",
                }
            ),
            html.Span(
                str(value) if value is not None else "—",
                style={
                    "color"    : "#ffffff",
                    "fontSize" : "13px",
                    "fontWeight": "500",
                }
            ),
        ], style={"marginBottom": "6px"})

    return dbc.Col(
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.Span(
                        cfg["label"],
                        style={
                            "color"    : "#ffffff",
                            "fontSize" : "16px",
                            "fontWeight": "700",
                        }
                    ),
                    html.Br(),
                    html.Span(
                        f"{cfg['source_type']} / "
                        f"{cfg['pattern']} / "
                        f"{cfg['frequency']}",
                        style={
                            "color"     : "#aaaaaa",
                            "fontSize"  : "11px",
                            "fontFamily": "monospace",
                        }
                    ),
                ]),
                style={
                    "backgroundColor": cfg["color"],
                    "borderColor"    : cfg["color"],
                }
            ),
            dbc.CardBody([

                # Status badge
                html.Div([
                    html.Span(
                        f"{emoji}  {status}",
                        style={
                            "color"    : color,
                            "fontSize" : "22px",
                            "fontWeight": "800",
                        }
                    ),
                    html.Span(
                        f"  Latest: {latest_date}",
                        style={"color": "#aaaaaa", "fontSize": "13px"}
                    ),
                ], style={
                    "marginBottom": "16px",
                    "paddingBottom": "12px",
                    "borderBottom": "1px solid #333",
                }),

                _metric_row(
                    "Volume",
                    f"{int(volume_obs):,} rows"
                    if volume_obs is not None else "—"
                ),
                _metric_row(
                    "vs baseline",
                    f"{volume_dev:+.1f}%"
                    if volume_dev is not None else "—"
                ),
                _metric_row("Worst check", worst_check),
                _metric_row("Arrived",     arrival_str),

                html.Div([
                    html.Span(
                        "SLA",
                        style={
                            "color"  : "#888888",
                            "fontSize": "13px",
                            "display": "inline-block",
                            "width"  : "110px",
                        }
                    ),
                    sla_badge,
                ], style={"marginBottom": "6px"}),

            ], style={"backgroundColor": bg}),
        ], style={
            "backgroundColor": bg,
            "border"         : f"1px solid {color}",
        }),
        md=6,
    )


# ── Section 2: Calendar heatmap ────────────────────────────────────────────

def _build_heatmap(
    cfg     : dict,
    runs_df : pd.DataFrame,
) -> dbc.Card:

    fqn   = cfg["fqn"]

    pipe_runs = (
        runs_df[runs_df["fully_qualified_name"] == fqn].copy()
        if not runs_df.empty else pd.DataFrame()
    )

    if pipe_runs.empty:
        return dbc.Card([
            dbc.CardHeader(
                html.H6(cfg["label"], className="mb-0 text-white")
            ),
            dbc.CardBody(
                html.P(
                    "No run history found.",
                    className="text-muted small mb-0"
                )
            )
        ], style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})

    pipe_runs["business_date"] = pd.to_datetime(pipe_runs["business_date"])
    pipe_runs = pipe_runs.sort_values("business_date")

    dates    = pipe_runs["business_date"].tolist()
    statuses = pipe_runs["overall_status"].tolist()
    crit     = pipe_runs["total_checks_critical"].tolist()
    warned   = pipe_runs["total_checks_warned"].tolist()

    hover = [
        f"<b>{d.strftime('%Y-%m-%d')}</b><br>"
        f"Status: {s}<br>"
        f"Critical: {int(c)}  Warning: {int(w)}"
        for d, s, c, w in zip(dates, statuses, crit, warned)
    ]

    point_colors = [
        STATUS_COLOR.get(str(s), STATUS_COLOR["UNKNOWN"])
        for s in statuses
    ]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x         = dates,
        y         = [0] * len(dates),
        mode      = "markers",
        marker    = dict(
            symbol = "square",
            size   = 22,
            color  = point_colors,
            line   = dict(color="#1a1a1a", width=2),
        ),
        hoverinfo  = "text",
        hovertext  = hover,
        showlegend = False,
    ))

    fig.update_layout(
        height        = 120,
        paper_bgcolor = "#2b2b2b",
        plot_bgcolor  = "#2b2b2b",
        margin        = dict(l=10, r=10, t=10, b=60),
        showlegend    = False,
        xaxis = dict(
            gridcolor  = "#333",
            tickcolor  = "#555",
            linecolor  = "#444",
            tickformat = "%b %-d",
            tickangle  = -60,
            tickfont   = dict(color="#aaaaaa", size=10),
        ),
        yaxis      = dict(visible=False, fixedrange=True),
        hovermode  = "closest",
        hoverlabel = dict(
            bgcolor     = "#2b2b2b",
            bordercolor = "#555",
            font_size   = 12,
            font_color  = "#ffffff",
        ),
    )

    return dbc.Card([
        dbc.CardHeader(
            html.H6(
                f"{cfg['label']} — 60 Day History",
                className="mb-0 text-white"
            )
        ),
        dbc.CardBody([
            dcc.Graph(
                figure = fig,
                config = {"displayModeBar": False},
                style  = {"margin": "-10px -10px -20px"}
            )
        ])
    ], className="mb-3",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})


# ── Section 3: Reliability metrics table ──────────────────────────────────

def _build_reliability_table(
    pipelines: dict,
    runs_df  : pd.DataFrame,
    checks_df: pd.DataFrame,
) -> dbc.Card:

    rows = []

    for key, cfg in pipelines.items():
        fqn     = cfg["fqn"]
        metrics = _compute_reliability_metrics(runs_df, checks_df, fqn)

        # ── Typical volume from baseline window ────────────────────────────
        # Reads directly from the raw table count per date
        # within the clean historical window.
        # Does NOT use uc1_validation_results_b because historical
        # clean dates may not have had Agent 1 runs.
        avg_vol_str   = "—"
        anomaly_days  = 0
        anomaly_color = "#aaaaaa"

        try:
            date_col = cfg["date_col"]
            vol_df   = execute_query(f"""
                SELECT
                    ROUND(AVG(daily_count), 0)    AS avg_vol,
                    ROUND(STDDEV(daily_count), 0) AS std_vol
                FROM (
                    SELECT
                        {date_col}  AS business_date,
                        COUNT(*)    AS daily_count
                    FROM {fqn}
                    WHERE {date_col} BETWEEN
                        :window_start AND :window_end
                    GROUP BY {date_col}
                )
            """, {
                "window_start": BASELINE_WINDOW_START,
                "window_end"  : BASELINE_WINDOW_END,
            })
            if not vol_df.empty:
                av = _safe_float(vol_df.iloc[0]["avg_vol"])
                sv = _safe_float(vol_df.iloc[0]["std_vol"])
                if av is not None:
                    avg_vol_str = (
                        f"{int(av):,} rows"
                        + (f"  (stddev ±{int(sv):,})" if sv else "")
                    )
        except Exception as e:
            logger.error(f"Typical volume query failed for {key}: {e}")

        # ── Anomaly days — all dates, not just baseline window ─────────────
        # Counts how many dates had a VOLUME_ANOMALY WARNING or CRITICAL
        # across the full run history, not just the baseline window.
        try:
            cutoff = (date.today() - timedelta(days=60)).isoformat()
            anom_df = execute_query(f"""
                SELECT COUNT(DISTINCT business_date) AS anomaly_days
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
                WHERE fully_qualified_name = :fqn
                AND check_status IN ('WARNING', 'CRITICAL')
                AND business_date >= :cutoff
            """, {"fqn": fqn, "cutoff": cutoff})
            if not anom_df.empty:
                anomaly_days  = int(anom_df.iloc[0]["anomaly_days"] or 0)
                anomaly_color = (
                    "#ff6b6b" if anomaly_days >= 3
                    else "#ffa500" if anomaly_days >= 1
                    else "#00c851"
                )
        except Exception as e:
            logger.error(f"Anomaly days query failed for {key}: {e}")

        # ── Most common failure — all check types not just volume ──────────
        # Uses ALL failed checks not just WARNING/CRITICAL volume checks
        # so it reflects the most frequent problem type overall.
        most_common   = "—"
        common_color  = "#aaaaaa"
        try:
            cutoff = (date.today() - timedelta(days=60)).isoformat()

            common_df = execute_query(f"""
                SELECT
                    check_type,
                    COUNT(*) AS cnt
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
                WHERE fully_qualified_name = :fqn
                AND check_status         IN ('WARNING', 'CRITICAL')
                AND business_date        >= :cutoff
                GROUP BY check_type
                ORDER BY cnt DESC
                LIMIT 1
            """, {"fqn": fqn, "cutoff": cutoff})
            if not common_df.empty:
                most_common  = str(common_df.iloc[0]["check_type"])
                common_color = "#ffa500"
        except Exception as e:
            logger.error(f"Most common failure query failed for {key}: {e}")

        # ── Success rate colour ────────────────────────────────────────────
        sr = metrics.get("success_rate")
        success_color = (
            "#00c851" if sr and sr >= 90
            else "#ffa500" if sr and sr >= 75
            else "#ff6b6b" if sr is not None
            else "#aaaaaa"
        )

        dur = metrics.get("avg_duration")

        # ── Build row ──────────────────────────────────────────────────────
        rows.append({
            "pipeline"       : cfg["label"],
            "type"           : f"{cfg['source_type']} / {cfg['pattern']}",
            "success_rate"   : f"{sr}%" if sr is not None else "—",
            "typical_volume" : avg_vol_str,
            "anomaly_days"   : f"{anomaly_days} days",
            "common_failure" : most_common,
            "avg_duration"   : f"{dur}s" if dur is not None else "—",
            "total_runs"     : str(metrics.get("total_runs", 0)),
        })

    return dbc.Card([
        dbc.CardHeader(
            html.H6(
                "60-Day Reliability Metrics",
                className="mb-0 text-white"
            )
        ),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="ph-reliability-grid",
                    row_data=rows,
                    col_defs=[
                        {"field": "pipeline",       "headerName": "Pipeline",             "flex": 1, "minWidth": 220},
                        {"field": "type",           "headerName": "Type",              "minWidth": 150},
                        {"field": "success_rate",   "headerName": "Success Rate",         "width": 120},
                        {"field": "typical_volume", "headerName": "Typical Volume",       "flex": 1},
                        {"field": "anomaly_days",   "headerName": "Anomaly Days",         "width": 120},
                        {"field": "common_failure", "headerName": "Most Common Failure",  "flex": 1, "minWidth": 280},
                        {"field": "avg_duration",   "headerName": "Avg Duration",         "width": 110},
                        {"field": "total_runs",     "headerName": "Total Runs",           "width": 100},
                    ],
                    page_size=10,
                    height=150,
                )
            ),
        ], style={"padding": "0"}),
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})

# ── Section 4: Volume trend chart ─────────────────────────────────────────

def _build_volume_chart(
    pipeline_volumes: list,
) -> dbc.Card:
    """pipeline_volumes: list of (cfg, vol_df) tuples, one per pipeline."""

    n_rows = max(len(pipeline_volumes), 1)
    fig = make_subplots(
        rows             = n_rows,
        cols             = 1,
        shared_xaxes     = False,
        vertical_spacing = 0.14,
        subplot_titles   = [
            f"{cfg['label']} — Daily Volume" for cfg, _ in pipeline_volumes
        ]
    )

    # ── Baseline window — clean historical dates only ──────────────────────
    # Uses 2026-05-19 to 2026-06-17 which is the clean baseline period.
    # Excludes controlled anomaly dates and July failure dates so the
    # baseline mean is not dragged down by injected issues.
    BASELINE_START = BASELINE_WINDOW_START
    BASELINE_END   = BASELINE_WINDOW_END

    for row_idx, (cfg, vol_df) in enumerate(pipeline_volumes, start=1):
        color = cfg["color_light"]

        if vol_df.empty:
            continue

        dates  = vol_df["business_date"].tolist()
        counts = vol_df["row_count"].tolist()

        # ── Baseline mean from clean window only ───────────────────────────
        clean_mask = (
            (vol_df["business_date"] >= pd.Timestamp(BASELINE_START)) &
            (vol_df["business_date"] <= pd.Timestamp(BASELINE_END)) &
            (vol_df["row_count"] > 0)
        )
        clean_df = vol_df[clean_mask]

        if not clean_df.empty:
            baseline_mean = clean_df["row_count"].mean()
        else:
            # Fallback: use non-zero dates if clean window not available
            nonzero = vol_df[vol_df["row_count"] > 0]
            baseline_mean = nonzero["row_count"].mean() if not nonzero.empty else 0

        # ── Warning and critical deviation thresholds ──────────────────────
        warn_threshold = baseline_mean * 0.80   # 20% below = warning
        crit_threshold = baseline_mean * 0.60   # 40% below = critical

        # ── Per-point colours, sizes, symbols ─────────────────────────────
        point_colors  = []
        point_sizes   = []
        point_symbols = []

        for c in counts:
            if c == 0:
                # Zero rows — pipeline failure
                point_colors.append("#ff0000")
                point_sizes.append(14)
                point_symbols.append("x")
            elif baseline_mean > 0 and c < crit_threshold:
                # More than 40% below baseline — critical anomaly
                point_colors.append("#ff6b6b")
                point_sizes.append(9)
                point_symbols.append("circle")
            elif baseline_mean > 0 and c < warn_threshold:
                # 20-40% below baseline — warning anomaly
                point_colors.append("#ffa500")
                point_sizes.append(9)
                point_symbols.append("circle")
            elif baseline_mean > 0 and c > baseline_mean * 1.40:
                # More than 40% above baseline — spike anomaly
                point_colors.append("#ff6b6b")
                point_sizes.append(9)
                point_symbols.append("circle")
            elif baseline_mean > 0 and c > baseline_mean * 1.20:
                # 20-40% above baseline — warning spike
                point_colors.append("#ffa500")
                point_sizes.append(9)
                point_symbols.append("circle")
            else:
                # Normal
                point_colors.append(color)
                point_sizes.append(6)
                point_symbols.append("circle")

        # ── Per-point hover text ───────────────────────────────────────────
        hover_texts = []
        for d, c in zip(dates, counts):
            if c == 0:
                note = "⚠️ Pipeline produced zero rows"
            elif baseline_mean > 0:
                dev = (c - baseline_mean) / baseline_mean * 100
                if abs(dev) >= 40:
                    note = f"🔴 Critical anomaly: {dev:+.1f}% from baseline"
                elif abs(dev) >= 20:
                    note = f"🟠 Volume anomaly: {dev:+.1f}% from baseline"
                else:
                    note = f"✅ Normal: {dev:+.1f}% from baseline"
            else:
                note = ""

            hover_texts.append(
                f"<b>{d.strftime('%Y-%m-%d')}</b><br>"
                f"Volume: {c:,} rows<br>"
                f"{note}"
            )

        # ── Baseline band (±20% shaded area) ──────────────────────────────
        if baseline_mean > 0:
            # Upper and lower warning bounds as a shaded band
            fig.add_trace(
                go.Scatter(
                    x          = dates + dates[::-1],
                    y          = (
                        [baseline_mean * 1.20] * len(dates) +
                        [baseline_mean * 0.80] * len(dates)
                    ),
                    fill       = "toself",
                    fillcolor  = "rgba(255,165,0,0.06)",
                    line       = dict(width=0),
                    hoverinfo  = "skip",
                    showlegend = False,
                    name       = "normal_band",
                ),
                row=row_idx, col=1,
            )

            # Critical band lower (below 40%)
            fig.add_trace(
                go.Scatter(
                    x          = dates + dates[::-1],
                    y          = (
                        [baseline_mean * 0.80] * len(dates) +
                        [0] * len(dates)
                    ),
                    fill       = "toself",
                    fillcolor  = "rgba(255,107,107,0.06)",
                    line       = dict(width=0),
                    hoverinfo  = "skip",
                    showlegend = False,
                    name       = "critical_band",
                ),
                row=row_idx, col=1,
            )

        # ── Baseline mean line ─────────────────────────────────────────────
        if baseline_mean > 0:
            fig.add_hline(
                y               = baseline_mean,
                line_dash       = "dash",
                line_color      = "#4a9edd",
                line_width      = 1.5,
                annotation_text = (
                    f"Baseline avg: {int(baseline_mean):,}"
                    f" ({BASELINE_START} to {BASELINE_END})"
                ),
                annotation_font_color = "#4a9edd",
                annotation_font_size  = 10,
                annotation_position   = "bottom right",
                row=row_idx, col=1,
            )

            # Warning threshold line
            fig.add_hline(
                y               = warn_threshold,
                line_dash       = "dot",
                line_color      = "#ffa500",
                line_width      = 1,
                annotation_text = f"−20%: {int(warn_threshold):,}",
                annotation_font_color = "#ffa500",
                annotation_font_size  = 9,
                annotation_position   = "bottom right",
                row=row_idx, col=1,
            )

            # Critical threshold line
            fig.add_hline(
                y               = crit_threshold,
                line_dash       = "dot",
                line_color      = "#ff6b6b",
                line_width      = 1,
                annotation_text = f"−40%: {int(crit_threshold):,}",
                annotation_font_color = "#ff6b6b",
                annotation_font_size  = 9,
                annotation_position   = "bottom right",
                row=row_idx, col=1,
            )

        # ── Zero baseline ──────────────────────────────────────────────────
        fig.add_hline(
            y          = 0,
            line_dash  = "solid",
            line_color = "#2a2a2a",
            line_width = 1,
            row=row_idx, col=1,
        )

        # ── Main volume trace ──────────────────────────────────────────────
        fig.add_trace(
            go.Scatter(
                x    = dates,
                y    = counts,
                mode = "lines+markers",
                name = cfg["label"],
                line = dict(color=color, width=2),
                marker = dict(
                    color  = point_colors,
                    size   = point_sizes,
                    symbol = point_symbols,
                    line   = dict(color="#1a1a1a", width=1),
                ),
                hoverinfo  = "text",
                hovertext  = hover_texts,
                showlegend = False,
            ),
            row=row_idx, col=1,
        )

    fig.update_layout(
        height        = 250 * n_rows,
        paper_bgcolor = "#2b2b2b",
        plot_bgcolor  = "#2b2b2b",
        font          = dict(color="#aaaaaa", size=11),
        margin        = dict(l=60, r=180, t=40, b=60),
        showlegend    = False,
        hovermode     = "closest",
        hoverlabel    = dict(
            bgcolor     = "#2b2b2b",
            bordercolor = "#555",
            font_size   = 12,
            font_color  = "#ffffff",
        ),
    )

    axis_names = ["xaxis", "yaxis"] + [
        f"{a}{i}" for i in range(2, n_rows + 1) for a in ("xaxis", "yaxis")
    ]
    for ax in axis_names:
        fig.update_layout(**{ax: dict(
            gridcolor = "#333333",
            tickcolor = "#555555",
            linecolor = "#444444",
            tickfont  = dict(color="#aaaaaa", size=10),
        )})

    for ann in fig["layout"]["annotations"]:
        ann["font"] = dict(color="#888888", size=12)

    # ── Legend card content ────────────────────────────────────────────────
    legend = html.Div([
        html.Span(
            "✕ ",
            style={"color": "#ff0000", "fontWeight": "900",
                   "fontSize": "14px", "marginRight": "4px"}
        ),
        html.Span(
            "Zero rows (pipeline failure)   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Span(
            "● ",
            style={"color": "#ff6b6b", "fontSize": "16px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "Critical anomaly (>40% from baseline)   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Span(
            "● ",
            style={"color": "#ffa500", "fontSize": "16px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "Warning anomaly (20-40% from baseline)   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Span(
            "● ",
            style={"color": "#4a9edd", "fontSize": "16px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "Normal   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Br(),
        html.Span(
            "── ",
            style={"color": "#4a9edd", "fontSize": "14px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "Baseline mean (clean historical window)   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Span(
            "·· ",
            style={"color": "#ffa500", "fontSize": "18px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "±20% warning band   ",
            style={"color": "#aaaaaa", "fontSize": "11px",
                   "marginRight": "16px"}
        ),
        html.Span(
            "·· ",
            style={"color": "#ff6b6b", "fontSize": "18px",
                   "marginRight": "4px"}
        ),
        html.Span(
            "±40% critical band",
            style={"color": "#aaaaaa", "fontSize": "11px"}
        ),
    ], style={
        "padding"        : "10px 16px",
        "backgroundColor": "#1a1a1a",
        "borderRadius"   : "6px",
        "marginBottom"   : "12px",
        "lineHeight"     : "2",
    })

    return dbc.Card([
        dbc.CardHeader(
            html.H6("Volume Trend — 60 Days", className="mb-0 text-white")
        ),
        dbc.CardBody([
            legend,
            dcc.Graph(
                figure = fig,
                config = {"displayModeBar": False},
            )
        ])
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})


# ── Section 5: Failure drill-down ──────────────────────────────────────────

def _build_failure_table(pipelines: dict, checks_df: pd.DataFrame) -> dbc.Card:

    if checks_df.empty:
        return dbc.Card([
            dbc.CardHeader(
                html.H6("Failure History", className="mb-0 text-white")
            ),
            dbc.CardBody(
                html.P(
                    "No failures found in this period.",
                    className="text-muted small"
                )
            )
        ], style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})

    grid_rows = []
    for _, row in checks_df.head(50).iterrows():
        status = str(row.get("check_status", ""))

        fqn        = str(row.get("fully_qualified_name", ""))
        pipe_label = next(
            (cfg["label"] for cfg in pipelines.values()
             if cfg["fqn"] == fqn),
            fqn.split(".")[-1]
        )

        col_name = str(row.get("column_name", "") or "table-level")
        dev      = _safe_float(row.get("deviation_pct"))
        obs      = _safe_float(row.get("observed_value"))

        grid_rows.append({
            "business_date" : str(row.get("business_date", ""))[:10],
            "pipeline"      : pipe_label,
            "check_status"  : status,
            "check_type"    : str(row.get("check_type", "")),
            "column_name"   : col_name,
            "observed"      : f"{obs:.2f}" if obs is not None else "—",
            "deviation"     : f"{dev:+.1f}%" if dev is not None else "—",
        })

    return dbc.Card([
        dbc.CardHeader(
            html.H6(
                f"Failure History — Last {len(checks_df)} events",
                className="mb-0 text-white"
            )
        ),
        dbc.CardBody([
            dag.AgGrid(
                **ag_grid_props(
                    grid_id="ph-failure-history-grid",
                    row_data=grid_rows,
                    col_defs=[
                        {"field": "business_date", "headerName": "Date",    "minWidth": 120},
                        {"field": "pipeline",      "headerName": "Pipeline",   "flex": 1, "minWidth": 220},
                        {"field": "check_status",  "headerName": "Status",  "minWidth": 150,
                         "cellStyle": {"function": AG_STATUS_CELL_STYLE_JS}},
                        {"field": "check_type",    "headerName": "Check Type", "flex": 1, "minWidth": 200},
                        {"field": "column_name",   "headerName": "Column",     "flex": 1, "minWidth": 220},
                        {"field": "observed",      "headerName": "Observed",   "width": 110},
                        {"field": "deviation",     "headerName": "Deviation",  "width": 110},
                    ],
                    page_size=20,
                    status_col="check_status",
                )
            ),
        ], style={"padding": "0"}),
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"})


# ── Main page builder ──────────────────────────────────────────────────────

def _build_page() -> html.Div:
    pipelines = _load_pipelines()

    if not pipelines:
        return dbc.Alert(
            "No active pipelines found in the Table Registry. "
            "Onboard a table via the Table Onboarding Wizard to see it here.",
            color="warning"
        )

    try:
        fqns      = [cfg["fqn"] for cfg in pipelines.values()]
        runs_df   = _load_pipeline_runs(fqns, days=60)
        checks_df = _load_check_detail(fqns, days=60)
        arrivals  = {
            key: _load_arrival_times(cfg, days=60)
            for key, cfg in pipelines.items()
        }
        volumes = {
            key: _load_volume_history(cfg, days=60)
            for key, cfg in pipelines.items()
        }
    except Exception as e:
        logger.error(f"Pipeline health page load failed: {e}")
        return dbc.Alert(
            f"Could not load pipeline data: {str(e)}",
            color="danger"
        )

    return html.Div([

        # ── Section 1: Current status ──────────────────────────────────────
        html.H5(
            "Current Status",
            style={
                "color"       : "#ffffff",
                "fontSize"    : "16px",
                "fontWeight"  : "600",
                "marginBottom": "16px",
            }
        ),
        dbc.Row([
            _build_status_card(cfg, runs_df, checks_df, arrivals[key])
            for key, cfg in pipelines.items()
        ], className="mb-4"),

        # ── Section 2: Calendar heatmaps ───────────────────────────────────
        html.H5(
            "60-Day History",
            style={
                "color"       : "#ffffff",
                "fontSize"    : "16px",
                "fontWeight"  : "600",
                "marginBottom": "16px",
            }
        ),
        *[_build_heatmap(cfg, runs_df) for cfg in pipelines.values()],

        html.Div(style={"marginBottom": "24px"}),

        # ── Section 3: Reliability metrics ────────────────────────────────
        _build_reliability_table(pipelines, runs_df, checks_df),

        # ── Section 4: Volume trend ────────────────────────────────────────
        _build_volume_chart(
            [(cfg, volumes[key]) for key, cfg in pipelines.items()]
        ),

        # ── Section 5: Failure drill-down ──────────────────────────────────
        html.H5(
            "Failure History",
            style={
                "color"       : "#ffffff",
                "fontSize"    : "16px",
                "fontWeight"  : "600",
                "marginBottom": "16px",
            }
        ),
        _build_failure_table(pipelines, checks_df),

    ])


# ── Callback ───────────────────────────────────────────────────────────────

@callback(
    Output("ph-page-content", "children"),
    Input("ph-refresh-interval", "n_intervals"),
)
def render_pipeline_health(n_intervals):
    return _build_page()

@callback(
    Output("ph-refresh-interval",   "disabled"),
    Output("ph-refresh-toggle",     "children"),
    Output("ph-refresh-toggle",     "color"),
    Output("ph-refresh-indicator",  "children"),
    Output("ph-refresh-paused",     "data"),
    Input("ph-refresh-toggle",      "n_clicks"),
    State("ph-refresh-paused",      "data"),
    prevent_initial_call=True,
)
def toggle_ph_refresh(n_clicks, is_paused):
    new_paused = not is_paused
    if new_paused:
        return (
            True,
            "▶ Resume Auto-Refresh",
            "success",
            "Auto-refresh paused",
            True,
        )
    return (
        False,
        "⏸ Pause Auto-Refresh",
        "secondary",
        "Auto-refreshing every 5 minutes",
        False,
    )