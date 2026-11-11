# components/alerts.py

import dash_bootstrap_components as dbc
from dash import html
import math

# ─────────────────────────────────────────────
# BASIC ALERT COMPONENTS
# ─────────────────────────────────────────────

def success_alert(message: str):
    return dbc.Alert(
        message,
        color="success",
        dismissable=True,
        duration=4000
    )


def error_alert(message: str):
    return dbc.Alert(
        message,
        color="danger",
        dismissable=True
    )


def warning_alert(message: str):
    return dbc.Alert(
        message,
        color="warning",
        dismissable=True
    )


def info_alert(message: str):
    return dbc.Alert(
        message,
        color="info",
        dismissable=True
    )


# ─────────────────────────────────────────────
# SHARED CONSTANTS
# ─────────────────────────────────────────────

STATUS_EMOJI = {
    "CRITICAL": "🔴",
    "WARNING" : "🟡",
    "PASS"    : "🟢",
    "ERROR"   : "⚫"
}

STATUS_COLOR = {
    "CRITICAL": "danger",
    "WARNING" : "warning",
    "PASS"    : "success",
    "ERROR"   : "dark"
}

STATUS_BORDER = {
    "CRITICAL": "#ff4444",
    "WARNING" : "#ffa500",
    "PASS"    : "#00c851",
    "ERROR"   : "#666666"
}


# ─────────────────────────────────────────────
# SHARED TEAMS ALERT PREVIEW MODAL
# ─────────────────────────────────────────────

