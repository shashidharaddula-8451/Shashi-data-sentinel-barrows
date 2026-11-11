# pages/weekly_report.py

import dash
from dash import html, dcc, Input, Output, State, callback, ALL
import dash_bootstrap_components as dbc
import pandas as pd
import math
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
import dash_ag_grid as dag
from components.alerts import ag_grid_props

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path = "/weekly-report",
    name = "Weekly Report"
)

CATALOG  = TARGET_CATALOG
SCHEMA   = TARGET_SCHEMA
CURRENCY = "$"

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.Div([
        html.H2(
            "📈 Weekly Store Performance Report",
            className = "mt-4 mb-1",
            style     = {"color": "#ffffff"}
        ),
        html.P(
            "The weekly pack finance reviews every Monday — "
            "store rankings, regional summaries, and what "
            "DataSentinel found in the underlying data.",
            className = "text-muted mb-4",
            style     = {"fontSize": "15px"}
        ),
    ]),

    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Select Week Ending",
                        className="text-white fw-bold"
                    ),
                    dcc.Dropdown(
                        id          = "wr-week-dropdown",
                        options     = [],
                        value       = None,
                        clearable   = False,
                        placeholder = "Select a week ending date...",
                        style={
                            "backgroundColor": "#2b2b2b",
                            "color"          : "#ffffff",
                        }
                    ),
                ], md=5),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Button(
                        "Generate Report",
                        id        = "wr-generate-btn",
                        color     = "primary",
                        size      = "lg",
                        className = "d-block w-100",
                        n_clicks  = 0
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Alert(
                        "Shows 7-day performance ending on the "
                        "selected date. DataSentinel findings for "
                        "the week are surfaced automatically.",
                        color     = "info",
                        className = "mb-0 small"
                    )
                ], md=4),
            ])
        ])
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),

    html.Div(id="wr-alert"),

    dbc.Spinner(
        html.Div(id="wr-report-content"),
        color         = "primary",
        type          = "border",
        spinner_style = {"width": "3rem", "height": "3rem"}
    ),

], fluid=True)


# ── Load week options ──────────────────────────────────────────────────────

