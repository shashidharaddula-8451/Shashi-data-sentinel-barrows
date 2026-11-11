# pages/financial_report.py

import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import pandas as pd
import math
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
import dash_ag_grid as dag
from components.alerts import ag_grid_props
from components.report_helpers import (
    format_ai_explanation,
    format_analyst_body,
    format_missed,
)

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path = "/financial-report",
    name = "Financial Report"
)

CATALOG  = TARGET_CATALOG
SCHEMA   = TARGET_SCHEMA
CURRENCY = "$"

# ── Analyst narratives — Gold data only ───────────────────────────────────
# Each narrative is written from the perspective of a finance analyst
# who only sees the Gold layer output. They have NO knowledge of:
#   - raw record counts
#   - null rates in raw tables
#   - Silver survival rates
#   - Agent check results
# They only know what appears in the Gold store metrics report.

ANALYST_NARRATIVES = {
    "2026-06-20": {
        "headline": "Revenue significantly below expectations",
        "body_sentences": [
            "Revenue and transaction count are both well below what "
            "we would expect for a Saturday.",
            "What is unusual is that all 25 stores are reporting and "
            "all regions are down by a similar margin — this does not "
            "look like underperformance at specific stores.",
            "When every region declines proportionally, in my experience "
            "that is rarely a genuine business pattern. It is more likely "
            "a platform or data issue.",
            "Basket value is actually above our normal — the transactions "
            "that did arrive were worth more than usual, which makes the "
            "low volume even more suspicious.",
            "I will not circulate this report until I have spoken to "
            "the data team.",
        ],
        "missed_bullets": [
            "The transaction pipeline delivered only 150 raw records "
            "against a baseline of 636 — a 76% volume shortfall that "
            "the Gold report cannot reveal.",
            "DataSentinel flagged VOLUME_ANOMALY CRITICAL at 6am. "
            "The pipeline completed without errors — no failed jobs, "
            "no Databricks alerts. The data simply did not arrive "
            "from the source system.",
            "The $35,131 revenue figure represents only 26% of a "
            "normal trading day. The remaining 74% of the day's "
            "transactions are missing from every downstream report.",
        ]
    },
    "2026-06-21": {
        "headline": "Revenue down 23% — quiet day or data issue?",
        "body_sentences": [
            "Revenue came in below our typical daily figure.",
            "474 transactions is light but not impossible for a quieter "
            "period. The basket value looks normal and the return rate "
            "is within range.",
            "Nothing in the Gold data obviously flags a problem — the "
            "numbers look plausible for a slow trading day.",
            "The only thing giving me pause is that it follows June 20 "
            "which was also significantly below expectations. Two "
            "consecutive low days across all regions is unusual.",
            "I will flag it in the morning standup but no urgent action "
            "based on what I can see in this report.",
        ],
        "missed_bullets": [
            "21.99% of raw net_amount values were NULL — nearly 1 in 5 "
            "transactions arrived from the source system with no "
            "financial value recorded.",
            "The Silver transformation correctly excluded those records, "
            "causing 208 of 682 raw transactions to be silently dropped "
            "before reaching Gold. The analyst sees 474 transactions — "
            "the real day had 682.",
            "DataSentinel detected NULL_SPIKE CRITICAL at 6am "
            "(threshold 5%, observed 21.99%). The analyst saw a "
            "plausible quiet day. DataSentinel saw a data quality failure.",
            "The revenue shortfall is not a business result. "
            "Every store's June 21 figure is understated.",
        ]
    },
    "2026-06-22": {
        "headline": "Strong revenue day — return rates need checking",
        "body_sentences": [
            "Revenue is tracking normally today.",
            "A few stores are showing return rates above 100% which "
            "is clearly a data anomaly — returns cannot exceed total "
            "transactions.",
            "I will raise it with the data team but the overall revenue "
            "and transaction figures look fine.",
        ],
        "missed_bullets": [
            "return_count exceeded total_transactions on 3 stores — "
            "a mathematically impossible result indicating a Gold "
            "calculation error.",
            "The return rate KPI for those stores on this date is "
            "meaningless. Any loss prevention analysis using June 22 "
            "return rates will reach incorrect conclusions.",
        ]
    },
    "2026-06-23": {
        "headline": "Revenue significantly down — investigating now",
        "body_sentences": [
            "Revenue is well below our typical daily figure and basket "
            "value is also very low.",
            "This is significant enough to flag immediately.",
            "I am reaching out to store operations to understand what "
            "happened — could be a pricing issue, a system outage, "
            "or a genuine business drop.",
            "I will not circulate today's numbers until we have an "
            "explanation.",
        ],
        "missed_bullets": [
            "The revenue drop was caused by a data injection error in "
            "the Gold pipeline that applied a 0.40 multiplier to all "
            "financial amounts.",
            "No actual business event caused this drop. The analyst "
            "spent the morning calling store managers about a problem "
            "that did not exist in the real world.",
            "DataSentinel detected the KPI anomaly at 6am. Without it, "
            "the incorrect revenue figures would have been circulated "
            "as fact.",
        ]
    },
    "2026-06-24": {
        "headline": "Store metrics normal — inventory worth checking",
        "body_sentences": [
            "Revenue and transaction metrics look normal for the "
            "store side today.",
            "Basket value and return rate are both within expected "
            "ranges.",
            "The inventory net quantity change is showing figures "
            "about five times the normal daily level — this is "
            "unusual and worth investigating.",
            "Could be a large warehouse receipt or a data error. "
            "I will ask the supply chain team if they ran a bulk "
            "movement today.",
        ],
        "missed_bullets": [
            "A formula error was introduced in the Gold inventory "
            "pipeline that added 9,999 to every net_quantity_change "
            "value. All 20 warehouse rows are wrong by exactly 9,999 units.",
            "The supply chain team would confirm no bulk movement "
            "occurred — but without DataSentinel, hours would be "
            "spent investigating a phantom event.",
            "DataSentinel detected FORMULA CRITICAL on the inventory "
            "KPI at 6am before any procurement decisions were made.",
        ]
    },
    "2026-07-19": {
        "headline": "No transaction data today — pipeline running late",
        "body_sentences": [
            "The Gold store metrics table has no records for today.",
            "This happens occasionally when the pipeline runs behind "
            "schedule — sometimes the batch just takes longer to land.",
            "Inventory numbers look completely normal: four warehouses "
            "reporting, typical movement volumes.",
            "I will check again after lunch and flag to the data team "
            "if still empty by midday.",
        ],
        "missed_bullets": [
            "The transaction pipeline produced exactly zero raw records. "
            "This was not a late pipeline — it ran and completed "
            "successfully but delivered nothing.",
            "DataSentinel flagged VOLUME_ANOMALY CRITICAL at 6am "
            "with a -100% deviation from the baseline of 636 records.",
            "The analyst planned to check again at lunch. "
            "DataSentinel escalated to the engineering team at 6am — "
            "three hours earlier.",
        ]
    },
    "2026-07-20": {
        "headline": "Revenue very low — partial recovery from yesterday",
        "body_sentences": [
            "We had no data at all yesterday so this looks like a "
            "partial recovery — some transactions are coming through "
            "but nowhere near the usual volume.",
            "Basket value is actually above normal which is interesting — "
            "the transactions that did arrive were higher value than "
            "our typical day.",
            "Return rate numbers are distorted by small sample sizes — "
            "most stores had fewer than 5 transactions so a single "
            "return skews the percentage significantly.",
            "I am treating today's numbers as unreliable and will "
            "raise it in the 9am standup.",
        ],
        "missed_bullets": [
            "The 77 Silver transactions were perfectly clean — zero "
            "null spikes, zero schema issues, 96.3% survival rate. "
            "Reconciliation Agent returned all PASS.",
            "The shortfall was entirely a volume problem — only 80 of "
            "the expected 636 transactions arrived (12% of normal). "
            "The pipeline worked correctly. The source simply did not "
            "deliver.",
            "DataSentinel knew by 6am: pipeline delivery failure, not "
            "a transformation issue. These require completely different "
            "fixes.",
            "The elevated return rates on individual stores are a "
            "statistical artifact of small sample sizes — not a "
            "genuine business signal.",
        ]
    },
}

