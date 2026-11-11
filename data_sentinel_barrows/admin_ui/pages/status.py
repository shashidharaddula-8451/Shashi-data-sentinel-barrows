# pages/status.py

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
from datetime import datetime, date
import logging
from db.connection import execute_query
from config.settings import TARGET_CATALOG, TARGET_SCHEMA

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/status",
    name="Platform Status"
)

# ── Constants ──────────────────────────────────────────────────────────────

CATALOG = TARGET_CATALOG
SCHEMA  = TARGET_SCHEMA

# ── Layout ─────────────────────────────────────────────────────────────────

layout = dbc.Container([

    dcc.Interval(
        id          = "status-refresh-interval",
        interval    = 60 * 1000,
        n_intervals = 0,
        disabled    = True
    ),

    dcc.Store(id="status-refresh-paused", data=True),

    dbc.Row([
        dbc.Col([
            html.Div(
                id    = "status-refresh-indicator",
                style = {"color": "#64748b", "fontSize": "12px",
                        "marginBottom": "8px"}
            )
        ], md=8),
        dbc.Col([
            dbc.Button(
                "⏸ Pause Auto-Refresh",
                id       = "status-refresh-toggle",
                color    = "secondary",
                outline  = True,
                size     = "sm",
                n_clicks = 0,
                style    = {"fontSize": "12px"}
            )
        ], md=4, className="d-flex justify-content-end mb-2"),
    ]),

    dcc.Loading(
        id    = "status-loading",
        type  = "circle",
        color = "#00c851",
        children = html.Div(id="status-page-content")
    )

], fluid=True, style={"maxWidth": "800px", "margin": "0 auto", "padding": "40px 20px"})


# ── Data loading ───────────────────────────────────────────────────────────

def _load_latest_agent1_status() -> dict:
    """
    Returns the latest A1 validation run status per source table,
    for the most recent business date that has any run.
    """
    try:
        df = execute_query(f"""
            SELECT
                fully_qualified_name,
                overall_status,
                total_checks_critical,
                total_checks_warned,
                created_timestamp,
                business_date
            FROM (
                SELECT
                    fully_qualified_name,
                    overall_status,
                    total_checks_critical,
                    total_checks_warned,
                    created_timestamp,
                    business_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY fully_qualified_name
                        ORDER BY business_date DESC, created_timestamp DESC
                    ) AS rn
                FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
            )
            WHERE rn = 1
        """)
        if df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            fqn = str(row["fully_qualified_name"])
            result[fqn] = {
                "status"           : str(row["overall_status"]),
                "critical"         : int(row["total_checks_critical"] or 0),
                "warned"           : int(row["total_checks_warned"] or 0),
                "created_timestamp": row["created_timestamp"],
                "business_date"    : row["business_date"],
            }
        return result
    except Exception as e:
        logger.error(f"Failed to load A1 status: {e}")
        return {}


def _load_latest_agent4_status() -> dict:
    """
    Returns the latest A4 KPI validation run status per gold table,
    for the most recent business date that has any run.
    """
    try:
        df = execute_query(f"""
            SELECT
                gold_fully_qualified_name,
                overall_status,
                total_kpis_critical,
                total_kpis_warned,
                created_timestamp,
                business_date
            FROM (
                SELECT
                    gold_fully_qualified_name,
                    overall_status,
                    total_kpis_critical,
                    total_kpis_warned,
                    created_timestamp,
                    business_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY gold_fully_qualified_name
                        ORDER BY business_date DESC, created_timestamp DESC
                    ) AS rn
                FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            )
            WHERE rn = 1
        """)
        if df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            fqn = str(row["gold_fully_qualified_name"])
            result[fqn] = {
                "status"           : str(row["overall_status"]),
                "critical"         : int(row["total_kpis_critical"] or 0),
                "warned"           : int(row["total_kpis_warned"] or 0),
                "created_timestamp": row["created_timestamp"],
                "business_date"    : row["business_date"],
            }
        return result
    except Exception as e:
        logger.error(f"Failed to load A4 status: {e}")
        return {}