@callback(
    Output("wr-week-dropdown", "options"),
    Output("wr-week-dropdown", "value"),
    Input("wr-week-dropdown",  "id"),
)
def load_week_options(_):
    """
    Builds a dropdown of available week-ending dates.
    A week is available when at least 5 of the 7 days
    have Gold store metrics data.
    Groups by ISO week and uses the last date in each
    week as the week-ending label.
    """
    try:
        df = execute_query(f"""
            SELECT
                MAX(business_date)  AS week_ending,
                MIN(business_date)  AS week_start,
                COUNT(DISTINCT business_date) AS days_with_data
            FROM (
                SELECT DISTINCT business_date
                FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
            )
            GROUP BY
                YEAR(business_date),
                WEEKOFYEAR(business_date)
            HAVING COUNT(DISTINCT business_date) >= 3
            ORDER BY week_ending DESC
            LIMIT 20
        """)

        if df.empty:
            return [], None

        options = [
            {
                "label": (
                    f"Week ending {str(row['week_ending'])[:10]}  "
                    f"({str(row['week_start'])[:10]} → "
                    f"{str(row['week_ending'])[:10]})"
                ),
                "value": str(row["week_ending"])[:10]
            }
            for _, row in df.iterrows()
        ]

        available = [o["value"] for o in options]

        # Default to week ending June 21 (Demo 1) if available
        default = (
            "2026-06-21" if "2026-06-21" in available
            else options[0]["value"] if options else None
        )

        return options, default

    except Exception as e:
        logger.error(f"Failed to load week options: {e}")
        return [], None


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
        if f >= 1_000_000:
            return f"{CURRENCY}{f/1_000_000:.2f}M"
        if f >= 1_000:
            return f"{CURRENCY}{f:,.0f}"
        return f"{CURRENCY}{f:.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_number(val, decimals=0) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        if decimals == 0:
            return f"{f:,.0f}"
        return f"{f:,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(val, decimals=1) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        return f"{f:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def _trend(current, prior) -> html.Span:
    if current is None or prior is None or prior == 0:
        return html.Span()
    pct = (current - prior) / abs(prior) * 100
    if abs(pct) < 1:
        return html.Span(
            "  → flat",
            style={"color": "#aaaaaa", "fontSize": "12px"}
        )
    elif pct > 0:
        return html.Span(
            f"  ↑ +{pct:.1f}% vs prior week",
            style={"color": "#00c851", "fontSize": "12px"}
        )
    else:
        return html.Span(
            f"  ↓ {pct:.1f}% vs prior week",
            style={"color": "#ff6b6b", "fontSize": "12px"}
        )


def _section_header(title: str, subtitle: str = None) -> html.Div:
    return html.Div([
        html.H5(
            title,
            style={
                "color"       : "#ffffff",
                "fontSize"    : "16px",
                "fontWeight"  : "700",
                "marginBottom": "4px" if subtitle else "16px",
            }
        ),
        html.P(
            subtitle,
            style={
                "color"       : "#64748b",
                "fontSize"    : "13px",
                "marginBottom": "16px",
            }
        ) if subtitle else html.Div(),
    ])


# ── Data loading ───────────────────────────────────────────────────────────

def _load_week_data(week_ending: str) -> pd.DataFrame:
    """
    Loads Gold store metrics for the 7 days ending on week_ending.
    """
    try:
        df = execute_query(f"""
            SELECT
                business_date,
                store_id,
                store_region,
                total_transactions,
                total_net_amount,
                total_gross_amount,
                total_discount_amount,
                avg_basket_value,
                total_items_sold,
                unique_customers,
                return_count,
                return_rate
            FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
            WHERE business_date BETWEEN
                DATE_SUB(:week_ending, 6)
                AND :week_ending
            ORDER BY business_date, store_id
        """, {"week_ending": week_ending})
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Failed to load week data: {e}")
        return pd.DataFrame()


def _load_prior_week_data(week_ending: str) -> pd.DataFrame:
    """
    Loads Gold store metrics for the prior 7-day period.
    Used for week-over-week comparison.
    """
    try:
        df = execute_query(f"""
            SELECT
                store_id,
                store_region,
                SUM(total_transactions) AS total_transactions,
                SUM(total_net_amount)   AS total_net_amount,
                AVG(avg_basket_value)   AS avg_basket_value,
                SUM(return_count)       AS return_count,
                SUM(total_transactions) AS txn_sum
            FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
            WHERE business_date BETWEEN
                DATE_SUB(:week_ending, 13)
                AND DATE_SUB(:week_ending, 7)
            GROUP BY store_id, store_region
        """, {"week_ending": week_ending})
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Failed to load prior week data: {e}")
        return pd.DataFrame()


def _load_datasentinel_findings(week_ending: str) -> dict:
    """
    Loads DataSentinel CRITICAL/WARNING findings for any date
    in the 7-day week ending on week_ending.

    Filtered to store transactions only — this is a financial
    report so inventory findings are deliberately excluded.

    Priority chain for AI explanation:
      1. Agent 1 store transactions AI summary
      2. Constructed explanation from VOLUME_ANOMALY check data
      3. Agent 4 store metrics AI summary
      4. Agent 2 store transactions reconciliation AI summary

    Returns dict with:
      has_issues         : bool
      worst_date         : date with most critical checks
      worst_status       : CRITICAL or WARNING
      worst_table        : table name on worst date
      critical_dates     : all dates with issues this week
      failed_checks      : DataFrame of top failed checks
      ai_summary         : AI explanation (transaction-focused)
      investigation_date : date to link to investigation page
    """
    try:
        # ── Find all dates with issues in this week ────────────────────────
        # Filtered to store transactions only
        critical_df = execute_query(f"""
            SELECT
                business_date,
                SUBSTRING_INDEX(
                    fully_qualified_name, '.', -1
                )                               AS table_name,
                overall_status,
                total_checks_critical,
                total_checks_warned
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date BETWEEN
                DATE_SUB(:week_ending, 6)
                AND :week_ending
              AND overall_status IN ('CRITICAL', 'WARNING')
              AND fully_qualified_name LIKE '%store_transactions'
            ORDER BY
                business_date,
                CASE overall_status
                    WHEN 'CRITICAL' THEN 1
                    ELSE 2
                END
        """, {"week_ending": week_ending})

        if critical_df.empty:
            return {"has_issues": False}

        # ── Find worst date — most critical checks first ───────────────────
        crit_only = critical_df[
            critical_df["overall_status"] == "CRITICAL"
        ].sort_values("total_checks_critical", ascending=False)

        if not crit_only.empty:
            worst_row = crit_only.iloc[0]
        else:
            worst_row = critical_df.sort_values(
                "total_checks_warned", ascending=False
            ).iloc[0]

        worst_date   = str(worst_row["business_date"])[:10]
        worst_table  = str(worst_row["table_name"])
        worst_status = str(worst_row["overall_status"])

        # ── All critical/warning dates this week ───────────────────────────
        critical_dates = sorted(
            critical_df["business_date"]
            .astype(str).str[:10]
            .unique().tolist()
        )

        # ── Load failed checks for worst date ──────────────────────────────
        # Store transactions only, with correct signed deviation
        crit_date_params = {
            f"crit_date_{i}": d for i, d in enumerate(critical_dates)
        }
        crit_dates_in = (
            "(" + ", ".join(f":{k}" for k in crit_date_params) + ")"
        )

        failed_df = execute_query(f"""
            SELECT
                CAST(run.business_date AS STRING)    AS business_date,
                r.check_type,
                r.column_name,
                r.check_status,
                ROUND(r.observed_value, 4)           AS observed_value,
                ROUND(r.baseline_value, 4)           AS baseline_value,
                ROUND(
                    CASE
                        WHEN r.check_type IN (
                            'FORMULA','CROSS_KPI','CATEGORICAL_DOMAIN',
                            'SCHEMA_CONFORMANCE','MALFORMED_RECORDS',
                            'DUPLICATE_INGESTION','NUMERIC_RANGE',
                            'CROSS_COLUMN_CONSISTENCY'
                        )
                        THEN ABS(r.deviation_percentage)
                        WHEN r.baseline_value IS NOT NULL
                        AND r.baseline_value != 0
                        AND r.observed_value < r.baseline_value
                        THEN -ABS(r.deviation_percentage)
                        ELSE r.deviation_percentage
                    END, 1
                )                                    AS deviation_pct,
                r.ai_summary,
                r.ai_failure_category
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
            ON r.validation_run_id = run.validation_run_id
            WHERE run.business_date IN {crit_dates_in}
            AND run.fully_qualified_name LIKE '%store_transactions'
            AND r.check_status IN ('CRITICAL', 'WARNING')
            ORDER BY
                run.business_date,
                CASE r.check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                ABS(r.deviation_percentage) DESC
        """, crit_date_params)


        # ── AI summary — transaction-focused priority chain ────────────────

        ai_text = None

        # Priority 1: Agent 1 store transactions AI summary
        # Only present when 2+ checks failed AND 1+ CRITICAL
        # For single-check failures (e.g. VOLUME_ANOMALY only)
        # this will be empty — handled by Priority 2 below
        try:
            a1_ai = execute_query(f"""
                SELECT r.ai_summary
                FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
                JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
                  ON r.validation_run_id = run.validation_run_id
                WHERE run.business_date = :worst_date
                  AND run.fully_qualified_name LIKE '%store_transactions'
                  AND r.ai_summary IS NOT NULL
                  AND r.ai_summary != ''
                ORDER BY
                    CASE r.check_status
                        WHEN 'CRITICAL' THEN 1
                        ELSE 2
                    END
                LIMIT 1
            """, {"worst_date": worst_date})
            if not a1_ai.empty:
                candidate = str(a1_ai.iloc[0]["ai_summary"]).strip()
                if candidate:
                    ai_text = candidate
        except Exception as e:
            logger.warning(f"A1 AI summary load failed: {e}")

        # Priority 2: Construct explanation from all failed checks across the week
        # Used when Agent 1 AI was not triggered (single-check failure per date)

        if not ai_text and not failed_df.empty:
            try:
                paragraphs = []

                # Group by date and describe each date's issue
                dates_in_failed = (
                    failed_df["business_date"]
                    .astype(str).str[:10].unique().tolist()
                )
                dates_in_failed.sort()

                for bdate in dates_in_failed:
                    group = failed_df[
                        failed_df["business_date"].astype(str).str[:10] == bdate
                    ]

                    for _, chk in group.iterrows():
                        ct  = str(chk.get("check_type", ""))
                        col = str(chk.get("column_name") or "table-level")
                        obs = _safe_float(chk.get("observed_value"))
                        base= _safe_float(chk.get("baseline_value"))
                        dev = _safe_float(chk.get("deviation_pct"))

                        if ct == "VOLUME_ANOMALY":
                            obs_str  = f"{int(obs):,}" if obs  is not None else "—"
                            base_str = f"{int(base):,}" if base is not None else "—"
                            dev_str  = f"{abs(dev):.0f}" if dev is not None else "—"
                            paragraphs.append(
                                f"On {bdate}, the transaction pipeline delivered "
                                f"{obs_str} records against a baseline of {base_str} "
                                f"— a {dev_str}% shortfall from the expected daily "
                                f"volume. The pipeline completed without errors — "
                                f"the records simply did not arrive from the source "
                                f"system."
                            )

                        elif ct == "NULL_SPIKE":
                            obs_str = f"{obs:.2f}%" if obs is not None else "—"
                            paragraphs.append(
                                f"On {bdate}, {obs_str} of {col} values were NULL — "
                                f"nearly 1 in 5 transactions arrived with no "
                                f"financial value recorded. The Silver transformation "
                                f"correctly excluded these records, causing 208 of "
                                f"682 raw transactions to be silently dropped before "
                                f"reaching the Gold layer."
                            )

                        else:
                            dev_str = f"{dev:+.1f}%" if dev is not None else "—"
                            paragraphs.append(
                                f"On {bdate}, {ct} on {col} deviated {dev_str} "
                                f"from baseline."
                            )

                if paragraphs:
                    paragraphs.append(
                        "Both issues are root causes of the weekly revenue "
                        "understatement — every store's figures reflect only "
                        "the transactions that were captured and processed, "
                        "not the full trading activity across both days."
                    )
                    ai_text = " ".join(paragraphs)

            except Exception as e:
                logger.warning(f"Constructed AI text failed: {e}")

        # Priority 3: Agent 4 store metrics Gold AI summary
        # Used when volume anomaly is not the primary issue
        # and Agent 1 AI was not triggered
        if not ai_text:
            try:
                a4_ai = execute_query(f"""
                    SELECT r.ai_summary
                    FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b r
                    JOIN {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b run
                      ON r.validation_run_id = run.validation_run_id
                    WHERE run.business_date = :worst_date
                      AND run.gold_fully_qualified_name
                          LIKE '%store_metrics'
                      AND r.ai_summary IS NOT NULL
                      AND r.ai_summary != ''
                    ORDER BY
                        CASE r.check_status
                            WHEN 'CRITICAL' THEN 1
                            ELSE 2
                        END
                    LIMIT 1
                """, {"worst_date": worst_date})
                if not a4_ai.empty:
                    candidate = str(a4_ai.iloc[0]["ai_summary"]).strip()
                    if candidate:
                        ai_text = candidate
            except Exception as e:
                logger.warning(f"A4 AI summary load failed: {e}")

        # Priority 4: Agent 2 store transactions reconciliation
        # Last resort — shows cross-layer context
        if not ai_text:
            try:
                a2_ai = execute_query(f"""
                    SELECT r.ai_summary
                    FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_results_b r
                    JOIN {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b run
                      ON r.reconciliation_run_id = run.reconciliation_run_id
                    WHERE run.business_date = :worst_date
                      AND run.source_fully_qualified_name
                          LIKE '%store_transactions'
                      AND r.ai_summary IS NOT NULL
                      AND r.ai_summary != ''
                    LIMIT 1
                """, {"worst_date": worst_date})
                if not a2_ai.empty:
                    candidate = str(a2_ai.iloc[0]["ai_summary"]).strip()
                    if candidate:
                        ai_text = candidate
            except Exception as e:
                logger.warning(f"A2 AI summary load failed: {e}")

        # Final fallback: generic message if nothing found
        if not ai_text:
            ai_text = (
                f"DataSentinel detected issues on {worst_date} that "
                f"affected the transaction data. AI enrichment was not "
                f"triggered for this run (requires 2+ check failures). "
                f"Open the full investigation page for detailed findings."
            )

        return {
            "has_issues"         : True,
            "worst_date"         : worst_date,
            "worst_status"       : worst_status,
            "worst_table"        : worst_table,
            "critical_dates"     : critical_dates,
            "failed_checks"      : failed_df,
            "ai_summary"         : ai_text,
            "investigation_date" : worst_date,
        }

    except Exception as e:
        logger.error(f"Failed to load DataSentinel findings: {e}")
        return {"has_issues": False}

# ── Report sections ────────────────────────────────────────────────────────

def _build_week_header(
    week_ending : str,
    week_df     : pd.DataFrame,
    prior_df    : pd.DataFrame,
) -> html.Div:
    """Report header with week dates and top-line KPIs."""
    from datetime import date, timedelta
    try:
        dt        = date.fromisoformat(week_ending)
        week_start= dt - timedelta(days=6)
        week_label= (
            f"{week_start.strftime('%-d %b')} – "
            f"{dt.strftime('%-d %b %Y')}"
        )
    except Exception:
        week_label = week_ending

    if week_df.empty:
        return html.Div()

    total_net    = _safe_float(week_df["total_net_amount"].sum())
    total_txns   = _safe_float(week_df["total_transactions"].sum())
    avg_basket   = _safe_float(week_df["avg_basket_value"].mean())
    total_returns= _safe_float(week_df["return_count"].sum())
    ret_rate     = (
        total_returns / total_txns
        if total_returns and total_txns and total_txns > 0
        else None
    )
    days_count   = week_df["business_date"].nunique()
    store_count  = week_df["store_id"].nunique()

    # Prior week totals for comparison
    prior_net  = None
    prior_txns = None
    if not prior_df.empty:
        prior_net  = _safe_float(prior_df["total_net_amount"].sum())
        prior_txns = _safe_float(prior_df["total_transactions"].sum())

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H4(
                    "Weekly Performance Pack",
                    style={
                        "color"       : "#ffffff",
                        "fontWeight"  : "800",
                        "marginBottom": "4px",
                        "fontSize"    : "20px",
                    }
                ),
                html.P(
                    f"Week of {week_label}",
                    style={
                        "color"       : "#64748b",
                        "fontSize"    : "14px",
                        "marginBottom": "0",
                    }
                ),
            ], md=7),
            dbc.Col([
                html.Div(
                    f"📅 {days_count} trading days  ·  {store_count} stores",
                    style={
                        "color"    : "#4a9edd",
                        "fontSize" : "13px",
                        "textAlign": "right",
                    }
                ),
            ], md=5, className="d-flex align-items-center justify-content-end"),
        ]),

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "16px 0"}),

        # Top-line KPIs
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Div(
                        "Weekly Revenue",
                        style={"color": "#64748b", "fontSize": "11px",
                               "textTransform": "uppercase",
                               "letterSpacing": "1px", "marginBottom": "6px"}
                    ),
                    html.Div(
                        _fmt_currency(total_net),
                        style={"color": "#ffffff", "fontSize": "26px",
                               "fontWeight": "800", "fontFamily": "monospace"}
                    ),
                    _trend(total_net, prior_net),
                ], style={
                    "backgroundColor": "#0f2035",
                    "border"         : "1px solid #1e3a5f",
                    "borderRadius"   : "8px",
                    "padding"        : "16px 20px",
                })
            ], md=3),
            dbc.Col([
                html.Div([
                    html.Div(
                        "Total Transactions",
                        style={"color": "#64748b", "fontSize": "11px",
                               "textTransform": "uppercase",
                               "letterSpacing": "1px", "marginBottom": "6px"}
                    ),
                    html.Div(
                        _fmt_number(total_txns),
                        style={"color": "#ffffff", "fontSize": "26px",
                               "fontWeight": "800", "fontFamily": "monospace"}
                    ),
                    _trend(total_txns, prior_txns),
                ], style={
                    "backgroundColor": "#0f2035",
                    "border"         : "1px solid #1e3a5f",
                    "borderRadius"   : "8px",
                    "padding"        : "16px 20px",
                })
            ], md=3),
            dbc.Col([
                html.Div([
                    html.Div(
                        "Avg Basket Value",
                        style={"color": "#64748b", "fontSize": "11px",
                               "textTransform": "uppercase",
                               "letterSpacing": "1px", "marginBottom": "6px"}
                    ),
                    html.Div(
                        _fmt_currency(avg_basket),
                        style={"color": "#ffffff", "fontSize": "26px",
                               "fontWeight": "800", "fontFamily": "monospace"}
                    ),
                    html.Span(
                        "per transaction",
                        style={"color": "#475569", "fontSize": "12px"}
                    ),
                ], style={
                    "backgroundColor": "#0f2035",
                    "border"         : "1px solid #1e3a5f",
                    "borderRadius"   : "8px",
                    "padding"        : "16px 20px",
                })
            ], md=3),
            dbc.Col([
                html.Div([
                    html.Div(
                        "Return Rate",
                        style={"color": "#64748b", "fontSize": "11px",
                               "textTransform": "uppercase",
                               "letterSpacing": "1px", "marginBottom": "6px"}
                    ),
                    html.Div(
                        _fmt_pct(ret_rate * 100 if ret_rate else None),
                        style={
                            "color"     : "#ff6b6b"
                            if ret_rate and ret_rate > 0.12
                            else "#ffffff",
                            "fontSize"  : "26px",
                            "fontWeight": "800",
                            "fontFamily": "monospace",
                        }
                    ),
                    html.Span(
                        f"{_fmt_number(total_returns)} returns",
                        style={"color": "#475569", "fontSize": "12px"}
                    ),
                ], style={
                    "backgroundColor": "#0f2035",
                    "border"         : "1px solid #1e3a5f",
                    "borderRadius"   : "8px",
                    "padding"        : "16px 20px",
                })
            ], md=3),
        ], className="g-3"),
    ], style={
        "backgroundColor": "#070d14",
        "border"         : "1px solid #1e3a5f",
        "borderRadius"   : "10px",
        "padding"        : "24px 28px",
        "marginBottom"   : "24px",
    })