def build_alert_modal(modal_id: str = "shared-alert-modal") -> dbc.Modal:
    """
    Returns a reusable Teams alert preview modal.

    Each page using this must have:
      - A dcc.Store with id="{modal_id}-store"
      - A trigger button in the layout
      - Callbacks to populate the store and toggle the modal

    Args:
        modal_id: Unique ID prefix per page to avoid callback conflicts.
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(
                    id=f"{modal_id}-title",
                    children="Teams Alert Preview"
                ),
                close_button=True
            ),
            dbc.ModalBody(
                id=f"{modal_id}-body",
                children=[]
            ),
            dbc.ModalFooter([
                html.Div([
                    html.Small(
                        "Preview of the MessageCard sent to ",
                        className="text-muted"
                    ),
                    html.Small(
                        "platform-support",
                        className="text-info fw-bold"
                    ),
                    html.Small(
                        " Teams channel.",
                        className="text-muted"
                    )
                ], className="me-auto"),
                dbc.Button(
                    "Close",
                    id=f"{modal_id}-close-btn",
                    color="secondary",
                    n_clicks=0
                )
            ])
        ],
        id=modal_id,
        size="lg",
        is_open=False,
        scrollable=True
    )


def build_alert_card_body(
    agent_name     : str,
    table_name     : str,
    fqn            : str,
    business_date  : str,
    status         : str,
    checks_run     : int,
    checks_passed  : int,
    checks_warned  : int,
    checks_critical: int,
    failed_checks  : list,
    ai_summary     : str   = None,
    ai_action      : str   = None,
    ai_category    : str   = None,
    ai_confidence  : float = None,
    run_id         : str   = "",
    extra_facts    : list  = None
) -> list:
    """
    Builds the content for a Teams alert preview modal body.
    Works for all four agents.

    Args:
        agent_name    : Display name e.g. "Validation Agent — Raw Ingestion Validation"
        table_name    : Short table name
        fqn           : Fully qualified table name
        business_date : Business date string
        status        : CRITICAL, WARNING, PASS
        checks_run    : Total checks executed
        checks_passed : Number of PASS checks
        checks_warned : Number of WARNING checks
        checks_critical: Number of CRITICAL checks
        failed_checks : List of dicts with keys:
                        check_type, column_name, check_status,
                        observed_value, deviation_pct,
                        threshold_warning, threshold_critical
        ai_summary    : AI-generated summary text
        ai_action     : AI-generated recommended action
        ai_category   : AI failure category string
        ai_confidence : Float 0.0 to 1.0
        run_id        : Run ID for audit footer
        extra_facts   : Additional {"name": str, "value": str} facts
                        to show in the alert details section
    """
    emoji  = STATUS_EMOJI.get(status, "⚪")
    color  = STATUS_COLOR.get(status, "secondary")
    border = STATUS_BORDER.get(status, "#666666")

    elements = []

    # ── Header ─────────────────────────────────────────────────────────────
    elements.append(
        dbc.Card([
            dbc.CardBody([
                html.H5(
                    f"{emoji} {status} — Data Quality Alert",
                    className=f"text-{color} mb-1"
                ),
                html.P(
                    agent_name,
                    className="text-muted mb-0 small"
                )
            ])
        ],
        className="mb-3",
        style={
            "borderLeft"     : f"4px solid {border}",
            "backgroundColor": "#2b2b2b"
        })
    )

    # ── Alert Details ──────────────────────────────────────────────────────
    standard_facts = [
        ("Table",         table_name),
        ("Full Name",     fqn),
        ("Business Date", business_date),
        ("Status",        f"{emoji} {status}"),
    ]

    if extra_facts:
        standard_facts.extend(
            [(f["name"], f["value"]) for f in extra_facts]
        )

    fact_rows = []
    for i in range(0, len(standard_facts), 2):
        pair = standard_facts[i:i+2]
        cols = []
        for name, value in pair:
            cols.append(
                dbc.Col([
                    html.Small(name, className="text-muted d-block"),
                    html.Strong(str(value), className="small text-break")
                ], md=6)
            )
        fact_rows.append(dbc.Row(cols, className="mb-2"))

    elements.append(
        dbc.Card([
            dbc.CardHeader(
                html.Strong("📋 Alert Details"),
                style={"backgroundColor": "#343a40", "color": "white"}
            ),
            dbc.CardBody(fact_rows)
        ], className="mb-3")
    )

    # ── Check Summary ──────────────────────────────────────────────────────
    elements.append(
        dbc.Card([
            dbc.CardHeader(
                html.Strong("📊 Check Summary"),
                style={"backgroundColor": "#343a40", "color": "white"}
            ),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.H4(str(checks_run), className="mb-0"),
                        html.Small("Total", className="text-muted")
                    ], md=3, className="text-center"),
                    dbc.Col([
                        html.H4(
                            str(checks_passed),
                            className="mb-0 text-success"
                        ),
                        html.Small("✅ Passed", className="text-muted")
                    ], md=3, className="text-center"),
                    dbc.Col([
                        html.H4(
                            str(checks_warned),
                            className="mb-0",
                            style={"color": "#ffa500"}
                        ),
                        html.Small("🟡 Warning", className="text-muted")
                    ], md=3, className="text-center"),
                    dbc.Col([
                        html.H4(
                            str(checks_critical),
                            className="mb-0 text-danger"
                        ),
                        html.Small("🔴 Critical", className="text-muted")
                    ], md=3, className="text-center"),
                ])
            ])
        ], className="mb-3")
    )

    # ── Failed Checks ──────────────────────────────────────────────────────
    if failed_checks:
        check_items = []
        for check in failed_checks:
            c_status = check.get("check_status", "")
            c_emoji  = STATUS_EMOJI.get(c_status, "⚪")
            c_type   = check.get("check_type", "")
            c_col    = check.get("column_name", "table-level") or "table-level"
            c_obs    = check.get("observed_value")
            c_dev    = check.get("deviation_pct")
            c_warn   = (
                check.get("threshold_warning") or
                check.get("warn_threshold")
            )
            c_crit   = (
                check.get("threshold_critical") or
                check.get("crit_threshold")
            )

            obs_str  = f"{c_obs:.4f}"  if c_obs  is not None else "N/A"
            dev_str  = f"{c_dev:.2f}%" if c_dev  is not None else "N/A"
            warn_str = str(c_warn)     if c_warn is not None else "N/A"
            crit_str = str(c_crit)     if c_crit is not None else "N/A"

            check_items.append(
                dbc.ListGroupItem([
                    html.Div([
                        html.Span(
                            f"{c_emoji} {c_type}",
                            className="fw-bold me-2 small"
                        ),
                        dbc.Badge(
                            c_status,
                            color=(
                                "danger"
                                if c_status == "CRITICAL"
                                else "warning"
                            ),
                            className="me-2"
                        ),
                        html.Small(
                            f"on {c_col}",
                            className="text-muted"
                        )
                    ]),
                    html.Div([
                        html.Small(
                            f"Observed: {obs_str}  |  "
                            f"Deviation: {dev_str}  |  "
                            f"Warn ≥ {warn_str}  |  "
                            f"Critical ≥ {crit_str}",
                            className="text-muted"
                        )
                    ], className="mt-1")
                ],
                style={
                    "backgroundColor": (
                        "#3d0000"
                        if c_status == "CRITICAL"
                        else "#3d2600"
                    ),
                    "color": (
                        "#ff6b6b"
                        if c_status == "CRITICAL"
                        else "#ffa500"
                    ),
                    "border"      : "none",
                    "marginBottom": "4px",
                    "borderRadius": "4px"
                })
            )

        elements.append(
            dbc.Card([
                dbc.CardHeader(
                    html.Strong(f"❌ Issues Found ({len(failed_checks)})"),
                    style={"backgroundColor": "#343a40", "color": "white"}
                ),
                dbc.CardBody([
                    dbc.ListGroup(check_items, flush=True)
                ])
            ], className="mb-3")
        )

    # ── AI Analysis ────────────────────────────────────────────────────────
    if ai_summary:
        try:
            conf_pct = (
                f"{float(ai_confidence):.0%}"
                if ai_confidence is not None
                else "N/A"
            )
        except (TypeError, ValueError):
            conf_pct = "N/A"

        elements.append(
            dbc.Card([
                dbc.CardHeader(
                    html.Strong("🤖 AI Analysis"),
                    style={"backgroundColor": "#343a40", "color": "white"}
                ),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Badge(
                                ai_category or "N/A",
                                color=color,
                                className="me-2 mb-2"
                            ),
                            dbc.Badge(
                                f"Confidence: {conf_pct}",
                                color="secondary",
                                className="mb-2"
                            )
                        ])
                    ]),
                    html.P(
                        html.Strong("Summary:"),
                        className="mb-1 mt-2"
                    ),
                    html.P(
                        ai_summary,
                        className="border-start border-info ps-3 mb-3 small"
                    ),
                    html.P(
                        html.Strong("Recommended Action:"),
                        className="mb-1"
                    ),
                    html.P(
                        ai_action or "No specific action recommended.",
                        className="border-start border-success ps-3 small"
                    )
                ])
            ], className="mb-3")
        )
    else:
        elements.append(
            dbc.Alert(
                "AI enrichment was not triggered for this run.",
                color="info",
                className="mb-3"
            )
        )

    # ── Footer ─────────────────────────────────────────────────────────────
    elements.append(html.Hr())
    elements.append(
        html.Small(
            f"Channel: platform-support  |  Run ID: {run_id}",
            className="text-muted"
        )
    )

    return elements

import math

def fmt_optional(val, decimals=None) -> str:
    """
    Safely formats an optional numeric value for display.
    Handles None, float('nan'), empty string, and "nan" string.
    Returns "—" for any missing/invalid value.

    Args:
        val      : The value to format
        decimals : Optional decimal places. If None returns str(val)
    """
    if val is None:
        return "—"

    # Handle string "nan" that sometimes comes through
    if isinstance(val, str):
        if val.strip().lower() in ("nan", "none", "", "null"):
            return "—"
        return val

    # Handle float nan
    try:
        f = float(val)
        if math.isnan(f):
            return "—"
        if decimals is not None:
            return f"{f:.{decimals}f}"
        # Return without trailing zeros for clean display
        if f == int(f):
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return "—"
    

def fmt_number(val) -> str:
    """
    Formats a numeric value for display in result grids.

    Rules:
      None / nan        → '—'
      Integer values    → no decimal  (20.0 → '20')
      Float values      → 2 decimals  (0.0977 → '0.10')
      Zero              → '0'
    """
    if val is None:
        return "—"
    try:
        f = float(val)
        if math.isnan(f):
            return "—"
        if f == 0:
            return "0"
        if f == int(f):
            return str(int(f))
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_deviation(val, check_type: str = "") -> str:
    """
    Formats a deviation percentage with correct sign.

    Rules:
      None / nan                        → '—'
      FORMULA / CROSS_KPI / RANGE       → always positive (violation count/rate)
      ANOMALY / VOLUME / SURVIVAL etc.  → signed (- for drop, + for spike)
      Zero                              → '0.00'

    Sign is preserved from the raw value passed in.
    Caller is responsible for computing signed deviation before calling.
    """
    if val is None:
        return "—"
    try:
        f = float(val)
        if math.isnan(f):
            return "—"
        if f == 0:
            return "0.00"

        # Checks where deviation is always a violation rate (never negative)
        unsigned_checks = {
            "FORMULA", "CROSS_KPI", "RANGE",
            "SCHEMA_CONFORMANCE", "DUPLICATE_INGESTION",
            "MALFORMED_RECORDS"
        }
        if check_type.upper() in unsigned_checks:
            return f"{abs(f):.2f}"

        # All other checks: show sign explicitly
        if f > 0:
            return f"+{f:.2f}"
        else:
            return f"{f:.2f}"   # negative already has - sign

    except (TypeError, ValueError):
        return "—"


def fmt_threshold(val) -> str:
    """
    Formats a threshold value for display.

    Rules:
      None / nan    → '—'
      Integer value → no decimal  (5.0 → '5')
      Float value   → 2 decimals  (0.5 → '0.50')
      Zero          → '0'
    """
    if val is None:
        return "—"
    try:
        f = float(val)
        if math.isnan(f):
            return "—"
        if f == 0:
            return "0"
        if f == int(f):
            return str(int(f))
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return "—"


def compute_signed_deviation(
    observed_val,
    baseline_val,
    check_type: str = ""
) -> float:
    """
    Computes signed deviation percentage.

    For directional checks (ANOMALY, VOLUME_ANOMALY, NULL_SPIKE etc.):
      positive = observed above baseline (spike)
      negative = observed below baseline (drop)

    For violation count checks (FORMULA, CROSS_KPI, RANGE):
      always returns raw deviation (always positive)

    Returns None if inputs are invalid.
    """
    unsigned_checks = {
        "FORMULA", "CROSS_KPI", "RANGE",
        "SCHEMA_CONFORMANCE", "DUPLICATE_INGESTION",
        "MALFORMED_RECORDS"
    }

    try:
        obs  = float(observed_val or 0)
        base = float(baseline_val or 0)
        ct   = check_type.upper()

        if ct in unsigned_checks:
            # Violation rate — already positive from DB
            return abs(obs)

        if base == 0:
            if obs == 0:
                return 0.0
            # No baseline — cannot compute meaningful percentage
            return None

        return ((obs - base) / abs(base)) * 100

    except (TypeError, ValueError):
        return None


STATUS_CODE = {
    "CRITICAL": 1,
    "WARNING" : 2,
    "PASS"    : 3,
    "ERROR"   : 4
}


def add_status_code(
    rows       : list,
    status_col : str = "check_status"
) -> list:
    """
    Adds a numeric _status_code field to each row dict.

    Required before passing rows to any DataTable that colours
    rows by status.

    Args:
        rows       : list of row dicts (the DataTable data)
        status_col : name of the column containing
                     CRITICAL / WARNING / PASS / ERROR

    Returns:
        Same list with _status_code added to each dict.
        Modifies in place and also returns the list.

    Example:
        table_rows = add_status_code(table_rows, "check_status")
        table_rows = add_status_code(table_rows, "overall_status")
        table_rows = add_status_code(table_rows, "last_review_status")
    """
    for row in rows:
        status           = str(row.get(status_col, "")).strip().upper()
        row["_status_code"] = STATUS_CODE.get(status, 0)
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# AG GRID HELPERS — modern replacement for DataTable
# ═════════════════════════════════════════════════════════════════════════════

import dash_mantine_components as dmc


# ── Status Badge (DMC) ─────────────────────────────────────────────────────

STATUS_DMC_COLOR = {
    "CRITICAL": "red",
    "WARNING" : "yellow",
    "PASS"    : "green",
    "ERROR"   : "gray",
}


def status_badge(status: str) -> dmc.Badge:
    """
    Returns a styled DMC Badge for CRITICAL / WARNING / PASS / ERROR.
    Use in any layout to replace plain text status display.
    """
    color = STATUS_DMC_COLOR.get(status, "gray")
    emoji = STATUS_EMOJI.get(status, "⚪")
    return dmc.Badge(
        f"{emoji} {status}",
        color=color,
        variant="light",
        size="sm",
        radius="sm",
    )


# ── AG Grid default column definitions ─────────────────────────────────────

AG_GRID_DEFAULT_COL_DEF = {
    "resizable"          : True,
    "sortable"           : True,
    "filter"             : True,
    "filterParams"       : {"buttons": ["reset"]},
    "cellStyle"          : {"fontSize": "14px"},
    "minWidth"           : 100,
    "tooltipValueGetter" : {"function": "params.value"},
}

AG_GRID_THEME = "ag-theme-alpine-dark"


# JavaScript function for AG Grid conditional row styling
AG_STATUS_ROW_STYLE_JS = """
    function(params) {
        var status = params.data ? (params.data.overall_status || params.data.check_status || params.data.last_review_status || '') : '';
        status = status.toUpperCase();
        if (status === 'CRITICAL') {
            return {backgroundColor: '#3d0000', color: '#ff6b6b'};
        } else if (status === 'WARNING') {
            return {backgroundColor: '#3d2000', color: '#ffa500'};
        } else if (status === 'PASS') {
            return {backgroundColor: '#002800', color: '#00c851'};
        } else if (status === 'ERROR') {
            return {backgroundColor: '#1a1a1a', color: '#888888'};
        }
        return null;
    }