GENERIC_NARRATIVE = {
    "headline": "Numbers look normal — no concerns today",
    "body_sentences": [
        "All metrics are within expected ranges.",
        "Revenue, basket value, transaction count, and return rate "
        "are all tracking normally against historical patterns.",
        "No action required.",
    ],
    "missed_bullets": [
        "DataSentinel found no significant issues on this date. "
        "All checks passed within configured thresholds.",
    ]
}


# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    html.Div([
        html.H2(
            "📊 Daily Financial Report",
            className = "mt-4 mb-1",
            style     = {"color": "#ffffff"}
        ),
        html.P(
            "Simulating the morning report your finance team reviews "
            "every day — and what they would miss without DataSentinel.",
            className = "text-muted mb-4",
            style     = {"fontSize": "15px"}
        ),
    ]),

    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label(
                        "Select Business Date",
                        className="text-white fw-bold"
                    ),
                    dcc.Dropdown(
                        id          = "fr-date-dropdown",
                        options     = [],
                        value       = None,
                        clearable   = False,
                        placeholder = "Select a date...",
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
                        id        = "fr-generate-btn",
                        color     = "primary",
                        size      = "lg",
                        className = "d-block w-100",
                        n_clicks  = 0
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("\u00a0", className="text-white"),
                    dbc.Alert(
                        "This report shows Gold layer data exactly as "
                        "a finance analyst would see it — no data "
                        "quality context included.",
                        color     = "info",
                        className = "mb-0 small"
                    )
                ], md=4),
            ])
        ])
    ], className="mb-4",
    style={"backgroundColor": "#2b2b2b", "border": "1px solid #444"}),

    html.Div(id="fr-alert"),

    dbc.Spinner(
        html.Div(id="fr-report-content"),
        color         = "primary",
        type          = "border",
        spinner_style = {"width": "3rem", "height": "3rem"}
    ),

], fluid=True)


# ── Date dropdown ──────────────────────────────────────────────────────────

