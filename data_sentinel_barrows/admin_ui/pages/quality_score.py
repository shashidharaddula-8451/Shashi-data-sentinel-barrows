# pages/quality_score.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import math
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/quality-score",
    name="Quality Score"
)

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

# ── Weights ────────────────────────────────────────────────────────────────

WEIGHTS = {
    "raw_completeness"    : 0.25,
    "pipeline_reliability": 0.25,
    "kpi_accuracy"        : 0.25,
    "freshness"           : 0.15,
    "governance_health"   : 0.10,
}

DIMENSION_LABELS = {
    "raw_completeness"    : "Raw completeness",
    "pipeline_reliability": "Pipeline reliability",
    "kpi_accuracy"        : "KPI accuracy",
    "freshness"           : "Freshness",
    "governance_health"   : "Governance health",
}

DIMENSION_DESCRIPTIONS = {
    "raw_completeness"    : "Null rates, volume anomalies, malformed records",
    "pipeline_reliability": "Raw → Silver → Gold survival rates",
    "kpi_accuracy"        : "Formula correctness, anomaly detection, range bounds",
    "freshness"           : "Layer latency and data presence checks",
    "governance_health"   : "Silver transformation code review results",
}

# ── Score computation helpers ──────────────────────────────────────────────

def _checks_to_score(pass_count: int, warn_count: int, crit_count: int) -> float:
    """
    Converts check counts to a 0–100 score.

    Scoring:
      PASS     = full weight
      WARNING  = 50% deduction from that check's weight
      CRITICAL = 100% deduction from that check's weight

    Returns 100.0 when there are no checks (nothing to fail).
    """
    total = pass_count + warn_count + crit_count
    if total == 0:
        return 100.0

    points_earned = pass_count + (warn_count * 0.5)
    return round((points_earned / total) * 100, 1)


def _weighted_overall(dimensions: dict) -> float:
    """
    Computes overall score as weighted average of dimension scores.
    Skips dimensions with score of None (no data).
    Adjusts weights proportionally when dimensions are missing.
    """
    total_weight  = 0.0
    weighted_sum  = 0.0

    for key, weight in WEIGHTS.items():
        score = dimensions.get(key)
        if score is not None:
            weighted_sum  += score * weight
            total_weight  += weight

    if total_weight == 0:
        return None

    return round(weighted_sum / total_weight, 1)


# ── Data loading ───────────────────────────────────────────────────────────

def _score_from_counts(counts: dict) -> float:
    return _checks_to_score(
        int(counts.get("PASS",     0)),
        int(counts.get("WARNING",  0)),
        int(counts.get("CRITICAL", 0)),
    )


def _dims_from_daily_counts(bdate: str, per_dim_counts: dict) -> dict:
    """
    per_dim_counts: {dimension_key: {business_date_str: {status: cnt}}}
    Builds the 5-dimension score dict for one date from pre-aggregated counts.
    """
    dims = {}
    for key in WEIGHTS.keys():
        counts = per_dim_counts.get(key, {}).get(bdate)
        dims[key] = _score_from_counts(counts) if counts else None
    return dims