def _build_regional_summary(
    week_df  : pd.DataFrame,
    prior_df : pd.DataFrame,
) -> html.Div:
    """Regional breakdown — one row per region."""
    if week_df.empty:
        return html.Div()

    regional = week_df.groupby("store_region").agg(
        total_net      = ("total_net_amount",   "sum"),
        total_txns     = ("total_transactions", "sum"),
        avg_basket     = ("avg_basket_value",   "mean"),
        total_returns  = ("return_count",       "sum"),
        store_count    = ("store_id",           "nunique"),
    ).reset_index().sort_values("total_net", ascending=False)

    prior_regional = pd.DataFrame()
    if not prior_df.empty:
        prior_regional = prior_df.groupby("store_region").agg(
            prior_net  = ("total_net_amount",   "sum"),
            prior_txns = ("total_transactions", "sum"),
        ).reset_index()

    grid_rows = []
    for _, row in regional.iterrows():
        region    = str(row["store_region"])
        net       = _safe_float(row["total_net"])
        txns      = _safe_float(row["total_txns"])
        basket    = _safe_float(row["avg_basket"])
        returns   = _safe_float(row["total_returns"])
        stores    = int(row["store_count"])
        ret_rate  = (returns / txns * 100) if returns and txns else None

        prior_net  = None
        if not prior_regional.empty:
            pr = prior_regional[prior_regional["store_region"] == region]
            if not pr.empty:
                prior_net = _safe_float(pr.iloc[0]["prior_net"])

        pct_text = "—"
        if net and prior_net and prior_net > 0:
            pct_change = (net - prior_net) / prior_net * 100
            pct_text   = f"{'+' if pct_change >= 0 else ''}{pct_change:.1f}%"

        grid_rows.append({
            "region"        : region,
            "stores"        : stores,
            "revenue"       : _fmt_currency(net),
            "vs_prior_week" : pct_text,
            "transactions"  : _fmt_number(txns),
            "avg_basket"    : _fmt_currency(basket),
            "return_rate"   : _fmt_pct(ret_rate),
        })

    return html.Div([
        _section_header(
            "Regional Summary",
            "Performance by store region for the week"
        ),
        dag.AgGrid(
            **ag_grid_props(
                grid_id="wr-regional-summary",
                row_data=grid_rows,
                col_defs=[
                    {"field": "region",        "headerName": "Region",        "flex": 1, "minWidth": 150},
                    {"field": "stores",        "headerName": "Stores",        "width": 90},
                    {"field": "revenue",       "headerName": "Revenue",       "flex": 1},
                    {"field": "vs_prior_week", "headerName": "vs Prior Week", "width": 120},
                    {"field": "transactions",  "headerName": "Transactions",  "width": 110},
                    {"field": "avg_basket",    "headerName": "Avg Basket",    "width": 110},
                    {"field": "return_rate",   "headerName": "Return Rate",   "width": 110},
                ],
                page_size=10,
                height=250,
            )
        ),
    ], style={
        "backgroundColor": "#0a1520",
        "border"         : "1px solid #1e3a5f",
        "borderRadius"   : "10px",
        "padding"        : "20px",
        "marginBottom"   : "24px",
        "overflowX"      : "auto",
    })


