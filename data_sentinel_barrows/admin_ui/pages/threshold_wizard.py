# pages/threshold_wizard.py

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, ctx
import dash_bootstrap_components as dbc
from db.connection import execute_query, execute_write
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import error_alert, success_alert, warning_alert
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path  = "/threshold-wizard",
    name  = "Threshold Management Wizard"
)

PREFIX = f"{TARGET_CATALOG}.{TARGET_SCHEMA}."

# ── Light theme constants ──────────────────────────────────────────────────

PAGE_BG       = "#f8f9fa"
CARD_BG       = "#ffffff"
CARD_SHADOW   = "0 2px 8px rgba(0,0,0,0.08)"
TEXT_PRIMARY  = "#212529"
TEXT_MUTED    = "#6c757d"
TEXT_HEADING  = "#343a40"
BORDER_COLOR  = "#dee2e6"
STEP_ACTIVE   = "#0d6efd"
STEP_COMPLETE = "#198754"
STEP_INACTIVE = "#adb5bd"
WIZARD_WIDTH  = {"maxWidth": "960px", "margin": "0 auto"}

CARD_STYLE = {
    "backgroundColor": CARD_BG,
    "border"         : f"1px solid {BORDER_COLOR}",
    "borderRadius"   : "12px",
    "boxShadow"      : CARD_SHADOW,
    "padding"        : "28px 32px",
    "marginBottom"   : "24px",
}

LABEL_STYLE = {
    "color"       : TEXT_PRIMARY,
    "fontWeight"  : "600",
    "fontSize"    : "14px",
    "marginBottom": "6px",
}

MUTED_STYLE = {
    "color"   : TEXT_MUTED,
    "fontSize": "12px",
}

STEPS = [
    {"num": 1, "label": "Select Scope"},
    {"num": 2, "label": "Edit Thresholds"},
    {"num": 3, "label": "Impact Preview"},
    {"num": 4, "label": "Review & Apply"},
]

# ── Progress bar ───────────────────────────────────────────────────────────

def build_progress_bar(current_step: int) -> html.Div:
    steps = []
    for i, s in enumerate(STEPS):
        num     = s["num"]
        label   = s["label"]
        is_done = num < current_step
        is_curr = num == current_step

        if is_done:
            circle_style = {
                "width"          : "36px",
                "height"         : "36px",
                "borderRadius"   : "50%",
                "backgroundColor": STEP_COMPLETE,
                "color"          : "#fff",
                "display"        : "flex",
                "alignItems"     : "center",
                "justifyContent" : "center",
                "fontWeight"     : "700",
                "fontSize"       : "14px",
                "margin"         : "0 auto 6px",
            }
            circle_content = "✓"
        elif is_curr:
            circle_style = {
                "width"          : "36px",
                "height"         : "36px",
                "borderRadius"   : "50%",
                "backgroundColor": STEP_ACTIVE,
                "color"          : "#fff",
                "display"        : "flex",
                "alignItems"     : "center",
                "justifyContent" : "center",
                "fontWeight"     : "700",
                "fontSize"       : "14px",
                "margin"         : "0 auto 6px",
            }
            circle_content = str(num)
        else:
            circle_style = {
                "width"          : "36px",
                "height"         : "36px",
                "borderRadius"   : "50%",
                "backgroundColor": "#e9ecef",
                "color"          : STEP_INACTIVE,
                "display"        : "flex",
                "alignItems"     : "center",
                "justifyContent" : "center",
                "fontWeight"     : "700",
                "fontSize"       : "14px",
                "margin"         : "0 auto 6px",
            }
            circle_content = str(num)

        label_color = (
            STEP_COMPLETE if is_done else
            STEP_ACTIVE   if is_curr else
            STEP_INACTIVE
        )

        steps.append(html.Div([
            html.Div(circle_content, style=circle_style),
            html.Div(
                label,
                style={
                    "fontSize"  : "11px",
                    "color"     : label_color,
                    "fontWeight": "600" if is_curr else "400",
                    "textAlign" : "center",
                }
            )
        ], style={"textAlign": "center", "flex": "1"}))

        if i < len(STEPS) - 1:
            line_color = (
                STEP_COMPLETE if num < current_step else "#e9ecef"
            )
            steps.append(html.Div(style={
                "flex"           : "0 0 40px",
                "height"         : "2px",
                "backgroundColor": line_color,
                "marginTop"      : "17px",
                "marginBottom"   : "auto",
            }))

    return html.Div(
        steps,
        style={
            "display"     : "flex",
            "alignItems"  : "flex-start",
            "marginBottom": "32px",
        }
    )


# ── Layout ─────────────────────────────────────────────────────────────────

