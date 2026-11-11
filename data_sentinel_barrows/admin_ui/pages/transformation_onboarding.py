# pages/transformation_onboarding.py
# Agent 3 — Transformation Review Onboarding Wizard

import dash
from dash import dcc, html, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
from db.connection import execute_query, execute_write
from config.settings import TARGET_CATALOG, TARGET_SCHEMA
from components.alerts import error_alert, warning_alert
import logging
import uuid
import json

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/transformation-onboarding",
    name="Transformation Onboarding",
)

# ── Theme constants (dark — matches other wizards) ────────────────────────────

PAGE_BG       = "#1A1B1E"
CARD_BG       = "#25262B"
CARD_SHADOW   = "0 2px 12px rgba(0,0,0,0.3)"
TEXT_PRIMARY  = "#C1C2C5"
TEXT_MUTED    = "#909296"
TEXT_HEADING  = "#E0E0E0"
BORDER_COLOR  = "#373A40"
STEP_ACTIVE   = "#4a9edd"
STEP_COMPLETE = "#00c851"
STEP_INACTIVE = "#5C5F66"

CARD_STYLE = {
    "backgroundColor": CARD_BG,
    "borderRadius"   : "10px",
    "padding"        : "24px",
    "border"         : f"1px solid {BORDER_COLOR}",
    "boxShadow"      : CARD_SHADOW,
}
LABEL_STYLE = {
    "color"       : TEXT_PRIMARY,
    "fontWeight"  : "600",
    "fontSize"    : "13px",
    "marginBottom": "6px",
}
MUTED_STYLE = {
    "color"   : TEXT_MUTED,
    "fontSize": "12px",
}
WIZARD_WIDTH = {"maxWidth": "960px", "margin": "0 auto"}

PREFIX = f"{TARGET_CATALOG}.{TARGET_SCHEMA}."

STEPS = [
    {"num": 1, "label": "Target & Source"},
    {"num": 2, "label": "Review Checks"},
    {"num": 3, "label": "Review & Confirm"},
]

CHECK_TYPES = [
    {
        "id"         : "JOIN_FANOUT",
        "label"      : "Join Fan-out Detection",
        "description": "Detects joins that inadvertently multiply rows",
        "default_on" : True,
    },
    {
        "id"         : "NULL_FILTER",
        "label"      : "Null Filter Analysis",
        "description": "Identifies WHERE clauses that silently drop NULLs",
        "default_on" : True,
    },
    {
        "id"         : "AGGREGATION_ORDER",
        "label"      : "Aggregation Order Check",
        "description": "Validates filter-before-aggregate ordering",
        "default_on" : True,
    },
    {
        "id"         : "ROW_COUNT_RATIO",
        "label"      : "Row Count Ratio",
        "description": "Compares output vs input row count against expected survival rate",
        "default_on" : True,
    },
]