"""

# JavaScript cellStyle for ALL cells in status-aware grids.
# Reads the row's status field and applies the matching text color
# to every cell, replicating the old get_status_style_conditions behavior.
AG_STATUS_ROW_CELL_STYLE_JS = """
    function(params) {
        var status = params.data
            ? (params.data.overall_status || params.data.check_status || params.data.last_review_status || '')
            : '';
        status = status.toUpperCase();
        var style = {fontSize: '14px'};
        if (status === 'CRITICAL') { style.color = '#ff6b6b'; }
        else if (status === 'WARNING') { style.color = '#ffa500'; }
        else if (status === 'PASS')    { style.color = '#00c851'; }
        else if (status === 'ERROR')   { style.color = '#888888'; }
        return style;
    }
"""

# JavaScript cellStyle for status badge column (fallback for non-badge grids)
AG_STATUS_CELL_STYLE_JS = """
    function(params) {
        var val = (params.value || '').toUpperCase();
        if (val === 'CRITICAL') return {color: '#ff4444', fontWeight: 'bold'};
        if (val === 'WARNING')  return {color: '#ffa500', fontWeight: 'bold'};
        if (val === 'PASS')     return {color: '#00c851', fontWeight: 'bold'};
        if (val === 'ERROR')    return {color: '#888888', fontWeight: 'bold'};
        return null;
    }