def _load_ai_context() -> dict:
    """
    Loads the most recent AI summary for any CRITICAL or WARNING check
    across A1 and A4, to populate the "What this means" section.

    Returns dict with keys: summary, action, alert_timestamp, table_name
    """
    try:
        # A1 — check for most recent AI-enriched failure
        df_a1 = execute_query(f"""
            SELECT
                r.ai_summary,
                r.ai_recommended_action,
                r.ai_failure_category,
                run.created_timestamp   AS alert_timestamp,
                run.fully_qualified_name,
                run.business_date
            FROM {CATALOG}.{SCHEMA}.uc1_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc1_validation_run_b run
              ON r.validation_run_id = run.validation_run_id
            WHERE r.check_status IN ('CRITICAL', 'WARNING')
              AND r.ai_summary IS NOT NULL
              AND r.ai_summary != ''
            ORDER BY run.business_date DESC, run.created_timestamp DESC
            LIMIT 1
        """)

        # A4 — check for most recent AI-enriched KPI failure
        df_a4 = execute_query(f"""
            SELECT
                r.ai_summary,
                r.ai_recommended_action,
                r.ai_failure_category,
                run.created_timestamp   AS alert_timestamp,
                run.gold_fully_qualified_name AS fully_qualified_name,
                run.business_date
            FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_results_b r
            JOIN {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b run
              ON r.validation_run_id = run.validation_run_id
            WHERE r.check_status IN ('CRITICAL', 'WARNING')
              AND r.ai_summary IS NOT NULL
              AND r.ai_summary != ''
            ORDER BY run.business_date DESC, run.created_timestamp DESC
            LIMIT 1
        """)

        # Use the most recent of A1 or A4
        a1_ts = None
        a4_ts = None

        if not df_a1.empty:
            a1_ts = df_a1.iloc[0]["alert_timestamp"]
        if not df_a4.empty:
            a4_ts = df_a4.iloc[0]["alert_timestamp"]

        if a1_ts is None and a4_ts is None:
            return {}

        if a4_ts is not None and (a1_ts is None or a4_ts >= a1_ts):
            row = df_a4.iloc[0]
        else:
            row = df_a1.iloc[0]

        return {
            "summary"        : str(row.get("ai_summary", "") or ""),
            "action"         : str(row.get("ai_recommended_action", "") or ""),
            "alert_timestamp": row.get("alert_timestamp"),
            "table_name"     : str(row.get("fully_qualified_name", "")).split(".")[-1]
        }

    except Exception as e:
        logger.error(f"Failed to load AI context: {e}")
        return {}


def _load_latest_timestamp() -> datetime:
    """
    Returns the most recent created_timestamp across
    A1 and A4 validation runs — used as "Last updated".
    """
    try:
        df = execute_query(f"""
            SELECT MAX(ts) AS latest FROM (
                SELECT MAX(created_timestamp) AS ts
                FROM {CATALOG}.{SCHEMA}.uc1_validation_run_b
                UNION ALL
                SELECT MAX(created_timestamp) AS ts
                FROM {CATALOG}.{SCHEMA}.uc4_kpi_validation_run_b
            )
        """)
        if df.empty or df.iloc[0]["latest"] is None:
            return None
        return df.iloc[0]["latest"]
    except Exception as e:
        logger.error(f"Failed to load latest timestamp: {e}")
        return None

# ── text cleanup function ──────────────────────────────────────────────────────
import re

def _clean_narrative_text(text: str) -> str:
    """
    Cleans AI summary text for business-facing display.

    1. Reduces decimal places to 2 for any number with more than 2
    2. Converts rate thresholds expressed as decimals to percentages
       when the context indicates they are rates
    """
    if not text:
        return text

    # Round numbers with more than 2 decimal places
    def round_match(m):
        num_str = m.group(0)
        has_pct = num_str.endswith('%')
        clean   = num_str.rstrip('%')
        try:
            val = float(clean)
            if '.' in clean and len(clean.split('.')[1]) > 2:
                formatted = f"{val:.2f}"
                return formatted + ('%' if has_pct else '')
            return num_str
        except (ValueError, TypeError):
            return num_str

    text = re.sub(r'\d+\.\d{3,}%?', round_match, text)

    # Convert "maximum of 0.X" and "minimum of 0.X" to percentages
    # when value is between 0 and 1 — these are rate thresholds
    # stored as decimals in the KPI registry but should display as %
    def convert_threshold(m):
        prefix = m.group(1)   # "maximum of " or "minimum of "
        val    = float(m.group(2))
        if 0 < val < 1:
            return f"{prefix}{val * 100:.0f}%"
        return m.group(0)

    text = re.sub(
        r'((?:maximum|minimum|max|min) of )(0\.\d+)',
        convert_threshold,
        text,
        flags=re.IGNORECASE
    )

    return text

# ── Status derivation ──────────────────────────────────────────────────────