LANGUAGE_OPTIONS = [
    {"label": "Python", "value": "PYTHON"},
    {"label": "SQL",    "value": "SQL"},
    {"label": "Scala",  "value": "SCALA"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_col(df, candidates, fallback_idx=0):
    cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    return df.columns[fallback_idx]


def _input_style():
    return {
        "backgroundColor": "#2C2E33",
        "color"          : TEXT_PRIMARY,
        "border"         : f"1px solid {BORDER_COLOR}",
        "fontSize"       : "13px",
    }


# ── Progress bar ──────────────────────────────────────────────────────────────

def build_progress_bar(current_step: int) -> html.Div:
    steps = []
    for i, s in enumerate(STEPS):
        num   = s["num"]
        label = s["label"]
        is_done = num < current_step
        is_curr = num == current_step

        if is_done:
            circle_style = {
                "width": "36px", "height": "36px", "borderRadius": "50%",
                "backgroundColor": STEP_COMPLETE, "color": "#fff",
                "display": "flex", "alignItems": "center",
                "justifyContent": "center", "fontWeight": "700",
                "fontSize": "16px",
            }
            circle = html.Div("\u2713", style=circle_style)
        elif is_curr:
            circle_style = {
                "width": "36px", "height": "36px", "borderRadius": "50%",
                "backgroundColor": STEP_ACTIVE, "color": "#fff",
                "display": "flex", "alignItems": "center",
                "justifyContent": "center", "fontWeight": "700",
                "fontSize": "16px",
            }
            circle = html.Div(str(num), style=circle_style)
        else:
            circle_style = {
                "width": "36px", "height": "36px", "borderRadius": "50%",
                "backgroundColor": "#2C2E33", "color": STEP_INACTIVE,
                "display": "flex", "alignItems": "center",
                "justifyContent": "center", "fontWeight": "700",
                "fontSize": "16px", "border": f"2px solid {STEP_INACTIVE}",
            }
            circle = html.Div(str(num), style=circle_style)

        label_color = (
            STEP_COMPLETE if is_done
            else STEP_ACTIVE if is_curr
            else STEP_INACTIVE
        )
        step_el = html.Div([
            circle,
            html.Small(label, style={
                "color": label_color, "marginTop": "6px",
                "fontWeight": "600" if is_curr else "400",
                "fontSize": "12px",
            }),
        ], style={"display": "flex", "flexDirection": "column",
                  "alignItems": "center", "flex": "1"})
        steps.append(step_el)

        if i < len(STEPS) - 1:
            line_color = STEP_COMPLETE if num < current_step else "#373A40"
            steps.append(html.Div(style={
                "flex": "1", "height": "2px", "backgroundColor": line_color,
                "alignSelf": "center", "margin": "0 8px",
                "marginBottom": "20px",
            }))

    return html.Div(steps, style={
        "display": "flex", "alignItems": "flex-start",
        "marginBottom": "32px", "padding": "0 20px",
    })


# ── Nav buttons ───────────────────────────────────────────────────────────────

def _nav_buttons(step, show_back=True):
    btns = []
    if show_back and step > 1:
        btns.append(dbc.Button(
            "\u2190 Back", id=f"to-back-{step}-visible",
            color="light", outline=True,
            style={"color": TEXT_PRIMARY, "borderColor": BORDER_COLOR,
                   "marginRight": "12px"},
        ))
    if step < len(STEPS):
        btns.append(dbc.Button(
            "Next \u2192", id=f"to-next-{step}-visible",
            color="primary", style={"fontWeight": "600"},
        ))
    return html.Div(btns, style={"marginTop": "24px"})


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

def layout() -> html.Div:
    return html.Div(id="to-wizard-page", children=[
        # Stores
        dcc.Store(id="to-step",    data=1),
        dcc.Store(id="to-meta",    data={}),
        dcc.Store(id="to-checks",  data={}),

        # Hidden persistent buttons (bridge pattern)
        html.Div([
            dbc.Button(id="to-next-1", style={"display": "none"}),
            dbc.Button(id="to-next-2", style={"display": "none"}),
            dbc.Button(id="to-back-2", style={"display": "none"}),
            dbc.Button(id="to-back-3", style={"display": "none"}),
            dbc.Button(id="to-execute-btn", style={"display": "none"}),
        ]),

        # Alert region
        html.Div(id="to-alert"),

        # Execution modal
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle("Registration Results"),
                close_button=True,
                style={"backgroundColor": CARD_BG, "color": TEXT_HEADING,
                       "borderBottom": f"1px solid {BORDER_COLOR}"},
            ),
            dbc.ModalBody(id="to-exec-body",
                          style={"backgroundColor": CARD_BG,
                                 "color": TEXT_PRIMARY}),
            dbc.ModalFooter(
                dbc.Button("Close", id="to-close-modal", color="light",
                           style={"color": TEXT_PRIMARY}),
                style={"backgroundColor": CARD_BG,
                       "borderTop": f"1px solid {BORDER_COLOR}"},
            ),
        ], id="to-exec-modal", is_open=False, centered=True, size="lg"),

        # Main content
        html.Div([
            html.H3("\U0001f50d Transformation Review Wizard",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "8px"}),
            html.P("Register a notebook transformation for automated SQL/code review.",
                   style={**MUTED_STYLE, "marginBottom": "32px"}),
            dcc.Loading(
                id="to-step-loading",
                type="circle",
                color=STEP_ACTIVE,
                overlay_style={"visibility": "visible", "opacity": 0.4,
                               "filter": "blur(1px)"},
                children=[
                    html.Div(id="to-progress-bar"),
                    html.Div(id="to-step-content"),
                ],
            ),
        ], style={**WIZARD_WIDTH, "padding": "32px 16px"}),
    ], style={"backgroundColor": PAGE_BG, "minHeight": "100vh"})