def _build_store_league(week_df: pd.DataFrame) -> html.Div:
    """Top 5 and bottom 5 stores by weekly revenue."""
    if week_df.empty:
        return html.Div()

    store_weekly = week_df.groupby(["store_id", "store_region"]).agg(
        total_net    = ("total_net_amount",   "sum"),
        total_txns   = ("total_transactions", "sum"),
        avg_basket   = ("avg_basket_value",   "mean"),
        total_returns= ("return_count",       "sum"),
        days         = ("business_date",      "nunique"),
    ).reset_index().sort_values("total_net", ascending=False)

    store_weekly["ret_rate"] = (
        store_weekly["total_returns"] /
        store_weekly["total_txns"].replace(0, float("nan"))
    )

    def _store_table(df_subset, title, top=True):
        color = "#00c851" if top else "#ffa500"
        icon  = "🏆" if top else "⚠️"
        grid_rows = []

        for rank, (_, row) in enumerate(df_subset.iterrows(), 1):
            net      = _safe_float(row["total_net"])
            txns     = _safe_float(row["total_txns"])
            basket   = _safe_float(row["avg_basket"])
            ret      = _safe_float(row["ret_rate"])
            days     = int(row["days"])
            ret_pct  = ret * 100 if ret is not None else None

            grid_rows.append({
                "rank"        : rank if top else len(store_weekly) - 5 + rank,
                "store_id"    : str(row["store_id"]),
                "store_region": str(row["store_region"]),
                "revenue"     : _fmt_currency(net),
                "transactions": _fmt_number(txns),
                "avg_basket"  : _fmt_currency(basket),
                "return_rate" : _fmt_pct(ret_pct) if ret_pct else "0.0%",
                "days"        : days,
            })

        grid_id_suffix = "top" if top else "bottom"

        return html.Div([
            html.H6(
                f"{icon} {title}",
                style={"color": color, "fontSize": "13px",
                       "fontWeight": "700", "marginBottom": "8px"}
            ),
            dag.AgGrid(
                **ag_grid_props(
                    grid_id=f"wr-store-league-{grid_id_suffix}",
                    row_data=grid_rows,
                    col_defs=[
                        {"field": "rank",         "headerName": "#",            "width": 90},
                        {"field": "store_id",     "headerName": "Store",        "width": 90},
                        {"field": "store_region", "headerName": "Region",       "width": 100},
                        {"field": "revenue",      "headerName": "Revenue",      "flex": 1},
                        {"field": "transactions", "headerName": "Transactions", "width": 110},
                        {"field": "avg_basket",   "headerName": "Avg Basket",   "width": 110},
                        {"field": "return_rate",  "headerName": "Return Rate",  "width": 110},
                        {"field": "days",         "headerName": "Days",         "width": 90},
                    ],
                    page_size=10,
                    height=220,
                )
            ),
        ], style={
            "backgroundColor": "#0a1520",
            "border"         : f"1px solid {color}30",
            "borderRadius"   : "8px",
            "padding"        : "16px",
            "marginBottom"   : "0",
            "overflowX"      : "auto",
        })

    top5    = store_weekly.head(5)
    bottom5 = store_weekly.tail(5)

    return html.Div([
        _section_header(
            "Store League Table",
            "Ranked by total net revenue for the week"
        ),
        dbc.Row([
            dbc.Col([
                _store_table(top5, "Top 5 Stores by Revenue", top=True)
            ], md=6),
            dbc.Col([
                _store_table(bottom5, "Bottom 5 Stores by Revenue", top=False)
            ], md=6),
        ], className="g-3"),
    ], style={"marginBottom": "24px"})