def _load_dimension_scores_for_date(business_date: str) -> dict:
    """
    Computes all five dimension scores for a single business date.
    Kept for on-demand single-date lookups; the 90-day history load uses
    _load_all_dimension_counts instead to avoid one round-trip per date.

    Dimension definitions (revised):

    raw_completeness:
        A1 checks about DATA CONTENT quality
        NULL_SPIKE, MALFORMED_RECORDS, NUMERIC_RANGE,
        CATEGORICAL_DOMAIN, CROSS_COLUMN_CONSISTENCY,
        CARDINALITY_DRIFT, SCHEMA_CONFORMANCE
        Does NOT include VOLUME_ANOMALY — that is pipeline reliability

    pipeline_reliability:
        A1 VOLUME_ANOMALY (did the pipeline deliver expected records)
        A2 ROW_COUNT checks (did records survive Raw→Silver→Gold)
        Combined because both measure pipeline delivery, not data content

    kpi_accuracy:
        A4 all check types

    freshness:
        A2 LAYER_FRESHNESS checks only

    governance_health:
        A3 review results
    """

    # ── 1. Raw completeness — content quality only ─────────────────────────
    try:
        df_raw = execute_query(f"""
            SELECT
                check_status,
                COUNT(*) AS cnt
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
            WHERE business_date = :business_date
              AND check_type IN (
                  'NULL_SPIKE',
                  'MALFORMED_RECORDS',
                  'SCHEMA_CONFORMANCE',
                  'NUMERIC_RANGE',
                  'CATEGORICAL_DOMAIN',
                  'CROSS_COLUMN_CONSISTENCY',
                  'CARDINALITY_DRIFT'
              )
            GROUP BY check_status
        """, {"business_date": business_date})
        raw_score = None if df_raw.empty else _score_from_counts(
            df_raw.set_index("check_status")["cnt"].to_dict()
        )
    except Exception as e:
        logger.error(f"Raw completeness query failed: {e}")
        raw_score = None

    # ── 2. Pipeline reliability — delivery quality ─────────────────────────
    try:
        df_vol = execute_query(f"""
            SELECT
                check_status,
                COUNT(*) AS cnt
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
            WHERE business_date = :business_date
              AND check_type    = 'VOLUME_ANOMALY'
            GROUP BY check_status
        """, {"business_date": business_date})

        df_recon = execute_query(f"""
            SELECT
                check_status,
                COUNT(*) AS cnt
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
            WHERE business_date = :business_date
              AND check_type IN (
                  'BRONZE_TO_SILVER_ROW_COUNT',
                  'SILVER_TO_GOLD_ROW_COUNT'
              )
            GROUP BY check_status
        """, {"business_date": business_date})

        combined: dict[str, int] = {}
        for df in [df_vol, df_recon]:
            if not df.empty:
                for status, cnt in df.set_index(
                    "check_status"
                )["cnt"].to_dict().items():
                    combined[status] = combined.get(status, 0) + int(cnt)

        pipe_score = _score_from_counts(combined) if combined else None
    except Exception as e:
        logger.error(f"Pipeline reliability query failed: {e}")
        pipe_score = None

    # ── 3. KPI accuracy ────────────────────────────────────────────────────
    try:
        df_kpi = execute_query(f"""
            SELECT
                check_status,
                COUNT(*) AS cnt
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
            WHERE business_date = :business_date
            GROUP BY check_status
        """, {"business_date": business_date})
        kpi_score = None if df_kpi.empty else _score_from_counts(
            df_kpi.set_index("check_status")["cnt"].to_dict()
        )
    except Exception as e:
        logger.error(f"KPI accuracy query failed: {e}")
        kpi_score = None

    # ── 4. Freshness ───────────────────────────────────────────────────────
    try:
        df_fresh = execute_query(f"""
            SELECT
                check_status,
                COUNT(*) AS cnt
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
            WHERE business_date = :business_date
              AND check_type    = 'LAYER_FRESHNESS'
            GROUP BY check_status
        """, {"business_date": business_date})
        fresh_score = None if df_fresh.empty else _score_from_counts(
            df_fresh.set_index("check_status")["cnt"].to_dict()
        )
    except Exception as e:
        logger.error(f"Freshness query failed: {e}")
        fresh_score = None

    # ── 5. Governance health ───────────────────────────────────────────────
    try:
        df_gov = execute_query(f"""
            SELECT
                overall_status,
                COUNT(*) AS cnt
            FROM (
                SELECT
                    overall_status,
                    ROW_NUMBER() OVER (
                        PARTITION BY transformation_id
                        ORDER BY review_timestamp DESC
                    ) AS rn
                FROM {CATALOG}.{SCHEMA}.uc3_review_results_b
                WHERE DATE(review_timestamp) <= :business_date
            )
            WHERE rn = 1
            GROUP BY overall_status
        """, {"business_date": business_date})
        if df_gov.empty:
            gov_score = None
        else:
            counts = df_gov.set_index("overall_status")["cnt"].to_dict()
            gov_score = _checks_to_score(
                int(counts.get("PASS",         0)) +
                int(counts.get("NOT_REVIEWED", 0)),
                int(counts.get("WARNING",      0)),
                int(counts.get("CRITICAL",     0)),
            )
    except Exception as e:
        logger.error(f"Governance health query failed: {e}")
        gov_score = None

    return {
        "raw_completeness"    : raw_score,
        "pipeline_reliability": pipe_score,
        "kpi_accuracy"        : kpi_score,
        "freshness"           : fresh_score,
        "governance_health"   : gov_score,
    }