@callback(
    Output("fr-date-dropdown", "options"),
    Output("fr-date-dropdown", "value"),
    Input("fr-date-dropdown",  "id"),
)
def load_date_options(_):
    try:
        df = execute_query(f"""
            SELECT
                all_dates.business_date,
                CASE
                    WHEN gold.has_gold = 1
                    THEN CAST(all_dates.business_date AS STRING)
                    ELSE CONCAT(
                        CAST(all_dates.business_date AS STRING),
                        ' — no store data'
                    )
                END AS label
            FROM (
                SELECT DISTINCT business_date
                FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics

                UNION

                SELECT DISTINCT business_date
                FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
                WHERE fully_qualified_name =
                    '{CATALOG}.{SCHEMA}.uc1_raw_store_transactions'
            ) all_dates
            LEFT JOIN (
                SELECT DISTINCT business_date, 1 AS has_gold
                FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
            ) gold
              ON all_dates.business_date = gold.business_date
            ORDER BY all_dates.business_date DESC
            LIMIT 60
        """)
        if df.empty:
            return [], None

        options = [
            {
                "label": str(row["label"]),
                "value": str(row["business_date"])[:10]
            }
            for _, row in df.iterrows()
        ]

        available = [o["value"] for o in options]
        default = (
            "2026-07-20" if "2026-07-20" in available
            else "2026-07-19" if "2026-07-19" in available
            else options[0]["value"] if options else None
        )

        return options, default

    except Exception as e:
        logger.error(f"Failed to load date options: {e}")
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


def _trend_indicator(observed, baseline) -> html.Span:
    if observed is None or baseline is None or baseline == 0:
        return html.Span()
    pct = (observed - baseline) / abs(baseline) * 100
    if abs(pct) < 2:
        return html.Span(
            "  → vs baseline",
            style={"color": "#aaaaaa", "fontSize": "13px"}
        )
    elif pct > 0:
        return html.Span(
            f"  ↑ {pct:+.1f}% vs baseline",
            style={"color": "#00c851", "fontSize": "13px"}
        )
    else:
        return html.Span(
            f"  ↓ {pct:+.1f}% vs baseline",
            style={"color": "#ff6b6b", "fontSize": "13px"}
        )


