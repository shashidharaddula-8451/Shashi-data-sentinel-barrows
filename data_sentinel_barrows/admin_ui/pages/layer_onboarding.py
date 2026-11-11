# pages/layer_onboarding.py
# Agent 2 — Layer Reconciliation Onboarding Wizard

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, ctx, MATCH
import dash_bootstrap_components as dbc
from db.connection import execute_query, execute_write, validate_identifier, get_connection
from config.settings import TARGET_CATALOG, TARGET_SCHEMA, THRESHOLD_UNITS
from components.alerts import error_alert, warning_alert
from datetime import date, timedelta
import logging
import uuid
import json

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path="/layer-onboarding",
    name="Layer Onboarding",
)

# ── Theme constants (dark — matches Agent 1 wizard) ──────────────────────────

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
    {"num": 1, "label": "Source & Layers"},
    {"num": 2, "label": "Recon Checks"},
    {"num": 3, "label": "Review & Confirm"},
]

LAYER_NAMES = ["BRONZE", "SILVER", "GOLD"]

CHECK_TYPES = [
    {
        "id"         : "ROW_COUNT",
        "label"      : "Row Count Survival",
        "description": "Verifies row count survival rate between layers",
        "default_on" : True,
        "warn"       : 5,
        "crit"       : 10,
        "unit"       : "PERCENTAGE",
    },
    {
        "id"         : "AGGREGATE",
        "label"      : "Aggregate Reconciliation",
        "description": "SUM comparison of numeric columns across layers",
        "default_on" : True,
        "warn"       : 2,
        "crit"       : 5,
        "unit"       : "PERCENTAGE",
    },
    {
        "id"         : "FRESHNESS",
        "label"      : "Data Freshness",
        "description": "Checks data presence and latency between layers",
        "default_on" : True,
        "warn"       : 30,
        "crit"       : 60,
        "unit"       : "MINUTES",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_col(df, candidates, fallback_idx=0):
    cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    return df.columns[fallback_idx]


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
            circle = html.Div("✓", style=circle_style)
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
            line_color = (
                STEP_COMPLETE if num < current_step else "#373A40"
            )
            steps.append(html.Div(style={
                "flex": "1", "height": "2px", "backgroundColor": line_color,
                "alignSelf": "center", "margin": "0 8px", "marginBottom": "20px",
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
            "← Back", id=f"lo-back-{step}-visible",
            color="light", outline=True,
            style={"color": TEXT_PRIMARY, "borderColor": BORDER_COLOR,
                   "marginRight": "12px"},
        ))
    if step < len(STEPS):
        btns.append(dbc.Button(
            "Next →", id=f"lo-next-{step}-visible",
            color="primary", style={"fontWeight": "600"},
        ))
    return html.Div(btns, style={"marginTop": "24px"})


# ── Layout (function — dynamic) ───────────────────────────────────────────────

def layout() -> html.Div:
    return html.Div(id="lo-wizard-page", children=[
        # Stores
        dcc.Store(id="lo-step",          data=1),
        dcc.Store(id="lo-source-meta",   data={}),
        dcc.Store(id="lo-layers",        data=[]),
        dcc.Store(id="lo-checks",        data={}),
        dcc.Store(id="lo-render-trigger", data=0),

        # Hidden persistent buttons (bridge pattern)
        html.Div([
            dbc.Button(id="lo-next-1", style={"display": "none"}),
            dbc.Button(id="lo-next-2", style={"display": "none"}),
            dbc.Button(id="lo-back-2", style={"display": "none"}),
            dbc.Button(id="lo-back-3", style={"display": "none"}),
            dbc.Button(id="lo-execute-btn", style={"display": "none"}),
        ]),

        # Execution modal
        dbc.Modal([
            dbc.ModalHeader("Layer Onboarding"),
            dbc.ModalBody(id="lo-exec-body"),
            dbc.ModalFooter(
                dbc.Button("Close", id="lo-exec-close", color="secondary")
            ),
        ], id="lo-exec-modal", size="lg", is_open=False,
           backdrop="static", className="ob-exec-modal-content"),

        # Visible content
        html.Div([
            html.Div([
                html.H2("🔗 Layer Reconciliation Wizard",
                        style={"color": TEXT_HEADING, "fontWeight": "700",
                               "marginBottom": "8px"}),
                html.P("Register downstream layers and configure "
                       "reconciliation checks between them.",
                       style={**MUTED_STYLE, "fontSize": "14px"}),
            ], style={"textAlign": "center", "padding": "32px 0 24px"}),

            html.Div(id="lo-progress-bar"),
            html.Div(id="lo-alert", className="mb-3"),

            dcc.Loading(
                id="lo-step-loading",
                type="circle",
                color=STEP_ACTIVE,
                overlay_style={
                    "visibility": "visible",
                    "opacity"   : 0.4,
                    "filter"    : "blur(1px)",
                },
                children=html.Div(id="lo-step-content"),
            ),
        ], style={**WIZARD_WIDTH, "padding": "0 16px 60px"}),

    ], style={"backgroundColor": PAGE_BG, "minHeight": "100vh"})


# ── Step 1 — Source Table & Layer Chain ───────────────────────────────────────

def build_step1(prefill: dict = None, layers: list = None) -> html.Div:
    p = prefill or {}
    layers = layers or []

    # Build layer rows
    layer_rows = []
    if not layers:
        layers = [{"layer_name": "SILVER", "catalog": "", "schema": "",
                   "table": "", "survival_rate": 92, "latency": 120}]

    for idx, lyr in enumerate(layers):
        layer_rows.append(_build_layer_row(idx, lyr))

    return html.Div([
        html.Div([
            html.H4("Step 1 — Source Table & Layer Chain",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P("Select the source table (already onboarded) and "
                   "define downstream layers.",
                   style=MUTED_STYLE),
        ], style={"marginBottom": "24px"}),

        # Source table selection
        html.Div([
            html.H6("📋 Source Table",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            dbc.Row([
                dbc.Col([
                    html.Label("Registered Table", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id="lo-source-table",
                        options=_seed_options(p.get("source_fqn")),
                        placeholder="Loading registered tables…",
                        value=p.get("source_fqn"),
                        clearable=False,
                        className="ob-dropdown",
                    ),
                    html.Small(
                        "Only tables onboarded via Validation Agent are available.",
                        style=MUTED_STYLE,
                    ),
                ], md=12),
            ], className="mb-3"),
        ], style=CARD_STYLE),

        html.Hr(style={"borderColor": BORDER_COLOR, "margin": "24px 0"}),

        # Layer chain
        html.Div([
            html.Div([
                html.H6("🔗 Downstream Layers",
                        style={"color": TEXT_HEADING, "fontWeight": "700"}),
                dbc.Button(
                    "+ Add Layer", id="lo-add-layer-btn",
                    color="info", size="sm", outline=True,
                    style={"fontSize": "12px"},
                ),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "16px"}),

            html.Div(id="lo-layer-rows", children=layer_rows),
        ], style=CARD_STYLE),

        _nav_buttons(step=1, show_back=False),
    ])


def _seed_options(val):
    """Return a single-item options list if val is set, else empty.
    This ensures the dropdown value always has a matching option on
    first render; the MATCH callback will replace with the full list."""
    if val:
        return [{"label": val, "value": val}]
    return []


def _build_layer_row(idx, lyr=None):
    lyr = lyr or {}
    cat_val = lyr.get("catalog", "") or None
    sch_val = lyr.get("schema", "") or None
    tbl_val = lyr.get("table", "") or None
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Layer", style=LABEL_STYLE),
                dcc.Dropdown(
                    id={"type": "lo-layer-name", "index": idx},
                    options=[{"label": n, "value": n} for n in LAYER_NAMES],
                    value=lyr.get("layer_name", "SILVER"),
                    clearable=False,
                    className="ob-dropdown",
                ),
            ], md=2),
            dbc.Col([
                html.Label("Target Catalog", style=LABEL_STYLE),
                dcc.Dropdown(
                    id={"type": "lo-layer-catalog", "index": idx},
                    options=_seed_options(cat_val),
                    placeholder="Catalog…",
                    value=cat_val,
                    className="ob-dropdown",
                ),
            ], md=2),
            dbc.Col([
                html.Label("Schema", style=LABEL_STYLE),
                dcc.Dropdown(
                    id={"type": "lo-layer-schema", "index": idx},
                    options=_seed_options(sch_val),
                    placeholder="Schema…",
                    value=sch_val,
                    className="ob-dropdown",
                ),
            ], md=2),
            dbc.Col([
                html.Label("Table", style=LABEL_STYLE),
                dcc.Dropdown(
                    id={"type": "lo-layer-table", "index": idx},
                    options=_seed_options(tbl_val),
                    placeholder="Table…",
                    value=tbl_val,
                    className="ob-dropdown",
                ),
            ], md=2),
            dbc.Col([
                html.Label("Survival %", style=LABEL_STYLE),
                dbc.Input(
                    id={"type": "lo-layer-survival", "index": idx},
                    type="number", min=0, max=100,
                    value=lyr.get("survival_rate", 92),
                    style={"backgroundColor": "#2C2E33",
                           "color": TEXT_PRIMARY,
                           "border": f"1px solid {BORDER_COLOR}",
                           "fontSize": "13px"},
                ),
            ], md=1),
            dbc.Col([
                html.Label("Latency (min)", style=LABEL_STYLE),
                dbc.Input(
                    id={"type": "lo-layer-latency", "index": idx},
                    type="number", min=0,
                    value=lyr.get("latency", 120),
                    style={"backgroundColor": "#2C2E33",
                           "color": TEXT_PRIMARY,
                           "border": f"1px solid {BORDER_COLOR}",
                           "fontSize": "13px"},
                ),
            ], md=1),
            dbc.Col([
                html.Label(" ", style=LABEL_STYLE),
                dbc.Button(
                    "✕", id={"type": "lo-remove-layer", "index": idx},
                    color="danger", size="sm", outline=True,
                    style={"width": "100%"},
                ),
            ], md=1),
        ], className="mb-2 align-items-end g-2"),
    ], style={"padding": "12px", "borderBottom": f"1px solid {BORDER_COLOR}",
             "backgroundColor": CARD_BG})