def layout():
    return html.Div(id="tw-wizard-page", children=[

        # Fixed page background
        html.Div(style={
            "position"       : "fixed",
            "top"            : 0,
            "left"           : 0,
            "right"          : 0,
            "bottom"         : 0,
            "backgroundColor": PAGE_BG,
            "zIndex"         : -1,
        }),

        # ── Stores ────────────────────────────────────────────────────────
        dcc.Store(id="tw-step",        data=1),
        dcc.Store(id="tw-scope",       data={}),
        dcc.Store(id="tw-thresholds",  data=[]),
        dcc.Store(id="tw-impact",      data={}),

        # ── Persistent hidden buttons ──────────────────────────────────────
        html.Div([
            dbc.Button(id="tw-next-1", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-next-2", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-next-3", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-back-2", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-back-3", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-back-4", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-apply",  n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="tw-restart",n_clicks=0,
                       style={"display": "none"}),
        ], style={"display": "none"}),

        # ── Visible content ────────────────────────────────────────────────
        html.Div([

            # Header
            html.Div([
                html.H2(
                    "⚙️ Threshold Management Wizard",
                    style={
                        "color"       : TEXT_HEADING,
                        "fontWeight"  : "700",
                        "marginBottom": "4px",
                    }
                ),
                html.P(
                    "Update warning and critical thresholds for column "
                    "and table-level validation checks. Preview the impact "
                    "before applying.",
                    style={**MUTED_STYLE, "fontSize": "14px"}
                ),
            ], style={"marginBottom": "32px", "paddingTop": "24px"}),

            # Progress bar
            html.Div(id="tw-progress-bar"),

            # Alert
            html.Div(id="tw-alert", className="mb-3"),

            # Step content
            dcc.Loading(
                id       = "tw-loading",
                type     = "circle",
                color    = STEP_ACTIVE,
                children = html.Div(id="tw-step-content"),
            ),

        ], style={**WIZARD_WIDTH, "padding": "0 16px 60px"}),

    ], style={"backgroundColor": PAGE_BG, "minHeight": "100vh"})


# ── Step 1 — Select Scope ──────────────────────────────────────────────────