# ══════════════════════════════════════════════════════════════════════════════
# STEP BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

# ── Step 1 — Target & Source ──────────────────────────────────────────────────

def build_step1(meta: dict) -> html.Div:
    return html.Div([
        html.Div([
            html.H4("Step 1 \u2014 Target & Source",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P("Identify the transformation target, source, and notebook.",
                   style=MUTED_STYLE),
        ], style={"marginBottom": "24px"}),

        html.Div([
            # Target table dropdown
            dbc.Row([
                dbc.Col([
                    html.Label("Target Table", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id="to-target-table",
                        options=[],
                        value=meta.get("target_fqn"),
                        placeholder="Select a SILVER or GOLD table...",
                        className="ob-dropdown",
                    ),
                    html.Small(
                        "Tables from the layer registry (SILVER / GOLD).",
                        style=MUTED_STYLE,
                    ),
                ], md=12),
            ], className="mb-3"),

            # Auto-filled target layer + source table
            dbc.Row([
                dbc.Col([
                    html.Label("Target Layer", style=LABEL_STYLE),
                    dbc.Input(
                        id="to-target-layer", type="text",
                        value=meta.get("target_layer", ""),
                        disabled=True, style=_input_style(),
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Source Table", style=LABEL_STYLE),
                    dbc.Input(
                        id="to-source-table", type="text",
                        value=meta.get("source_fqn", ""),
                        disabled=True, style=_input_style(),
                    ),
                    html.Small(
                        "Auto-detected upstream layer table.",
                        style=MUTED_STYLE,
                    ),
                ], md=8),
            ], className="mb-3"),

            html.Hr(style={"borderColor": BORDER_COLOR}),

            # Notebook path
            dbc.Row([
                dbc.Col([
                    html.Label("Notebook Path", style=LABEL_STYLE),
                    dbc.Input(
                        id="to-notebook-path", type="text",
                        placeholder="/Users/you@example.com/transform_notebook",
                        value=meta.get("notebook_path", ""),
                        style=_input_style(),
                    ),
                    html.Small(
                        "Full workspace path to the transformation notebook.",
                        style=MUTED_STYLE,
                    ),
                ], md=12),
            ], className="mb-3"),

            # Language + Function name
            dbc.Row([
                dbc.Col([
                    html.Label("Notebook Language", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id="to-notebook-lang",
                        options=LANGUAGE_OPTIONS,
                        value=meta.get("notebook_language", "PYTHON"),
                        clearable=False,
                        className="ob-dropdown",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Function Name", style=LABEL_STYLE),
                    dbc.Input(
                        id="to-function-name", type="text",
                        placeholder="transform_raw_to_silver",
                        value=meta.get("function_name", ""),
                        style=_input_style(),
                    ),
                    html.Small(
                        "Main entry-point function in the notebook.",
                        style=MUTED_STYLE,
                    ),
                ], md=8),
            ], className="mb-3"),

            # Description
            dbc.Row([
                dbc.Col([
                    html.Label("Transformation Description", style=LABEL_STYLE),
                    dbc.Textarea(
                        id="to-description",
                        placeholder="Describe what this transformation does...",
                        value=meta.get("description", ""),
                        style={**_input_style(), "height": "80px"},
                    ),
                ], md=12),
            ], className="mb-3"),

            # Expected survival rate
            dbc.Row([
                dbc.Col([
                    html.Label("Expected Survival Rate (%)", style=LABEL_STYLE),
                    dbc.Input(
                        id="to-survival-rate", type="number",
                        min=0, max=100, step=1,
                        value=meta.get("expected_survival_rate", 92),
                        style=_input_style(),
                    ),
                    html.Small(
                        "Percentage of rows expected to survive the transformation.",
                        style=MUTED_STYLE,
                    ),
                ], md=4),
            ], className="mb-3"),
        ], style=CARD_STYLE),

        _nav_buttons(step=1, show_back=False),
    ])


# ── Step 2 — Review Checks ────────────────────────────────────────────────────

def build_step2(meta: dict, checks_prefill: dict) -> html.Div:
    p = checks_prefill or {}

    check_rows = []
    for chk in CHECK_TYPES:
        chk_pre = p.get(chk["id"], {})
        enabled = chk_pre.get("enabled", chk["default_on"])

        check_rows.append(
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id={"type": "to-check-enabled",
                            "index": chk["id"]},
                        value=enabled,
                        label=chk["label"],
                        style={"color": TEXT_PRIMARY},
                    ),
                    html.Small(chk["description"], style=MUTED_STYLE),
                ], md=12),
            ], className="mb-3",
               style={"padding": "12px",
                      "borderBottom": f"1px solid {BORDER_COLOR}"})
        )

    target_short = meta.get("target_fqn", "?").split(".")[-1]
    return html.Div([
        html.Div([
            html.H4("Step 2 \u2014 Review Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                f"Select which automated code review checks to enable "
                f"for {target_short}.",
                style=MUTED_STYLE,
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            html.H6("\U0001f50d Code Review Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            *check_rows,
        ], style=CARD_STYLE),

        _nav_buttons(step=2, show_back=True),
    ])


# ── Step 3 — Review & Confirm ─────────────────────────────────────────────────

def build_step3(meta: dict, checks: dict) -> html.Div:

    def srow(label, value, color=TEXT_PRIMARY):
        return dbc.Row([
            dbc.Col(html.Small(label,
                               style={**MUTED_STYLE, "fontWeight": "600"}),
                    md=4),
            dbc.Col(html.Span(value,
                              style={"color": color, "fontWeight": "600",
                                     "fontSize": "14px"}), md=8),
        ], className="mb-2")

    enabled_checks = [k for k, v in checks.items() if v.get("enabled")]

    # Check detail rows
    check_rows = []
    for k, v in checks.items():
        if not v.get("enabled"):
            continue
        label_map = {c["id"]: c["label"] for c in CHECK_TYPES}
        check_rows.append(
            dbc.Row([
                dbc.Col(html.Small(
                    label_map.get(k, k),
                    style={"color": TEXT_PRIMARY, "fontWeight": "600"}), md=8),
                dbc.Col(
                    dbc.Badge("Enabled", color="success",
                              style={"fontSize": "11px"}), md=4),
            ], className="mb-1")
        )

    return html.Div([
        html.Div([
            html.H4("Step 3 \u2014 Review & Confirm",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P("Review the configuration before registering.",
                   style=MUTED_STYLE),
        ], style={"marginBottom": "24px"}),

        # Transformation summary
        html.Div([
            html.H6("\U0001f4cb Transformation Details",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Target", meta.get("target_fqn", "\u2014")),
            srow("Target Layer", meta.get("target_layer", "\u2014")),
            srow("Source", meta.get("source_fqn", "\u2014")),
            srow("Notebook", meta.get("notebook_path", "\u2014")),
            srow("Language", meta.get("notebook_language", "\u2014")),
            srow("Function", meta.get("function_name", "\u2014")),
            srow("Survival Rate",
                 str(meta.get('expected_survival_rate', '—')) + "%"),
            srow("Description", meta.get("description", "\u2014")),
        ], style={**CARD_STYLE, "marginBottom": "16px"}),

        # Checks summary
        html.Div([
            html.H6("\U0001f50d Enabled Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            html.Div([
                html.Small([
                    "Total: ",
                    html.Span(
                        f"{len(enabled_checks)}/{len(CHECK_TYPES)}",
                        style={"color": STEP_COMPLETE if enabled_checks
                               else TEXT_MUTED, "fontWeight": "700"}),
                ], style={**MUTED_STYLE, "fontWeight": "600",
                          "marginBottom": "10px", "display": "block"}),
            ]),
            *check_rows,
        ], style={**CARD_STYLE, "marginBottom": "24px"}),

        # Buttons
        html.Div([
            dbc.Button(
                "\u2190 Back", id="to-back-3-visible",
                color="light", outline=True,
                style={"color": TEXT_PRIMARY, "borderColor": BORDER_COLOR,
                       "marginRight": "12px"},
            ),
            dbc.Button(
                "\U0001f680 Register Transformation", id="to-execute-btn-visible",
                color="primary", size="lg",
                style={"fontWeight": "700", "padding": "10px 32px"},
            ),
        ]),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

# ── Render step ───────────────────────────────────────────────────────────────

@callback(
    Output("to-step-content",  "children"),
    Output("to-progress-bar",  "children"),
    Input("to-step",           "data"),
    State("to-meta",           "data"),
    State("to-checks",         "data"),
)
def render_step(step, meta, checks):
    bar = build_progress_bar(step)
    if step == 1:
        return build_step1(meta or {}), bar
    elif step == 2:
        return build_step2(meta or {}, checks or {}), bar
    elif step == 3:
        return build_step3(meta or {}, checks or {}), bar
    return html.Div("Unknown step"), bar


# ── Load target table options ─────────────────────────────────────────────────

@callback(
    Output("to-target-table", "options"),
    Input("to-target-table",  "id"),
)
def load_target_tables(_):
    """Populate dropdown with SILVER and GOLD tables from layer registry."""
    try:
        df = execute_query(f"""
            SELECT DISTINCT
                layer_fully_qualified_name,
                layer_name
            FROM {PREFIX}uc2_layer_registry_b
            WHERE layer_name IN ('SILVER', 'GOLD')
              AND is_active = true
            ORDER BY layer_name, layer_fully_qualified_name
        """)
        if df.empty:
            return []
        fqn_col = _find_col(df, ["layer_fully_qualified_name"], 0)
        lyr_col = _find_col(df, ["layer_name"], 1)
        return [
            {"label": f"[{row[lyr_col]}] {row[fqn_col]}",
             "value": f"{row[fqn_col]}||{row[lyr_col]}"}
            for _, row in df.iterrows()
        ]
    except Exception as e:
        logger.error(f"load_target_tables: {e}")
        return []


# ── Auto-fill layer + source when target selected ─────────────────────────────

@callback(
    Output("to-target-layer", "value"),
    Output("to-source-table", "value"),
    Input("to-target-table",  "value"),
)
def autofill_source(target_val):
    if not target_val:
        return "", ""
    parts = target_val.split("||")
    if len(parts) != 2:
        return "", ""
    target_fqn, target_layer = parts
    try:
        df = execute_query(
            f"""
            SELECT source_fully_qualified_name
            FROM {PREFIX}uc2_layer_registry_b
            WHERE layer_fully_qualified_name = :target_fqn
              AND layer_name = :target_layer
            LIMIT 1
        """,
            {"target_fqn": target_fqn, "target_layer": target_layer},
        )
        if df.empty:
            return target_layer, ""
        src_col = _find_col(df, ["source_fully_qualified_name"], 0)
        source_fqn = df.iloc[0][src_col]

        # Find the immediate upstream layer table
        layer_order = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
        current_order = layer_order.get(target_layer, 0)
        upstream_layer = (
            [k for k, v in layer_order.items() if v == current_order - 1]
            or ["BRONZE"]
        )[0]

        df2 = execute_query(
            f"""
            SELECT layer_fully_qualified_name
            FROM {PREFIX}uc2_layer_registry_b
            WHERE source_fully_qualified_name = :source_fqn
              AND layer_name = :upstream_layer
              AND is_active = true
            LIMIT 1
        """,
            {"source_fqn": source_fqn, "upstream_layer": upstream_layer},
        )
        if not df2.empty:
            upstream_col = _find_col(df2,
                                    ["layer_fully_qualified_name"], 0)
            return target_layer, df2.iloc[0][upstream_col]
        return target_layer, source_fqn
    except Exception as e:
        logger.error(f"autofill_source: {e}")
        return target_val.split("||")[1] if "||" in target_val else "", ""


# ── Bridge callbacks (visible → hidden) ───────────────────────────────────────

for _step in [1, 2]:
    callback(
        Output(f"to-next-{_step}", "n_clicks"),
        Input(f"to-next-{_step}-visible", "n_clicks"),
        prevent_initial_call=True,
    )(lambda n: n)

for _step in [2, 3]:
    callback(
        Output(f"to-back-{_step}", "n_clicks"),
        Input(f"to-back-{_step}-visible", "n_clicks"),
        prevent_initial_call=True,
    )(lambda n: n)

callback(
    Output("to-execute-btn", "n_clicks"),
    Input("to-execute-btn-visible", "n_clicks"),
    prevent_initial_call=True,
)(lambda n: n)


# ── Next 1 → 2 ────────────────────────────────────────────────────────────────

@callback(
    Output("to-step",    "data",     allow_duplicate=True),
    Output("to-meta",    "data",     allow_duplicate=True),
    Output("to-alert",   "children", allow_duplicate=True),
    Input("to-next-1",   "n_clicks"),
    State("to-target-table",  "value"),
    State("to-target-layer",  "value"),
    State("to-source-table",  "value"),
    State("to-notebook-path", "value"),
    State("to-notebook-lang", "value"),
    State("to-function-name", "value"),
    State("to-description",   "value"),
    State("to-survival-rate", "value"),
    prevent_initial_call=True,
)
def next_step1(n, target_val, target_layer, source_fqn,
               notebook_path, notebook_lang, function_name,
               description, survival_rate):
    if not n:
        raise dash.exceptions.PreventUpdate

    # Validation
    if not target_val:
        return (dash.no_update, dash.no_update,
                error_alert("Please select a target table."))
    if not notebook_path or not notebook_path.strip():
        return (dash.no_update, dash.no_update,
                error_alert("Please enter the notebook path."))
    if not function_name or not function_name.strip():
        return (dash.no_update, dash.no_update,
                error_alert("Please enter the function name."))

    target_fqn = target_val.split("||")[0] if "||" in target_val else target_val

    meta = {
        "target_fqn"             : target_fqn,
        "target_layer"           : target_layer or "",
        "source_fqn"             : source_fqn or "",
        "notebook_path"          : notebook_path.strip(),
        "notebook_language"      : notebook_lang or "PYTHON",
        "function_name"          : function_name.strip(),
        "description"            : (description or "").strip(),
        "expected_survival_rate" : survival_rate or 92,
    }
    return 2, meta, html.Div()


# ── Next 2 → 3 ────────────────────────────────────────────────────────────────

@callback(
    Output("to-step",    "data",     allow_duplicate=True),
    Output("to-checks",  "data",     allow_duplicate=True),
    Output("to-alert",   "children", allow_duplicate=True),
    Input("to-next-2",   "n_clicks"),
    State({"type": "to-check-enabled", "index": dash.ALL}, "value"),
    State({"type": "to-check-enabled", "index": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def next_step2(n, enabled_vals, enabled_ids):
    if not n:
        raise dash.exceptions.PreventUpdate

    checks = {}
    for val, id_dict in zip(enabled_vals, enabled_ids):
        chk_id = id_dict["index"]
        checks[chk_id] = {"enabled": bool(val)}

    any_enabled = any(v["enabled"] for v in checks.values())
    if not any_enabled:
        return (dash.no_update, dash.no_update,
                warning_alert("Please enable at least one check."))

    return 3, checks, html.Div()


# ── Back 2 → 1 ────────────────────────────────────────────────────────────────

@callback(
    Output("to-step",  "data", allow_duplicate=True),
    Output("to-alert", "children", allow_duplicate=True),
    Input("to-back-2", "n_clicks"),
    prevent_initial_call=True,
)
def back_step2(n):
    if not n:
        raise dash.exceptions.PreventUpdate
    return 1, html.Div()


# ── Back 3 → 2 ────────────────────────────────────────────────────────────────

@callback(
    Output("to-step",  "data", allow_duplicate=True),
    Output("to-alert", "children", allow_duplicate=True),
    Input("to-back-3", "n_clicks"),
    prevent_initial_call=True,
)
def back_step3(n):
    if not n:
        raise dash.exceptions.PreventUpdate
    return 2, html.Div()


# ── Execute — Register Transformation ─────────────────────────────────────────

@callback(
    Output("to-exec-modal", "is_open"),
    Output("to-exec-body",  "children"),
    Input("to-execute-btn", "n_clicks"),
    State("to-meta",        "data"),
    State("to-checks",      "data"),
    prevent_initial_call=True,
)
def execute_onboarding(n, meta, checks):
    if not n:
        raise dash.exceptions.PreventUpdate

    steps = []
    all_ok = True

    # Build checks_enabled JSON
    enabled_list = [k for k, v in checks.items() if v.get("enabled")]
    checks_json = json.dumps(enabled_list)

    # Generate transformation ID
    transformation_id = str(uuid.uuid4())

    # Insert into uc3_transformation_registry_b
    try:
        execute_write(
            f"""
            INSERT INTO {PREFIX}uc3_transformation_registry_b (
                transformation_id,
                target_fully_qualified_name,
                target_layer,
                notebook_path,
                notebook_language,
                function_name,
                source_fully_qualified_name,
                transformation_description,
                checks_enabled,
                expected_survival_rate,
                is_active,
                registered_timestamp,
                registered_by
            ) VALUES (
                :transformation_id,
                :target_fqn,
                :target_layer,
                :notebook_path,
                :notebook_language,
                :function_name,
                :source_fqn,
                :transformation_description,
                :checks_enabled,
                :expected_survival_rate,
                true,
                current_timestamp(),
                'transformation_wizard'
            )
        """,
            {
                "transformation_id": transformation_id,
                "target_fqn": meta.get("target_fqn", ""),
                "target_layer": meta.get("target_layer", ""),
                "notebook_path": meta.get("notebook_path", ""),
                "notebook_language": meta.get("notebook_language", "PYTHON"),
                "function_name": meta.get("function_name", ""),
                "source_fqn": meta.get("source_fqn", ""),
                "transformation_description": meta.get("description", "") or "",
                "checks_enabled": checks_json,
                "expected_survival_rate": float(meta.get("expected_survival_rate", 92)) / 100.0,
            },
        )
        steps.append({
            "label" : "Transformation registered",
            "state" : "done",
            "detail": f"ID: {transformation_id[:12]}...",
        })
    except Exception as e:
        all_ok = False
        steps.append({
            "label" : "Transformation registration failed",
            "state" : "error",
            "detail": str(e)[:100],
        })

    # Build modal body
    rows = []
    for s in steps:
        icon = "\u2705" if s["state"] == "done" else "\u274c"
        rows.append(dbc.Row([
            dbc.Col(html.Span(icon, style={"fontSize": "18px"}), width="auto"),
            dbc.Col([
                html.Div(s["label"],
                         style={"fontWeight": "600", "color": TEXT_PRIMARY}),
                html.Small(s["detail"], style=MUTED_STYLE),
            ]),
        ], className="mb-3"))

    summary_color = STEP_COMPLETE if all_ok else "#ff6b6b"
    summary_text  = (
        "Transformation registered successfully!"
        if all_ok
        else "Registration completed with errors."
    )
    rows.append(html.Hr(style={"borderColor": BORDER_COLOR}))
    rows.append(html.Div(
        summary_text,
        style={"color": summary_color, "fontWeight": "700",
               "fontSize": "15px", "textAlign": "center"},
    ))

    return True, html.Div(rows)


# ── Close modal ───────────────────────────────────────────────────────────────

@callback(
    Output("to-exec-modal", "is_open", allow_duplicate=True),
    Input("to-close-modal", "n_clicks"),
    prevent_initial_call=True,
)
def close_modal(n):
    return False