def _counts_by_date(df, date_col="business_date", status_col="check_status") -> dict:
    """Groups a (date, status, cnt) dataframe into {date_str: {status: cnt}}."""
    result: dict = {}
    if df.empty:
        return result
    for _, row in df.iterrows():
        bdate  = str(row[date_col])[:10]
        status = row[status_col]
        cnt    = int(row["cnt"])
        day_counts = result.setdefault(bdate, {})
        day_counts[status] = day_counts.get(status, 0) + cnt
    return result


def _load_all_dimension_counts(dates: list, conn=None) -> dict:
    """
    Runs each dimension's query ONCE across the full date range instead of
    once per date, collapsing what used to be up to `len(dates) * 6` SQL
    round-trips into 6. Returns {dimension_key: {date_str: {status: cnt}}}.
    """
    if not dates:
        return {}

    lo, hi = min(dates), max(dates)
    params = {"lo": lo, "hi": hi}

    df_raw = execute_query(f"""
        SELECT business_date, check_status, COUNT(*) AS cnt
        FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
        WHERE business_date BETWEEN :lo AND :hi
          AND check_type IN (
              'NULL_SPIKE', 'MALFORMED_RECORDS', 'SCHEMA_CONFORMANCE',
              'NUMERIC_RANGE', 'CATEGORICAL_DOMAIN',
              'CROSS_COLUMN_CONSISTENCY', 'CARDINALITY_DRIFT'
          )
        GROUP BY business_date, check_status
    """, params, conn=conn)

    df_vol = execute_query(f"""
        SELECT business_date, check_status, COUNT(*) AS cnt
        FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b
        WHERE business_date BETWEEN :lo AND :hi
          AND check_type = 'VOLUME_ANOMALY'
        GROUP BY business_date, check_status
    """, params, conn=conn)

    df_recon = execute_query(f"""
        SELECT business_date, check_status, COUNT(*) AS cnt
        FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
        WHERE business_date BETWEEN :lo AND :hi
          AND check_type IN ('BRONZE_TO_SILVER_ROW_COUNT', 'SILVER_TO_GOLD_ROW_COUNT')
        GROUP BY business_date, check_status
    """, params, conn=conn)

    df_kpi = execute_query(f"""
        SELECT business_date, check_status, COUNT(*) AS cnt
        FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
        WHERE business_date BETWEEN :lo AND :hi
        GROUP BY business_date, check_status
    """, params, conn=conn)

    df_fresh = execute_query(f"""
        SELECT business_date, check_status, COUNT(*) AS cnt
        FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b
        WHERE business_date BETWEEN :lo AND :hi
          AND check_type = 'LAYER_FRESHNESS'
        GROUP BY business_date, check_status
    """, params, conn=conn)

    df_gov = execute_query(f"""
        SELECT business_date, overall_status, COUNT(*) AS cnt
        FROM (
            SELECT
                DATE(review_timestamp) AS business_date,
                overall_status,
                ROW_NUMBER() OVER (
                    PARTITION BY transformation_id
                    ORDER BY review_timestamp DESC
                ) AS rn
            FROM {CATALOG}.{SCHEMA}.uc3_review_results_b
            WHERE DATE(review_timestamp) <= :hi
        )
        WHERE rn = 1
        GROUP BY business_date, overall_status
    """, params, conn=conn)

    raw_by_date   = _counts_by_date(df_raw)
    vol_by_date   = _counts_by_date(df_vol)
    recon_by_date = _counts_by_date(df_recon)
    kpi_by_date   = _counts_by_date(df_kpi)
    fresh_by_date = _counts_by_date(df_fresh)

    # Combine VOLUME_ANOMALY + ROW_COUNT into pipeline_reliability per date
    pipe_by_date: dict = {}
    for bdate, counts in vol_by_date.items():
        for status, cnt in counts.items():
            pipe_by_date.setdefault(bdate, {})[status] = \
                pipe_by_date.get(bdate, {}).get(status, 0) + cnt
    for bdate, counts in recon_by_date.items():
        for status, cnt in counts.items():
            pipe_by_date.setdefault(bdate, {})[status] = \
                pipe_by_date.get(bdate, {}).get(status, 0) + cnt

    # Governance health treats DATE(review_timestamp) <= business_date as a
    # running "as-of" snapshot rather than an exact-date match, so replicate
    # that by forward-filling the most recent gov snapshot onto every date
    # in the requested range that has no exact match.
    gov_by_date: dict = {}
    gov_dates_sorted = sorted(_counts_by_date(df_gov, status_col="overall_status").items())
    last_counts = None
    gi = 0
    for bdate in sorted(dates):
        while gi < len(gov_dates_sorted) and gov_dates_sorted[gi][0] <= bdate:
            last_counts = gov_dates_sorted[gi][1]
            gi += 1
        if last_counts is not None:
            gov_by_date[bdate] = last_counts

    return {
        "raw_completeness"    : raw_by_date,
        "pipeline_reliability": pipe_by_date,
        "kpi_accuracy"        : kpi_by_date,
        "freshness"           : fresh_by_date,
        "governance_health"   : gov_by_date,
    }