def _kpi_card(
    label    : str,
    value    : str,
    trend,
    icon     : str  = "📊",
    highlight: bool = False,
) -> dbc.Col:
    border = "#ffa500" if highlight else "#1e3a5f"
    bg     = "#2a1a00" if highlight else "#0f2035"
    return dbc.Col(
        html.Div([
            html.Div(
                f"{icon}  {label}",
                style={
                    "color"        : "#64748b",
                    "fontSize"     : "12px",
                    "fontWeight"   : "600",
                    "textTransform": "uppercase",
                    "letterSpacing": "1px",
                    "marginBottom" : "8px",
                }
            ),
            html.Div(
                value,
                style={
                    "color"     : "#ffffff",
                    "fontSize"  : "28px",
                    "fontWeight": "800",
                    "lineHeight": "1",
                    "fontFamily": "monospace",
                }
            ),
            html.Div(trend, style={"marginTop": "6px"}),
        ], style={
            "backgroundColor": bg,
            "border"         : f"1px solid {border}",
            "borderRadius"   : "8px",
            "padding"        : "20px",
            "height"         : "100%",
        }),
        md=3, className="mb-3"
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


def _store_table(
    df   : pd.DataFrame,
    title: str,
    top  : bool = True,
) -> html.Div:
    if df.empty:
        return html.Div()

    subset = df.head(5) if top else df.tail(5)
    grid_rows = []

    for _, row in subset.iterrows():
        net       = _safe_float(row.get("total_net_amount"))
        txns      = _safe_float(row.get("total_transactions"))
        bskt      = _safe_float(row.get("avg_basket_value"))
        ret_raw   = _safe_float(row.get("return_rate"))

        ret_display = (
            _fmt_pct(ret_raw * 100)
            if ret_raw is not None and ret_raw > 0
            else "0.0%"
        )

        grid_rows.append({
            "store_id"    : str(row.get("store_id", "")),
            "store_region": str(row.get("store_region", "")),
            "net_revenue" : _fmt_currency(net),
            "transactions": _fmt_number(txns),
            "avg_basket"  : _fmt_currency(bskt),
            "return_rate" : ret_display,
        })

    color = "#00c851" if top else "#ffa500"
    icon  = "🏆" if top else "⚠️"
    grid_id_suffix = "top" if top else "bottom"

    return html.Div([
        html.H6(
            f"{icon} {title}",
            style={"color": color, "fontSize": "13px",
                   "fontWeight": "700", "marginBottom": "8px"}
        ),
        dag.AgGrid(
            **ag_grid_props(
                grid_id=f"fr-store-{grid_id_suffix}",
                row_data=grid_rows,
                col_defs=[
                    {"field": "store_id",     "headerName": "Store",        "width": 90},
                    {"field": "store_region", "headerName": "Region",       "width": 100},
                    {"field": "net_revenue",  "headerName": "Net Revenue",  "flex": 1},
                    {"field": "transactions", "headerName": "Transactions", "width": 110},
                    {"field": "avg_basket",   "headerName": "Avg Basket",   "width": 110},
                    {"field": "return_rate",  "headerName": "Return Rate",  "width": 110},
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
        "marginBottom"   : "16px",
        "overflowX"      : "auto",
    })


# ── Data loading ───────────────────────────────────────────────────────────

def _load_store_metrics(business_date: str) -> pd.DataFrame:
    try:
        df = execute_query(f"""
            SELECT
                store_id, store_region, business_date,
                total_transactions, total_gross_amount,
                total_discount_amount, total_net_amount,
                avg_basket_value, total_items_sold,
                unique_customers, return_count, return_rate
            FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
            WHERE business_date = :business_date
            ORDER BY total_net_amount DESC
        """, {"business_date": business_date})
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Failed to load store metrics: {e}")
        return pd.DataFrame()


def _load_inventory_metrics(business_date: str) -> pd.DataFrame:
    try:
        df = execute_query(f"""
            SELECT
                warehouse_id, event_type, event_count,
                total_quantity_in, total_quantity_out,
                net_quantity_change, total_cost_impact,
                unique_skus, unique_stores
            FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_inventory_summary
            WHERE business_date = :business_date
            ORDER BY warehouse_id, event_type
        """, {"business_date": business_date})
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Failed to load inventory metrics: {e}")
        return pd.DataFrame()


def _load_baselines() -> dict:
    try:
        df = execute_query(f"""
            SELECT kpi_name, mean_value
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_baseline_metrics_b
            ORDER BY baseline_date DESC
        """)
        if df.empty:
            return {}
        baselines = {}
        for _, row in df.iterrows():
            key = str(row["kpi_name"])
            if key not in baselines:
                baselines[key] = _safe_float(row["mean_value"])
        return baselines
    except Exception as e:
        logger.error(f"Failed to load baselines: {e}")
        return {}


def _load_historical_averages() -> dict:
    try:
        df = execute_query(f"""
            SELECT
                AVG(daily_net)    AS avg_daily_net,
                AVG(daily_txns)   AS avg_daily_txns
            FROM (
                SELECT
                    business_date,
                    SUM(total_net_amount)   AS daily_net,
                    SUM(total_transactions) AS daily_txns
                FROM {CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics
                WHERE business_date BETWEEN '2026-05-19' AND '2026-06-17'
                GROUP BY business_date
            )
        """)
        if df.empty:
            return {}
        return {
            "avg_daily_net" : _safe_float(df.iloc[0]["avg_daily_net"]),
            "avg_daily_txns": _safe_float(df.iloc[0]["avg_daily_txns"]),
        }
    except Exception as e:
        logger.error(f"Failed to load historical averages: {e}")
        return {}


def _load_datasentinel_findings(business_date: str) -> dict:
    """
    Loads DataSentinel headline findings for a specific business date.
    Prioritises transaction pipeline findings for financial context.
    Returns a summary dict for the DataSentinel panel.
    """
    try:
        # A1 runs for this date
        a1_df = execute_query(f"""
            SELECT
                SUBSTRING_INDEX(fully_qualified_name, '.', -1) AS table_name,
                fully_qualified_name,
                overall_status,
                total_checks_critical,
                total_checks_warned
            FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            WHERE business_date = :business_date
            ORDER BY
                CASE overall_status
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'WARNING'  THEN 2
                    ELSE 3
                END
        """, {"business_date": business_date})

        if a1_df.empty:
            return {"has_issues": False}

        overall_status = "PASS"
        for _, r in a1_df.iterrows():
            s = str(r.get("overall_status", "PASS"))
            if s == "CRITICAL":
                overall_status = "CRITICAL"
                break
            elif s == "WARNING" and overall_status != "CRITICAL":
                overall_status = "WARNING"

        if overall_status == "PASS":
            return {"has_issues": False}

        # Load failed checks for transaction table only
        failed_df = execute_query(f"""
            SELECT
                r.check_type,
                r.column_name,
                r.check_status,
                ROUND(r.observed_value, 4)   AS observed_value,
                ROUND(r.baseline_value, 4)   AS baseline_value,
                ROUND(
                    CASE
                        WHEN r.check_type IN (
                            'FORMULA','CROSS_KPI',
                            'CATEGORICAL_DOMAIN',
                            'SCHEMA_CONFORMANCE',
                            'MALFORMED_RECORDS',
                            'NUMERIC_RANGE',
                            'CROSS_COLUMN_CONSISTENCY'
                        )
                        THEN ABS(r.deviation_percentage)
                        WHEN r.baseline_value IS NOT NULL
                         AND r.baseline_value != 0
                         AND r.observed_value < r.baseline_value
                        THEN -ABS(r.deviation_percentage)
                        ELSE r.deviation_percentage
                    END, 1
                )                            AS deviation_pct,
                r.ai_summary
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
              ON r.validation_run_id = run.validation_run_id
            WHERE run.business_date = :business_date
              AND run.fully_qualified_name LIKE '%store_transactions'
              AND r.check_status IN ('CRITICAL', 'WARNING')
            ORDER BY
                CASE r.check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                ABS(r.deviation_percentage) DESC
        """, {"business_date": business_date})

        # A2 findings
        a2_df = execute_query(f"""
            SELECT overall_status, total_checks_critical
            FROM {CATALOG}.{SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date = :business_date
              AND source_fully_qualified_name LIKE '%store_transactions'
            LIMIT 1
        """, {"business_date": business_date})

        # A4 findings
        a4_df = execute_query(f"""
            SELECT overall_status, total_kpis_critical
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date = :business_date
              AND gold_fully_qualified_name LIKE '%store_metrics'
            LIMIT 1
        """, {"business_date": business_date})

        # AI summary — prioritise A1 store transactions
        ai_text = None

        # Priority 1: A1 AI summary
        if not failed_df.empty:
            a1_ai = failed_df[
                failed_df["ai_summary"].notna() &
                (failed_df["ai_summary"] != "")
            ]
            if not a1_ai.empty:
                ai_text = str(a1_ai.iloc[0]["ai_summary"])

        # Priority 2: construct from VOLUME_ANOMALY check
        if not ai_text and not failed_df.empty:
            vol = failed_df[
                failed_df["check_type"] == "VOLUME_ANOMALY"
            ]
            null = failed_df[
                failed_df["check_type"] == "NULL_SPIKE"
            ]
            parts = []
            if not vol.empty:
                obs  = _safe_float(vol.iloc[0]["observed_value"])
                base = _safe_float(vol.iloc[0]["baseline_value"])
                dev  = _safe_float(vol.iloc[0]["deviation_pct"])
                obs_str  = f"{int(obs):,}" if obs  is not None else "—"
                base_str = f"{int(base):,}" if base is not None else "—"
                dev_str  = f"{abs(dev):.0f}" if dev is not None else "—"
                parts.append(
                    f"On {business_date}, the transaction pipeline "
                    f"delivered {obs_str} records against a baseline "
                    f"of {base_str} — a {dev_str}% shortfall. "
                    f"The pipeline completed without errors — "
                    f"the records simply did not arrive from the "
                    f"source system."
                )
            if not null.empty:
                obs = _safe_float(null.iloc[0]["observed_value"])
                obs_str = f"{obs:.2f}%" if obs is not None else "—"
                parts.append(
                    f"On {business_date}, {obs_str} of net_amount "
                    f"values were NULL — nearly 1 in 5 transactions "
                    f"arrived with no financial value. The Silver "
                    f"transformation correctly excluded these records, "
                    f"silently dropping them before Gold."
                )
            if parts:
                parts.append(
                    "These are the root causes of today's revenue "
                    "understatement — the Gold figures reflect only "
                    "what was captured, not the full trading activity."
                )
                ai_text = " ".join(parts)

        # Priority 3: A4 AI summary
        if not ai_text:
            a4_ai = execute_query(f"""
                SELECT ai_summary
                FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b
                WHERE business_date = :business_date
                  AND ai_summary IS NOT NULL
                  AND ai_summary != ''
                ORDER BY
                    CASE check_status WHEN 'CRITICAL' THEN 1 ELSE 2 END
                LIMIT 1
            """, {"business_date": business_date})
            if not a4_ai.empty:
                ai_text = str(a4_ai.iloc[0]["ai_summary"])

        if not ai_text:
            ai_text = (
                f"DataSentinel detected issues on {business_date}. "
                f"Open the full investigation for detailed findings."
            )

        return {
            "has_issues"    : True,
            "overall_status": overall_status,
            "business_date" : business_date,
            "failed_checks" : failed_df,
            "a2_status"     : str(
                a2_df.iloc[0]["overall_status"]
            ) if not a2_df.empty else None,
            "a4_status"     : str(
                a4_df.iloc[0]["overall_status"]
            ) if not a4_df.empty else None,
            "ai_summary"    : ai_text,
        }

    except Exception as e:
        logger.error(f"Failed to load DataSentinel findings: {e}")
        return {"has_issues": False}


# ── DataSentinel panel ─────────────────────────────────────────────────────

def _build_datasentinel_panel(
    findings      : dict,
    business_date : str,
) -> html.Div:
    """
    DataSentinel findings panel — collapsed by default.
    Shows headline findings for the selected date.
    Links to the full investigation page.
    """
    if not findings.get("has_issues"):
        return html.Div([
            html.Div([
                html.Span("✅  ", style={"fontSize": "18px"}),
                html.Span(
                    "DataSentinel: No issues detected for this date",
                    style={"color": "#00c851", "fontSize": "14px",
                           "fontWeight": "700"}
                ),
                html.P(
                    "All validation checks passed. "
                    "This report's data is trustworthy.",
                    style={"color": "#64748b", "fontSize": "13px",
                           "marginTop": "6px", "marginBottom": "0"}
                ),
            ], style={
                "backgroundColor": "#002800",
                "border"         : "1px solid #00c851",
                "borderRadius"   : "10px",
                "padding"        : "16px 20px",
                "marginBottom"   : "24px",
            })
        ])

    overall_status = findings.get("overall_status", "CRITICAL")
    failed         = findings.get("failed_checks", pd.DataFrame())
    a2_status      = findings.get("a2_status")
    a4_status      = findings.get("a4_status")
    ai_text        = findings.get("ai_summary", "")

    status_color = "#ff6b6b" if overall_status == "CRITICAL" else "#ffa500"
    status_bg    = "#3d0000" if overall_status == "CRITICAL" else "#3d2000"
    status_emoji = "🔴" if overall_status == "CRITICAL" else "🟡"

    # ── Agent status pills ─────────────────────────────────────────────────
    def _agent_pill(label, status):
        if status is None:
            return html.Span()
        clr = (
            "#ff6b6b" if status == "CRITICAL"
            else "#ffa500" if status == "WARNING"
            else "#00c851"
        )
        bg = (
            "#3d0000" if status == "CRITICAL"
            else "#3d2000" if status == "WARNING"
            else "#002800"
        )
        emj = (
            "🔴" if status == "CRITICAL"
            else "🟡" if status == "WARNING"
            else "🟢"
        )
        return html.Span(
            f"{emj} {label}: {status}",
            style={
                "backgroundColor": bg,
                "color"          : clr,
                "fontSize"       : "12px",
                "fontWeight"     : "600",
                "padding"        : "3px 10px",
                "borderRadius"   : "4px",
                "marginRight"    : "8px",
                "border"         : f"1px solid {clr}40",
            }
        )

    # ── Failed checks rows ─────────────────────────────────────────────────
    check_rows = []
    if not failed.empty:
        for _, chk in failed.iterrows():
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
                        style={"color": clr, "fontSize": "12px",
                               "fontWeight": "700", "fontFamily": "monospace",
                               "marginRight": "10px"}
                    ),
                    html.Span(
                        f"on {col}",
                        style={"color": "#64748b", "fontSize": "12px",
                               "marginRight": "10px"}
                    ),
                    html.Span(
                        f"observed {obs_str}",
                        style={"color": clr, "fontSize": "12px",
                               "fontFamily": "monospace",
                               "marginRight": "10px"}
                    ),
                    html.Span(
                        f"deviation: {dev:+.1f}%"
                        if dev is not None else "",
                        style={"color": clr, "fontSize": "12px",
                               "fontFamily": "monospace"}
                    ),
                ], style={"marginBottom": "5px"})
            )

    # ── Panel body ─────────────────────────────────────────────────────────
    panel_body = html.Div([
        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        # Agent status summary
        html.Div([
            html.Span(
                "Agent status:  ",
                style={"color": "#64748b", "fontSize": "12px",
                       "marginRight": "8px"}
            ),
            _agent_pill("Validation Agent", overall_status),
            _agent_pill("Reconciliation Agent", a2_status),
            _agent_pill("KPI Assurance Agent", a4_status),
        ], style={"marginBottom": "14px"}),

        # Failed checks
        html.Div([
            html.Span(
                "What was detected:",
                style={"color": "#64748b", "fontSize": "12px",
                       "fontWeight": "600", "display": "block",
                       "marginBottom": "8px"}
            ),
            *check_rows,
        ], style={"marginBottom": "14px"}) if check_rows else html.Div(),

        # AI explanation
        html.Div([
            html.Span(
                "🤖 AI Explanation:",
                style={"color": "#4a9edd", "fontSize": "12px",
                       "fontWeight": "700", "display": "block",
                       "marginBottom": "8px", "marginTop": "12px"}
            ),
            format_ai_explanation(ai_text),
        ], style={
            "backgroundColor": "#070d14",
            "borderLeft"     : "3px solid #1e3a5f",
            "padding"        : "12px 16px",
            "marginTop"      : "4px",
        }) if ai_text else html.Div(),

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        # Investigation link
        html.A(
            dbc.Button(
                f"🔍 View Full Investigation for {business_date} →",
                color     = "danger"
                if overall_status == "CRITICAL" else "warning",
                outline   = True,
                size      = "sm",
            ),
            href = f"/sentinel-investigation?date={business_date}",
        ),
    ])

    # ── Collapsible wrapper ────────────────────────────────────────────────
    return html.Div([
        html.Div(
            id       = "fr-ds-header",
            n_clicks = 0,
            children = [
                dbc.Row([
                    dbc.Col([
                        html.Span(
                            f"{status_emoji}  DataSentinel detected "
                            f"{overall_status} for {business_date}",
                            style={"color": status_color, "fontSize": "15px",
                                   "fontWeight": "700"}
                        ),
                    ], md=9),
                    dbc.Col([
                        html.Span(
                            "▼ Click to expand",
                            id    = "fr-ds-chevron",
                            style = {"color": "#475569", "fontSize": "12px",
                                     "float": "right"}
                        ),
                    ], md=3),
                ], align="center"),
            ],
            style={"cursor": "pointer", "userSelect": "none"}
        ),
        dbc.Collapse(
            panel_body,
            id      = "fr-ds-collapse",
            is_open = False,
        ),
    ], style={
        "backgroundColor": status_bg,
        "border"         : f"1px solid {status_color}40",
        "borderRadius"   : "10px",
        "padding"        : "20px 24px",
        "marginBottom"   : "24px",
        "cursor"         : "pointer",
    })