# ── Step 2 — Reconciliation Checks ────────────────────────────────────────────

def _get_numeric_columns(fqn: str) -> list:
    """Return numeric column options for a given table FQN."""
    try:
        logger.info(f"_get_numeric_columns: DESCRIBE TABLE {fqn}")
        validate_identifier(fqn)
        df = execute_query(f"DESCRIBE TABLE {fqn}")
        if df is None or df.empty:
            logger.warning(f"_get_numeric_columns: empty result for {fqn}")
            return []
        NUMERIC = {"INT", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL",
                   "SMALLINT", "TINYINT", "LONG"}
        options = []
        for _, row in df.iterrows():
            cname = str(row.iloc[0]).strip()
            dtype = str(row.iloc[1]).strip().upper().split("(")[0]
            if cname and not cname.startswith("#") and dtype in NUMERIC:
                options.append({"label": f"{cname} ({dtype})",
                                "value": cname})
        logger.info(f"_get_numeric_columns: {fqn} -> {len(options)} numeric cols")
        return options
    except Exception as e:
        logger.error(f"_get_numeric_columns({fqn}): {e}")
        return []


def build_step2(layers: list, checks_prefill: dict = None) -> html.Div:
    p = checks_prefill or {}

    if not layers:
        return html.Div([
            warning_alert("No layers defined. Go back to Step 1."),
            _nav_buttons(step=2, show_back=True),
        ])

    # Pre-fetch numeric columns for each target table
    _numeric_cache = {}
    logger.info(f"build_step2: {len(layers)} layers, prefetching numeric cols")
    for lyr in layers:
        fqn = lyr.get("fqn", "")
        logger.info(f"build_step2: layer={lyr.get('layer_name')} fqn={fqn}")
        if fqn and fqn not in _numeric_cache:
            _numeric_cache[fqn] = _get_numeric_columns(fqn)
    logger.info("build_step2: cache=%s",
                 {k: len(v) for k, v in _numeric_cache.items()})

    transition_cards = []
    for idx, lyr in enumerate(layers):
        from_layer = "BRONZE" if idx == 0 else layers[idx - 1].get("layer_name", "?")
        to_layer   = lyr.get("layer_name", "?")
        trans_key  = f"{from_layer}_{to_layer}"
        trans_pre  = p.get(trans_key, {})

        check_rows = []
        for chk in CHECK_TYPES:
            chk_pre = trans_pre.get(chk["id"], {})
            enabled = chk_pre.get("enabled", chk["default_on"])
            warn    = chk_pre.get("warn", chk["warn"])
            crit    = chk_pre.get("crit", chk["crit"])

            check_rows.append(
                dbc.Row([
                    dbc.Col([
                        dbc.Switch(
                            id={"type": "lo-check-enabled",
                                "index": f"{trans_key}__{chk['id']}"},
                            value=enabled,
                            label=chk["label"],
                            style={"color": TEXT_PRIMARY},
                        ),
                        html.Small(chk["description"], style=MUTED_STYLE),
                    ], md=6),
                    dbc.Col([
                        html.Label("Warn", style={**LABEL_STYLE, "fontSize": "11px"}),
                        dbc.Input(
                            id={"type": "lo-check-warn",
                                "index": f"{trans_key}__{chk['id']}"},
                            type="number", min=0, value=warn,
                            disabled=not enabled,
                            style={"backgroundColor": "#2C2E33",
                                   "color": TEXT_PRIMARY,
                                   "border": f"1px solid {BORDER_COLOR}",
                                   "fontSize": "13px"},
                        ),
                    ], md=2),
                    dbc.Col([
                        html.Label("Crit", style={**LABEL_STYLE, "fontSize": "11px"}),
                        dbc.Input(
                            id={"type": "lo-check-crit",
                                "index": f"{trans_key}__{chk['id']}"},
                            type="number", min=0, value=crit,
                            disabled=not enabled,
                            style={"backgroundColor": "#2C2E33",
                                   "color": TEXT_PRIMARY,
                                   "border": f"1px solid {BORDER_COLOR}",
                                   "fontSize": "13px"},
                        ),
                    ], md=2),
                    dbc.Col([
                        html.Label("Unit", style={**LABEL_STYLE, "fontSize": "11px"}),
                        html.Div(
                            dbc.Badge(chk["unit"], color="secondary",
                                      style={"fontSize": "11px"}),
                            style={"paddingTop": "8px"},
                        ),
                    ], md=2),
                ], className="mb-3 align-items-end")
            )

            # AGGREGATE: add column picker
            if chk["id"] == "AGGREGATE":
                pre_cols = chk_pre.get("columns", [])
                target_fqn = lyr.get("fqn", "")
                agg_options = _numeric_cache.get(target_fqn, [])
                check_rows.append(
                    dbc.Row([
                        dbc.Col([
                            html.Label("Reconciliation Columns",
                                       style={**LABEL_STYLE, "fontSize": "11px"}),
                            dcc.Dropdown(
                                id={"type": "lo-agg-columns",
                                    "index": trans_key},
                                options=agg_options,
                                value=pre_cols,
                                multi=True,
                                placeholder="Select numeric columns…"
                                    if agg_options
                                    else "No numeric columns found",
                                disabled=not enabled,
                                className="ob-dropdown ob-multi",
                            ),
                            html.Small(
                                f"{len(agg_options)} numeric column(s) "
                                f"detected in {target_fqn.split('.')[-1]}."
                                if agg_options
                                else "No numeric columns found in target table.",
                                style=MUTED_STYLE,
                            ),
                        ], md=12),
                    ], className="mb-3")
                )

        target_fqn = lyr.get("fqn", "?")
        transition_cards.append(
            html.Div([
                html.Div([
                    dbc.Badge(from_layer, color="secondary",
                              className="me-2", style={"fontSize": "12px"}),
                    html.Span("→ ", style={"color": TEXT_MUTED,
                                           "fontSize": "16px"}),
                    dbc.Badge(to_layer, color="info",
                              className="ms-2", style={"fontSize": "12px"}),
                    html.Small(f"  ({target_fqn})",
                               style={**MUTED_STYLE, "marginLeft": "12px"}),
                ], style={"marginBottom": "16px"}),
                *check_rows,
            ], style={**CARD_STYLE, "marginBottom": "16px"})
        )

    return html.Div([
        html.Div([
            html.H4("Step 2 — Reconciliation Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P(
                f"{len(layers)} layer transition(s) to configure.",
                style=MUTED_STYLE,
            ),
        ], style={"marginBottom": "24px"}),
        *transition_cards,
        _nav_buttons(step=2, show_back=True),
    ])