def _load_history_with_today(days: int = 90) -> tuple:
    """
    Returns (history, today_dims) where:
      history    = list of (business_date_str, overall_score) oldest → newest
      today_dims = the 5-dimension score dict for the latest date

    Replaces the old per-date loop (up to `days * 6` SQL round-trips) with
    one date-list query plus one range query per dimension (6 total).
    """
    try:
        df_dates = execute_query(f"""
            SELECT DISTINCT business_date
            FROM (
                SELECT business_date FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
                UNION
                SELECT business_date FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
                UNION
                SELECT business_date FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            )
            ORDER BY business_date DESC
            LIMIT {int(days)}
        """)

        if df_dates.empty:
            return [], {key: None for key in WEIGHTS.keys()}

        dates = [str(row["business_date"])[:10] for _, row in df_dates.iterrows()]

        per_dim_counts = _load_all_dimension_counts(dates)

        history = []
        for bdate in dates:
            dims    = _dims_from_daily_counts(bdate, per_dim_counts)
            overall = _weighted_overall(dims)
            if overall is not None:
                history.append((bdate, overall))

        history.sort(key=lambda x: x[0])

        latest_date = history[-1][0] if history else max(dates)
        today_dims  = _dims_from_daily_counts(latest_date, per_dim_counts)

        return history, today_dims

    except Exception as e:
        logger.error(f"History load failed: {e}")
        return [], {key: None for key in WEIGHTS.keys()}