def _derive_domain_statuses(a1: dict, a4: dict) -> dict:
    """
    Maps raw table statuses to the four business domains.

    Customer Data    → A1 uc1_raw_store_transactions
                       (customer-related checks: NULL_SPIKE on customer_id,
                        loyalty fields; if txn table is OK we treat as OK)
    Transaction Data → A1 uc1_raw_store_transactions overall
    Inventory Data   → A1 uc1_raw_inventory_movements overall
    Financial Reports→ A4 uc2_gold_daily_store_metrics overall
                       (worst of A4 gold store + A4 gold inventory)
    """

    TXN_FQN = f"{CATALOG}.{SCHEMA}.uc1_raw_store_transactions"
    INV_FQN = f"{CATALOG}.{SCHEMA}.uc1_raw_inventory_movements"
    GOLD_STORE_FQN = f"{CATALOG}.{SCHEMA}.uc2_gold_daily_store_metrics"
    GOLD_INV_FQN   = f"{CATALOG}.{SCHEMA}.uc2_gold_daily_inventory_summary"

    txn_status       = a1.get(TXN_FQN, {}).get("status", "UNKNOWN")
    inv_status       = a1.get(INV_FQN, {}).get("status", "UNKNOWN")
    gold_store_status= a4.get(GOLD_STORE_FQN, {}).get("status", "UNKNOWN")
    gold_inv_status  = a4.get(GOLD_INV_FQN, {}).get("status", "UNKNOWN")

    severity = {"CRITICAL": 3, "WARNING": 2, "PASS": 1, "UNKNOWN": 0}

    # Financial reports = worst of gold store and gold inventory
    fin_status = (
        gold_store_status
        if severity.get(gold_store_status, 0) >= severity.get(gold_inv_status, 0)
        else gold_inv_status
    )

    # Customer data = same source as transactions
    # but we only flag CRITICAL if there are customer-specific failures
    # For simplicity at PoC: mirror transaction status, but cap at WARNING
    # (a volume drop doesn't mean customer data is wrong)
    if txn_status == "CRITICAL":
        cust_status = "WARNING"
    else:
        cust_status = txn_status

    return {
        "customer"    : cust_status,
        "transaction" : txn_status,
        "inventory"   : inv_status,
        "financial"   : fin_status,
    }


# ── UI rendering helpers ───────────────────────────────────────────────────

_STATUS_CONFIG = {
    "PASS"   : {
        "emoji"     : "🟢",
        "label"     : "All systems normal",
        "color"     : "#00c851",
        "bg"        : "#002800",
        "border"    : "#00c851",
    },
    "WARNING": {
        "emoji"     : "🟡",
        "label"     : "Minor anomalies — monitoring",
        "color"     : "#ffa500",
        "bg"        : "#3d2000",
        "border"    : "#ffa500",
    },
    "CRITICAL": {
        "emoji"     : "🔴",
        "label"     : "Quality issues detected — team investigating",
        "color"     : "#ff6b6b",
        "bg"        : "#3d0000",
        "border"    : "#ff6b6b",
    },
    "UNKNOWN": {
        "emoji"     : "⚪",
        "label"     : "Status unavailable",
        "color"     : "#aaaaaa",
        "bg"        : "#1a1a1a",
        "border"    : "#555555",
    },
}


def _status_row(domain_label: str, status: str) -> html.Div:
    """Renders a single domain status row."""
    cfg = _STATUS_CONFIG.get(status, _STATUS_CONFIG["UNKNOWN"])

    return html.Div([
        html.Div(
            domain_label,
            style={
                "color"     : "#ffffff",
                "fontSize"  : "18px",
                "fontWeight": "500",
                "flex"      : "1",
            }
        ),
        html.Div([
            html.Span(cfg["emoji"], style={"marginRight": "8px", "fontSize": "20px"}),
            html.Span(
                cfg["label"],
                style={
                    "color"   : cfg["color"],
                    "fontSize": "16px",
                    "fontWeight": "500",
                }
            ),
        ], style={"display": "flex", "alignItems": "center", "flexShrink": "0"}),
    ],
    style={
        "display"        : "flex",
        "justifyContent" : "space-between",
        "alignItems"     : "center",
        "padding"        : "16px 20px",
        "marginBottom"   : "8px",
        "borderRadius"   : "8px",
        "backgroundColor": cfg["bg"],
        "borderLeft"     : f"4px solid {cfg['border']}",
    })