"""

# JavaScript cellRenderer for status pill badge (colored bg + white text)
AG_STATUS_BADGE_RENDERER_JS = """
    function(params) {
        var val = (params.value || '').toUpperCase();
        var colorMap = {
            'CRITICAL': '#dc3545',
            'WARNING' : '#fd7e14',
            'PASS'    : '#198754',
            'ERROR'   : '#6c757d'
        };
        var bg = colorMap[val];
        if (!bg) return params.value || '';
        return '<span style="background:' + bg
            + '; color:#fff; padding:2px 10px; border-radius:12px;'
            + ' font-size:12px; font-weight:600; display:inline-block;'
            + ' line-height:1.6; letter-spacing:0.3px;">' + val + '</span>';
    }
"""

# JavaScript cellStyle for deviation columns (red negative, green positive)
AG_DEVIATION_CELL_STYLE_JS = """
    function(params) {
        var val = parseFloat(params.value);
        if (isNaN(val)) return null;
        if (val < 0) return {color: '#ff6b6b', fontWeight: 'bold'};
        if (val > 0) return {color: '#ffa500', fontWeight: 'bold'};
        return {color: '#00c851'};
    }
"""


def ag_grid_props(
    grid_id   : str,
    row_data  : list       = None,
    col_defs  : list       = None,
    status_col: str        = None,
    page_size : int        = 12,
    selection  : str        = None,
    height    : str        = None,
) -> dict:
    """
    Returns a dict of standard AG Grid properties.
    Use with: dag.AgGrid(**ag_grid_props(...))

    Args:
        grid_id   : component ID
        row_data  : list of row dicts (default empty list)
        col_defs  : list of AG Grid columnDef dicts
        status_col: column to apply status conditional row styling
        page_size : rows per page (default 12)
        selection  : 'single' or 'multiple' for row selection
        height    : explicit grid height (default auto-sized)
    """
    props = {
        "id"                     : grid_id,
        "rowData"                : row_data or [],
        "columnDefs"             : col_defs or [],
        "defaultColDef"          : AG_GRID_DEFAULT_COL_DEF,
        "className"              : AG_GRID_THEME,
        "columnSize"             : "autoSize",
        "columnSizeOptions"      : {"skipHeader": False},
        "style"                  : {"width": "100%"},
        "dashGridOptions"        : {
            "pagination"             : True,
            "paginationPageSize"     : page_size,
            "animateRows"            : True,
            "rowHeight"              : 40,
            "headerHeight"           : 42,
            "domLayout"              : "autoHeight" if not height else "normal",
            "tooltipShowDelay"       : 200,
            "enableCellTextSelection": True,
            "ensureDomOrder"         : True,
        },
    }

    if status_col:
        # CSS class rules for row coloring — uses !important in custom.css
        # to override AG Grid theme's --ag-foreground-color variable
        status_expr = "(params.data.overall_status || params.data.check_status || params.data.last_review_status || '').toUpperCase()"
        props["dashGridOptions"]["rowClassRules"] = {
            "row-critical": f"params.data && {status_expr} === 'CRITICAL'",
            "row-warning" : f"params.data && {status_expr} === 'WARNING'",
            "row-pass"    : f"params.data && {status_expr} === 'PASS'",
            "row-error"   : f"params.data && {status_expr} === 'ERROR'",
        }
    if selection:
        props["dashGridOptions"]["rowSelection"] = selection

    if height:
        props["style"] = {"width": "100%", "height": height}

    return props