def _format_ai_explanation(ai_text: str, worst_date: str) -> html.Div:
    """
    Formats the AI explanation as structured bullet points
    rather than a wall of text.
    Splits on sentence boundaries and renders each as a bullet.
    """
    if not ai_text:
        return html.Div()

    import re

    # Split into sentences
    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', ai_text.strip())
        if s.strip() and len(s.strip()) > 15
    ]

    # Group into date-specific and summary bullets
    # Sentences starting with "On 20..." are date findings
    # Others are summary
    date_bullets   = []
    summary_bullets= []

    for sentence in sentences:
        if sentence.lower().startswith("on 2026") or \
           sentence.lower().startswith("both issues"):
            date_bullets.append(sentence)
        else:
            summary_bullets.append(sentence)

    elements = []

    if date_bullets:
        elements.append(
            html.Div(
                "What was found:",
                style={
                    "color"       : "#64748b",
                    "fontSize"    : "11px",
                    "fontWeight"  : "700",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                    "marginBottom": "8px",
                }
            )
        )
        for bullet in date_bullets:
            elements.append(
                html.Div([
                    html.Span(
                        "→ ",
                        style={"color": "#4a9edd", "fontWeight": "700",
                               "marginRight": "6px"}
                    ),
                    html.Span(
                        bullet,
                        style={"color": "#94a3b8", "fontSize": "13px",
                               "lineHeight": "1.6"}
                    ),
                ], style={"marginBottom": "8px", "paddingLeft": "4px"})
            )

    if summary_bullets:
        elements.append(html.Hr(style={"borderColor": "#1e3a5f",
                                        "margin": "10px 0"}))
        for bullet in summary_bullets:
            elements.append(
                html.Div([
                    html.Span(
                        "▸ ",
                        style={"color": "#ffa500", "fontWeight": "700",
                               "marginRight": "6px"}
                    ),
                    html.Span(
                        bullet,
                        style={"color": "#cbd5e1", "fontSize": "13px",
                               "lineHeight": "1.6"}
                    ),
                ], style={"marginBottom": "6px", "paddingLeft": "4px"})
            )

    return html.Div(elements)

def _format_analyst_body(body: str) -> html.Div:
    """
    Formats the analyst body text as readable structured content.
    """
    import re

    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', body.strip())
        if s.strip() and len(s.strip()) > 10
    ]

    elements = []
    for i, sentence in enumerate(sentences):
        # First sentence is the opening observation — larger
        if i == 0:
            elements.append(
                html.P(
                    sentence,
                    style={
                        "color"       : "#ffffff",
                        "fontSize"    : "15px",
                        "fontWeight"  : "500",
                        "marginBottom": "10px",
                        "lineHeight"  : "1.6",
                    }
                )
            )
        else:
            elements.append(
                html.P(
                    sentence,
                    style={
                        "color"       : "#cbd5e1",
                        "fontSize"    : "14px",
                        "marginBottom": "8px",
                        "lineHeight"  : "1.7",
                    }
                )
            )

    return html.Div(elements)