def _fmt_timestamp(ts) -> str:
    """Formats a timestamp as '06:24 today' or '06:24 on 19 Jul'."""
    if ts is None:
        return "unknown"
    try:
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        now = datetime.now()
        time_str = ts.strftime("%H:%M")
        if ts.date() == now.date():
            return f"{time_str} today"
        return f"{time_str} on {ts.strftime('%-d %b')}"
    except Exception:
        return str(ts)


def _any_issue(statuses: dict) -> bool:
    return any(v in ("CRITICAL", "WARNING") for v in statuses.values())


def _any_critical(statuses: dict) -> bool:
    return any(v == "CRITICAL" for v in statuses.values())


def _build_narrative(statuses: dict, ai_ctx: dict) -> list:
    """
    Builds the 'What this means' section as clean bullet points.
    Handles AI text that may contain numbered lists, sentence fragments,
    or plain paragraphs.
    """
    import re

    elements = []

    if not _any_issue(statuses):
        return elements

    # ── Heading ────────────────────────────────────────────────────────────
    elements.append(
        html.Hr(style={"borderColor": "#444", "margin": "32px 0 24px"})
    )
    elements.append(
        html.H5(
            "What this means",
            style={
                "color"       : "#ffffff",
                "fontSize"    : "18px",
                "fontWeight"  : "600",
                "marginBottom": "16px",
            }
        )
    )

    # ── Collect bullet points ──────────────────────────────────────────────
    bullets = []

    def extract_bullets(text: str) -> list:
        """
        Splits text into clean bullet points.

        Handles three formats the AI produces:
          1. Numbered:  "1. Do this. 2. Do that."
          2. Sentenced: "Something happened. Something else happened."
          3. Mixed:     "Overview sentence. 1. Step one. 2. Step two."

        Returns a list of clean strings with no leading numbers or dots.
        """
        if not text or not text.strip():
            return []

        text = text.strip()

        # Detect if text contains numbered list items
        numbered_pattern = re.compile(
            r'(?:^|\s)(\d+)[.)]\s+', re.MULTILINE
        )

        if numbered_pattern.search(text):
            # Split on numbered list markers
            # e.g. "Overview. 1. First step. 2. Second step."
            parts = re.split(r'\s*\d+[.)]\s+', text)
            result = []
            for part in parts:
                part = part.strip()
                if part:
                    # Remove trailing period only if it is the last char
                    # and not part of an abbreviation
                    result.append(part)
            return result
        else:
            # Split on sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return [s.strip() for s in sentences if s.strip()]

    if ai_ctx.get("summary"):
        bullets.extend(extract_bullets(ai_ctx["summary"]))
    else:
        # Fallback from statuses
        if statuses["transaction"] in ("CRITICAL", "WARNING"):
            bullets.append(
                "Transaction data quality issues have been detected "
                "and are under investigation."
            )
        if statuses["inventory"] in ("CRITICAL", "WARNING"):
            bullets.append(
                "Inventory data anomalies have been detected "
                "and are being monitored."
            )
        if statuses["financial"] in ("CRITICAL", "WARNING"):
            bullets.append(
                "Financial reports sourcing today's data may show "
                "incomplete or inaccurate figures."
            )

    if ai_ctx.get("action"):
        bullets.extend(extract_bullets(ai_ctx["action"]))
    elif _any_critical(statuses):
        bullets.append(
            "Please do not use today's data for financial decisions "
            "until the platform shows all systems normal."
        )

    if ai_ctx.get("alert_timestamp"):
        alert_str = _fmt_timestamp(ai_ctx["alert_timestamp"])
        bullets.append(
            f"The data engineering team was notified at {alert_str} "
            f"and is actively working on resolution."
        )

    # ── Render bullets — plain li tags, no numbers ─────────────────────────
    if bullets:
        elements.append(
            html.Ul(
                [
                    html.Li(
                        # Strip any leading "N." or "N)" the AI left in
                        re.sub(r'^\d+[.)]\s*', '', _clean_narrative_text(bullet)).strip(),
                        style={
                            "color"       : "#cccccc",
                            "fontSize"    : "16px",
                            "lineHeight"  : "1.6",
                            "marginBottom": "10px",
                        }
                    )
                    for bullet in bullets
                    if bullet and bullet.strip()
                    # Skip bullets that are only a number or empty
                    and not re.match(r'^\d+[.)]?\s*$', _clean_narrative_text(bullet.strip()))
                ],
                style={
                    "paddingLeft" : "24px",
                    "marginTop"   : "0",
                    "marginBottom": "0",
                    "listStyleType": "disc",   # ← explicit disc bullets
                }
            )
        )

    return elements