def _compute_trends(history: list) -> dict:
    """
    Computes trend vs 7 days ago and 30 days ago.
    history is list of (date_str, score) ordered oldest → newest.
    Returns dict with keys: vs_week, vs_month (floats or None).
    """
    if not history:
        return {"vs_week": None, "vs_month": None}

    latest_score = history[-1][1]
    latest_date  = history[-1][0]

    from datetime import date, timedelta
    try:
        latest_dt = date.fromisoformat(latest_date)
    except ValueError:
        return {"vs_week": None, "vs_month": None}

    target_week  = str(latest_dt - timedelta(days=7))
    target_month = str(latest_dt - timedelta(days=30))

    week_score  = None
    month_score = None

    for bdate, score in history:
        if bdate <= target_week:
            week_score = score
        if bdate <= target_month:
            month_score = score

    vs_week  = round(latest_score - week_score, 1)  if week_score  is not None else None
    vs_month = round(latest_score - month_score, 1) if month_score is not None else None

    return {"vs_week": vs_week, "vs_month": vs_month}


# ── UI helpers ─────────────────────────────────────────────────────────────

def _score_color(score: float) -> str:
    if score is None:
        return "#aaaaaa"
    if score >= 90:
        return "#00c851"
    if score >= 75:
        return "#ffa500"
    return "#ff6b6b"


def _score_bg(score: float) -> str:
    if score is None:
        return "#1a1a1a"
    if score >= 90:
        return "#002800"
    if score >= 75:
        return "#3d2000"
    return "#3d0000"


def _trend_element(label: str, delta) -> html.Span:
    if delta is None:
        return html.Span()
    arrow  = "↑" if delta >= 0 else "↓"
    color  = "#00c851" if delta >= 0 else "#ff6b6b"
    sign   = "+" if delta >= 0 else ""
    return html.Span(
        f"{arrow} {sign}{delta} pts {label}",
        style={
            "color"      : color,
            "fontSize"   : "15px",
            "marginRight": "24px",
        }
    )


def _dimension_row(key: str, score) -> html.Div:
    label       = DIMENSION_LABELS[key]
    description = DIMENSION_DESCRIPTIONS[key]
    color       = _score_color(score)
    bg          = _score_bg(score)
    score_text  = f"{score}/100" if score is not None else "No data"

    # Progress bar width
    bar_width = f"{score}%" if score is not None else "0%"

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div(
                    label,
                    style={
                        "color"    : "#ffffff",
                        "fontSize" : "16px",
                        "fontWeight": "500",
                    }
                ),
                html.Div(
                    description,
                    style={
                        "color"   : "#888888",
                        "fontSize": "13px",
                        "marginTop": "2px",
                    }
                ),
            ], md=6),
            dbc.Col([
                # Progress bar
                html.Div([
                    html.Div(
                        style={
                            "width"          : bar_width,
                            "height"         : "6px",
                            "backgroundColor": color,
                            "borderRadius"   : "3px",
                            "transition"     : "width 0.3s ease",
                        }
                    )
                ], style={
                    "backgroundColor": "#333333",
                    "borderRadius"   : "3px",
                    "marginTop"      : "8px",
                    "marginBottom"   : "4px",
                }),
            ], md=4, className="d-flex align-items-center"),
            dbc.Col([
                html.Div(
                    score_text,
                    style={
                        "color"    : color,
                        "fontSize" : "16px",
                        "fontWeight": "700",
                        "textAlign": "right",
                    }
                )
            ], md=2),
        ], align="center"),
    ], style={
        "padding"        : "16px 20px",
        "marginBottom"   : "8px",
        "borderRadius"   : "8px",
        "backgroundColor": bg,
        "borderLeft"     : f"4px solid {color}",
    })