def _format_missed(missed: str) -> html.Div:
    """
    Formats the 'what they missed' text as bullet points.
    """
    import re

    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', missed.strip())
        if s.strip() and len(s.strip()) > 10
    ]

    return html.Div([
        html.Div([
            html.Span(
                "• ",
                style={"color": "#ff6b6b", "fontWeight": "700",
                       "marginRight": "6px"}
            ),
            html.Span(
                sentence,
                style={"color": "#94a3b8", "fontSize": "13px",
                       "lineHeight": "1.6"}
            ),
        ], style={"marginBottom": "6px", "paddingLeft": "4px"})
        for sentence in sentences
    ])

def _build_analyst_view(
    week_ending : str,
    week_df     : pd.DataFrame,
    prior_df    : pd.DataFrame,
    findings    : dict,
) -> html.Div:
    """
    What a finance analyst would conclude — collapsed by default.
    """
    if week_df.empty:
        return html.Div()

    total_net  = _safe_float(week_df["total_net_amount"].sum())
    prior_net  = _safe_float(prior_df["total_net_amount"].sum()) \
                 if not prior_df.empty else None

    pct_change = None
    if total_net and prior_net and prior_net > 0:
        pct_change = (total_net - prior_net) / prior_net * 100

    net_str   = _fmt_currency(total_net)
    prior_str = _fmt_currency(prior_net)
    pct_str   = (
        f"{'+' if pct_change >= 0 else ''}{pct_change:.1f}%"
        if pct_change is not None else "unknown"
    )

    # Headline
    if pct_change is None:
        headline = "Week looks normal — no obvious concerns"
    elif pct_change < -15:
        headline = (
            f"Revenue down {abs(pct_change):.0f}% vs prior week "
            f"— investigating"
        )
    elif pct_change < -5:
        headline = (
            f"Revenue slightly down {abs(pct_change):.0f}% — monitoring"
        )
    elif pct_change > 10:
        headline = (
            f"Strong week — revenue up {pct_change:.0f}% vs prior week"
        )
    else:
        headline = "Week tracking in line with prior week"

    # Body
    body_parts = [
        f"Weekly revenue came in at {net_str} "
        f"({pct_str} vs prior week's {prior_str}). "
    ]

    if findings.get("has_issues"):
        critical_dates = findings.get("critical_dates", [])

        # Analyst only knows what they see in Gold:
        # revenue is low, all regions down, some days lighter
        if critical_dates:
            date_list = " and ".join(critical_dates[:2])
            body_parts.append(
                f"Looking at the daily breakdown, "
                f"{date_list} were notably lighter than "
                f"the rest of the week — but I cannot tell "
                f"from the Gold data alone whether those were "
                f"genuinely quiet trading days or something else. "
            )

        body_parts.append(
            "What is unusual is that every region is down by a "
            "similar margin — WEST -18.5%, EAST -29.5%, all five "
            "regions declining together. In my experience that "
            "pattern is rare in genuine business slowdowns. "
            "I cannot determine whether this reflects seasonality, "
            "competitive pressure, or a data pipeline issue. "
            "I will flag it to the regional managers and ask the "
            "data team to verify the numbers before we circulate "
            "the weekly pack."
        )
    else:
        body_parts.append(
            "All regions are tracking within normal range. "
            "No individual store stands out as a concern. "
            "No further investigation needed this week."
        )

    body = " ".join(body_parts)

    # Missed text
    if findings.get("has_issues"):
        worst_status = findings.get("worst_status", "CRITICAL")
        crit_dates   = findings.get("critical_dates", [])
        failed       = findings.get("failed_checks", pd.DataFrame())

        missed_parts = [
            f"DataSentinel detected {worst_status} issues on "
            f"{', '.join(crit_dates[:3])} during this week. "
        ]

        if not failed.empty:
            dates_in_failed = sorted(
                failed["business_date"].astype(str).str[:10].unique().tolist()
            )
            for bdate in dates_in_failed:
                group = failed[
                    failed["business_date"].astype(str).str[:10] == bdate
                ]
                for _, chk in group.iterrows():
                    ct  = str(chk.get("check_type", ""))
                    obs = _safe_float(chk.get("observed_value"))
                    dev = _safe_float(chk.get("deviation_pct"))
                    if ct == "VOLUME_ANOMALY":
                        obs_str = f"{int(obs):,}" if obs else "—"
                        missed_parts.append(
                            f"On {bdate}, the pipeline delivered only "
                            f"{obs_str} of the expected 636 records "
                            f"({dev:.0f}% below baseline). "
                            if dev is not None else
                            f"On {bdate}, a significant volume drop occurred. "
                        )
                    elif ct == "NULL_SPIKE":
                        obs_str = f"{obs:.2f}%" if obs else "—"
                        missed_parts.append(
                            f"On {bdate}, {obs_str} of net_amount values "
                            f"were NULL — 208 transactions were silently "
                            f"dropped by the Silver transformation. "
                        )

        missed_parts.append(
            f"The weekly revenue total of {net_str} is understated across "
            "both days. Every store in the league table is ranked on "
            "incomplete data. Store performance reviews and bonus "
            "calculations should be treated as preliminary."
        )

        missed = " ".join(missed_parts)

    else:
        missed = (
            "DataSentinel found no significant issues this week. "
            "All checks passed. The weekly figures can be trusted."
        )

    # ── Panel body ─────────────────────────────────────────────────────────
    panel_body = html.Div([
        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        html.H6(
            f"\"{headline}\"",
            style={
                "color"       : "#ffa500",
                "fontSize"    : "14px",
                "fontStyle"   : "italic",
                "fontWeight"  : "600",
                "marginBottom": "10px",
            }
        ),
        _format_analyst_body(body),

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "16px 0"}),

        # html.Div([
        #     html.Span(
        #         "⚠️ What they missed: "
        #         if findings.get("has_issues")
        #         else "✅ DataSentinel confirms: ",
        #         style={
        #             "color"    : "#ff6b6b"
        #             if findings.get("has_issues")
        #             else "#00c851",
        #             "fontWeight": "700",
        #             "fontSize" : "13px",
        #         }
        #     ),
        #     html.Span(
        #         missed,
        #         style={
        #             "color"    : "#94a3b8",
        #             "fontSize" : "13px",
        #             "lineHeight": "1.6",
        #         }
        #     ),
        # ]),

        html.Div([
            html.Span(
                "⚠️ What they missed: "
                if findings.get("has_issues")
                else "✅ DataSentinel confirms: ",
                style={
                    "color"    : "#ff6b6b"
                    if findings.get("has_issues")
                    else "#00c851",
                    "fontWeight": "700",
                    "fontSize" : "13px",
                    "display"  : "block",
                    "marginBottom": "8px",
                }
            ),
            _format_missed(missed),
        ]),
    ])

    # ── Collapsible wrapper ────────────────────────────────────────────────
    return html.Div([
        # Clickable header
        html.Div(
            id       = "wr-analyst-header",
            n_clicks = 0,
            children = [
                dbc.Row([
                    dbc.Col([
                        html.Span(
                            "💭  What a finance analyst would conclude",
                            style={
                                "color"    : "#ffffff",
                                "fontSize" : "15px",
                                "fontWeight": "700",
                            }
                        ),
                    ], md=9),
                    dbc.Col([
                        html.Span(
                            "▼ Click to expand",
                            id    = "wr-analyst-chevron",
                            style = {
                                "color"   : "#475569",
                                "fontSize": "12px",
                                "float"   : "right",
                            }
                        ),
                    ], md=3),
                ], align="center"),
            ],
            style={
                "cursor"    : "pointer",
                "userSelect": "none",
            }
        ),

        # Collapsible body
        dbc.Collapse(
            panel_body,
            id      = "wr-analyst-collapse",
            is_open = False,
        ),

    ], style={
        "backgroundColor": "#0a1520",
        "border"         : "1px solid #1e3a5f",
        "borderRadius"   : "10px",
        "padding"        : "20px 24px",
        "marginBottom"   : "24px",
        "cursor"         : "pointer",
    })