# ── Analyst panel ──────────────────────────────────────────────────────────

def _build_analyst_panel(
    business_date : str,
    total_net     : float,
    total_txns    : float,
    avg_basket    : float,
    avg_daily_net : float,
    avg_daily_txns: float,
) -> html.Div:
    """
    Finance analyst conclusion — collapsed by default.
    Based ONLY on Gold data — no DataSentinel knowledge.
    """
    narrative = ANALYST_NARRATIVES.get(
        business_date, GENERIC_NARRATIVE
    )

    # Dynamically build headline for unknown dates
    if business_date not in ANALYST_NARRATIVES:
        if total_net and avg_daily_net and avg_daily_net > 0:
            pct = (total_net - avg_daily_net) / avg_daily_net * 100
            if pct < -15:
                headline = (
                    f"Revenue down {abs(pct):.0f}% — investigating"
                )
            elif pct < -5:
                headline = "Revenue slightly below expectations"
            elif pct > 10:
                headline = "Strong revenue day"
            else:
                headline = "Numbers look normal — no concerns today"
        else:
            headline = narrative["headline"]
    else:
        headline = narrative["headline"]

    # Panel body
    panel_body = html.Div([
        html.Hr(style={"borderColor": "#1e3a5f", "margin": "14px 0"}),

        html.H6(
            f"\"{headline}\"",
            style={"color": "#ffa500", "fontSize": "14px",
                   "fontStyle": "italic", "fontWeight": "600",
                   "marginBottom": "12px"}
        ),

        format_analyst_body(narrative.get("body_sentences", [])),

        html.Hr(style={"borderColor": "#1e3a5f", "margin": "16px 0"}),

        html.Span(
            "⚠️ What they missed: ",
            style={"color": "#ff6b6b", "fontWeight": "700",
                   "fontSize": "13px", "display": "block",
                   "marginBottom": "8px"}
        ),
        format_missed(narrative.get("missed_bullets", [])),
    ])

    # Collapsible wrapper
    return html.Div([
        html.Div(
            id       = "fr-analyst-header",
            n_clicks = 0,
            children = [
                dbc.Row([
                    dbc.Col([
                        html.Span(
                            "💭  What a finance analyst would conclude",
                            style={"color": "#ffffff", "fontSize": "15px",
                                   "fontWeight": "700"}
                        ),
                    ], md=9),
                    dbc.Col([
                        html.Span(
                            "▼ Click to expand",
                            id    = "fr-analyst-chevron",
                            style = {"color": "#475569", "fontSize": "12px",
                                     "float": "right"}
                        ),
                    ], md=3),
                ], align="center"),
            ],
            style={"cursor": "pointer", "userSelect": "none"}
        ),
        dbc.Collapse(
            panel_body,
            id      = "fr-analyst-collapse",
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


# ── Report builder ─────────────────────────────────────────────────────────

def _build_report(business_date: str) -> html.Div:

    store_df  = _load_store_metrics(business_date)
    inv_df    = _load_inventory_metrics(business_date)
    baselines = _load_baselines()
    hist_avgs = _load_historical_averages()
    findings  = _load_datasentinel_findings(business_date)

    # ── Aggregates ─────────────────────────────────────────────────────────
    if not store_df.empty:
        total_net   = _safe_float(store_df["total_net_amount"].sum())
        total_txns  = _safe_float(store_df["total_transactions"].sum())
        avg_basket  = _safe_float(store_df["avg_basket_value"].mean())
        store_count = len(store_df)

        avg_txns_per_store = (
            total_txns / store_count
            if total_txns and store_count > 0 else 0
        )

        if avg_txns_per_store >= 5:
            total_ret = _safe_float(store_df["return_count"].sum())
            ret_rate  = (
                total_ret / total_txns
                if total_ret and total_txns else None
            )
        else:
            ret_rate = None
    else:
        total_net   = None
        total_txns  = None
        avg_basket  = None
        ret_rate    = None
        store_count = 0

    if not inv_df.empty:
        net_qty     = _safe_float(inv_df["net_quantity_change"].sum())
        cost_impact = _safe_float(inv_df["total_cost_impact"].sum())
        total_events= _safe_float(inv_df["event_count"].sum())
    else:
        net_qty      = None
        cost_impact  = None
        total_events = None

    avg_daily_net   = hist_avgs.get("avg_daily_net")
    avg_daily_txns  = hist_avgs.get("avg_daily_txns")
    baseline_basket = baselines.get("avg_basket_value")
    baseline_ret    = baselines.get("return_rate")

    # ── Return rate card values ────────────────────────────────────────────
    if ret_rate is not None:
        ret_display   = _fmt_pct(ret_rate * 100)
        ret_trend     = _trend_indicator(ret_rate, baseline_ret)
        ret_highlight = ret_rate > 0.20
    else:
        ret_display   = "N/A"
        ret_trend     = html.Span(
            "  low transaction volume — rate not reliable",
            style={"color": "#555555", "fontSize": "12px",
                   "fontStyle": "italic"}
        )
        ret_highlight = False

    # ── Date label ─────────────────────────────────────────────────────────
    from datetime import datetime
    try:
        dt  = datetime.strptime(business_date, "%Y-%m-%d")
        day = dt.strftime("%A, %-d %B %Y")
    except Exception:
        day = business_date

    elements = []

    # ── Report header ──────────────────────────────────────────────────────
    elements.append(
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4(
                        "Good morning",
                        style={"color": "#ffffff", "fontWeight": "800",
                               "marginBottom": "4px", "fontSize": "22px"}
                    ),
                    html.P(
                        f"Here is your data summary for {day}",
                        style={"color": "#64748b", "fontSize": "14px",
                               "marginBottom": "0"}
                    ),
                ], md=8),
                dbc.Col([
                    html.Div(
                        f"📅 {business_date}",
                        style={"color": "#4a9edd", "fontSize": "13px",
                               "fontFamily": "monospace",
                               "textAlign": "right", "paddingTop": "8px"}
                    ),
                    html.Div(
                        f"{store_count} stores reporting"
                        if store_count > 0 else "No store data",
                        style={"color": "#475569", "fontSize": "12px",
                               "textAlign": "right"}
                    ),
                ], md=4),
            ]),
        ], style={
            "backgroundColor": "#070d14",
            "border"         : "1px solid #1e3a5f",
            "borderRadius"   : "10px",
            "padding"        : "24px 28px",
            "marginBottom"   : "24px",
        })
    )

    # ── Revenue summary ────────────────────────────────────────────────────
    if store_df.empty:
        elements.append(
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("⚠️", style={"fontSize": "28px",
                                               "marginRight": "16px"}),
                        html.Div([
                            html.H5(
                                "No store data available for this date",
                                style={"color": "#ff6b6b", "fontWeight": "700",
                                       "marginBottom": "6px"}
                            ),
                            html.P(
                                f"The Gold store metrics table has no "
                                f"records for {business_date}. The "
                                f"transaction pipeline may have failed "
                                f"to produce output.",
                                style={"color": "#cbd5e1", "fontSize": "14px",
                                       "marginBottom": "12px"}
                            ),
                            html.P(
                                "💭 \"The report hasn't loaded yet. "
                                "I'll check again after lunch.\"",
                                style={"color": "#ffa500", "fontSize": "14px",
                                       "fontStyle": "italic"}
                            ),
                        ])
                    ], style={"display": "flex", "alignItems": "flex-start"}),
                ], style={
                    "backgroundColor": "#1a0000",
                    "border"         : "1px solid #ff6b6b40",
                    "borderRadius"   : "10px",
                    "padding"        : "24px",
                    "marginBottom"   : "24px",
                })
            ])
        )
    else:
        elements.append(
            html.Div([
                _section_header(
                    "Revenue Summary",
                    "Aggregated across all reporting stores"
                ),
                dbc.Row([
                    _kpi_card(
                        "Total Net Revenue",
                        _fmt_currency(total_net),
                        _trend_indicator(total_net, avg_daily_net),
                        icon      = "💵",
                        highlight = (
                            total_net is not None and
                            avg_daily_net is not None and
                            total_net < avg_daily_net * 0.80
                        )
                    ),
                    _kpi_card(
                        "Total Transactions",
                        _fmt_number(total_txns),
                        _trend_indicator(total_txns, avg_daily_txns),
                        icon      = "🧾",
                        highlight = (
                            total_txns is not None and
                            avg_daily_txns is not None and
                            total_txns < avg_daily_txns * 0.50
                        )
                    ),
                    _kpi_card(
                        "Avg Basket Value",
                        _fmt_currency(avg_basket),
                        _trend_indicator(avg_basket, baseline_basket),
                        icon = "🛒",
                    ),
                    _kpi_card(
                        "Return Rate",
                        ret_display,
                        ret_trend,
                        icon      = "↩️",
                        highlight = ret_highlight,
                    ),
                ]),
            ], className="mb-4")
        )

        # Store performance
        elements.append(
            html.Div([
                _section_header(
                    "Store Performance",
                    "Ranked by net revenue for this date"
                ),
                dbc.Row([
                    dbc.Col([
                        _store_table(store_df, "Top 5 Stores", top=True)
                    ], md=6),
                    dbc.Col([
                        _store_table(store_df, "Bottom 5 Stores", top=False)
                    ], md=6),
                ]),
            ], className="mb-4")
        )

    # ── Inventory ──────────────────────────────────────────────────────────
    elements.append(
        html.Div([
            _section_header(
                "Inventory Movement",
                "Aggregated across all warehouses and event types"
            ),
            dbc.Row([
                _kpi_card(
                    "Net Quantity Change",
                    _fmt_number(net_qty),
                    html.Span(
                        "  total units moved today",
                        style={"color": "#aaaaaa", "fontSize": "13px"}
                    ),
                    icon = "📦",
                ),
                _kpi_card(
                    "Total Cost Impact",
                    _fmt_currency(cost_impact),
                    html.Span(),
                    icon = "💰",
                ),
                _kpi_card(
                    "Total Events",
                    _fmt_number(total_events),
                    html.Span(),
                    icon = "📋",
                ),
                dbc.Col(md=3),
            ]),
        ], className="mb-4")
    )

    # ── DataSentinel panel (collapsed, above analyst) ──────────────────────
    elements.append(
        _build_datasentinel_panel(findings, business_date)
    )

    # ── Analyst panel (collapsed) ──────────────────────────────────────────
    elements.append(
        _build_analyst_panel(
            business_date  = business_date,
            total_net      = total_net,
            total_txns     = total_txns,
            avg_basket     = avg_basket,
            avg_daily_net  = avg_daily_net,
            avg_daily_txns = avg_daily_txns,
        )
    )

    return html.Div(elements)