def _build_chart(history: list) -> dcc.Graph:
    """Builds a 90-day score trend line chart."""
    if not history:
        return html.P(
            "Not enough history to display trend chart.",
            style={"color": "#aaaaaa", "fontSize": "14px",
                   "textAlign": "center", "padding": "40px"}
        )

    dates  = [h[0] for h in history]
    scores = [h[1] for h in history]

    # Colour each point by score band
    point_colors = [_score_color(s) for s in scores]

    fig = go.Figure()

    # ── Shaded bands ──────────────────────────────────────────────────────
    fig.add_hrect(y0=90, y1=100, fillcolor="rgba(0,200,81,0.05)",
                  line_width=0, layer="below")
    fig.add_hrect(y0=75, y1=90,  fillcolor="rgba(255,165,0,0.05)",
                  line_width=0, layer="below")
    fig.add_hrect(y0=0,  y1=75,  fillcolor="rgba(255,107,107,0.05)",
                  line_width=0, layer="below")

    # ── Reference lines ────────────────────────────────────────────────────
    fig.add_hline(y=90, line_dash="dot", line_color="#00c851",
                  line_width=1,
                  annotation_text="Good",
                  annotation_position="right",
                  annotation_font_color="#00c851",
                  annotation_font_size=11)
    fig.add_hline(y=75, line_dash="dot", line_color="#ffa500",
                  line_width=1,
                  annotation_text="Fair",
                  annotation_position="right",
                  annotation_font_color="#ffa500",
                  annotation_font_size=11)

    # ── Score line ─────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x    = dates,
        y    = scores,
        mode = "lines+markers",
        name = "Quality Score",
        line = dict(color="#4a9edd", width=2.5),
        marker = dict(
            color = point_colors,
            size  = 7,
            line  = dict(color="#ffffff", width=1)
        ),
        hovertemplate = "<b>%{x}</b><br>Score: %{y}/100<extra></extra>",
    ))

    fig.update_layout(
        height         = 280,
        paper_bgcolor  = "#2b2b2b",
        plot_bgcolor   = "#2b2b2b",
        font           = dict(color="#aaaaaa", size=12),
        showlegend     = False,
        margin         = dict(l=50, r=80, t=20, b=40),
        yaxis          = dict(
            range      = [0, 105],
            gridcolor  = "#333333",
            tickcolor  = "#555555",
            linecolor  = "#444444",
            ticksuffix = "",
            dtick      = 25,
        ),
        xaxis          = dict(
            gridcolor  = "#333333",
            tickcolor  = "#555555",
            linecolor  = "#444444",
        ),
        hovermode = "x unified",
    )

    return dcc.Graph(
        figure = fig,
        config = {"displayModeBar": False},
    )


# ── Page builder ───────────────────────────────────────────────────────────

def _build_page(today_dims: dict, history: list, trends: dict) -> html.Div:

    overall = _weighted_overall(today_dims)
    overall_color = _score_color(overall)
    overall_bg    = _score_bg(overall)

    # Latest date with data
    latest_date = history[-1][0] if history else "—"

    return html.Div([

        # ── Page title ─────────────────────────────────────────────────────
        html.H2(
            "Data Quality Score",
            className="mt-4 mb-1",
            style={"color": "#ffffff"}
        ),
        html.P(
            "A single measure of overall data platform health, "
            "computed from all four validation agents.",
            className="text-muted mb-4",
            style={"fontSize": "15px"}
        ),

        dbc.Row([

            # ── Left: Overall score ────────────────────────────────────────
            dbc.Col([
                html.Div([
                    # Big number
                    html.Div(
                        f"{overall}/100" if overall is not None else "—",
                        style={
                            "color"     : overall_color,
                            "fontSize"  : "64px",
                            "fontWeight": "800",
                            "lineHeight": "1",
                            "marginBottom": "8px",
                        }
                    ),
                    html.Div(
                        "Overall Score",
                        style={
                            "color"       : "#aaaaaa",
                            "fontSize"    : "14px",
                            "marginBottom": "20px",
                        }
                    ),
                    # Trend line
                    html.Div([
                        _trend_element("vs last week",  trends.get("vs_week")),
                    ], style={"marginBottom": "6px"}),
                    html.Div([
                        _trend_element("vs last month", trends.get("vs_month")),
                    ]),
                    html.Div(
                        f"As of {latest_date}",
                        style={
                            "color"    : "#555555",
                            "fontSize" : "12px",
                            "marginTop": "20px",
                        }
                    ),
                ], style={
                    "backgroundColor": overall_bg,
                    "borderLeft"     : f"4px solid {overall_color}",
                    "borderRadius"   : "8px",
                    "padding"        : "32px",
                    "height"         : "100%",
                })
            ], md=4),

            # ── Right: Dimension breakdown ─────────────────────────────────
            dbc.Col([
                html.Div(
                    "Score breakdown",
                    style={
                        "color"       : "#aaaaaa",
                        "fontSize"    : "13px",
                        "marginBottom": "12px",
                        "fontWeight"  : "600",
                        "letterSpacing": "1px",
                        "textTransform": "uppercase",
                    }
                ),
                *[
                    _dimension_row(key, today_dims.get(key))
                    for key in WEIGHTS.keys()
                ],
                # ── Scoring legend ─────────────────────────────────────────
                html.Div([
                    html.Span("90–100 Good  ",
                              style={"color": "#00c851", "fontSize": "12px"}),
                    html.Span("75–89 Fair  ",
                              style={"color": "#ffa500", "fontSize": "12px"}),
                    html.Span("0–74 Needs attention",
                              style={"color": "#ff6b6b", "fontSize": "12px"}),
                ], style={"marginTop": "12px", "paddingLeft": "4px"}),
            ], md=8),

        ], className="mb-4"),

        # ── Historical chart ───────────────────────────────────────────────
        dbc.Card([
            dbc.CardHeader(
                html.H6(
                    "90-Day Score Trend",
                    className="mb-0 text-white"
                )
            ),
            dbc.CardBody([
                _build_chart(history)
            ])
        ], style={
            "backgroundColor": "#2b2b2b",
            "border"         : "1px solid #444"
        }),

    ], style={"maxWidth": "1100px"})