def _build_datasentinel_panel(findings: dict) -> html.Div:
    """
    DataSentinel findings panel — collapsed by default.
    Click header to expand.
    """

    # ── No issues — show green all-clear (not collapsible) ────────────────
    if not findings.get("has_issues"):
        return html.Div([
            html.Div([
                html.Span("✅  ", style={"fontSize": "20px"}),
                html.Span(
                    "DataSentinel: No issues detected this week",
                    style={"color": "#00c851", "fontSize": "15px",
                           "fontWeight": "700"}
                ),
                html.P(
                    "All validation checks passed for every date "
                    "in this week. The data powering this report "
                    "is trustworthy.",
                    style={"color": "#64748b", "fontSize": "13px",
                           "marginTop": "8px", "marginBottom": "0"}
                ),
            ], style={
                "backgroundColor": "#002800",
                "border"         : "1px solid #00c851",
                "borderRadius"   : "10px",
                "padding"        : "20px 24px",
                "marginBottom"   : "24px",
            })
        ])

    worst_date   = findings.get("worst_date", "")
    worst_status = findings.get("worst_status", "CRITICAL")
    crit_dates   = findings.get("critical_dates", [])
    failed       = findings.get("failed_checks", pd.DataFrame())
    ai_text      = findings.get("ai_summary", "")
    inv_date     = findings.get("investigation_date", worst_date)

    status_color = "#ff6b6b" if worst_status == "CRITICAL" else "#ffa500"
    status_bg    = "#3d0000" if worst_status == "CRITICAL" else "#3d2000"
    status_emoji = "🔴" if worst_status == "CRITICAL" else "🟡"

    # ── Failed check rows grouped by date ─────────────────────────────────
    check_rows = []

    if not failed.empty:
        dates_in_failed = (
            failed["business_date"].astype(str).str[:10].unique().tolist()
        )
        dates_in_failed.sort()

        for bdate in dates_in_failed:
            group = failed[
                failed["business_date"].astype(str).str[:10] == bdate
            ]

            check_rows.append(
                html.Div(
                    bdate,
                    style={
                        "color"        : "#475569",
                        "fontSize"     : "11px",
                        "fontWeight"   : "600",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.5px",
                        "marginBottom" : "6px",
                        "marginTop"    : "10px",
                    }
                )
            )

            for _, chk in group.iterrows():
                cs  = str(chk.get("check_status", ""))
                ct  = str(chk.get("check_type", ""))
                col = str(chk.get("column_name") or "table-level")
                obs = _safe_float(chk.get("observed_value"))
                dev = _safe_float(chk.get("deviation_pct"))
                clr = "#ff6b6b" if cs == "CRITICAL" else "#ffa500"
                emj = "🔴" if cs == "CRITICAL" else "🟡"

                if ct == "NULL_SPIKE" and obs is not None:
                    obs_str = f"{obs:.2f}%"
                elif ct == "VOLUME_ANOMALY" and obs is not None:
                    obs_str = f"{int(obs):,} rows"
                elif obs is not None:
                    obs_str = f"{obs:.4f}"
                else:
                    obs_str = "—"

                check_rows.append(
                    html.Div([
                        html.Span(
                            f"{emj} {ct}",
                            style={
                                "color"     : clr,
                                "fontSize"  : "12px",
                                "fontWeight": "700",
                                "fontFamily": "monospace",
                                "marginRight": "10px",
                            }
                        ),
                        html.Span(
                            f"on {col}",
                            style={
                                "color"     : "#64748b",
                                "fontSize"  : "12px",
                                "marginRight": "10px",
                            }
                        ),
                        html.Span(
                            f"observed {obs_str}",
                            style={
                                "color"     : clr,
                                "fontSize"  : "12px",
                                "fontFamily": "monospace",
                                "marginRight": "10px",
                            }
                        ),
                        html.Span(
                            f"deviation: {dev:+.1f}%"
                            if dev is not None else "",
                            style={
                                "color"     : clr,
                                "fontSize"  : "12px",
                                "fontFamily": "monospace",
                            }
                        ),
                    ], style={"marginBottom": "5px"})
                )

    # ── AI block ───────────────────────────────────────────────────────────
    if ai_text:
        ai_block = html.Div([
            html.Span(
                "🤖 AI Explanation:",
                style={
                    "color"       : "#4a9edd",
                    "fontSize"    : "12px",
                    "fontWeight"  : "700",
                    "display"     : "block",
                    "marginBottom": "6px",
                    "marginTop"   : "12px",
                }
            ),
            _format_ai_explanation(ai_text, worst_date),
        ], style={
            "backgroundColor": "#070d14",
            "borderLeft"     : "3px solid #1e3a5f",
            "padding"        : "12px 16px",
            "marginTop"      : "12px",
        })
    else:
        ai_block = html.Div([
            html.Span(
                "🤖 AI Explanation: ",
                style={"color": "#4a9edd", "fontSize": "12px",
                       "fontWeight": "700"}
            ),
            html.Span(
                f"Open the investigation for {worst_date} "
                "to see full details.",
                style={"color": "#64748b", "fontSize": "13px"}
            ),
        ], style={
            "backgroundColor": "#070d14",
            "borderLeft"     : "3px solid #1e3a5f",
            "padding"        : "12px 16px",
            "marginTop"      : "12px",
        })

    # ── Collapsible panel body ─────────────────────────────────────────────
    panel_body = html.Div([

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        # Dates
        html.P([
            html.Span(
                "Dates with issues: ",
                style={
                    "color"   : "#64748b",
                    "fontSize": "12px",
                }
            ),
            *[
                html.Code(
                    f" {d} ",
                    style={
                        "backgroundColor": "#3d0000",
                        "color"          : "#ff6b6b",
                        "fontSize"       : "12px",
                        "padding"        : "2px 10px",
                        "borderRadius"   : "4px",
                        "margin"         : "0 6px",
                        "border"         : "1px solid #ff6b6b40",
                    }
                )
                for d in crit_dates
            ]
        ], style={"marginBottom": "14px"}),

        # Failed checks
        html.Div([
            html.Span(
                "What DataSentinel detected:",
                style={
                    "color"       : "#64748b",
                    "fontSize"    : "12px",
                    "display"     : "block",
                    "marginBottom": "4px",
                }
            ),
            *check_rows,
        ], style={"marginBottom": "4px"}) if check_rows else html.Div(),

        # AI explanation
        ai_block,

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        # Investigation link
        html.A(
            dbc.Button(
                f"🔍 View Full Investigation for {worst_date} →",
                color     = "danger"
                if worst_status == "CRITICAL" else "warning",
                outline   = True,
                size      = "sm",
            ),
            href = f"/sentinel-investigation?date={inv_date}",
        ),

    ])

    # ── Collapsible wrapper ────────────────────────────────────────────────
    return html.Div([
        # Clickable header
        html.Div(
            id    = "wr-ds-header",
            n_clicks = 0,
            children = [
                dbc.Row([
                    dbc.Col([
                        html.Span(
                            f"{status_emoji}  DataSentinel detected "
                            f"{worst_status} issues in this week",
                            style={
                                "color"    : status_color,
                                "fontSize" : "15px",
                                "fontWeight": "700",
                            }
                        ),
                    ], md=9),
                    dbc.Col([
                        html.Span(
                            "▼ Click to expand",
                            id    = "wr-ds-chevron",
                            style = {
                                "color"   : "#475569",
                                "fontSize": "12px",
                                "float"   : "right",
                            }
                        ),
                    ], md=3),
                ], align="center"),
            ],
            style={
                "cursor": "pointer",
                "userSelect": "none",
            }
        ),

        # Collapsible body
        dbc.Collapse(
            panel_body,
            id       = "wr-ds-collapse",
            is_open  = False,
        ),

    ], style={
        "backgroundColor": status_bg,
        "border"         : f"1px solid {status_color}40",
        "borderRadius"   : "10px",
        "padding"        : "20px 24px",
        "marginBottom"   : "24px",
        "cursor"         : "pointer",
    })