def build_step1() -> html.Div:

    # Load all registered tables
    try:
        df_tables = execute_query(f"""
            SELECT DISTINCT table_name, fully_qualified_name
            FROM {PREFIX}uc1_table_registry_b
            WHERE is_active = true
            ORDER BY table_name
        """)
        table_options = [
            {"label": r["table_name"], "value": r["fully_qualified_name"]}
            for _, r in df_tables.iterrows()
        ]
    except Exception as e:
        logger.error(f"build_step1 load tables: {e}")
        table_options = []

    # Load all check types from both registries
    try:
        df_col_checks = execute_query(f"""
            SELECT DISTINCT validation_name AS check_type
            FROM {PREFIX}uc1_column_validation_registry_b
            WHERE is_active = true
            ORDER BY 1
        """)
        df_tbl_checks = execute_query(f"""
            SELECT DISTINCT validation_name AS check_type
            FROM {PREFIX}uc1_table_validation_registry_b
            WHERE is_active = true
            ORDER BY 1
        """)
        all_checks = set(
            df_col_checks["check_type"].tolist() +
            df_tbl_checks["check_type"].tolist()
        )
        check_options = [
            {"label": c, "value": c}
            for c in sorted(all_checks)
        ]
    except Exception as e:
        logger.error(f"build_step1 load checks: {e}")
        check_options = []

    return html.Div([
        html.Div([
            html.H4("Step 1 — Select Scope",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                "Choose what you want to update. You can target a "
                "specific table, a specific check type, or both.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([

            # Scope type
            dbc.Row([
                dbc.Col([
                    html.Label("Scope Type", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "tw-scope-type",
                        options   = [
                            {"label": "Single Table — all checks",
                             "value": "table_all"},
                            {"label": "Single Table — specific check type",
                             "value": "table_check"},
                            {"label": "All Tables — specific check type",
                             "value": "all_check"},
                            {"label": "All Tables — all checks",
                             "value": "all_all"},
                        ],
                        value     = "table_all",
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                ], md=6),
                dbc.Col([
                    html.Label("Check Level", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "tw-check-level",
                        options   = [
                            {"label": "Both (Column + Table)",
                             "value": "both"},
                            {"label": "Column-level only",
                             "value": "column"},
                            {"label": "Table-level only",
                             "value": "table"},
                        ],
                        value     = "both",
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                ], md=6),
            ], className="mb-3"),

            # Table selector
            dbc.Row([
                dbc.Col([
                    html.Label("Table", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "tw-table-select",
                        options     = table_options,
                        placeholder = "Select a table…",
                        clearable   = True,
                        className   = "ob-dropdown",
                    ),
                    html.Small(
                        "Required when scope is Single Table",
                        style=MUTED_STYLE
                    ),
                ], md=6),
                dbc.Col([
                    html.Label("Check Type", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "tw-check-type-select",
                        options     = check_options,
                        placeholder = "Select check type…",
                        clearable   = True,
                        className   = "ob-dropdown",
                    ),
                    html.Small(
                        "Required when scope is specific check type",
                        style=MUTED_STYLE
                    ),
                ], md=6),
            ], className="mb-3"),

            # Impact preview window
            dbc.Row([
                dbc.Col([
                    html.Label("Impact Preview Window", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "tw-preview-window",
                        options   = [
                            {"label": "Last 30 days",  "value": "30"},
                            {"label": "Last 60 days",  "value": "60"},
                            {"label": "Last 90 days",  "value": "90"},
                        ],
                        value     = "90",
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                    html.Small(
                        "Historical window used to preview alert impact",
                        style=MUTED_STYLE
                    ),
                ], md=6),
            ], className="mb-3"),

        ], style=CARD_STYLE),

        _nav_buttons_tw(step=1, show_back=False),
    ])


# ── Step 2 — Edit Thresholds ───────────────────────────────────────────────

def build_step2(scope: dict, current_thresholds: list) -> html.Div:

    if not current_thresholds:
        return html.Div([
            warning_alert("No thresholds found for the selected scope."),
            _nav_buttons_tw(step=2, show_back=True),
        ])

    # Group by check level
    col_checks = [t for t in current_thresholds
                  if t.get("level") == "column"]
    tbl_checks = [t for t in current_thresholds
                  if t.get("level") == "table"]

    def threshold_row(t, i):
        row_id = t["row_id"]
        return html.Div([
            dbc.Row([
                # Table name
                dbc.Col([
                    html.Small(
                        t.get("table_name", "—"),
                        style={"color"     : TEXT_PRIMARY,
                               "fontWeight": "600",
                               "fontSize"  : "13px"}
                    ),
                ], md=3),
                # Column name (only for column checks)
                dbc.Col([
                    html.Small(
                        t.get("column_name", "—"),
                        style={"color"  : TEXT_MUTED,
                               "fontSize": "12px"}
                    ),
                ], md=2),
                # Check type
                dbc.Col([
                    dbc.Badge(
                        t.get("check_type", "—"),
                        color    = "light",
                        text_color= "dark",
                        style    = {"fontSize": "11px"}
                    ),
                ], md=2),
                # Current warn
                dbc.Col([
                    html.Small(
                        f"Current: "
                        f"{t.get('current_warn','—')}%",
                        style={"color": TEXT_MUTED,
                               "fontSize": "11px"}
                    ),
                    dbc.Input(
                        id          = {"type": "tw-warn-input",
                                       "index": row_id},
                        value       = t.get("current_warn"),
                        type        = "number",
                        min         = 0,
                        max         = 100,
                        placeholder = "Warn %",
                        style       = {
                            "backgroundColor": "#ffffff",
                            "color"          : TEXT_PRIMARY,
                            "border"         : f"1px solid {BORDER_COLOR}",
                            "fontSize"       : "13px",
                            "marginTop"      : "4px",
                        },
                    ),
                ], md=2),
                # Current crit
                dbc.Col([
                    html.Small(
                        f"Current: "
                        f"{t.get('current_crit','—')}%",
                        style={"color": TEXT_MUTED,
                               "fontSize": "11px"}
                    ),
                    dbc.Input(
                        id          = {"type": "tw-crit-input",
                                       "index": row_id},
                        value       = t.get("current_crit"),
                        type        = "number",
                        min         = 0,
                        max         = 100,
                        placeholder = "Crit %",
                        style       = {
                            "backgroundColor": "#ffffff",
                            "color"          : TEXT_PRIMARY,
                            "border"         : f"1px solid {BORDER_COLOR}",
                            "fontSize"       : "13px",
                            "marginTop"      : "4px",
                        },
                    ),
                ], md=2),
            ], className="align-items-center"),
        ], style={
            "padding"        : "10px 16px",
            "borderBottom"   : f"1px solid {BORDER_COLOR}",
            "backgroundColor": CARD_BG,
        })

    def section(title, checks, level_icon):
        if not checks:
            return html.Div()
        return html.Div([
            html.H6(
                f"{level_icon} {title}",
                style={"color"       : TEXT_HEADING,
                       "fontWeight"  : "700",
                       "marginBottom": "12px"}
            ),
            html.Div([
                # Header
                html.Div([
                    dbc.Row([
                        dbc.Col(html.Small("Table",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=3),
                        dbc.Col(html.Small("Column",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("Check Type",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("New Warn %",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("New Crit %",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                    ])
                ], style={
                    "padding"        : "8px 16px",
                    "backgroundColor": "#e9ecef",
                    "borderRadius"   : "6px 6px 0 0",
                    "border"         : f"1px solid {BORDER_COLOR}",
                }),
                html.Div(
                    [threshold_row(t, i)
                     for i, t in enumerate(checks)],
                    style={
                        "border"      : f"1px solid {BORDER_COLOR}",
                        "borderTop"   : "none",
                        "borderRadius": "0 0 6px 6px",
                        "maxHeight"   : "380px",
                        "overflowY"   : "auto",
                    }
                ),
            ], style={"marginBottom": "24px"}),
        ])

    scope_desc = _scope_description(scope)

    return html.Div([
        html.Div([
            html.H4("Step 2 — Edit Thresholds",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                f"Editing thresholds for: {scope_desc}. "
                f"Change the warn and critical percentages below.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            dbc.Alert([
                html.Strong("ℹ️ How to edit: "),
                html.Span(
                    "Update the Warn % and Crit % fields. "
                    "Leave blank to keep current value. "
                    "Warn should always be lower than Crit."
                ),
            ], color="info", className="mb-4"),

            section(
                "Column-Level Checks", col_checks, "🔢"
            ),
            section(
                "Table-Level Checks", tbl_checks, "🏷️"
            ),
        ], style={**CARD_STYLE}),

        _nav_buttons_tw(step=2, show_back=True),
    ])


# ── Step 3 — Impact Preview ────────────────────────────────────────────────

def build_step3(
    scope          : dict,
    old_thresholds : list,
    new_thresholds : list,
    preview_days   : int = 90,
) -> html.Div:

    fqn_filter = scope.get("fqn")
    check_filter = scope.get("check_type")
    since = str(date.today() - timedelta(days=preview_days))

    # Build where clause for validation results
    where_parts  = ["business_date >= :since"]
    where_params = {"since": since}
    if fqn_filter:
        where_parts.append(
            "fully_qualified_name = :fqn_filter"
        )
        where_params["fqn_filter"] = fqn_filter
    if check_filter:
        where_parts.append(
            "check_type = :check_filter"
        )
        where_params["check_filter"] = check_filter
    where_str = " AND ".join(where_parts)

    # Load historical results
    try:
        df = execute_query(f"""
            SELECT
                check_type,
                check_status,
                observed_value,
                deviation_percentage,
                threshold_warning,
                threshold_critical
            FROM {PREFIX}uc1_validation_results_b
            WHERE {where_str}
        """, where_params)
    except Exception as e:
        logger.error(f"build_step3 load results: {e}")
        df = None

    if df is None or df.empty:
        return html.Div([
            html.Div([
                html.H4("Step 3 — Impact Preview",
                        style={"color": TEXT_HEADING,
                               "fontWeight": "700",
                               "marginBottom": "4px"}),
                html.P("Preview impact of threshold changes.",
                       style=MUTED_STYLE),
            ], style={"marginBottom": "24px"}),

            dbc.Alert(
                f"No validation results found for the last "
                f"{preview_days} days matching this scope. "
                f"Cannot generate impact preview.",
                color="warning"
            ),

            _nav_buttons_tw(step=3, show_back=True),
        ])

    # Build lookup: row_id → new thresholds
    new_thresh_map = {
        t["row_id"]: t for t in new_thresholds
    }

    # Count current outcomes
    current_pass  = int((df["check_status"] == "PASS").sum())
    current_warn  = int((df["check_status"] == "WARNING").sum())
    current_crit  = int((df["check_status"] == "CRITICAL").sum())
    total_checks  = len(df)

    # Simulate new outcomes using deviation_percentage
    # Compare against new thresholds
    # We apply per-check-type thresholds
    # Build check_type → new thresholds map
    check_thresh = {}
    for t in new_thresholds:
        ct = t.get("check_type")
        if ct:
            if ct not in check_thresh:
                check_thresh[ct] = {
                    "warn": t.get("new_warn", t.get("current_warn")),
                    "crit": t.get("new_crit", t.get("current_crit")),
                }

    def simulate_status(row):
        ct   = row.get("check_type")
        dev  = row.get("deviation_percentage")
        obs  = row.get("observed_value")

        if ct not in check_thresh:
            return row.get("check_status", "PASS")

        warn = check_thresh[ct].get("warn")
        crit = check_thresh[ct].get("crit")

        if warn is None or crit is None:
            return row.get("check_status", "PASS")

        # Use absolute deviation percentage
        val = abs(float(dev)) if dev is not None else 0.0

        if val >= float(crit):
            return "CRITICAL"
        elif val >= float(warn):
            return "WARNING"
        return "PASS"

    df["simulated_status"] = df.apply(simulate_status, axis=1)

    new_pass = int((df["simulated_status"] == "PASS").sum())
    new_warn = int((df["simulated_status"] == "WARNING").sum())
    new_crit = int((df["simulated_status"] == "CRITICAL").sum())

    # Delta
    d_warn = new_warn - current_warn
    d_crit = new_crit - current_crit
    d_pass = new_pass - current_pass

    def delta_badge(val):
        if val > 0:
            return dbc.Badge(
                f"+{val}",
                color="danger" if val > 0 else "success",
                className="ms-1"
            )
        elif val < 0:
            return dbc.Badge(
                str(val),
                color="success",
                className="ms-1"
            )
        return dbc.Badge("0", color="secondary", className="ms-1")

    def impact_card(label, current, new, delta, color):
        return html.Div([
            html.Small(label,
                       style={**MUTED_STYLE, "fontWeight": "600"}),
            dbc.Row([
                dbc.Col([
                    html.Div("Current",
                             style={"fontSize": "11px",
                                    "color"   : TEXT_MUTED}),
                    html.Div(str(current),
                             style={"fontSize"  : "24px",
                                    "fontWeight": "700",
                                    "color"     : color,
                                    "fontFamily": "monospace"}),
                ], md=4),
                dbc.Col([
                    html.Div("→",
                             style={"fontSize"  : "20px",
                                    "color"     : TEXT_MUTED,
                                    "paddingTop": "12px",
                                    "textAlign" : "center"}),
                ], md=2),
                dbc.Col([
                    html.Div("Proposed",
                             style={"fontSize": "11px",
                                    "color"   : TEXT_MUTED}),
                    html.Div(str(new),
                             style={"fontSize"  : "24px",
                                    "fontWeight": "700",
                                    "color"     : color,
                                    "fontFamily": "monospace"}),
                ], md=4),
                dbc.Col([
                    html.Div("Δ",
                             style={"fontSize": "11px",
                                    "color"   : TEXT_MUTED}),
                    delta_badge(delta),
                ], md=2),
            ], className="align-items-center mt-1"),
        ], style={
            "backgroundColor": "#f8f9fa",
            "border"         : f"1px solid {BORDER_COLOR}",
            "borderLeft"     : f"4px solid {color}",
            "borderRadius"   : "8px",
            "padding"        : "12px 16px",
            "marginBottom"   : "12px",
        })

    # Overall verdict
    total_alerts_current = current_warn + current_crit
    total_alerts_new     = new_warn + new_crit
    alert_delta          = total_alerts_new - total_alerts_current

    if alert_delta > total_alerts_current * 0.5:
        verdict_color = "danger"
        verdict_icon  = "🔴"
        verdict_text  = (
            f"Proposed thresholds would generate "
            f"{abs(alert_delta)} more alerts "
            f"({round(abs(alert_delta)/max(total_alerts_current,1)*100)}% increase). "
            f"Consider whether this is intentional."
        )
    elif alert_delta < 0 and abs(alert_delta) > total_alerts_current * 0.5:
        verdict_color = "warning"
        verdict_icon  = "🟡"
        verdict_text  = (
            f"Proposed thresholds would suppress "
            f"{abs(alert_delta)} alerts. "
            f"Ensure genuine failures will not be missed."
        )
    elif alert_delta == 0:
        verdict_color = "success"
        verdict_icon  = "🟢"
        verdict_text  = (
            "No change in alert volume. "
            "Thresholds adjusted but outcome distribution unchanged."
        )
    else:
        verdict_color = "success"
        verdict_icon  = "🟢"
        verdict_text  = (
            f"Minor change — {abs(alert_delta)} "
            f"{'more' if alert_delta > 0 else 'fewer'} alerts. "
            f"Looks reasonable."
        )

    return html.Div([
        html.Div([
            html.H4("Step 3 — Impact Preview",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                f"Simulated against last {preview_days} days of "
                f"validation results ({total_checks:,} checks).",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            # Verdict banner
            dbc.Alert(
                f"{verdict_icon}  {verdict_text}",
                color     = verdict_color,
                className = "mb-4",
            ),

            # Impact cards
            dbc.Row([
                dbc.Col(impact_card(
                    "🔴 CRITICAL",
                    current_crit, new_crit, d_crit, "#dc3545"
                ), md=4),
                dbc.Col(impact_card(
                    "🟡 WARNING",
                    current_warn, new_warn, d_warn, "#ffa500"
                ), md=4),
                dbc.Col(impact_card(
                    "🟢 PASS",
                    current_pass, new_pass, d_pass, "#198754"
                ), md=4),
            ], className="mb-4"),

            # Summary table
            html.H6("Threshold Changes Summary",
                    style={"color"       : TEXT_HEADING,
                           "fontWeight"  : "700",
                           "marginBottom": "12px"}),
            html.Div([
                html.Div([
                    dbc.Row([
                        dbc.Col(html.Small("Check Type",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=3),
                        dbc.Col(html.Small("Column",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("Old Warn",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("New Warn",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("Old Crit",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=2),
                        dbc.Col(html.Small("New Crit",
                            style={**MUTED_STYLE,
                                   "fontWeight": "600"}), md=1),
                    ])
                ], style={
                    "padding"        : "8px 16px",
                    "backgroundColor": "#e9ecef",
                    "borderRadius"   : "6px 6px 0 0",
                    "border"         : f"1px solid {BORDER_COLOR}",
                }),
                html.Div([
                    html.Div([
                        dbc.Row([
                            dbc.Col(
                                html.Small(
                                    t.get("check_type", "—"),
                                    style={"color"     : TEXT_PRIMARY,
                                           "fontWeight": "600",
                                           "fontSize"  : "12px"}
                                ), md=3
                            ),
                            dbc.Col(
                                html.Small(
                                    t.get("column_name", "—"),
                                    style={"color"   : TEXT_MUTED,
                                           "fontSize": "12px"}
                                ), md=2
                            ),
                            dbc.Col(
                                html.Small(
                                    f"{t.get('current_warn','—')}%",
                                    style={"color"   : TEXT_MUTED,
                                           "fontSize": "12px"}
                                ), md=2
                            ),
                            dbc.Col(
                                html.Small(
                                    f"{t.get('new_warn','—')}%",
                                    style={
                                        "color"     : (
                                            "#0d6efd"
                                            if t.get("new_warn") !=
                                               t.get("current_warn")
                                            else TEXT_MUTED
                                        ),
                                        "fontWeight": "600",
                                        "fontSize"  : "12px",
                                    }
                                ), md=2
                            ),
                            dbc.Col(
                                html.Small(
                                    f"{t.get('current_crit','—')}%",
                                    style={"color"   : TEXT_MUTED,
                                           "fontSize": "12px"}
                                ), md=2
                            ),
                            dbc.Col(
                                html.Small(
                                    f"{t.get('new_crit','—')}%",
                                    style={
                                        "color"     : (
                                            "#0d6efd"
                                            if t.get("new_crit") !=
                                               t.get("current_crit")
                                            else TEXT_MUTED
                                        ),
                                        "fontWeight": "600",
                                        "fontSize"  : "12px",
                                    }
                                ), md=1
                            ),
                        ])
                    ], style={
                        "padding"     : "8px 16px",
                        "borderBottom": f"1px solid {BORDER_COLOR}",
                    })
                    for t in new_thresholds
                ], style={
                    "border"      : f"1px solid {BORDER_COLOR}",
                    "borderTop"   : "none",
                    "borderRadius": "0 0 6px 6px",
                    "maxHeight"   : "300px",
                    "overflowY"   : "auto",
                }),
            ]),
        ], style=CARD_STYLE),

        _nav_buttons_tw(step=3, show_back=True),
    ])


# ── Step 4 — Review & Apply ────────────────────────────────────────────────

def build_step4(
    scope         : dict,
    new_thresholds: list,
    apply_result  : dict = None,
) -> html.Div:

    scope_desc    = _scope_description(scope)
    changes_count = len([
        t for t in new_thresholds
        if (t.get("new_warn") != t.get("current_warn") or
            t.get("new_crit") != t.get("current_crit"))
    ])

    if apply_result and apply_result.get("done"):
        ok = apply_result.get("all_ok", False)
        if ok:
            banner = dbc.Alert([
                html.H5("✅ Thresholds Updated Successfully!",
                        className="mb-1"),
                html.P(
                    f"{apply_result.get('updated', 0)} threshold "
                    f"records updated.",
                    className="mb-0",
                    style={"fontSize": "13px"}
                ),
            ], color="success")
        else:
            banner = dbc.Alert([
                html.H5("⚠️ Update Completed with Errors",
                        className="mb-1"),
                html.P(
                    f"{apply_result.get('updated', 0)} updated, "
                    f"{apply_result.get('errors', 0)} failed.",
                    className="mb-0",
                    style={"fontSize": "13px"}
                ),
            ], color="warning")

        return html.Div([
            html.Div([
                html.H4("Thresholds Updated",
                        style={"color"     : TEXT_HEADING,
                               "fontWeight": "700",
                               "marginBottom": "4px"}),
            ], style={"marginBottom": "24px"}),

            html.Div([banner], style=CARD_STYLE),

            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        "⚙️ Update More Thresholds",
                        id    = "tw-restart-visible",
                        color = "primary",
                        style = {"marginRight": "12px",
                                 "fontWeight" : "600"}
                    ),
                    dbc.Button(
                        "🔍 View Validation Results",
                        href  = "/validation-results",
                        color = "outline-secondary",
                        outline=True,
                    ),
                ], className="d-flex align-items-center"),
            ]),
        ])

    def srow(label, value, color=TEXT_PRIMARY):
        return dbc.Row([
            dbc.Col(html.Small(label,
                style={**MUTED_STYLE, "fontWeight": "600"}), md=4),
            dbc.Col(html.Span(value,
                style={"color"     : color,
                       "fontWeight": "600",
                       "fontSize"  : "14px"}), md=8),
        ], className="mb-2")

    return html.Div([
        html.Div([
            html.H4("Step 4 — Review & Apply",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                "Final review before updating thresholds.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            html.H6("Summary",
                    style={"color"       : TEXT_HEADING,
                           "fontWeight"  : "700",
                           "marginBottom": "16px"}),
            srow("Scope",           scope_desc),
            srow("Records Changed", str(changes_count),
                 STEP_ACTIVE),
            srow("Level",           scope.get("check_level_label", "Both")),

            html.Hr(style={"borderColor": BORDER_COLOR,
                           "margin"     : "16px 0"}),

            dbc.Alert(
                "⚠️ This will immediately update thresholds in the "
                "validation registry. Next validation run will use "
                "the new values.",
                color="warning", className="mb-0"
            ),
        ], style={**CARD_STYLE, "marginBottom": "24px"}),

        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "← Back",
                    id      = "tw-back-4-visible",
                    color   = "light",
                    outline = True,
                    style   = {
                        "color"      : TEXT_PRIMARY,
                        "borderColor": BORDER_COLOR,
                        "marginRight": "12px",
                    }
                ),
                dbc.Button(
                    "✅ Apply Threshold Changes",
                    id    = "tw-apply-visible",
                    color = "success",
                    size  = "lg",
                    style = {
                        "fontWeight": "700",
                        "padding"   : "10px 32px",
                    }
                ),
            ], className="d-flex align-items-center"),
        ]),
    ])


# ── Helpers ────────────────────────────────────────────────────────────────

def _nav_buttons_tw(step: int, show_back: bool = True) -> dbc.Row:
    back_btn = dbc.Button(
        "← Back",
        id      = f"tw-back-{step}-visible",
        color   = "light",
        outline = True,
        style   = {
            "color"      : TEXT_PRIMARY,
            "borderColor": BORDER_COLOR,
            "marginRight": "12px",
        },
    ) if show_back else html.Div()

    next_label = "Next →" if step < 3 else "Review →"

    return dbc.Row([
        dbc.Col([
            back_btn,
            dbc.Button(
                next_label,
                id    = f"tw-next-{step}-visible",
                color = "primary",
                style = {"fontWeight": "600",
                         "padding"   : "8px 24px"},
            ),
        ], className="d-flex align-items-center"),
    ], className="mt-4")


def _scope_description(scope: dict) -> str:
    scope_type = scope.get("scope_type", "")
    fqn        = scope.get("fqn", "")
    table_name = fqn.split(".")[-1] if fqn else "All Tables"
    check_type = scope.get("check_type", "All Checks")

    if scope_type == "table_all":
        return f"{table_name} — All Checks"
    if scope_type == "table_check":
        return f"{table_name} — {check_type}"
    if scope_type == "all_check":
        return f"All Tables — {check_type}"
    return "All Tables — All Checks"


def _load_thresholds(scope: dict) -> list:
    """
    Loads current thresholds from column and/or
    table validation registries based on scope.
    """
    fqn          = scope.get("fqn")
    check_type   = scope.get("check_type")
    check_level  = scope.get("check_level", "both")
    rows         = []

    # ── Column-level ──────────────────────────────────────────────────────
    if check_level in ("both", "column"):
        try:
            where_parts  = ["1=1"]
            where_params = {}
            if fqn:
                where_parts.append(
                    "fully_qualified_name = :fqn"
                )
                where_params["fqn"] = fqn
            if check_type:
                where_parts.append(
                    "validation_name = :check_type"
                )
                where_params["check_type"] = check_type
            where_str = " AND ".join(where_parts)

            df = execute_query(f"""
                SELECT
                    column_validation_id AS row_id,
                    fully_qualified_name,
                    column_name,
                    validation_name      AS check_type,
                    warning_threshold    AS current_warn,
                    critical_threshold   AS current_crit,
                    is_active
                FROM {PREFIX}uc1_column_validation_registry_b
                WHERE {where_str}
                  AND is_active = true
                ORDER BY fully_qualified_name,
                         column_name,
                         validation_name
            """, where_params)
            for _, r in df.iterrows():
                rows.append({
                    "row_id"      : str(r["row_id"]),
                    "level"       : "column",
                    "table_name"  : str(
                        r["fully_qualified_name"]
                    ).split(".")[-1],
                    "fqn"         : str(r["fully_qualified_name"]),
                    "column_name" : str(r.get("column_name", "—")),
                    "check_type"  : str(r["check_type"]),
                    "current_warn": (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "current_crit": (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                    "new_warn"    : (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "new_crit"    : (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                })
            for _, r in df.iterrows():
                rows.append({
                    "row_id"      : str(r["row_id"]),
                    "level"       : "column",
                    "table_name"  : str(
                        r["fully_qualified_name"]
                    ).split(".")[-1],
                    "fqn"         : str(r["fully_qualified_name"]),
                    "column_name" : str(r.get("column_name", "—")),
                    "check_type"  : str(r["check_type"]),
                    "current_warn": (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "current_crit": (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                    "new_warn"    : (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "new_crit"    : (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                })
        except Exception as e:
            logger.error(f"_load_thresholds column: {e}")

    # ── Table-level ───────────────────────────────────────────────────────
    if check_level in ("both", "table"):
        try:
            where_parts  = ["1=1"]
            where_params = {}
            if fqn:
                where_parts.append(
                    "fully_qualified_name = :fqn"
                )
                where_params["fqn"] = fqn
            if check_type:
                where_parts.append(
                    "validation_name = :check_type"
                )
                where_params["check_type"] = check_type
            where_str = " AND ".join(where_parts)

            df = execute_query(f"""
                SELECT
                    table_validation_id AS row_id,
                    fully_qualified_name,
                    validation_name     AS check_type,
                    warning_threshold   AS current_warn,
                    critical_threshold  AS current_crit,
                    is_active
                FROM {PREFIX}uc1_table_validation_registry_b
                WHERE {where_str}
                  AND is_active = true
                ORDER BY fully_qualified_name,
                         validation_name
            """, where_params)
            for _, r in df.iterrows():
                rows.append({
                    "row_id"      : str(r["row_id"]),
                    "level"       : "table",
                    "table_name"  : str(
                        r["fully_qualified_name"]
                    ).split(".")[-1],
                    "fqn"         : str(r["fully_qualified_name"]),
                    "column_name" : "—",
                    "check_type"  : str(r["check_type"]),
                    "current_warn": (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "current_crit": (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                    "new_warn"    : (
                        float(r["current_warn"])
                        if r["current_warn"] is not None else None
                    ),
                    "new_crit"    : (
                        float(r["current_crit"])
                        if r["current_crit"] is not None else None
                    ),
                })
        except Exception as e:
            logger.error(f"_load_thresholds table: {e}")

    return rows


def _apply_thresholds(new_thresholds: list) -> dict:
    """
    Updates warning and critical thresholds in both
    registry tables using row_id (UUID primary key).
    """
    updated = 0
    errors  = 0

    for t in new_thresholds:
        row_id    = t.get("row_id")
        level     = t.get("level")
        new_warn  = t.get("new_warn")
        new_crit  = t.get("new_crit")
        curr_warn = t.get("current_warn")
        curr_crit = t.get("current_crit")

        # Skip if no change
        if new_warn == curr_warn and new_crit == curr_crit:
            continue

        # Skip if no valid id
        if not row_id:
            continue

        warn_val = (
            "NULL" if new_warn is None else float(new_warn)
        )
        crit_val = (
            "NULL" if new_crit is None else float(new_crit)
        )

        if level == "column":
            table  = f"{PREFIX}uc1_column_validation_registry_b"
            id_col = "column_validation_id"
        else:
            table  = f"{PREFIX}uc1_table_validation_registry_b"
            id_col = "table_validation_id"

        try:
            execute_write(f"""
                UPDATE {table}
                SET
                    warning_threshold  = {warn_val},
                    critical_threshold = {crit_val}
                WHERE {id_col} = :row_id
            """, {"row_id": row_id})
            updated += 1
        except Exception as e:
            logger.error(
                f"_apply_thresholds failed for {row_id}: {e}"
            )
            errors += 1

    return {
        "done"   : True,
        "all_ok" : errors == 0,
        "updated": updated,
        "errors" : errors,
    }


# ══════════════════════════════════════════════════════════════════════════
# BRIDGE CALLBACKS
# ══════════════════════════════════════════════════════════════════════════

@callback(
    Output("tw-next-1", "n_clicks"),
    Input("tw-next-1-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_next1(n): return n or 0

@callback(
    Output("tw-next-2", "n_clicks"),
    Input("tw-next-2-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_next2(n): return n or 0

@callback(
    Output("tw-next-3", "n_clicks"),
    Input("tw-next-3-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_next3(n): return n or 0

@callback(
    Output("tw-back-2", "n_clicks"),
    Input("tw-back-2-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_back2(n): return n or 0

@callback(
    Output("tw-back-3", "n_clicks"),
    Input("tw-back-3-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_back3(n): return n or 0

@callback(
    Output("tw-back-4", "n_clicks"),
    Input("tw-back-4-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_back4(n): return n or 0

@callback(
    Output("tw-apply", "n_clicks"),
    Input("tw-apply-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_apply(n): return n or 0

@callback(
    Output("tw-restart", "n_clicks"),
    Input("tw-restart-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_tw_restart(n): return n or 0


# ══════════════════════════════════════════════════════════════════════════
# STEP NAVIGATION CALLBACKS
# ══════════════════════════════════════════════════════════════════════════

# ── Step 1 → 2 ────────────────────────────────────────────────────────────

@callback(
    Output("tw-step",       "data",     allow_duplicate=True),
    Output("tw-scope",      "data",     allow_duplicate=True),
    Output("tw-thresholds", "data",     allow_duplicate=True),
    Output("tw-alert",      "children", allow_duplicate=True),
    Input("tw-next-1",      "n_clicks"),
    State("tw-scope-type",        "value"),
    State("tw-check-level",       "value"),
    State("tw-table-select",      "value"),
    State("tw-check-type-select", "value"),
    State("tw-preview-window",    "value"),
    prevent_initial_call=True,
)
def tw_next1(
    n_clicks,
    scope_type, check_level, fqn, check_type, preview_window
):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    # Validate
    if scope_type in ("table_all", "table_check") and not fqn:
        return (
            dash.no_update, dash.no_update,
            dash.no_update,
            error_alert("Please select a table.")
        )
    if scope_type in ("table_check", "all_check") and not check_type:
        return (
            dash.no_update, dash.no_update,
            dash.no_update,
            error_alert("Please select a check type.")
        )

    level_labels = {
        "both"  : "Column + Table",
        "column": "Column only",
        "table" : "Table only",
    }

    scope = {
        "scope_type"       : scope_type,
        "check_level"      : check_level,
        "check_level_label": level_labels.get(check_level, "Both"),
        "fqn"              : fqn if fqn else None,
        "check_type"       : check_type if check_type else None,
        "preview_window"   : int(preview_window or 90),
    }

    # Load current thresholds
    thresholds = _load_thresholds(scope)

    if not thresholds:
        return (
            dash.no_update, dash.no_update,
            dash.no_update,
            error_alert(
                "No thresholds found for the selected scope. "
                "Check your selection and try again."
            )
        )

    return 2, scope, thresholds, html.Div()


# ── Step 2 → 3 ────────────────────────────────────────────────────────────

@callback(
    Output("tw-step",       "data",     allow_duplicate=True),
    Output("tw-thresholds", "data",     allow_duplicate=True),
    Output("tw-alert",      "children", allow_duplicate=True),
    Input("tw-next-2",      "n_clicks"),
    State({"type": "tw-warn-input", "index": ALL}, "value"),
    State({"type": "tw-warn-input", "index": ALL}, "id"),
    State({"type": "tw-crit-input", "index": ALL}, "value"),
    State("tw-thresholds",  "data"),
    prevent_initial_call=True,
)
def tw_next2(
    n_clicks,
    warn_vals, warn_ids, crit_vals,
    thresholds
):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    # Build row_id → index map
    id_to_idx = {
        id_dict["index"]: i
        for i, id_dict in enumerate(warn_ids)
    }

    # Validate and update thresholds
    updated = list(thresholds)
    for i, t in enumerate(updated):
        row_id = t["row_id"]
        idx    = id_to_idx.get(row_id)
        if idx is None:
            continue

        new_warn = warn_vals[idx] if idx < len(warn_vals) else None
        new_crit = crit_vals[idx] if idx < len(crit_vals) else None

        # Validate warn < crit
        if (new_warn is not None and
                new_crit is not None and
                float(new_warn) >= float(new_crit)):
            return (
                dash.no_update, dash.no_update,
                error_alert(
                    f"Warn threshold must be less than Critical "
                    f"for {t.get('check_type')} "
                    f"on {t.get('column_name','table')}."
                )
            )

        updated[i] = {
            **t,
            "new_warn": new_warn,
            "new_crit": new_crit,
        }

    return 3, updated, html.Div()


# ── Step 3 → 4 ────────────────────────────────────────────────────────────

@callback(
    Output("tw-step",  "data",     allow_duplicate=True),
    Output("tw-alert", "children", allow_duplicate=True),
    Input("tw-next-3", "n_clicks"),
    prevent_initial_call=True,
)
def tw_next3(n_clicks):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    return 4, html.Div()


# ── Back buttons ───────────────────────────────────────────────────────────

@callback(
    Output("tw-step",  "data",     allow_duplicate=True),
    Output("tw-alert", "children", allow_duplicate=True),
    Input("tw-back-2", "n_clicks"),
    Input("tw-back-3", "n_clicks"),
    Input("tw-back-4", "n_clicks"),
    prevent_initial_call=True,
)
def tw_handle_back(b2, b3, b4):
    triggered = ctx.triggered_id
    mapping   = {
        "tw-back-2": 1,
        "tw-back-3": 2,
        "tw-back-4": 3,
    }
    return mapping.get(triggered, 1), html.Div()


# ── Apply ──────────────────────────────────────────────────────────────────

@callback(
    Output("tw-impact", "data",     allow_duplicate=True),
    Output("tw-alert",  "children", allow_duplicate=True),
    Input("tw-apply",   "n_clicks"),
    State("tw-thresholds", "data"),
    prevent_initial_call=True,
)
def tw_apply(n_clicks, thresholds):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    if not thresholds:
        return {}, error_alert("No thresholds to apply.")

    result = _apply_thresholds(thresholds)
    return result, html.Div()


# ── Restart ────────────────────────────────────────────────────────────────

@callback(
    Output("tw-step",       "data",     allow_duplicate=True),
    Output("tw-scope",      "data",     allow_duplicate=True),
    Output("tw-thresholds", "data",     allow_duplicate=True),
    Output("tw-impact",     "data",     allow_duplicate=True),
    Output("tw-alert",      "children", allow_duplicate=True),
    Input("tw-restart",     "n_clicks"),
    prevent_initial_call=True,
)
def tw_restart(n_clicks):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    return 1, {}, [], {}, html.Div()


# ── Step renderer ──────────────────────────────────────────────────────────

@callback(
    Output("tw-step-content", "children"),
    Output("tw-progress-bar", "children"),
    Input("tw-step",          "data"),
    Input("tw-impact",        "data"),
    State("tw-scope",         "data"),
    State("tw-thresholds",    "data"),
)
def tw_render_step(step, impact, scope, thresholds):
    step      = step      or 1
    scope     = scope     or {}
    thresholds= thresholds or []
    impact    = impact    or {}

    progress = build_progress_bar(step)

    if step == 1:
        return build_step1(), progress

    if step == 2:
        return build_step2(scope, thresholds), progress

    if step == 3:
        return build_step3(
            scope,
            thresholds,
            thresholds,
            preview_days=scope.get("preview_window", 90),
        ), progress

    if step == 4:
        return build_step4(
            scope, thresholds,
            apply_result=impact if impact.get("done") else None
        ), progress

    return html.Div("Unknown step."), progress