# ── Collapse callbacks ─────────────────────────────────────────────────────

@callback(
    Output("fr-ds-collapse", "is_open"),
    Output("fr-ds-chevron",  "children"),
    Input("fr-ds-header",    "n_clicks"),
    State("fr-ds-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_fr_ds(n_clicks, is_open):
    new_state = not is_open
    return new_state, "▲ Click to collapse" if new_state else "▼ Click to expand"


@callback(
    Output("fr-analyst-collapse", "is_open"),
    Output("fr-analyst-chevron",  "children"),
    Input("fr-analyst-header",    "n_clicks"),
    State("fr-analyst-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_fr_analyst(n_clicks, is_open):
    new_state = not is_open
    return new_state, "▲ Click to collapse" if new_state else "▼ Click to expand"


# ── Main callback ──────────────────────────────────────────────────────────

@callback(
    Output("fr-alert",          "children"),
    Output("fr-report-content", "children"),
    Input("fr-generate-btn",    "n_clicks"),
    State("fr-date-dropdown",   "value"),
    prevent_initial_call=True,
)
def generate_report(n_clicks, business_date):
    if not business_date:
        return (
            dbc.Alert("Please select a business date.", color="warning"),
            html.Div()
        )
    try:
        return "", _build_report(business_date)
    except Exception as e:
        logger.error(f"Financial report failed: {e}")
        import traceback
        traceback.print_exc()
        return (
            dbc.Alert(
                f"Could not generate report: {str(e)}",
                color="danger"
            ),
            html.Div()
        )