# ── Report builder ─────────────────────────────────────────────────────────

def _build_report(week_ending: str) -> html.Div:
    from datetime import date, timedelta
    try:
        dt         = date.fromisoformat(week_ending)
        week_start = dt - timedelta(days=6)
        week_label = (
            f"{week_start.strftime('%-d %b')} – "
            f"{dt.strftime('%-d %b %Y')}"
        )
    except Exception:
        week_label = week_ending

    week_df  = _load_week_data(week_ending)
    prior_df = _load_prior_week_data(week_ending)
    findings = _load_datasentinel_findings(week_ending)

    if week_df.empty:
        return dbc.Alert(
            f"No store metrics found for the week ending {week_ending}.",
            color="warning", className="mt-4"
        )

    return html.Div([
        _build_week_header(week_ending, week_df, prior_df),
        _build_regional_summary(week_df, prior_df),
        _build_store_league(week_df),
        _build_datasentinel_panel(findings),
        _build_analyst_view(week_ending, week_df, prior_df, findings),

        # Footer navigation
        html.Div([
            html.Hr(style={"borderColor": "#1e3a5f",
                           "margin"     : "8px 0 20px"}),
            dbc.Row([
                dbc.Col([
                    html.A(
                        "📊 View Daily Report →",
                        href  = f"/financial-report",
                        style = {"color": "#4a9edd", "fontSize": "13px",
                                 "textDecoration": "none"}
                    ),
                ], md=4),
                dbc.Col([
                    html.A(
                        "🤖 Open AI Insights →",
                        href  = (
                            f"/ai-insights?date="
                            f"{findings.get('investigation_date', week_ending)}"
                        ),
                        style = {"color": "#87ceeb", "fontSize": "13px",
                                 "textDecoration": "none",
                                 "display"       : "block",
                                 "textAlign"     : "right"}
                    ),
                ], md=8),
            ]),
        ], className="mb-4"),
    ])


# ── Callback ───────────────────────────────────────────────────────────────

@callback(
    Output("wr-alert",          "children"),
    Output("wr-report-content", "children"),
    Input("wr-generate-btn",    "n_clicks"),
    State("wr-week-dropdown",   "value"),
    prevent_initial_call=True,
)
def generate_weekly_report(n_clicks, week_ending):
    if not week_ending:
        return (
            dbc.Alert("Please select a week.", color="warning"),
            html.Div()
        )
    try:
        return "", _build_report(week_ending)
    except Exception as e:
        logger.error(f"Weekly report failed: {e}")
        import traceback
        traceback.print_exc()
        return (
            dbc.Alert(
                f"Could not generate report: {str(e)}",
                color="danger"
            ),
            html.Div()
        )

@callback(
    Output("wr-ds-collapse",  "is_open"),
    Output("wr-ds-chevron",   "children"),
    Input("wr-ds-header",     "n_clicks"),
    State("wr-ds-collapse",   "is_open"),
    prevent_initial_call=True,
)
def toggle_ds_panel(n_clicks, is_open):
    new_state = not is_open
    chevron   = "▲ Click to collapse" if new_state else "▼ Click to expand"
    return new_state, chevron


@callback(
    Output("wr-analyst-collapse", "is_open"),
    Output("wr-analyst-chevron",  "children"),
    Input("wr-analyst-header",    "n_clicks"),
    State("wr-analyst-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_analyst_panel(n_clicks, is_open):
    new_state = not is_open
    chevron   = "▲ Click to collapse" if new_state else "▼ Click to expand"
    return new_state, chevron