# ── Step 3 — Review & Confirm ─────────────────────────────────────────────────

def build_step3(source_meta: dict, layers: list, checks: dict) -> html.Div:
    source_fqn = source_meta.get("source_fqn", "—")

    def srow(label, value, color=TEXT_PRIMARY):
        return dbc.Row([
            dbc.Col(html.Small(label,
                               style={**MUTED_STYLE, "fontWeight": "600"}),
                    md=4),
            dbc.Col(html.Span(value,
                              style={"color": color, "fontWeight": "600",
                                     "fontSize": "14px"}), md=8),
        ], className="mb-2")

    # Layer summary rows
    layer_rows = []
    for idx, lyr in enumerate(layers):
        from_layer = "BRONZE" if idx == 0 else layers[idx-1].get("layer_name", "?")
        to_layer   = lyr.get("layer_name", "?")
        trans_key  = f"{from_layer}_{to_layer}"
        trans_chks = checks.get(trans_key, {})
        enabled_chks = [k for k, v in trans_chks.items()
                        if v.get("enabled", False)]

        # Check data rows
        check_rows = []
        for k, v in trans_chks.items():
            if not v.get("enabled", False):
                continue
            label = k
            if k == "AGGREGATE":
                cols = v.get("columns", [])
                if cols:
                    label = f"AGGREGATE ({', '.join(cols)})"
            check_rows.append(
                dbc.Row([
                    dbc.Col(html.Small(
                        label, style={"color": TEXT_PRIMARY,
                                  "fontWeight": "600"}), md=5),
                    dbc.Col(html.Small(
                        f"{v.get('warn', '—')}",
                        style={"color": "#ffa500",
                               "fontWeight": "600"}), md=3),
                    dbc.Col(html.Small(
                        f"{v.get('crit', '—')}",
                        style={"color": "#ff6b6b",
                               "fontWeight": "600"}), md=3),
                ], className="mb-1")
            )

        # Per-section mini header
        section_header = dbc.Row([
            dbc.Col(html.Small("Check",
                style={**MUTED_STYLE, "fontWeight": "700"}), md=5),
            dbc.Col(html.Small("Warn",
                style={**MUTED_STYLE, "fontWeight": "700",
                       "color": "#ffa500"}), md=3),
            dbc.Col(html.Small("Crit",
                style={**MUTED_STYLE, "fontWeight": "700",
                       "color": "#ff6b6b"}), md=3),
        ], style={"borderBottom": f"1px solid {BORDER_COLOR}",
                  "paddingBottom": "4px", "marginBottom": "6px"})

        layer_rows.append(
            html.Div([
                # Transition badge row
                html.Div([
                    dbc.Badge(from_layer, color="secondary",
                              className="me-1"),
                    html.Span(" → ", style={"color": TEXT_MUTED}),
                    dbc.Badge(to_layer, color="info", className="ms-1"),
                    html.Small(
                        f"  {lyr.get('fqn', '?')}",
                        style={**MUTED_STYLE, "marginLeft": "8px"},
                    ),
                ], style={"marginBottom": "10px"}),
                # Stats row
                dbc.Row([
                    dbc.Col(html.Small(
                        f"Survival: {lyr.get('survival_rate', '—')}%",
                        style={**MUTED_STYLE, "fontWeight": "600"}), md=3),
                    dbc.Col(html.Small(
                        f"Latency: {lyr.get('latency', '—')} min",
                        style={**MUTED_STYLE, "fontWeight": "600"}), md=3),
                    dbc.Col(html.Small([
                        "Checks: ",
                        html.Span(
                            f"{len(enabled_chks)}",
                            style={"color": STEP_COMPLETE
                                   if enabled_chks else TEXT_MUTED,
                                   "fontWeight": "700"}),
                    ], style={**MUTED_STYLE, "fontWeight": "600"}), md=3),
                ], className="mb-3"),
                # Section header + check rows
                section_header,
                *check_rows,
            ], style={"padding": "12px", "marginBottom": "8px",
                      "borderBottom": f"1px solid {BORDER_COLOR}"})
        )

    return html.Div([
        html.Div([
            html.H4("Step 3 — Review & Confirm",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "4px"}),
            html.P("Review the configuration before registering.",
                   style=MUTED_STYLE),
        ], style={"marginBottom": "24px"}),

        # Source summary
        html.Div([
            html.H6("📋 Source Table",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Source", source_fqn),
            srow("Layers", f"{len(layers)}"),
        ], style={**CARD_STYLE, "marginBottom": "16px"}),

        # Layers + checks
        html.Div([
            html.H6("🔗 Layer Transitions & Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            *layer_rows,
        ], style={**CARD_STYLE, "marginBottom": "24px"}),

        # Buttons
        html.Div([
            dbc.Button(
                "← Back", id="lo-back-3-visible",
                color="light", outline=True,
                style={"color": TEXT_PRIMARY, "borderColor": BORDER_COLOR,
                       "marginRight": "12px"},
            ),
            dbc.Button(
                "🚀 Register Layers", id="lo-execute-btn-visible",
                color="primary", size="lg",
                style={"fontWeight": "700", "padding": "10px 32px"},
            ),
        ]),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

# ── Master renderer ───────────────────────────────────────────────────────────

def _collect_layers_from_form(names, ids, catalogs, schemas, tables,
                              survivals, latencies):
    """Gather current Step 1 form state into a layers list."""
    layers = []
    for i in range(len(ids)):
        layers.append({
            "layer_name"   : names[i] if i < len(names) else "SILVER",
            "catalog"      : (catalogs[i] if i < len(catalogs) else "") or "",
            "schema"       : (schemas[i]  if i < len(schemas)  else "") or "",
            "table"        : (tables[i]   if i < len(tables)   else "") or "",
            "fqn"          : ".".join(filter(None, [
                catalogs[i] if i < len(catalogs) else "",
                schemas[i]  if i < len(schemas)  else "",
                tables[i]   if i < len(tables)   else "",
            ])) or "",
            "survival_rate": survivals[i] if i < len(survivals) else 92,
            "latency"      : latencies[i] if i < len(latencies) else 120,
        })
    return layers


@callback(
    Output("lo-step-content",  "children"),
    Output("lo-progress-bar",  "children"),
    Input("lo-step",           "data"),
    Input("lo-render-trigger", "data"),
    State("lo-source-meta",    "data"),
    State("lo-layers",         "data"),
    State("lo-checks",         "data"),
)
def render_step(step, _trigger, source_meta, layers, checks):
    step = step or 1
    bar  = build_progress_bar(step)

    if step == 1:
        return build_step1(source_meta, layers), bar
    elif step == 2:
        return build_step2(layers, checks), bar
    elif step == 3:
        return build_step3(source_meta, layers, checks), bar
    return html.Div("Unknown step"), bar


# ── Add / Remove layer rows ───────────────────────────────────────────────────

@callback(
    Output("lo-layers",          "data", allow_duplicate=True),
    Output("lo-source-meta",     "data", allow_duplicate=True),
    Output("lo-render-trigger",  "data", allow_duplicate=True),
    Input("lo-add-layer-btn",                          "n_clicks"),
    State("lo-source-table",                           "value"),
    State("lo-render-trigger",                         "data"),
    State({"type": "lo-layer-name",     "index": ALL}, "value"),
    State({"type": "lo-layer-name",     "index": ALL}, "id"),
    State({"type": "lo-layer-catalog",  "index": ALL}, "value"),
    State({"type": "lo-layer-schema",   "index": ALL}, "value"),
    State({"type": "lo-layer-table",    "index": ALL}, "value"),
    State({"type": "lo-layer-survival", "index": ALL}, "value"),
    State({"type": "lo-layer-latency",  "index": ALL}, "value"),
    prevent_initial_call=True,
)
def add_layer(n, source_fqn, trigger, names, ids, catalogs, schemas,
              tables, survivals, latencies):
    if not n:
        raise dash.exceptions.PreventUpdate
    layers = _collect_layers_from_form(
        names, ids, catalogs, schemas, tables, survivals, latencies
    )
    # Pick next sensible default name
    used = {l["layer_name"] for l in layers}
    new_name = "GOLD"
    for candidate in LAYER_NAMES:
        if candidate not in used and candidate != "BRONZE":
            new_name = candidate
            break
    layers.append({
        "layer_name": new_name, "catalog": "", "schema": "",
        "table": "", "fqn": "", "survival_rate": 92, "latency": 60,
    })
    meta = {"source_fqn": source_fqn} if source_fqn else {}
    return layers, meta, (trigger or 0) + 1


@callback(
    Output("lo-layers",          "data", allow_duplicate=True),
    Output("lo-source-meta",     "data", allow_duplicate=True),
    Output("lo-render-trigger",  "data", allow_duplicate=True),
    Input({"type": "lo-remove-layer", "index": ALL},   "n_clicks"),
    State("lo-source-table",                           "value"),
    State("lo-render-trigger",                         "data"),
    State({"type": "lo-layer-name",     "index": ALL}, "value"),
    State({"type": "lo-layer-name",     "index": ALL}, "id"),
    State({"type": "lo-layer-catalog",  "index": ALL}, "value"),
    State({"type": "lo-layer-schema",   "index": ALL}, "value"),
    State({"type": "lo-layer-table",    "index": ALL}, "value"),
    State({"type": "lo-layer-survival", "index": ALL}, "value"),
    State({"type": "lo-layer-latency",  "index": ALL}, "value"),
    prevent_initial_call=True,
)
def remove_layer(clicks, source_fqn, trigger, names, ids, catalogs,
                 schemas, tables, survivals, latencies):
    if not clicks or not any(clicks):
        raise dash.exceptions.PreventUpdate
    layers = _collect_layers_from_form(
        names, ids, catalogs, schemas, tables, survivals, latencies
    )
    # Find which button was clicked
    triggered_id = ctx.triggered_id
    if isinstance(triggered_id, dict):
        rm_idx = triggered_id["index"]
        if 0 <= rm_idx < len(layers) and len(layers) > 1:
            layers.pop(rm_idx)
    meta = {"source_fqn": source_fqn} if source_fqn else {}
    return layers, meta, (trigger or 0) + 1


# ── Load registered tables (source dropdown) ──────────────────────────────────

@callback(
    Output("lo-source-table", "options"),
    Input("lo-source-table",  "id"),
)
def load_source_tables(_):
    try:
        df = execute_query(f"""
            SELECT fully_qualified_name
            FROM {PREFIX}uc1_table_registry_b
            WHERE is_active = true
            ORDER BY fully_qualified_name
        """)
        if df.empty:
            return []
        return [
            {"label": r, "value": r}
            for r in df["fully_qualified_name"].tolist()
        ]
    except Exception as e:
        logger.error(f"load_source_tables: {e}")
        return []


# ── Load catalogs for layer target ────────────────────────────────────────────

@callback(
    Output({"type": "lo-layer-catalog", "index": MATCH}, "options"),
    Input({"type": "lo-layer-catalog",  "index": MATCH}, "id"),
)
def load_layer_catalogs(_):
    try:
        df = execute_query("SHOW CATALOGS")
        if df.empty:
            return []
        col = _find_col(df, ["catalog", "catalogName", "namespace"])
        return [{"label": r, "value": r} for r in df[col].tolist()]
    except Exception as e:
        logger.error(f"load_layer_catalogs: {e}")
        return []


@callback(
    Output({"type": "lo-layer-schema", "index": MATCH}, "options"),
    Input({"type": "lo-layer-catalog",  "index": MATCH}, "value"),
    Input({"type": "lo-layer-schema",   "index": MATCH}, "id"),
)
def load_layer_schemas(catalog, _):
    if not catalog:
        return []
    try:
        validate_identifier(catalog)
        df = execute_query(f"SHOW SCHEMAS IN {catalog}")
        if df.empty:
            return []
        col = _find_col(df, ["databaseName", "namespace", "schema"])
        return [{"label": r, "value": r} for r in df[col].tolist()]
    except Exception as e:
        logger.error(f"load_layer_schemas: {e}")
        return []


@callback(
    Output({"type": "lo-layer-table", "index": MATCH}, "options"),
    Input({"type": "lo-layer-schema",  "index": MATCH}, "value"),
    Input({"type": "lo-layer-table",   "index": MATCH}, "id"),
    State({"type": "lo-layer-catalog", "index": MATCH}, "value"),
)
def load_layer_tables(schema, _, catalog):
    if not schema or not catalog:
        return []
    try:
        validate_identifier(catalog)
        validate_identifier(schema)
        df = execute_query(f"SHOW TABLES IN {catalog}.{schema}")
        if df.empty:
            return []
        col = _find_col(df, ["tableName", "table_name", "table"],
                        fallback_idx=1)
        return [{"label": r, "value": r} for r in df[col].tolist()]
    except Exception as e:
        logger.error(f"load_layer_tables: {e}")
        return []


# NOTE: Aggregate column options are now pre-populated inline in build_step2
# via _get_numeric_columns(). No async MATCH callback needed.


# ── Bridge callbacks (visible → hidden) ───────────────────────────────────────

for _step in [1, 2]:
    callback(
        Output(f"lo-next-{_step}", "n_clicks"),
        Input(f"lo-next-{_step}-visible", "n_clicks"),
        prevent_initial_call=True,
    )(lambda n: n)

for _step in [2, 3]:
    callback(
        Output(f"lo-back-{_step}", "n_clicks"),
        Input(f"lo-back-{_step}-visible", "n_clicks"),
        prevent_initial_call=True,
    )(lambda n: n)

callback(
    Output("lo-execute-btn", "n_clicks"),
    Input("lo-execute-btn-visible", "n_clicks"),
    prevent_initial_call=True,
)(lambda n: n)


# ── Next Step 1 → 2 ──────────────────────────────────────────────────────────

@callback(
    Output("lo-step",        "data",     allow_duplicate=True),
    Output("lo-source-meta", "data",     allow_duplicate=True),
    Output("lo-layers",      "data",     allow_duplicate=True),
    Output("lo-alert",       "children", allow_duplicate=True),
    Input("lo-next-1",       "n_clicks"),
    State("lo-source-table",             "value"),
    State({"type": "lo-layer-name",     "index": ALL}, "value"),
    State({"type": "lo-layer-name",     "index": ALL}, "id"),
    State({"type": "lo-layer-catalog",  "index": ALL}, "value"),
    State({"type": "lo-layer-schema",   "index": ALL}, "value"),
    State({"type": "lo-layer-table",    "index": ALL}, "value"),
    State({"type": "lo-layer-survival", "index": ALL}, "value"),
    State({"type": "lo-layer-latency",  "index": ALL}, "value"),
    prevent_initial_call=True,
)
def next_step1(n, source_fqn,
               names, ids, catalogs, schemas, tables,
               survivals, latencies):
    if not n:
        raise dash.exceptions.PreventUpdate

    if not source_fqn:
        return (dash.no_update, dash.no_update, dash.no_update,
                error_alert("Please select a source table."))

    source_meta = {"source_fqn": source_fqn}
    layers = []
    for i in range(len(ids)):
        cat = catalogs[i] if i < len(catalogs) else ""
        sch = schemas[i]  if i < len(schemas)  else ""
        tbl = tables[i]   if i < len(tables)   else ""
        if not all([cat, sch, tbl]):
            return (dash.no_update, dash.no_update, dash.no_update,
                    error_alert(
                        f"Layer {i+1}: please fill catalog, schema, and table."
                    ))
        layers.append({
            "layer_name"   : names[i] if i < len(names) else "SILVER",
            "catalog"      : cat,
            "schema"       : sch,
            "table"        : tbl,
            "fqn"          : f"{cat}.{sch}.{tbl}",
            "survival_rate": survivals[i] if i < len(survivals) else 92,
            "latency"      : latencies[i] if i < len(latencies) else 120,
        })

    return 2, source_meta, layers, html.Div()


# ── Back 2 → 1 ────────────────────────────────────────────────────────────────

@callback(
    Output("lo-step",  "data", allow_duplicate=True),
    Output("lo-alert", "children", allow_duplicate=True),
    Input("lo-back-2", "n_clicks"),
    prevent_initial_call=True,
)
def back_step2(n):
    if not n:
        raise dash.exceptions.PreventUpdate
    return 1, html.Div()


# ── Next Step 2 → 3 ──────────────────────────────────────────────────────────

@callback(
    Output("lo-step",   "data",     allow_duplicate=True),
    Output("lo-checks", "data",     allow_duplicate=True),
    Output("lo-alert",  "children", allow_duplicate=True),
    Input("lo-next-2",  "n_clicks"),
    State({"type": "lo-check-enabled", "index": ALL}, "value"),
    State({"type": "lo-check-enabled", "index": ALL}, "id"),
    State({"type": "lo-check-warn",    "index": ALL}, "value"),
    State({"type": "lo-check-crit",    "index": ALL}, "value"),
    State({"type": "lo-agg-columns",   "index": ALL}, "value"),
    State({"type": "lo-agg-columns",   "index": ALL}, "id"),
    State("lo-checks",                 "data"),
    prevent_initial_call=True,
)
def next_step2(n, en_vals, en_ids, warn_vals, crit_vals,
               agg_col_vals, agg_col_ids, existing_checks):
    if not n:
        raise dash.exceptions.PreventUpdate

    checks = {}
    for i, id_dict in enumerate(en_ids):
        key = id_dict["index"]          # e.g. "RAW_SILVER__ROW_COUNT"
        trans_key, chk_id = key.split("__")
        if trans_key not in checks:
            checks[trans_key] = {}
        checks[trans_key][chk_id] = {
            "enabled": en_vals[i] if i < len(en_vals) else False,
            "warn"   : warn_vals[i] if i < len(warn_vals) else 0,
            "crit"   : crit_vals[i] if i < len(crit_vals) else 0,
        }

    # Attach aggregate columns
    for i, id_dict in enumerate(agg_col_ids or []):
        trans_key = id_dict["index"]
        if trans_key in checks and "AGGREGATE" in checks[trans_key]:
            checks[trans_key]["AGGREGATE"]["columns"] = (
                agg_col_vals[i] if i < len(agg_col_vals) else []
            ) or []

    return 3, checks, html.Div()


# ── Back 3 → 2 ────────────────────────────────────────────────────────────────

@callback(
    Output("lo-step",  "data", allow_duplicate=True),
    Output("lo-alert", "children", allow_duplicate=True),
    Input("lo-back-3", "n_clicks"),
    prevent_initial_call=True,
)
def back_step3(n):
    if not n:
        raise dash.exceptions.PreventUpdate
    return 2, html.Div()


# ── Execute ───────────────────────────────────────────────────────────────────

@callback(
    Output("lo-exec-modal", "is_open"),
    Output("lo-exec-body",  "children"),
    Input("lo-execute-btn", "n_clicks"),
    State("lo-source-meta", "data"),
    State("lo-layers",      "data"),
    State("lo-checks",      "data"),
    background=True,
    prevent_initial_call=True,
)
def execute_onboarding(n, source_meta, layers, checks):
    if not n:
        raise dash.exceptions.PreventUpdate

    source_fqn = source_meta.get("source_fqn", "")
    steps = []
    all_ok = True

    # A single shared connection for the whole run: each step below used to
    # open its own SQL-warehouse session (~1s each), and many layers/checks
    # easily racked up dozens of those sequentially — enough to blow past
    # the Databricks Apps 120s reverse-proxy request timeout and leave the
    # review page's spinner hanging with no visible error.
    conn = get_connection()

    # ── Register layers ───────────────────────────────────────────────────
    # One multi-row INSERT for all layers (RAW + each configured layer)
    # instead of one INSERT per row — same rationale as onboarding.py's
    # column/check batching: cuts N warehouse round-trips (~1-1.5s each)
    # down to 1.
    layer_count = 0
    layer_err   = []
    layer_rows, layer_params = [], {"source_fqn": source_fqn}

    # RAW layer (source itself) — no reconciliation_metrics of its own
    layer_rows.append("""(
        :layer_id_0, :source_fqn, 'BRONZE',
        :layer_fqn_0, :layer_catalog_0, :layer_schema_0, :layer_table_0,
        1.0, 0, NULL, true, current_timestamp(), 'layer_wizard'
    )""")
    layer_params.update({
        "layer_id_0"      : str(uuid.uuid4()),
        "layer_fqn_0"     : source_fqn,
        "layer_catalog_0" : source_fqn.split(".")[0],
        "layer_schema_0"  : source_fqn.split(".")[1],
        "layer_table_0"   : source_fqn.split(".")[2],
    })

    for idx, lyr in enumerate(layers, start=1):
        fqn = lyr["fqn"]
        recon_metrics = json.dumps(
            checks.get(
                f"BRONZE_{lyr['layer_name']}", {}
            ).get("AGGREGATE", {}).get("columns", [])
        ) if lyr == layers[0] else json.dumps(
            checks.get(
                f"{layers[layers.index(lyr)-1]['layer_name']}_{lyr['layer_name']}",
                {}
            ).get("AGGREGATE", {}).get("columns", [])
        )
        layer_rows.append(f"""(
            :layer_id_{idx}, :source_fqn, :layer_name_{idx},
            :layer_fqn_{idx}, :layer_catalog_{idx}, :layer_schema_{idx},
            :layer_table_{idx}, :expected_survival_rate_{idx},
            :expected_latency_minutes_{idx}, :reconciliation_metrics_{idx},
            true, current_timestamp(), 'layer_wizard'
        )""")
        layer_params.update({
            f"layer_id_{idx}"                 : str(uuid.uuid4()),
            f"layer_name_{idx}"               : lyr["layer_name"],
            f"layer_fqn_{idx}"                : fqn,
            f"layer_catalog_{idx}"            : lyr["catalog"],
            f"layer_schema_{idx}"             : lyr["schema"],
            f"layer_table_{idx}"              : lyr["table"],
            f"expected_survival_rate_{idx}"   : float(lyr.get("survival_rate", 92)) / 100.0,
            f"expected_latency_minutes_{idx}" : int(lyr.get("latency", 120)),
            f"reconciliation_metrics_{idx}"   : recon_metrics,
        })

    try:
        execute_write(
            f"""
            INSERT INTO {PREFIX}uc2_layer_registry_b (
                layer_id, source_fully_qualified_name, layer_name,
                layer_fully_qualified_name, layer_catalog, layer_schema,
                layer_table, expected_survival_rate,
                expected_latency_minutes, reconciliation_metrics, is_active,
                registered_timestamp, registered_by
            ) VALUES {", ".join(layer_rows)}
        """,
            layer_params,
            conn=conn,
        )
        layer_count = len(layer_rows)
    except Exception as e:
        layer_err.append(str(e)[:150])

    if layer_err:
        all_ok = False
    steps.append({
        "label" : "Layers registered",
        "state" : "done" if not layer_err else "error",
        "detail": f"{layer_count} layers" +
                  (f" | {len(layer_err)} errors" if layer_err else ""),
    })

    # ── Register check configs ────────────────────────────────────────────
    # Batched for the same round-trip reason as the layers insert above.
    chk_count = 0
    chk_err   = []
    chk_rows, chk_params = [], {"source_fqn": source_fqn}
    i = 0
    for trans_key, trans_checks in checks.items():
        parts = trans_key.split("_")
        from_layer = parts[0]
        to_layer   = parts[1]
        for chk_id, cfg in trans_checks.items():
            if not cfg.get("enabled", False):
                continue
            chk_rows.append(f"""(
                :layer_check_config_id_{i}, :source_fqn,
                :from_layer_{i}, :to_layer_{i}, :check_type_{i},
                :default_warning_threshold_{i},
                :default_critical_threshold_{i},
                :threshold_unit_{i},
                true, current_timestamp(), 'layer_wizard'
            )""")
            chk_params.update({
                f"layer_check_config_id_{i}"      : str(uuid.uuid4()),
                f"from_layer_{i}"                 : from_layer,
                f"to_layer_{i}"                   : to_layer,
                f"check_type_{i}"                 : chk_id,
                f"default_warning_threshold_{i}"  : float(cfg.get("warn", 0)),
                f"default_critical_threshold_{i}" : float(cfg.get("crit", 0)),
                f"threshold_unit_{i}"             : next(
                    c["unit"] for c in CHECK_TYPES if c["id"] == chk_id
                ),
            })
            i += 1

    if chk_rows:
        try:
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc2_layer_check_config_b (
                    layer_check_config_id,
                    source_fully_qualified_name,
                    from_layer, to_layer, check_type,
                    default_warning_threshold,
                    default_critical_threshold,
                    threshold_unit, is_active,
                    created_timestamp, created_by
                ) VALUES {", ".join(chk_rows)}
            """,
                chk_params,
                conn=conn,
            )
            chk_count = i
        except Exception as e:
            chk_err.append(str(e)[:150])

    if chk_err:
        all_ok = False
    steps.append({
        "label" : "Check configs created",
        "state" : "done" if not chk_err else "error",
        "detail": f"{chk_count} checks" +
                  (f" | {len(chk_err)} errors" if chk_err else ""),
    })

    # ── Register metric configs (AGGREGATE columns) ───────────────────────
    # Batched across ROW_COUNT + FRESHNESS + all AGGREGATE columns for every
    # transition into a single multi-row INSERT, same round-trip rationale
    # as above.
    met_count = 0
    met_err   = []
    met_rows, met_params = [], {"source_fqn": source_fqn}
    i = 0
    for trans_key, trans_checks in checks.items():
        parts = trans_key.split("_")
        from_layer = parts[0]
        to_layer   = parts[1]

        # ROW_COUNT metric
        if trans_checks.get("ROW_COUNT", {}).get("enabled"):
            rc = trans_checks["ROW_COUNT"]
            met_rows.append(f"""(
                :metric_config_id_{i}, :source_fqn,
                :from_layer_{i}, :to_layer_{i}, 'ROW_COUNT',
                'row_count_survival_rate', NULL, NULL,
                :warning_threshold_{i}, :critical_threshold_{i},
                'PERCENTAGE', true, 1,
                current_timestamp(), 'layer_wizard'
            )""")
            met_params.update({
                f"metric_config_id_{i}"   : str(uuid.uuid4()),
                f"from_layer_{i}"         : from_layer,
                f"to_layer_{i}"           : to_layer,
                f"warning_threshold_{i}"  : float(rc.get("warn", 5)),
                f"critical_threshold_{i}" : float(rc.get("crit", 10)),
            })
            i += 1

        # FRESHNESS metric
        if trans_checks.get("FRESHNESS", {}).get("enabled"):
            fr = trans_checks["FRESHNESS"]
            met_rows.append(f"""(
                :metric_config_id_{i}, :source_fqn,
                :from_layer_{i}, :to_layer_{i}, 'FRESHNESS',
                :metric_name_{i}, NULL, NULL,
                :warning_threshold_{i}, :critical_threshold_{i},
                'MINUTES', true, 99,
                current_timestamp(), 'layer_wizard'
            )""")
            met_params.update({
                f"metric_config_id_{i}"   : str(uuid.uuid4()),
                f"from_layer_{i}"         : from_layer,
                f"to_layer_{i}"           : to_layer,
                f"metric_name_{i}"        : f"{to_layer.lower()}_data_presence",
                f"warning_threshold_{i}"  : float(fr.get("warn", 30)),
                f"critical_threshold_{i}" : float(fr.get("crit", 60)),
            })
            i += 1

        # AGGREGATE metrics (per column)
        agg_cfg = trans_checks.get("AGGREGATE", {})
        if agg_cfg.get("enabled"):
            for order, col in enumerate(agg_cfg.get("columns", []), start=2):
                met_rows.append(f"""(
                    :metric_config_id_{i}, :source_fqn,
                    :from_layer_{i}, :to_layer_{i}, 'AGGREGATE',
                    :metric_name_{i}, :source_column_{i}, :target_column_{i},
                    :warning_threshold_{i}, :critical_threshold_{i},
                    'PERCENTAGE', true, :display_order_{i},
                    current_timestamp(), 'layer_wizard'
                )""")
                met_params.update({
                    f"metric_config_id_{i}"   : str(uuid.uuid4()),
                    f"from_layer_{i}"         : from_layer,
                    f"to_layer_{i}"           : to_layer,
                    f"metric_name_{i}"        : col,
                    f"source_column_{i}"      : col,
                    f"target_column_{i}"      : col,
                    f"warning_threshold_{i}"  : float(agg_cfg.get("warn", 2)),
                    f"critical_threshold_{i}" : float(agg_cfg.get("crit", 5)),
                    f"display_order_{i}"      : order,
                })
                i += 1

    if met_rows:
        try:
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc2_reconciliation_metric_config_b (
                    metric_config_id, source_fully_qualified_name,
                    from_layer, to_layer, check_type, metric_name,
                    source_column, target_column,
                    warning_threshold, critical_threshold,
                    threshold_unit, is_active, display_order,
                    created_timestamp, created_by
                ) VALUES {", ".join(met_rows)}
            """,
                met_params,
                conn=conn,
            )
            met_count = i
        except Exception as e:
            met_err.append(str(e)[:150])

    if met_err:
        all_ok = False
    steps.append({
        "label" : "Metric configs created",
        "state" : "done" if not met_err else "error",
        "detail": f"{met_count} metrics" +
                  (f" | {len(met_err)} errors" if met_err else ""),
    })

    # Build result modal
    step_items = []
    for s in steps:
        icon  = "✅" if s["state"] == "done" else "❌"
        color = STEP_COMPLETE if s["state"] == "done" else "#ff6b6b"
        step_items.append(
            html.Div([
                html.Span(icon, style={"marginRight": "10px",
                                       "fontSize": "18px"}),
                html.Span(s["label"],
                          style={"fontWeight": "600", "color": color,
                                 "marginRight": "12px"}),
                html.Small(s["detail"], style=MUTED_STYLE),
            ], style={"padding": "8px 0",
                      "borderBottom": f"1px solid {BORDER_COLOR}"})
        )

    summary_color = STEP_COMPLETE if all_ok else "#ffa500"
    body = html.Div([
        html.H5(
            "✅ Layer onboarding complete!" if all_ok
            else "⚠️ Completed with errors",
            style={"color": summary_color, "marginBottom": "16px"},
        ),
        *step_items,
    ])

    conn.close()

    return True, body


# ── Close modal ───────────────────────────────────────────────────────────────

@callback(
    Output("lo-exec-modal", "is_open", allow_duplicate=True),
    Input("lo-exec-close",  "n_clicks"),
    prevent_initial_call=True,
)
def close_modal(n):
    return False