def build_status_page(
    statuses    : dict,
    last_updated: datetime,
    ai_ctx      : dict
) -> html.Div:
    """Assembles the complete status page content."""

    all_clear = not _any_issue(statuses)

    # ── Overall banner ─────────────────────────────────────────────────────
    if all_clear:
        banner_bg    = "#002800"
        banner_border= "#00c851"
        banner_text  = "🟢  All data systems are operating normally"
        banner_color = "#00c851"
    elif _any_critical(statuses):
        banner_bg    = "#3d0000"
        banner_border= "#ff6b6b"
        banner_text  = "🔴  Some data systems require attention"
        banner_color = "#ff6b6b"
    else:
        banner_bg    = "#3d2000"
        banner_border= "#ffa500"
        banner_text  = "🟡  Minor data quality issues detected"
        banner_color = "#ffa500"

    return html.Div([

        # ── Page title ─────────────────────────────────────────────────────
        html.H1(
            "DATA PLATFORM HEALTH",
            style={
                "color"         : "#ffffff",
                "fontSize"      : "28px",
                "fontWeight"    : "700",
                "letterSpacing" : "2px",
                "marginBottom"  : "4px",
            }
        ),
        html.P(
            f"Last updated: {_fmt_timestamp(last_updated)}",
            style={
                "color"       : "#aaaaaa",
                "fontSize"    : "14px",
                "marginBottom": "32px",
            }
        ),

        # ── Overall banner ─────────────────────────────────────────────────
        html.Div(
            html.P(
                banner_text,
                style={
                    "color"    : banner_color,
                    "fontSize" : "16px",
                    "fontWeight": "600",
                    "margin"   : "0",
                }
            ),
            style={
                "backgroundColor": banner_bg,
                "border"         : f"1px solid {banner_border}",
                "borderRadius"   : "8px",
                "padding"        : "14px 20px",
                "marginBottom"   : "24px",
            }
        ),

        # ── Domain status rows ─────────────────────────────────────────────
        _status_row("Customer Data",     statuses["customer"]),
        _status_row("Transaction Data",  statuses["transaction"]),
        _status_row("Inventory Data",    statuses["inventory"]),
        _status_row("Financial Reports", statuses["financial"]),

        # ── Narrative (only when issues exist) ─────────────────────────────
        *_build_narrative(statuses, ai_ctx),

        # ── Footer ─────────────────────────────────────────────────────────
        html.Hr(style={"borderColor": "#333", "margin": "40px 0 20px"}),
        html.P([
            "This page refreshes automatically every 60 seconds. ",
            html.Br(),
            "For technical details, contact the data engineering team."
        ],
        style={
            "color"    : "#666666",
            "fontSize" : "13px",
            "textAlign": "center",
        })

    ])


def _error_page(message: str) -> html.Div:
    return html.Div([
        html.H1("DATA PLATFORM HEALTH",
                style={"color": "#ffffff", "fontSize": "28px",
                       "fontWeight": "700", "letterSpacing": "2px"}),
        html.P("Status temporarily unavailable.",
               style={"color": "#aaaaaa", "fontSize": "16px",
                      "marginTop": "16px"}),
        html.P(message,
               style={"color": "#666666", "fontSize": "13px"})
    ])


# ── Callback ───────────────────────────────────────────────────────────────

@callback(
    Output("status-page-content", "children"),
    Input("status-refresh-interval", "n_intervals"),
)
def refresh_status(n_intervals):
    try:
        a1           = _load_latest_agent1_status()
        a4           = _load_latest_agent4_status()
        ai_ctx       = _load_ai_context()
        last_updated = _load_latest_timestamp()

        if not a1 and not a4:
            return _error_page("No validation runs found in the database.")

        statuses = _derive_domain_statuses(a1, a4)

        return build_status_page(statuses, last_updated, ai_ctx)

    except Exception as e:
        logger.error(f"Status page render failed: {e}")
        import traceback
        traceback.print_exc()
        return _error_page(f"Could not load status data: {str(e)}")
    
@callback(
    Output("status-refresh-interval",  "disabled"),
    Output("status-refresh-toggle",    "children"),
    Output("status-refresh-toggle",    "color"),
    Output("status-refresh-indicator", "children"),
    Output("status-refresh-paused",    "data"),
    Input("status-refresh-toggle",     "n_clicks"),
    State("status-refresh-paused",     "data"),
    prevent_initial_call=True,
)
def toggle_status_refresh(n_clicks, is_paused):
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
        "Auto-refreshing every 60 seconds",
        False,
    )