def _error_page(message: str) -> html.Div:
    return html.Div([
        html.H2("Data Quality Score", className="mt-4 mb-2"),
        dbc.Alert(f"Could not load score data: {message}", color="danger")
    ])


# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([
    dcc.Interval(
        id          = "qs-refresh-interval",
        interval    = 5 * 60 * 1000,
        n_intervals = 0,
        disabled    = True
    ),

    dcc.Store(id="qs-refresh-paused", data=True),

    dbc.Row([
        dbc.Col([
            html.Div(
                id    = "qs-refresh-indicator",
                style = {"color": "#64748b", "fontSize": "12px",
                        "marginBottom": "8px"}
            )
        ], md=8),
        dbc.Col([
            dbc.Button(
                "⏸ Pause Auto-Refresh",
                id       = "qs-refresh-toggle",
                color    = "secondary",
                outline  = True,
                size     = "sm",
                n_clicks = 0,
                style    = {"fontSize": "12px"}
            )
        ], md=4, className="d-flex justify-content-end mb-2"),
    ]),

    dcc.Loading(
        id    = "qs-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="qs-page-content")
    )
], fluid=True)


# ── Callback ───────────────────────────────────────────────────────────────

@callback(
    Output("qs-page-content", "children"),
    Input("qs-refresh-interval", "n_intervals"),
    background=True,
)
def render_quality_score(n_intervals):
    try:
        history, today_dims = _load_history_with_today(days=90)

        if not history:
            return _error_page("No validation runs found.")

        trends = _compute_trends(history)

        return _build_page(today_dims, history, trends)

    except Exception as e:
        logger.error(f"Quality score page failed: {e}")
        import traceback
        traceback.print_exc()
        return _error_page(str(e))
    
@callback(
    Output("qs-refresh-interval",   "disabled"),
    Output("qs-refresh-toggle",     "children"),
    Output("qs-refresh-toggle",     "color"),
    Output("qs-refresh-indicator",  "children"),
    Output("qs-refresh-paused",     "data"),
    Input("qs-refresh-toggle",      "n_clicks"),
    State("qs-refresh-paused",      "data"),
    prevent_initial_call=True,
)
def toggle_qs_refresh(n_clicks, is_paused):
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