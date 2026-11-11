# pages/onboarding.py

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH, ctx
import dash_bootstrap_components as dbc
from db.connection import execute_query, execute_write, validate_identifier, get_connection
from config.settings import (
    TARGET_CATALOG, TARGET_SCHEMA,
    COLUMN_LEVEL_VALIDATIONS,
)
from components.alerts import error_alert, warning_alert
from datetime import date, timedelta
import logging
import uuid

logger = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path  = "/onboarding",
    name  = "Table Onboarding Wizard"
)

# ── Constants ──────────────────────────────────────────────────────────────

PREFIX        = f"{TARGET_CATALOG}.{TARGET_SCHEMA}."

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
WIZARD_WIDTH  = {"maxWidth": "900px", "margin": "0 auto"}

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
    {"num": 1, "label": "Table Details"},
    {"num": 2, "label": "Column Config"},
    {"num": 3, "label": "Table Checks"},
    {"num": 4, "label": "Baseline Window"},
    {"num": 5, "label": "Review & Confirm"},
]

# Types that are considered complex / JSON / nested
COMPLEX_TYPES = {"MAP", "STRUCT", "ARRAY", "VARIANT", "OBJECT"}

# Default checks pre-selected per data type
COLUMN_CHECK_DEFAULTS = {
    "STRING"    : ["NULL_SPIKE", "FORMAT_PATTERN", "CATEGORICAL_DOMAIN", "CARDINALITY_DRIFT"],
    "VARCHAR"   : ["NULL_SPIKE", "FORMAT_PATTERN", "CATEGORICAL_DOMAIN", "CARDINALITY_DRIFT"],
    "INT"       : ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT"],
    "BIGINT"    : ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT"],
    "DOUBLE"    : ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT"],
    "FLOAT"     : ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT"],
    "DECIMAL"   : ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT"],
    "DATE"      : ["NULL_SPIKE", "DATE_VALIDITY"],
    "TIMESTAMP" : ["NULL_SPIKE", "DATE_VALIDITY"],
    "BOOLEAN"   : ["NULL_SPIKE"],
    "DEFAULT"   : ["NULL_SPIKE"],
}

# Defaults for complex columns (native ARRAY/STRUCT/MAP/VARIANT).
# JSON_VALID/SCHEMA_DRIFT/KEY_CARDINALITY assume a STRING column holding
# serialized JSON (from_json(...)) and cannot run against a natively
# structured column, so they are not offered here.
COMPLEX_CHECK_DEFAULTS = ["NULL_SPIKE"]

# Sentinel value for tables with no date column
_NO_DATE_COL_VALUE  = "__NONE__"
_NO_DATE_COL_OPTION = {
    "label": "— No date column (use full table)",
    "value": _NO_DATE_COL_VALUE,
}

TABLE_CHECK_TYPES = [
    {
        "id"         : "VOLUME_ANOMALY",
        "label"      : "Volume Anomaly",
        "description": "Detects unexpected row count changes vs baseline",
        "default_on" : True,
        "warn"       : 20,
        "crit"       : 50,
    },
    {
        "id"         : "SCHEMA_DRIFT",
        "label"      : "Schema Drift",
        "description": "Detects unexpected column additions or removals",
        "default_on" : True,
        "warn"       : None,
        "crit"       : None,
    },
    {
        "id"         : "DUPLICATE_CHECK",
        "label"      : "Duplicate Check",
        "description": "Detects duplicate rows above threshold",
        "default_on" : False,
        "warn"       : 1,
        "crit"       : 5,
    },
    {
        "id"         : "PARTITION_FRESHNESS",
        "label"      : "Partition Freshness",
        "description": "Detects stale partitions beyond expected frequency",
        "default_on" : False,
        "warn"       : 1,
        "crit"       : 2,
    },
    {
        "id"         : "MALFORMED_RECORDS",
        "label"      : "Malformed Records",
        "description": "Detects records that failed schema parsing",
        "default_on" : True,
        "warn"       : 1,
        "crit"       : 5,
    },
]

# ── Helpers ────────────────────────────────────────────────────────────────

def is_complex_dtype(dtype: str) -> bool:
    """Return True if the data type is complex / JSON / nested."""
    norm = (dtype or "").upper().split("<")[0].split("(")[0].strip()
    return norm in COMPLEX_TYPES


def get_default_checks_for_dtype(dtype: str) -> list:
    """Return the default-selected checks for a given data type."""
    if is_complex_dtype(dtype):
        return list(COMPLEX_CHECK_DEFAULTS)
    dtype_upper = (dtype or "").upper().split("(")[0].strip()
    return COLUMN_CHECK_DEFAULTS.get(
        dtype_upper, COLUMN_CHECK_DEFAULTS["DEFAULT"]
    )


def get_available_checks_for_dtype(dtype: str) -> list:
    """Return the full list of available checks for a column type."""
    if is_complex_dtype(dtype):
        return list(COMPLEX_CHECK_DEFAULTS)
    return COLUMN_LEVEL_VALIDATIONS


def normalize_dtype(dtype: str) -> str:
    norm = (dtype or "STRING").upper().split("(")[0].strip()
    # Preserve STRUCT<...>, MAP<...>, ARRAY<...> as their base type
    base = (dtype or "STRING").upper().split("<")[0].split("(")[0].strip()
    if base in COMPLEX_TYPES:
        return base
    return norm


# ── Nested / complex column explosion ──────────────────────────────────────
# Complex columns (STRUCT / ARRAY) are expanded into leaf "virtual" columns
# so every nested field gets its own Enable switch, check list and
# thresholds, exactly like a primitive column.
#
# Path syntax (stored as column_name in the registries):
#   struct field      ->  parent.child            e.g. touchpoint.id
#   array element     ->  parent[]                e.g. tickets[]
#   array of struct   ->  parent[].child          e.g. accounts[].agency.name
# Arrays are exploded with explode_outer / LATERAL VIEW OUTER, so metrics
# for array fields are measured per element (empty/null arrays -> NULL).
# MAP / VARIANT are not expanded (kept as a single complex column).
# The same parser/resolver lives in agent1/pipeline/01_baseline_computation
# and 02_validation_agent — keep them in sync.

import re as _re

_PRIMITIVE_ALIASES = {
    "INTEGER": "INT", "LONG": "BIGINT", "SHORT": "SMALLINT",
    "BYTE": "TINYINT", "REAL": "FLOAT",
}


def _split_top_level(s: str, sep: str = ","):
    """Split on `sep` only at nesting depth 0 (ignores <> and ())."""
    parts, depth, buf, in_bt = [], 0, [], False
    for ch in s:
        if ch == "`":
            in_bt = not in_bt
        elif not in_bt:
            if ch in "<(":
                depth += 1
            elif ch in ">)":
                depth -= 1
            elif ch == sep and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _strip_type_suffix(t: str) -> str:
    m = _re.search(r"\s+(NOT\s+NULL|COMMENT)\b", t, flags=_re.I)
    return t[:m.start()].strip() if m else t.strip()


def _type_base(t: str) -> str:
    return t.strip().split("<")[0].split("(")[0].strip().upper()


def _type_inner(t: str) -> str:
    t = t.strip()
    return t[t.index("<") + 1: t.rindex(">")]


def _struct_fields(t: str):
    out = []
    for f in _split_top_level(_type_inner(t)):
        name, _, ftype = f.partition(":")
        out.append((name.strip().strip("`"), _strip_type_suffix(ftype)))
    return out


# Path building / resolution is shared with Column Registry & Baseline
# Explorer (components/nested_columns.py). Canonical paths follow the Unity
# Catalog schema view: stores.selected.items.id (array element = `items`).
from components.nested_columns import (  # noqa: E402
    flatten_nested_type,
    is_nested_path,
    nested_sql_source,
    normalize_path,
    path_root,
    schema_tree,
)


def _find_col(df, candidates, fallback_idx=0):
    cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    return df.columns[fallback_idx]


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
                "backgroundColor": "#2C2E33",
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
                STEP_COMPLETE if num < current_step else "#373A40"
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


# ── Nav buttons ────────────────────────────────────────────────────────────

def _nav_buttons(step: int, show_back: bool = True) -> dbc.Row:
    """
    Renders visible buttons with -visible suffix IDs.
    These sync to hidden persistent buttons via bridge callbacks.
    """
    back_btn = dbc.Button(
        "← Back",
        id      = f"ob-back-{step}-visible",
        color   = "light",
        outline = True,
        style   = {
            "color"      : TEXT_PRIMARY,
            "borderColor": BORDER_COLOR,
            "marginRight": "12px",
        },
    ) if show_back else html.Div()

    next_label = "Next →" if step < 4 else "Review →"

    return dbc.Row([
        dbc.Col([
            back_btn,
            dbc.Button(
                next_label,
                id    = f"ob-next-{step}-visible",
                color = "primary",
                style = {
                    "fontWeight": "600",
                    "padding"   : "8px 24px",
                },
            ),
        ], className="d-flex align-items-center"),
    ], className="mt-4")


# ── Layout ─────────────────────────────────────────────────────────────────

def layout():
    today    = date.today()
    end_dt   = today - timedelta(days=1)
    start_dt = end_dt - timedelta(days=29)

    return html.Div(id="ob-wizard-page", children=[

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
        dcc.Store(id="ob-step",         data=1),
        dcc.Store(id="ob-table-meta",   data={}),
        dcc.Store(id="ob-col-config",   data={}),
        dcc.Store(id="ob-table-checks", data={}),
        dcc.Store(id="ob-baseline",     data={}),
        dcc.Store(id="ob-existing",     data={}),
        dcc.Store(id="ob-exec-status",  data={}),

        # ── Persistent hidden components ───────────────────────────────────
        # These always exist in the DOM so Dash can register callbacks.
        # Visible counterparts (rendered dynamically in steps) sync
        # their values/clicks to these via bridge callbacks.
        html.Div([

            # ── Navigation buttons — hidden persistent versions ────────────
            dbc.Button(id="ob-next-1",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-next-2",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-next-3",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-next-4",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-back-2",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-back-3",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-back-4",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-back-5",        n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-back-existing", n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-modify-btn",    n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-execute-btn",   n_clicks=0,
                       style={"display": "none"}),
            dbc.Button(id="ob-restart-btn",   n_clicks=0,
                       style={"display": "none"}),

            # ── Baseline date pickers — hidden persistent versions ─────────
            dcc.DatePickerSingle(
                id    = "ob-baseline-start",
                date  = str(start_dt),
                style = {"display": "none"},
            ),
            dcc.DatePickerSingle(
                id    = "ob-baseline-end",
                date  = str(end_dt),
                style = {"display": "none"},
            ),

            # ── Baseline options — hidden persistent version ───────────────
            dcc.Checklist(
                id      = "ob-baseline-options",
                options = [{"label": "", "value": "recompute"}],
                value   = ["recompute"],
                style   = {"display": "none"},
            ),

            # ── Baseline warning placeholder ───────────────────────────────
            html.Div(id="ob-baseline-warning"),

        ], style={"display": "none"}),

        # ── Execution progress modal ───────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(
                html.Div([
                    html.Span(
                        "🚀 Onboarding Table",
                        style={
                            "fontWeight": "700",
                            "color"     : TEXT_HEADING,
                            "fontSize"  : "18px",
                        }
                    ),
                ]),
                close_button=True,
            ),
            dbc.ModalBody([
                dcc.Loading(
                    id             = "ob-exec-loading",
                    type           = "circle",
                    color          = STEP_ACTIVE,
                    overlay_style  = {
                        "visibility": "visible",
                        "filter"    : "blur(1px)"
                    },
                    custom_spinner = html.Div([
                        dbc.Spinner(color="primary", size="lg"),
                        html.P(
                            "Onboarding in progress…",
                            style={
                                "color"     : TEXT_PRIMARY,
                                "fontWeight": "600",
                                "fontSize"  : "15px",
                                "marginTop" : "16px",
                            }
                        ),
                        html.P(
                            "Registering table, columns, validations "
                            "and computing baselines. "
                            "This may take 30-60 seconds.",
                            style={
                                "color"   : TEXT_MUTED,
                                "fontSize": "13px",
                            }
                        ),
                    ], style={"textAlign": "center", "padding": "40px 20px"}),
                    children = html.Div(id="ob-exec-modal-body"),
                ),
            ]),
        ],
            id                 = "ob-exec-modal",
            is_open            = False,
            centered           = True,
            backdrop           = True,
            size               = "lg",
            style              = {"fontFamily": "inherit"},
            content_class_name = "ob-exec-modal-content",
        ),

        # ── Visible content wrapper ────────────────────────────────────────
        html.Div([

            # Header
            html.Div([
                html.H2(
                    "🧙 Table Onboarding Wizard",
                    style={
                        "color"       : TEXT_HEADING,
                        "fontWeight"  : "700",
                        "marginBottom": "4px",
                    }
                ),
                html.P(
                    "Register a new table for automated data quality "
                    "monitoring in 5 guided steps.",
                    style={**MUTED_STYLE, "fontSize": "14px"}
                ),
            ], style={"marginBottom": "32px", "paddingTop": "24px"}),

            # Progress bar
            html.Div(id="ob-progress-bar"),

            # Alert
            html.Div(id="ob-alert", className="mb-3"),

            # Step content (with loading overlay — keeps content visible)
            dcc.Loading(
                id="ob-step-loading",
                type="circle",
                color=STEP_ACTIVE,
                overlay_style={
                    "visibility": "visible",
                    "opacity"   : 0.4,
                    "filter"    : "blur(1px)",
                },
                children=html.Div(id="ob-step-content"),
            ),

        ], style={**WIZARD_WIDTH, "padding": "0 16px 60px"}),

    ], style={"backgroundColor": PAGE_BG, "minHeight": "100vh"})


# ── Step 1 — Table Details ─────────────────────────────────────────────────

def build_step1(prefill: dict = None) -> html.Div:
    p = prefill or {}
    return html.Div([
        html.Div([
            html.H4(
                "Step 1 — Table Details",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                "Select the table you want to onboard and provide "
                "its operational metadata.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Catalog", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "ob-catalog",
                        options     = [],
                        placeholder = "Loading catalogs…",
                        value       = p.get("catalog"),
                        clearable   = False,
                        className   = "ob-dropdown",
                    ),
                ], md=6),
                dbc.Col([
                    html.Label("Schema", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "ob-schema",
                        options     = [],
                        placeholder = "Select catalog first…",
                        value       = p.get("schema"),
                        clearable   = False,
                        className   = "ob-dropdown",
                    ),
                ], md=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    html.Label("Table", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "ob-table",
                        options     = [],
                        placeholder = "Select schema first…",
                        value       = p.get("table_name"),
                        clearable   = False,
                        className   = "ob-dropdown",
                    ),
                ], md=12),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    html.Label("Data Layer", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "ob-layer",
                        options   = [
                            {"label": "BRONZE", "value": "BRONZE"},
                            {"label": "SILVER", "value": "SILVER"},
                            {"label": "GOLD",   "value": "GOLD"},
                        ],
                        value     = p.get("layer", "BRONZE"),
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Ingestion Type", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "ob-ingestion-type",
                        options   = [
                            {"label": "FILE",        "value": "FILE"},
                            {"label": "CDC",         "value": "CDC"},
                            {"label": "API",         "value": "API"},
                            {"label": "AUTOLOADER",  "value": "AUTOLOADER"},
                            {"label": "BATCH",       "value": "BATCH"},
                            {"label": "STREAMING",   "value": "STREAMING"},
                        ],
                        value     = p.get("ingestion_type", "FILE"),
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Frequency", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id        = "ob-frequency",
                        options   = [
                            {"label": "DAILY",        "value": "DAILY"},
                            {"label": "HOURLY",       "value": "HOURLY"},
                            {"label": "NEAR_REALTIME","value": "NEAR_REALTIME"},
                            {"label": "BATCH",        "value": "BATCH"},
                            {"label": "WEEKLY",       "value": "WEEKLY"},
                        ],
                        value     = p.get("ingestion_frequency", "DAILY"),
                        clearable = False,
                        className = "ob-dropdown",
                    ),
                ], md=4),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    html.Label("Date Column", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id          = "ob-date-col",
                        options     = [],
                        placeholder = "Select table first…",
                        value       = p.get("date_column"),
                        clearable   = False,
                        className   = "ob-dropdown",
                    ),
                    html.Small(
                        "Date/timestamp column for baseline window. "
                        "Also detects date-like STRING columns. "
                        "Choose 'No date column' to baseline "
                        "over the full table.",
                        style=MUTED_STYLE
                    ),
                ], md=6),
                dbc.Col([
                    html.Label("Owner Email", style=LABEL_STYLE),
                    dbc.Input(
                        id          = "ob-owner",
                        placeholder = "e.g. s819534@8451.com",
                        value       = p.get("owner_email", ""),
                        type        = "email",
                        style       = {
                            "backgroundColor": "#2C2E33",
                            "color"          : TEXT_PRIMARY,
                            "border"         : f"1px solid {BORDER_COLOR}",
                        },
                    ),
                ], md=6),
            ], className="mb-4"),

        ], style=CARD_STYLE),

        _nav_buttons(step=1, show_back=False),
    ])


# ── Step 2 — Column Configuration ─────────────────────────────────────────

# ── Step 2 row builders ────────────────────────────────────────────────────
# Layout: Column (3) | On (1) | Check Types (4) | Warn % (2) | Crit % (2)
# STRUCT/ARRAY parents use "ob-cplx-*" ids. Their nested leaf fields live in a
# collapsible panel ({"type": "ob-nested-panel"}) that only opens when the
# parent is switched on (see toggle_complex_parent callback).

_STEP2_INPUT_STYLE = {
    "backgroundColor": "#2C2E33",
    "color"          : TEXT_PRIMARY,
    "border"         : f"1px solid {BORDER_COLOR}",
    "fontSize"       : "13px",
}

# Short, human labels for check chips (value stays the registry code)
_CHECK_SHORT_LABELS = {
    "NULL_SPIKE"              : "Null spike",
    "NUMERIC_RANGE"           : "Range",
    "DISTRIBUTION_DRIFT"      : "Distribution",
    "FORMAT_PATTERN"          : "Format",
    "CATEGORICAL_DOMAIN"      : "Domain",
    "CARDINALITY_DRIFT"       : "Cardinality",
    "CROSS_COLUMN_CONSISTENCY": "Cross-column",
    "MALFORMED_RECORDS"       : "Malformed",
}


def _check_label(code: str) -> str:
    return _CHECK_SHORT_LABELS.get(code, code.replace("_", " ").title())


def _lineage_label(path: str):
    """'stores.selected.items.id' -> muted 'stores.selected.items.' + bold 'id'."""
    prefix, _, leaf = normalize_path(path).rpartition(".")
    return [
        html.Span(prefix + "." if prefix else "",
                  style={"color": "#8B8D98", "fontWeight": "400"}),
        html.Span(leaf, style={"color": TEXT_PRIMARY, "fontWeight": "600"}),
    ]


def _step2_col_row(cname: str, dtype: str, existing: dict,
                   id_prefix: str = "ob-col", n_children: int = 0,
                   display_name=None, is_child: bool = False,
                   id_extra: dict = None, depth: int = 0,
                   type_label: str = None):
    norm_dt   = normalize_dtype(dtype)
    is_cplx   = is_complex_dtype(dtype)
    available = get_available_checks_for_dtype(dtype)
    # Complex parents with nested fields start OFF (collapsed)
    enabled   = existing.get("enabled", not bool(n_children))
    checks    = existing.get("checks", get_default_checks_for_dtype(dtype))
    extra     = id_extra or {}

    def _id(kind):
        return {"type": f"{id_prefix}-{kind}", "index": cname, **extra}

    if is_cplx:
        badge_color = "info"
        badge_label = (f"{norm_dt} · {n_children} fields" if n_children
                       else f"{norm_dt} · JSON")
    elif is_child:
        badge_color, badge_label = "success", (type_label or norm_dt.lower())
    else:
        badge_color, badge_label = "secondary", norm_dt

    name_block = [
        html.Div(
            display_name or cname,
            title=normalize_path(cname) if is_child else cname,
            style={
                "fontWeight": "600",
                "color"     : TEXT_PRIMARY,
                "fontSize"  : "13px" if is_child else "14px",
                "wordBreak" : "break-word",
                "lineHeight": "1.3",
                "fontFamily": "ui-monospace, SFMono-Regular, Menlo, monospace"
                              if is_child else None,
            },
        ),
        html.Div(
            [dbc.Badge(badge_label, color=badge_color,
                       style={"fontSize": "11px"})]
            + ([html.Small(" Switch on to configure nested fields",
                           style={**MUTED_STYLE, "fontSize": "11px",
                                  "marginLeft": "6px"})]
               if n_children else []),
            style={"marginTop": "4px"},
        ),
    ]

    return html.Div(
        dbc.Row([
            dbc.Col(
                html.Div([
                    dbc.Switch(
                        id    = _id("enabled"),
                        value = enabled,
                        style = {"marginTop": "2px"},
                    ),
                    html.Div(name_block, style={"minWidth": 0}),
                ], style={"display": "flex", "alignItems": "flex-start",
                          "gap": "8px"}),
                md=4, style={"minWidth": 0},
            ),
            dbc.Col(
                dcc.Dropdown(
                    id          = _id("checks"),
                    options     = [{"label": _check_label(c), "value": c,
                                    "title": c} for c in available],
                    value       = [c for c in checks if c in available],
                    multi       = True,
                    disabled    = not enabled,
                    placeholder = "Select check types…",
                    className   = "ob-dropdown ob-multi",
                ),
                md=4, style={"minWidth": 0},
            ),
            dbc.Col(
                dbc.Input(
                    id          = _id("warn"),
                    placeholder = "Warn %",
                    value       = existing.get("warn_threshold", 5),
                    type="number", min=0, max=100,
                    disabled    = not enabled,
                    style       = _STEP2_INPUT_STYLE,
                ),
                md=2,
            ),
            dbc.Col(
                dbc.Input(
                    id          = _id("crit"),
                    placeholder = "Crit %",
                    value       = existing.get("crit_threshold", 10),
                    type="number", min=0, max=100,
                    disabled    = not enabled,
                    style       = _STEP2_INPUT_STYLE,
                ),
                md=2,
            ),
        ], className="align-items-center g-2"),
        style={
            "padding"        : "8px 12px" if is_child else "10px 12px",
            "borderBottom"   : f"1px solid {BORDER_COLOR}",
            "backgroundColor": "#1D1E22" if is_child else CARD_BG,
        },
    )


def _step2_nested_panel(parent: str, parent_dtype: str, kids: list,
                        p: dict, parent_on: bool):
    """
    Nested fields of one complex column as a lineage tree that mirrors the
    Unity Catalog schema view:
        stores.requested                 int
        stores.selected                  array    (structure row)
          stores.selected.items          struct   (structure row)
            stores.selected.items.id     int
    Structure rows are informational; leaf rows are configurable.
    Child controls use 'ob-nest-*' ids keyed by (index=registry key,
    parent=column) so All on / All off target just this panel.
    """
    by_path = {normalize_path(k["name"]): k for k in kids}
    used = set()
    body = []

    # Flat list: every configurable leaf at the same level, named by its full
    # lineage path (stores.selected.items.id). Intermediate array/struct
    # levels are not shown as separate rows.
    for e in schema_tree(parent, parent_dtype):
        if e["kind"] != "leaf":
            continue
        k = by_path.get(e["path"])
        if not k:
            continue
        used.add(k["name"])
        body.append(_step2_col_row(
            k["name"], k["dtype"], p.get(k["name"], {}),
            id_prefix="ob-nest", display_name=_lineage_label(e["path"]),
            is_child=True, id_extra={"parent": parent},
            type_label=e["dtype"],
        ))

    # Fields kept in the registry that are no longer in the table schema
    for k in kids:
        if k["name"] not in used:
            body.append(_step2_col_row(
                k["name"], k["dtype"], p.get(k["name"], {}),
                id_prefix="ob-nest", display_name=_lineage_label(k["name"]),
                is_child=True, id_extra={"parent": parent},
            ))

    btn_style = {"fontSize": "11px", "padding": "2px 10px"}
    header = html.Div(
        dbc.Row([
            dbc.Col([
                html.Span("Nested fields of ", style=MUTED_STYLE),
                html.Code(parent, style={"color": "#00c851"}),
                html.Span(f" · {len(kids)} fields", style=MUTED_STYLE),
            ], width="auto"),
            dbc.Col([
                dbc.Button("All on", id={"type": "ob-nest-all-on", "parent": parent},
                           size="sm", color="success", outline=True,
                           className="me-2", style=btn_style),
                dbc.Button("All off", id={"type": "ob-nest-all-off", "parent": parent},
                           size="sm", color="secondary", outline=True,
                           style=btn_style),
            ], width="auto", className="ms-auto"),
        ], className="align-items-center g-2"),
        style={"padding": "8px 12px", "fontSize": "12px",
               "borderBottom": f"1px solid {BORDER_COLOR}"},
    )
    return html.Div(
        [header] + body,
        id    = {"type": "ob-nested-panel", "index": parent},
        style = {
            "display"        : "block" if parent_on else "none",
            "marginLeft"     : "24px",
            "borderLeft"     : "3px solid #00c851",
            "backgroundColor": "#1D1E22",
        },
    )


def build_step2(columns: list, prefill_cols: dict = None) -> html.Div:
    p = prefill_cols or {}

    if not columns:
        return html.Div([
            warning_alert("No columns detected. Check the table name."),
            _nav_buttons(step=2, show_back=True),
        ])

    complex_count = 0
    nested_count  = 0

    # Group nested leaf fields under their parent complex column
    children_by_parent = {}
    top_cols = []
    all_names = {c["name"] for c in columns}
    for col in columns:
        cfg  = p.get(col["name"], {})
        root = col["name"].split(".")[0].split("[")[0]
        # is_nested_child is set by Step 1; fall back to path syntax for
        # configs re-loaded from the registry (Modify flow).
        if cfg.get("is_nested_child") or (
            is_nested_path(col["name"]) and root in all_names
        ):
            parent = cfg.get("parent_column") or root
            p.setdefault(col["name"], {})
            p[col["name"]].setdefault("is_nested_child", True)
            p[col["name"]].setdefault("parent_column", parent)
            children_by_parent.setdefault(parent, []).append(col)
        else:
            top_cols.append(col)

    col_rows = []
    for col in top_cols:
        cname    = col["name"]
        dtype    = col["dtype"]
        existing = p.get(cname, {})
        kids     = children_by_parent.get(cname, [])
        if is_complex_dtype(dtype):
            complex_count += 1
        if kids:
            nested_count += len(kids)
            parent_on = existing.get("enabled", False)
            col_rows.append(_step2_col_row(
                cname, dtype, existing,
                id_prefix="ob-cplx", n_children=len(kids),
            ))
            col_rows.append(_step2_nested_panel(cname, dtype, kids, p, parent_on))
        else:
            col_rows.append(_step2_col_row(cname, dtype, existing))

    return html.Div([
        html.Div([
            html.H4(
                "Step 2 — Column Configuration",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                f"{len(top_cols)} columns detected"
                + (f" ({complex_count} complex/JSON"
                   + (f" with {nested_count} nested fields" if nested_count else "")
                   + ")." if complex_count else ".")
                + " Enable the checks you want to run on each column.",
                style=MUTED_STYLE
            ),
        ] + ([
            dbc.Alert(
                [
                    html.Strong(f"{complex_count} complex column(s) detected. "),
                    "STRUCT/ARRAY columns start switched off. Switch a "
                    "complex column on to expand its nested fields below "
                    "it with their full lineage path (e.g. "
                    "stores.selected.items.id); each nested field can "
                    "then be enabled and configured like a normal column.",
                ],
                color="info",
                className="py-2 mb-3",
                style={"fontSize": "13px"},
            )
        ] if complex_count else []),
        style={"marginBottom": "24px"}),

        html.Div([
            html.Div([
                dbc.Row([
                    dbc.Col(html.Small("On · Column / Type",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=4),
                    dbc.Col(html.Small("Check Types",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=4),
                    dbc.Col(html.Small("Warn %",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=2),
                    dbc.Col(html.Small("Crit %",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=2),
                ], className="g-2")
            ], style={
                "padding"        : "8px 12px",
                "backgroundColor": "#2C2E33",
                "borderRadius"   : "6px 6px 0 0",
                "border"         : f"1px solid {BORDER_COLOR}",
            }),
            html.Div(col_rows, style={
                "border"         : f"1px solid {BORDER_COLOR}",
                "borderTop"      : "none",
                "borderRadius"   : "0 0 6px 6px",
                "maxHeight"      : "420px",
                "overflowY"      : "auto",
                "backgroundColor": CARD_BG,
            }),
        ], style={"marginBottom": "24px"}),

        _nav_buttons(step=2, show_back=True),
    ])


# ── Step 3 — Table-Level Checks ────────────────────────────────────────────

def build_step3(prefill: dict = None) -> html.Div:
    p = prefill or {}

    check_rows = []
    for chk in TABLE_CHECK_TYPES:
        chk_id   = chk["id"]
        existing = p.get(chk_id, {})
        enabled  = existing.get("enabled", chk["default_on"])
        warn_val = existing.get("warn",    chk["warn"])
        crit_val = existing.get("crit",    chk["crit"])
        has_thr  = chk["warn"] is not None

        check_rows.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        dbc.Switch(
                            id    = {"type": "ob-tbl-check-enabled",
                                     "index": chk_id},
                            value = enabled,
                        ),
                    ], md=1),
                    dbc.Col([
                        html.Div(
                            chk["label"],
                            style={"fontWeight": "600",
                                   "color"     : TEXT_PRIMARY,
                                   "fontSize"  : "14px"}
                        ),
                        html.Small(chk["description"], style=MUTED_STYLE),
                    ], md=6),
                    dbc.Col([
                        dbc.Input(
                            id          = {"type": "ob-tbl-check-warn",
                                           "index": chk_id},
                            placeholder = "Warn %",
                            value       = warn_val,
                            type        = "number",
                            min         = 0,
                            max         = 100,
                            disabled    = not has_thr or not enabled,
                            style       = {
                                "backgroundColor": "#2C2E33",
                                "color"          : TEXT_PRIMARY,
                                "border"         : f"1px solid {BORDER_COLOR}",
                                "fontSize"       : "13px",
                            },
                        ) if has_thr else
                        html.Small("No threshold", style=MUTED_STYLE),
                    ], md=2),
                    dbc.Col([
                        dbc.Input(
                            id          = {"type": "ob-tbl-check-crit",
                                           "index": chk_id},
                            placeholder = "Crit %",
                            value       = crit_val,
                            type        = "number",
                            min         = 0,
                            max         = 100,
                            disabled    = not has_thr or not enabled,
                            style       = {
                                "backgroundColor": "#2C2E33",
                                "color"          : TEXT_PRIMARY,
                                "border"         : f"1px solid {BORDER_COLOR}",
                                "fontSize"       : "13px",
                            },
                        ) if has_thr else html.Div(),
                    ], md=2),
                ], className="align-items-center"),
            ], style={
                "padding"        : "14px 16px",
                "borderBottom"   : f"1px solid {BORDER_COLOR}",
                "backgroundColor": CARD_BG,
            })
        )

    return html.Div([
        html.Div([
            html.H4(
                "Step 3 — Table-Level Checks",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                "Configure checks that apply to the whole table.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            html.Div([
                dbc.Row([
                    dbc.Col(html.Small("On",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=1),
                    dbc.Col(html.Small("Check / Description",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=6),
                    dbc.Col(html.Small("Warn %",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=2),
                    dbc.Col(html.Small("Crit %",
                        style={**MUTED_STYLE, "fontWeight": "600"}),
                        md=2),
                ])
            ], style={
                "padding"        : "8px 16px",
                "backgroundColor": "#2C2E33",
                "borderRadius"   : "6px 6px 0 0",
                "border"         : f"1px solid {BORDER_COLOR}",
            }),
            html.Div(check_rows, style={
                "border"         : f"1px solid {BORDER_COLOR}",
                "borderTop"      : "none",
                "borderRadius"   : "0 0 6px 6px",
                "backgroundColor": CARD_BG,
            }),
        ], style={"marginBottom": "24px"}),

        _nav_buttons(step=3, show_back=True),
    ])


# ── Step 4 — Baseline Window ───────────────────────────────────────────────

def build_step4(prefill: dict = None) -> html.Div:
    p        = prefill or {}
    end_dt   = date.today() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=29)

    start_val = p.get("window_start", str(start_dt))
    end_val   = p.get("window_end",   str(end_dt))
    recompute = p.get("recompute_checked", ["recompute"])

    return html.Div([
        html.Div([
            html.H4(
                "Step 4 — Baseline Window",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                "Define the clean historical window used to compute "
                "statistical baselines for anomaly detection.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Baseline Start Date", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id             = "ob-baseline-start-visible",
                        date           = start_val,
                        display_format = "YYYY-MM-DD",
                        style          = {"width": "100%"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Baseline End Date", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id             = "ob-baseline-end-visible",
                        date           = end_val,
                        display_format = "YYYY-MM-DD",
                        style          = {"width": "100%"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Minimum Recommended", style=LABEL_STYLE),
                    html.Div(
                        "14 days",
                        style={**MUTED_STYLE, "paddingTop": "10px"}
                    ),
                ], md=4),
            ], className="mb-4"),

            # Warning rendered here from persistent hidden component
            html.Div(id="ob-baseline-warning-visible"),

            dbc.Row([
                dbc.Col([
                    html.Label("Options", style=LABEL_STYLE),
                    dbc.Checklist(
                        id      = "ob-baseline-options-visible",
                        options = [
                            {
                                "label": "Recompute baseline from scratch "
                                         "(overwrite if exists)",
                                "value": "recompute"
                            },
                        ],
                        value   = recompute,
                        style   = {"color": TEXT_PRIMARY},
                    ),
                    html.Small(
                        "Uncheck to skip baseline computation if "
                        "baselines already exist for this table.",
                        style=MUTED_STYLE
                    ),
                ]),
            ]),
        ], style=CARD_STYLE),

        _nav_buttons(step=4, show_back=True),
    ])


# ── Step 5 — Review & Confirm ──────────────────────────────────────────────

def build_step5(
    table_meta  : dict,
    col_config  : dict,
    table_checks: dict,
    baseline    : dict,
) -> html.Div:

    fqn = (
        f"{table_meta.get('catalog','?')}."
        f"{table_meta.get('schema','?')}."
        f"{table_meta.get('table_name','?')}"
    )

    enabled_cols   = [
        c for c, v in col_config.items() if v.get("enabled", True)
    ]
    disabled_cols  = [
        c for c, v in col_config.items() if not v.get("enabled", True)
    ]
    enabled_checks = [
        k for k, v in table_checks.items() if v.get("enabled", False)
    ]

    complex_cols = [
        c for c, v in col_config.items()
        if v.get("enabled", True) and v.get("is_complex", False)
    ]
    standard_cols = [
        c for c, v in col_config.items()
        if v.get("enabled", True) and not v.get("is_complex", False)
    ]
    total_col_checks = sum(
        len(v.get("checks", []))
        for v in col_config.values()
        if v.get("enabled", True)
    )
    total_tbl_checks = len(enabled_checks)
    total_checks     = total_col_checks + total_tbl_checks

    bl_start = baseline.get("window_start", "—")
    bl_end   = baseline.get("window_end",   "—")
    recompute= baseline.get("recompute",    True)

    try:
        days = (
            date.fromisoformat(bl_end) -
            date.fromisoformat(bl_start)
        ).days + 1
    except Exception:
        days = 0

    def srow(label, value, color=TEXT_PRIMARY):
        return dbc.Row([
            dbc.Col(
                html.Small(label,
                           style={**MUTED_STYLE, "fontWeight": "600"}),
                md=4
            ),
            dbc.Col(
                html.Span(value,
                          style={"color"     : color,
                                 "fontWeight": "600",
                                 "fontSize"  : "14px"}),
                md=8
            ),
        ], className="mb-2")

    return html.Div([
        html.Div([
            html.H4(
                "Step 5 — Review & Confirm",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                "Review the complete configuration before onboarding.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        # Table details
        html.Div([
            html.H6("📋 Table Details",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Fully Qualified Name", fqn),
            srow("Ingestion Pattern",   table_meta.get("layer",               "—")),
            srow("Source Type",         table_meta.get("ingestion_type",      "—")),
            srow("Frequency",           table_meta.get("ingestion_frequency",  "—")),
            srow("Date Column",
                 table_meta.get("date_column", "—")
                 if table_meta.get("date_column") != _NO_DATE_COL_VALUE
                 else "None (full table)"),
            srow("Owner",               table_meta.get("owner_email",          "—")),
        ], style={**CARD_STYLE, "marginBottom": "16px"}),

        # Column config
        html.Div([
            html.H6("🔢 Column Configuration",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Columns Enabled",
                 f"{len(enabled_cols)}", STEP_COMPLETE),
            srow("Columns Skipped",
                 f"{len(disabled_cols)}", TEXT_MUTED),
            srow("Standard Columns",
                 f"{len(standard_cols)}"),
            srow("Complex / JSON Columns",
                 f"{len(complex_cols)}",
                 "#4a9edd" if complex_cols else TEXT_MUTED),
            srow("Column-Level Checks",
                 f"{total_col_checks} total"),
            html.Div([
                # Header row
                html.Div(
                    dbc.Row([
                        dbc.Col(html.Small("Column",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=3),
                        dbc.Col(html.Small("Checks",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=5),
                        dbc.Col(html.Small("Warn %",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=2),
                        dbc.Col(html.Small("Crit %",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=2),
                    ]),
                    style={"padding"      : "6px 0",
                           "borderBottom" : f"1px solid {BORDER_COLOR}",
                           "marginBottom" : "2px"},
                ),
            ] + [
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            html.Small(
                                c,
                                style={"color"     : TEXT_PRIMARY,
                                       "fontWeight": "600"}
                            ),
                            dbc.Badge(
                                (
                                    normalize_dtype(
                                        col_config[c].get("dtype", "")
                                    ) + " · JSON"
                                ) if col_config[c].get("is_complex")
                                else normalize_dtype(
                                    col_config[c].get("dtype", "")
                                ),
                                color="info"
                                    if col_config[c].get("is_complex")
                                    else "secondary",
                                className="ms-2",
                                style={"fontSize": "10px",
                                       "verticalAlign": "middle"},
                            ),
                        ], md=3),
                        dbc.Col(
                            html.Small(
                                ", ".join(
                                    col_config[c].get("checks", [])
                                ) or "—",
                                style=MUTED_STYLE
                            ), md=5
                        ),
                        dbc.Col(
                            html.Small(
                                f"{col_config[c].get('warn_threshold', '—')}%",
                                style={"color": "#ffa500", "fontWeight": "600"}
                            ), md=2
                        ),
                        dbc.Col(
                            html.Small(
                                f"{col_config[c].get('crit_threshold', '—')}%",
                                style={"color": "#ff6b6b", "fontWeight": "600"}
                            ), md=2
                        ),
                    ])
                ], style={"padding"     : "5px 0",
                          "borderBottom": f"1px solid {BORDER_COLOR}"})
                for c in enabled_cols
            ], style={
                "maxHeight"      : "220px",
                "overflowY"      : "auto",
                "marginTop"      : "12px",
                "border"         : f"1px solid {BORDER_COLOR}",
                "borderRadius"   : "6px",
                "padding"        : "8px 12px",
                "backgroundColor": CARD_BG,
            }) if enabled_cols else html.Div(),
        ], style={**CARD_STYLE, "marginBottom": "16px"}),

        # Table checks
        html.Div([
            html.H6("🏷️ Table-Level Checks",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Checks Enabled",
                 f"{total_tbl_checks} of {len(TABLE_CHECK_TYPES)}"),
            html.Div([
                # Header row
                html.Div(
                    dbc.Row([
                        dbc.Col(html.Small("Check",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=5),
                        dbc.Col(html.Small("Status",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=3),
                        dbc.Col(html.Small("Warn %",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=2),
                        dbc.Col(html.Small("Crit %",
                            style={**MUTED_STYLE, "fontWeight": "700"}), md=2),
                    ]),
                    style={"padding"      : "6px 0",
                           "borderBottom" : f"1px solid {BORDER_COLOR}",
                           "marginBottom" : "2px"},
                ),
            ] + [
                html.Div([
                    dbc.Row([
                        dbc.Col(
                            html.Small(
                                chk["label"],
                                style={"color"     : TEXT_PRIMARY,
                                       "fontWeight": "600"}
                            ), md=5
                        ),
                        dbc.Col(
                            dbc.Badge(
                                "✓ Enabled"
                                if chk["id"] in enabled_checks
                                else "Disabled",
                                color=(
                                    "success"
                                    if chk["id"] in enabled_checks
                                    else "light"
                                ),
                                text_color=(
                                    "white"
                                    if chk["id"] in enabled_checks
                                    else "secondary"
                                ),
                            ), md=3
                        ),
                        dbc.Col([
                            html.Small(
                                f"{table_checks.get(chk['id'],{}).get('warn','—')}%",
                                style={"color": "#ffa500", "fontWeight": "600"}
                            ) if chk["warn"] is not None else html.Small("—", style=MUTED_STYLE),
                        ], md=2),
                        dbc.Col([
                            html.Small(
                                f"{table_checks.get(chk['id'],{}).get('crit','—')}%",
                                style={"color": "#ff6b6b", "fontWeight": "600"}
                            ) if chk["warn"] is not None else html.Small("—", style=MUTED_STYLE),
                        ], md=2),
                    ])
                ], style={"padding"     : "6px 0",
                          "borderBottom": f"1px solid {BORDER_COLOR}"})
                for chk in TABLE_CHECK_TYPES
            ], style={
                "marginTop"      : "12px",
                "border"         : f"1px solid {BORDER_COLOR}",
                "borderRadius"   : "6px",
                "padding"        : "8px 12px",
                "backgroundColor": CARD_BG,
            }),
        ], style={**CARD_STYLE, "marginBottom": "16px"}),

        # Baseline
        html.Div([
            html.H6("📊 Baseline Window",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Start Date",   bl_start),
            srow("End Date",     bl_end),
            srow("Window",       f"{days} days",
                 STEP_COMPLETE if days >= 14 else "#dc3545"),
            srow("Total Checks", f"{total_checks}"),
            srow("Recompute",    "Yes" if recompute else "No"),
            dbc.Alert(
                f"⚠️ Only {days} days selected. "
                f"Minimum 14 days recommended.",
                color="warning", className="mb-0 mt-2",
            ) if days < 14 else html.Div(),
        ], style={**CARD_STYLE, "marginBottom": "24px"}),

        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "← Back",
                    id      = "ob-back-5-visible",
                    color   = "light",
                    outline = True,
                    style   = {
                        "color"      : TEXT_PRIMARY,
                        "borderColor": BORDER_COLOR,
                        "marginRight": "12px",
                    }
                ),
                dbc.Button(
                    "🚀 Onboard Table",
                    id    = "ob-execute-btn-visible",
                    color = "primary",
                    size  = "lg",
                    style = {
                        "fontWeight": "700",
                        "padding"   : "10px 32px",
                    }
                ),
            ], className="d-flex align-items-center"),
        ]),
    ])


# ── Existing table summary ─────────────────────────────────────────────────

def build_existing_summary(existing: dict) -> html.Div:
    fqn = existing.get("fully_qualified_name", "—")

    def srow(label, value):
        return dbc.Row([
            dbc.Col(
                html.Small(label,
                           style={**MUTED_STYLE, "fontWeight": "600"}),
                md=4
            ),
            dbc.Col(
                html.Small(value,
                           style={"color"     : TEXT_PRIMARY,
                                  "fontWeight": "500"}),
                md=8
            ),
        ], className="mb-2")

    return html.Div([
        dbc.Alert([
            html.H5("⚠️ Table Already Registered", className="mb-1"),
            html.P(
                f"{fqn} is already registered in DataSentinel.",
                className="mb-0",
                style={"fontSize": "14px"}
            ),
        ], color="warning"),

        html.Div([
            html.H6(
                "Current Configuration",
                style={"color"       : TEXT_HEADING,
                       "fontWeight"  : "700",
                       "marginBottom": "16px"}
            ),
            srow("Table",              existing.get("table_name",            "—")),
            srow("FQN",                fqn),
            srow("Source Type",        existing.get("source_type",           "—")),
            srow("Ingestion Pattern",  existing.get("ingestion_pattern",     "—")),
            srow("Frequency",          existing.get("ingestion_frequency",   "—")),
            srow("Date Column",        existing.get("business_date_column",  "—")),
            srow("Registered By",      existing.get("registered_by",         "—")),
            srow("Registered",         existing.get("registered_timestamp",  "—")),
            srow("Columns Registered", str(existing.get("col_count",    0))),
            srow("Column Validations", str(existing.get("val_count",    0))),
            srow("Table Validations",  str(existing.get("tval_count",   0))),
            srow("Baselines Computed", str(existing.get("bl_count",     0))),
        ], style=CARD_STYLE),

        dbc.Row([
            dbc.Col([
                dbc.Button(
                    "✏️ Modify Configuration",
                    id    = "ob-modify-btn-visible",
                    color = "primary",
                    style = {
                        "marginRight": "12px",
                        "fontWeight" : "600",
                    }
                ),
                dbc.Button(
                    "← Choose Different Table",
                    id      = "ob-back-existing-visible",
                    color   = "light",
                    outline = True,
                    style   = {
                        "color"      : TEXT_PRIMARY,
                        "borderColor": BORDER_COLOR,
                    }
                ),
            ], className="d-flex align-items-center"),
        ]),
    ])

def _run_onboarding(
    table_meta  : dict,
    col_config  : dict,
    table_checks: dict,
    baseline    : dict,
) -> dict:
    """
    Executes all onboarding steps and returns a structured
    status dict for the progress modal.
    """
    fqn      = (
        f"{table_meta['catalog']}."
        f"{table_meta['schema']}."
        f"{table_meta['table_name']}"
    )
    tname    = table_meta["table_name"]
    date_col = table_meta.get("date_column", "inserted_dt")
    has_date = date_col and date_col != _NO_DATE_COL_VALUE
    bl_start = baseline.get("window_start")
    bl_end   = baseline.get("window_end")
    recompute= baseline.get("recompute", True)
    today    = str(date.today())

    # Build reusable WHERE clause for baseline queries
    if has_date and bl_start and bl_end:
        _date_where = (
            f"WHERE CAST(`{date_col}` AS DATE) "
            f"BETWEEN :bl_start AND :bl_end"
        )
        _date_where_and = (
            f"AND CAST(`{date_col}` AS DATE) "
            f"BETWEEN :bl_start AND :bl_end"
        )
        _date_params = {"bl_start": bl_start, "bl_end": bl_end}
    else:
        _date_where     = ""
        _date_where_and = ""
        _date_params    = {}

    steps   = []
    all_ok  = True

    col_count  = 0
    val_count  = 0
    tval_count = 0
    bl_count   = 0

    # A single shared connection for the whole run: each step below used to
    # open its own SQL-warehouse session (~1s each), and a table with many
    # columns/checks easily racked up 50-100+ of those sequentially — enough
    # to blow past the Databricks Apps 120s reverse-proxy request timeout
    # and leave the review page's spinner hanging with no visible error.
    conn = get_connection()

    # ── Step A: Register table ─────────────────────────────────────────────
    try:
        execute_write(
            f"""
            INSERT INTO {PREFIX}uc1_table_registry_b (
                table_id,
                table_catalog,
                table_schema,
                table_name,
                fully_qualified_name,
                source_type,
                ingestion_pattern,
                ingestion_frequency,
                business_date_column,
                is_active,
                registered_timestamp,
                registered_by
            ) VALUES (
                :table_id,
                :table_catalog,
                :table_schema,
                :table_name,
                :fully_qualified_name,
                :source_type,
                :ingestion_pattern,
                :ingestion_frequency,
                :business_date_column,
                true,
                current_timestamp(),
                'onboarding_wizard'
            )
        """,
            {
                "table_id": str(uuid.uuid4()),
                "table_catalog": table_meta.get("catalog", TARGET_CATALOG),
                "table_schema": table_meta.get("schema", TARGET_SCHEMA),
                "table_name": tname,
                "fully_qualified_name": fqn,
                "source_type": table_meta.get("ingestion_type", "FILE"),
                "ingestion_pattern": table_meta.get("layer", "BRONZE"),
                "ingestion_frequency": table_meta.get("ingestion_frequency", "DAILY"),
                "business_date_column": (
                    table_meta.get("date_column", "")
                    if table_meta.get("date_column") != _NO_DATE_COL_VALUE
                    else ""
                ),
            },
            conn=conn,
        )
        steps.append({
            "label" : "Table registered in registry",
            "state" : "done",
            "detail": fqn,
        })
    except Exception as e:
        steps.append({
            "label" : "Table registration",
            "state" : "error",
            "detail": str(e)[:120],
        })
        all_ok = False

    # ── Step B: Register columns ───────────────────────────────────────────
    # One multi-row INSERT instead of one INSERT per column: with a shared
    # connection each row was still a separate warehouse round-trip
    # (~1-1.5s), so a table with dozens of columns added tens of seconds on
    # its own. Batching trades per-row error isolation (a single bad row
    # fails the whole step) for a large latency win, which is the right
    # call here since these values are wizard-generated, not free text.
    col_err = []
    col_rows, col_params = [], {"fully_qualified_name": fqn}
    for i, (cname, cfg) in enumerate(col_config.items()):
        col_rows.append(f"""(
            :column_id_{i}, :fully_qualified_name, :column_name_{i},
            :expected_data_type_{i}, :is_nullable_{i}, :is_active_{i},
            false, current_timestamp(), 'onboarding_wizard'
        )""")
        col_params.update({
            f"column_id_{i}"          : str(uuid.uuid4()),
            f"column_name_{i}"        : cname,
            f"expected_data_type_{i}" : cfg.get("dtype", "STRING"),
            f"is_nullable_{i}"        : bool(cfg.get("nullable", True)),
            f"is_active_{i}"          : bool(cfg.get("enabled", True)),
        })

    if col_rows:
        try:
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc1_column_registry_b (
                    column_id,
                    fully_qualified_name,
                    column_name,
                    expected_data_type,
                    is_nullable,
                    is_active,
                    is_business_key,
                    created_timestamp,
                    created_by
                ) VALUES {", ".join(col_rows)}
            """,
                col_params,
                conn=conn,
            )
            col_count = len(col_config)
        except Exception as e:
            col_err.append(str(e)[:120])

    if col_err:
        all_ok = False
    steps.append({
        "label" : "Columns registered",
        "state" : "done" if not col_err else "error",
        "detail": (
            f"{col_count} of {len(col_config)} columns registered"
            + (f" | {len(col_err)} errors" if col_err else "")
        ),
    })

    # ── Step C: Column validations ─────────────────────────────────────────
    # Batched for the same reason as Step B — this loop is usually the
    # largest (columns × checks-per-column), so it's the biggest single
    # contributor to the wizard's wall-clock time.
    val_err = []
    val_rows, val_params = [], {"fully_qualified_name": fqn}
    i = 0
    for cname, cfg in col_config.items():
        if not cfg.get("enabled", True):
            continue
        for check_type in cfg.get("checks", []):
            val_rows.append(f"""(
                :column_validation_id_{i}, :fully_qualified_name, :column_name_{i},
                :validation_name_{i}, true, :warning_threshold_{i},
                :critical_threshold_{i}, 'PERCENT', current_timestamp(), 'onboarding_wizard'
            )""")
            val_params.update({
                f"column_validation_id_{i}" : str(uuid.uuid4()),
                f"column_name_{i}"          : cname,
                f"validation_name_{i}"      : check_type,
                f"warning_threshold_{i}"    : float(cfg.get("warn_threshold", 5)),
                f"critical_threshold_{i}"   : float(cfg.get("crit_threshold", 10)),
            })
            i += 1

    if val_rows:
        try:
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc1_column_validation_registry_b (
                    column_validation_id,
                    fully_qualified_name,
                    column_name,
                    validation_name,
                    is_active,
                    warning_threshold,
                    critical_threshold,
                    threshold_unit,
                    created_timestamp,
                    created_by
                ) VALUES {", ".join(val_rows)}
            """,
                val_params,
                conn=conn,
            )
            val_count = i
        except Exception as e:
            val_err.append(str(e)[:120])

    if val_err:
        all_ok = False
    steps.append({
        "label" : "Column validation rules configured",
        "state" : "done" if not val_err else "error",
        "detail": (
            f"{val_count} validation rules created"
            + (f" | {len(val_err)} errors" if val_err else "")
        ),
    })

    # ── Step D: Table checks ───────────────────────────────────────────────
    tval_err = []
    tval_rows, tval_params = [], {"fully_qualified_name": fqn}
    i = 0
    for chk_id, cfg in table_checks.items():
        if not cfg.get("enabled", False):
            continue
        warn = cfg.get("warn")
        crit = cfg.get("crit")
        tval_rows.append(f"""(
            :table_validation_id_{i}, :fully_qualified_name, :validation_name_{i},
            true, :warning_threshold_{i}, :critical_threshold_{i},
            'PERCENT', current_timestamp(), 'onboarding_wizard'
        )""")
        tval_params.update({
            f"table_validation_id_{i}" : str(uuid.uuid4()),
            f"validation_name_{i}"     : chk_id,
            f"warning_threshold_{i}"   : None if warn is None else float(warn),
            f"critical_threshold_{i}"  : None if crit is None else float(crit),
        })
        i += 1

    if tval_rows:
        try:
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc1_table_validation_registry_b (
                    table_validation_id,
                    fully_qualified_name,
                    validation_name,
                    is_active,
                    warning_threshold,
                    critical_threshold,
                    threshold_unit,
                    created_timestamp,
                    created_by
                ) VALUES {", ".join(tval_rows)}
            """,
                tval_params,
                conn=conn,
            )
            tval_count = i
        except Exception as e:
            tval_err.append(str(e)[:120])

    if tval_err:
        all_ok = False
    steps.append({
        "label" : "Table-level checks configured",
        "state" : "done" if not tval_err else "error",
        "detail": (
            f"{tval_count} table checks enabled"
            + (f" | {len(tval_err)} errors" if tval_err else "")
        ),
    })

    # ── Step E: Baselines ──────────────────────────────────────────────────
    if not recompute:
        steps.append({
            "label" : "Baseline computation",
            "state" : "done",
            "detail": "Skipped — recompute not selected",
        })
    elif not has_date and (not bl_start or not bl_end):
        # No date column — baselines use full table, no window needed
        bl_start = None
        bl_end   = None
        bl_err   = []
        days_in_window = 0
        # fall through to baseline computation below
    elif has_date and (not bl_start or not bl_end):
        steps.append({
            "label" : "Baseline computation",
            "state" : "error",
            "detail": "No baseline window dates provided",
        })
        all_ok = False

    if recompute and (has_date and bl_start and bl_end or not has_date):
        bl_err = []
        try:
            days_in_window = (
                date.fromisoformat(bl_end) -
                date.fromisoformat(bl_start)
            ).days + 1
        except Exception:
            days_in_window = 30

        def insert_baseline(
            col_name, check_type, metric_name,
            mean, stddev, min_val, max_val,
            p25, p50, p75, p95, sample_count
        ):
            execute_write(
                f"""
                INSERT INTO {PREFIX}uc1_baseline_metrics_b (
                    baseline_id,
                    fully_qualified_name,
                    column_name,
                    check_type,
                    metric_name,
                    baseline_date,
                    baseline_window_days,
                    expected_value,
                    mean_value,
                    stddev_value,
                    min_value,
                    max_value,
                    p25_value,
                    p50_value,
                    p75_value,
                    p95_value,
                    sample_count,
                    is_sufficient_data,
                    baseline_status,
                    computed_timestamp,
                    computed_by
                ) VALUES (
                    :baseline_id,
                    :fully_qualified_name,
                    :column_name,
                    :check_type,
                    :metric_name,
                    :baseline_date,
                    :baseline_window_days,
                    :expected_value,
                    :mean_value,
                    :stddev_value,
                    :min_value,
                    :max_value,
                    :p25_value,
                    :p50_value,
                    :p75_value,
                    :p95_value,
                    :sample_count,
                    :is_sufficient_data,
                    'ACTIVE',
                    current_timestamp(),
                    'onboarding_wizard'
                )
            """,
                {
                    "baseline_id": str(uuid.uuid4()),
                    "fully_qualified_name": fqn,
                    "column_name": col_name,
                    "check_type": check_type,
                    "metric_name": metric_name,
                    "baseline_date": str(today),
                    "baseline_window_days": days_in_window,
                    "expected_value": mean,
                    "mean_value": mean,
                    "stddev_value": stddev or 0,
                    "min_value": min_val,
                    "max_value": max_val,
                    "p25_value": p25 if p25 is not None else min_val,
                    "p50_value": p50 if p50 is not None else mean,
                    "p75_value": p75 if p75 is not None else max_val,
                    "p95_value": p95 if p95 is not None else max_val,
                    "sample_count": sample_count,
                    "is_sufficient_data": bool(sample_count >= 14),
                },
                conn=conn,
            )

        # Volume
        try:
            df_vol = execute_query(f"""
                SELECT
                    AVG(daily_count)             AS mean,
                    STDDEV(daily_count)           AS stddev,
                    MIN(daily_count)              AS min_val,
                    MAX(daily_count)              AS max_val,
                    PERCENTILE(daily_count, 0.25) AS p25,
                    PERCENTILE(daily_count, 0.50) AS p50,
                    PERCENTILE(daily_count, 0.75) AS p75,
                    PERCENTILE(daily_count, 0.95) AS p95,
                    COUNT(*)                      AS days
                FROM (
                    SELECT
                        CAST({date_col} AS DATE) AS dt,
                        COUNT(*)                 AS daily_count
                    FROM {fqn}
                    {_date_where}
                    GROUP BY CAST({date_col} AS DATE)
                )
            """, _date_params, conn=conn)
            if (not df_vol.empty and
                    df_vol.iloc[0]["mean"] is not None):
                r = df_vol.iloc[0]
                insert_baseline(
                    "_table_", "VOLUME_ANOMALY", "daily_row_count",
                    float(r["mean"]),
                    float(r["stddev"] or 0),
                    float(r["min_val"]),
                    float(r["max_val"]),
                    float(r["p25"]),
                    float(r["p50"]),
                    float(r["p75"]),
                    float(r["p95"]),
                    int(r["days"]),
                )
                bl_count += 1
        except Exception as e:
            bl_err.append(f"VOLUME: {str(e)[:80]}")

        # Column baselines
        for cname, cfg in col_config.items():
            if not cfg.get("enabled", True):
                continue
            checks = cfg.get("checks", [])
            dtype  = normalize_dtype(cfg.get("dtype", "STRING"))
            # Nested paths (a.b, a.items.b) need LATERAL VIEW explode in FROM;
            # pass the root column's type so resolution is schema-aware.
            top_dt = None
            if is_nested_path(cname):
                root   = cfg.get("parent_column") or path_root(cname)
                top_dt = (col_config.get(root) or {}).get("dtype")
            try:
                src_sql, cexpr = nested_sql_source(fqn, cname, top_dt)
            except ValueError as e:
                bl_err.append(f"{cname}: {str(e)[:80]}")
                continue
            is_num = dtype in (
                "INT", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL"
            )

            if "NULL_SPIKE" in checks:
                try:
                    df_nr = execute_query(f"""
                        SELECT
                            AVG(CASE WHEN {cexpr} IS NULL
                                THEN 1.0 ELSE 0.0 END) * 100 AS null_rate,
                            COUNT(*) AS cnt
                        FROM {src_sql}
                        {_date_where}
                    """, _date_params, conn=conn)
                    if (not df_nr.empty and
                            df_nr.iloc[0]["null_rate"] is not None):
                        r = df_nr.iloc[0]
                        insert_baseline(
                            cname, "NULL_SPIKE",
                            f"{cname}_null_spike",
                            float(r["null_rate"]), 0,
                            0, 100, 0,
                            float(r["null_rate"]),
                            float(r["null_rate"]),
                            100, int(r["cnt"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(f"NULL_SPIKE/{cname}: {str(e)[:60]}")

            if "NUMERIC_RANGE" in checks and is_num:
                try:
                    df_rr = execute_query(f"""
                        SELECT
                            AVG(CAST({cexpr} AS DOUBLE))              AS mean,
                            STDDEV(CAST({cexpr} AS DOUBLE))           AS stddev,
                            MIN(CAST({cexpr} AS DOUBLE))              AS min_val,
                            MAX(CAST({cexpr} AS DOUBLE))              AS max_val,
                            PERCENTILE(CAST({cexpr} AS DOUBLE), 0.25) AS p25,
                            PERCENTILE(CAST({cexpr} AS DOUBLE), 0.50) AS p50,
                            PERCENTILE(CAST({cexpr} AS DOUBLE), 0.75) AS p75,
                            PERCENTILE(CAST({cexpr} AS DOUBLE), 0.95) AS p95,
                            COUNT(*)                                   AS cnt
                        FROM {src_sql}
                        {_date_where}
                          {'AND' if _date_where else 'WHERE'} {cexpr} IS NOT NULL
                    """, _date_params, conn=conn)
                    if (not df_rr.empty and
                            df_rr.iloc[0]["mean"] is not None):
                        r = df_rr.iloc[0]
                        insert_baseline(
                            cname, "NUMERIC_RANGE",
                            f"{cname}_numeric_range",
                            float(r["mean"]),
                            float(r["stddev"] or 0),
                            float(r["min_val"]),
                            float(r["max_val"]),
                            float(r["p25"]),
                            float(r["p50"]),
                            float(r["p75"]),
                            float(r["p95"]),
                            int(r["cnt"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(f"RANGE/{cname}: {str(e)[:60]}")

            if "DISTRIBUTION_DRIFT" in checks and is_num and has_date:
                try:
                    df_an = execute_query(f"""
                        SELECT
                            AVG(daily_avg)                        AS mean,
                            STDDEV(daily_avg)                     AS stddev,
                            MIN(daily_avg)                        AS min_val,
                            MAX(daily_avg)                        AS max_val,
                            PERCENTILE(daily_avg, 0.25)           AS p25,
                            PERCENTILE(daily_avg, 0.50)           AS p50,
                            PERCENTILE(daily_avg, 0.75)           AS p75,
                            PERCENTILE(daily_avg, 0.95)           AS p95,
                            COUNT(*)                              AS days
                        FROM (
                            SELECT
                                CAST({date_col} AS DATE)     AS dt,
                                AVG(CAST({cexpr} AS DOUBLE)) AS daily_avg
                            FROM {src_sql}
                            {_date_where}
                              {'AND' if _date_where else 'WHERE'} {cexpr} IS NOT NULL
                            GROUP BY CAST({date_col} AS DATE)
                        )
                    """, _date_params, conn=conn)
                    if (not df_an.empty and
                            df_an.iloc[0]["mean"] is not None):
                        r = df_an.iloc[0]
                        insert_baseline(
                            cname, "DISTRIBUTION_DRIFT",
                            f"{cname}_distribution_drift",
                            float(r["mean"]),
                            float(r["stddev"] or 0),
                            float(r["min_val"]),
                            float(r["max_val"]),
                            float(r["p25"]),
                            float(r["p50"]),
                            float(r["p75"]),
                            float(r["p95"]),
                            int(r["days"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(
                        f"ANOMALY/{cname}: {str(e)[:60]}"
                    )

            # ── JSON / complex column checks ──────────────────────
            is_cplx = cfg.get("is_complex", False)

            if "JSON_VALID" in checks and is_cplx:
                try:
                    df_jv = execute_query(f"""
                        SELECT
                            COUNT(*) AS total,
                            SUM(CASE
                                WHEN {cname} IS NULL THEN 0
                                WHEN from_json({cname}, 'MAP<STRING,STRING>')
                                     IS NOT NULL THEN 1
                                ELSE 0
                            END) AS valid_json,
                            AVG(CASE
                                WHEN {cname} IS NULL THEN NULL
                                WHEN from_json({cname}, 'MAP<STRING,STRING>')
                                     IS NOT NULL THEN 0.0
                                ELSE 1.0
                            END) * 100 AS invalid_pct
                        FROM {fqn}
                        {_date_where}
                    """, _date_params, conn=conn)
                    if not df_jv.empty:
                        r = df_jv.iloc[0]
                        inv_pct = float(r["invalid_pct"] or 0)
                        insert_baseline(
                            cname, "JSON_VALID",
                            f"{cname}_json_valid",
                            inv_pct, 0, 0, 100, 0,
                            inv_pct, inv_pct,
                            100, int(r["total"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(f"JSON_VALID/{cname}: {str(e)[:60]}")

            if "KEY_CARDINALITY" in checks and is_cplx:
                try:
                    df_kc = execute_query(f"""
                        WITH keys AS (
                            SELECT explode(map_keys(
                                from_json({cname}, 'MAP<STRING,STRING>')
                            )) AS k
                            FROM {fqn}
                            {_date_where}
                              {'AND' if _date_where else 'WHERE'} {cexpr} IS NOT NULL
                        )
                        SELECT
                            COUNT(DISTINCT k) AS distinct_keys,
                            COUNT(*) AS total_keys
                        FROM keys
                    """, _date_params, conn=conn)
                    if not df_kc.empty:
                        r = df_kc.iloc[0]
                        dk = float(r["distinct_keys"] or 0)
                        insert_baseline(
                            cname, "KEY_CARDINALITY",
                            f"{cname}_key_cardinality",
                            dk, 0, dk, dk, dk, dk, dk,
                            100, int(r["total_keys"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(f"KEY_CARD/{cname}: {str(e)[:60]}")

            if "SCHEMA_DRIFT" in checks and is_cplx and has_date:
                try:
                    df_sd = execute_query(f"""
                        WITH keys AS (
                            SELECT
                                CAST({date_col} AS DATE) AS dt,
                                sort_array(collect_set(
                                    explode(map_keys(
                                        from_json({cname}, 'MAP<STRING,STRING>')
                                    ))
                                )) AS key_set
                            FROM {fqn}
                            {_date_where}
                              {'AND' if _date_where else 'WHERE'} {cexpr} IS NOT NULL
                            GROUP BY CAST({date_col} AS DATE)
                        )
                        SELECT COUNT(DISTINCT key_set) AS schema_variants,
                               COUNT(*) AS days
                        FROM keys
                    """, _date_params, conn=conn)
                    if not df_sd.empty:
                        r = df_sd.iloc[0]
                        sv = float(r["schema_variants"] or 1)
                        insert_baseline(
                            cname, "SCHEMA_DRIFT",
                            f"{cname}_schema_drift",
                            sv, 0, 1, sv, 1, sv, sv,
                            100, int(r["days"]),
                        )
                        bl_count += 1
                except Exception as e:
                    bl_err.append(f"SCHEMA_DRIFT/{cname}: {str(e)[:60]}")

        if bl_err:
            all_ok = False
        steps.append({
            "label" : "Statistical baselines computed",
            "state" : "done" if not bl_err else "error",
            "detail": (
                f"{bl_count} baselines computed "
                f"over {days_in_window}-day window"
                + (f" | {len(bl_err)} errors" if bl_err else "")
            ),
        })

    conn.close()

    return {
        "steps"     : steps,
        "done"      : True,
        "all_ok"    : all_ok,
        "col_count" : col_count,
        "val_count" : val_count,
        "tval_count": tval_count,
        "bl_count"  : bl_count,
    }


# ══════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════════════════════════════════
@callback(
    Output("ob-exec-modal",      "is_open",  allow_duplicate=True),
    Output("ob-exec-modal-body", "children", allow_duplicate=True),
    Output("ob-exec-status",     "data",     allow_duplicate=True),
    Input("ob-execute-btn-visible", "n_clicks"),
    State("ob-table-meta",   "data"),
    prevent_initial_call=True,
)
def open_exec_modal(n_clicks, table_meta):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    tname = (table_meta or {}).get("table_name", "")
    fqn   = (table_meta or {}).get("fqn", "")

    # Build pending UI
    pending_body = html.Div([
        html.Div([
            html.Small("Table: ", style={"color": TEXT_MUTED,
                                         "fontSize": "12px"}),
            html.Small(fqn or tname,
                       style={"color"     : TEXT_PRIMARY,
                              "fontWeight": "600",
                              "fontSize"  : "12px",
                              "fontFamily": "monospace"}),
        ], style={"marginBottom": "16px"}),

        dbc.Progress(
            value    = 0,
            animated = True,
            striped  = True,
            color    = "primary",
            style    = {"height": "8px", "marginBottom": "24px"},
        ),

        html.Div([
            dbc.Spinner(size="sm", color="primary",
                        spinner_style={"marginRight": "10px"}),
            html.Span("Onboarding in progress — please wait…",
                      style={"color"    : TEXT_PRIMARY,
                             "fontSize" : "14px",
                             "fontWeight": "500"}),
        ], style={"display"    : "flex",
                  "alignItems" : "center",
                  "marginBottom": "24px"}),

        html.Div([
            html.Div([
                dbc.Row([
                    dbc.Col(
                        html.Span("○", style={"fontSize"   : "16px",
                                              "color"      : STEP_INACTIVE,
                                              "marginRight": "10px"}),
                        md=1,
                        style={"display": "flex", "alignItems": "center"}
                    ),
                    dbc.Col(
                        html.Span(label,
                                  style={"color"   : TEXT_MUTED,
                                         "fontSize": "13px"}),
                        md=11
                    ),
                ], className="align-items-center"),
            ], style={"padding"        : "10px 16px",
                      "borderBottom"   : f"1px solid {BORDER_COLOR}",
                      "backgroundColor": PAGE_BG})
            for label in [
                "Registering table in registry",
                "Registering columns",
                "Configuring column validation rules",
                "Configuring table-level checks",
                "Computing statistical baselines",
            ]
        ], style={"border"      : f"1px solid {BORDER_COLOR}",
                  "borderRadius": "8px",
                  "overflow"    : "hidden"}),
    ])

    return True, pending_body, {"pending": True}

@callback(
    Output("ob-exec-modal-body", "children", allow_duplicate=True),
    Output("ob-exec-status",     "data",     allow_duplicate=True),
    Input("ob-exec-status",      "data"),
    State("ob-table-meta",   "data"),
    State("ob-col-config",   "data"),
    State("ob-table-checks", "data"),
    State("ob-baseline",     "data"),
    background=True,
    prevent_initial_call=True,
)
def run_onboarding(
    status, table_meta, col_config, table_checks, baseline
):
    # Only run when status is pending
    if not status or not status.get("pending"):
        raise dash.exceptions.PreventUpdate

    if not table_meta or not table_meta.get("table_name"):
        raise dash.exceptions.PreventUpdate

    tname = table_meta.get("table_name", "")
    fqn   = table_meta.get("fqn", "")

    # Run onboarding
    results = _run_onboarding(
        table_meta, col_config, table_checks, baseline
    )

    steps      = results.get("steps",     [])
    ok         = results.get("all_ok",    False)
    col_count  = results.get("col_count",  0)
    val_count  = results.get("val_count",  0)
    tval_count = results.get("tval_count", 0)
    bl_count   = results.get("bl_count",   0)

    done_count = sum(1 for s in steps
                     if s.get("state") in ("done", "error"))
    pct = int((done_count / len(steps)) * 100) if steps else 100

    # Build step rows
    step_rows = []
    for s in steps:
        state  = s.get("state",  "pending")
        label  = s.get("label",  "")
        detail = s.get("detail", "")

        if state == "done":
            icon       = "✅"
            icon_color = STEP_COMPLETE
            lbl_color  = TEXT_PRIMARY
            row_bg     = "rgba(0, 200, 81, 0.08)"
        elif state == "error":
            icon       = "❌"
            icon_color = "#dc3545"
            lbl_color  = "#dc3545"
            row_bg     = "rgba(220, 53, 69, 0.08)"
        else:
            icon       = "○"
            icon_color = STEP_INACTIVE
            lbl_color  = TEXT_MUTED
            row_bg     = PAGE_BG

        step_rows.append(
            html.Div([
                dbc.Row([
                    dbc.Col(
                        html.Span(icon,
                                  style={"fontSize"   : "18px",
                                         "color"      : icon_color,
                                         "marginRight": "8px"}),
                        md=1,
                        style={"display"   : "flex",
                               "alignItems": "center"}
                    ),
                    dbc.Col([
                        html.Div(label,
                                 style={"fontWeight": "600",
                                        "color"     : lbl_color,
                                        "fontSize"  : "13px"}),
                        html.Small(detail,
                                   style={"color"   : TEXT_MUTED,
                                          "fontSize": "11px"}),
                    ], md=11),
                ], className="align-items-center"),
            ], style={
                "padding"        : "10px 16px",
                "borderBottom"   : f"1px solid {BORDER_COLOR}",
                "backgroundColor": row_bg,
            })
        )

    # Banner
    if ok:
        banner = dbc.Alert([
            html.H5("🎉 Table Successfully Onboarded!",
                    className="mb-1"),
            html.P(
                f"{tname} is now registered and ready for "
                f"automated data quality monitoring.",
                className="mb-0",
                style={"fontSize": "13px"}
            ),
        ], color="success", className="mb-3")
    else:
        banner = dbc.Alert([
            html.H5("⚠️ Completed with Errors",
                    className="mb-1"),
            html.P(
                "Some steps failed. Successful steps have been saved.",
                className="mb-0",
                style={"fontSize": "13px"}
            ),
        ], color="warning", className="mb-3")

    # Stats
    def stat_box(label, value):
        return html.Div([
            html.Div(str(value),
                     style={"fontSize"  : "28px",
                             "fontWeight": "800",
                             "color"     : STEP_COMPLETE,
                             "fontFamily": "monospace",
                             "lineHeight": "1"}),
            html.Small(label, style=MUTED_STYLE),
        ], style={
            "textAlign"      : "center",
            "padding"        : "14px 8px",
            "backgroundColor": PAGE_BG,
            "borderRadius"   : "8px",
            "border"         : f"1px solid {BORDER_COLOR}",
        })

    stats = dbc.Row([
        dbc.Col(stat_box("Columns",    col_count),  md=3),
        dbc.Col(stat_box("Col Rules",  val_count),  md=3),
        dbc.Col(stat_box("Tbl Checks", tval_count), md=3),
        dbc.Col(stat_box("Baselines",  bl_count),   md=3),
    ], className="mb-3 g-2")

    # Action buttons
    action_buttons = dbc.Row([
        dbc.Col([
            dbc.Button("🔍 View Validation Results",
                       href="/validation-results",
                       color="primary", size="sm",
                       style={"marginRight": "8px",
                              "fontWeight" : "600"}),
            dbc.Button("📋 Table Registry",
                       href="/table-registry",
                       color="outline-secondary",
                       outline=True, size="sm",
                       style={"marginRight": "8px"}),
            dbc.Button("➕ Onboard Another",
                       id="ob-restart-btn",
                       color="outline-primary",
                       outline=True, size="sm"),
        ], className="d-flex flex-wrap gap-2"),
    ], className="mt-3")

    # Table info
    table_info = html.Div([
        html.Small("Table: ",
                   style={"color": TEXT_MUTED, "fontSize": "12px"}),
        html.Small(fqn or tname,
                   style={"color"     : TEXT_PRIMARY,
                          "fontWeight": "600",
                          "fontSize"  : "12px",
                          "fontFamily": "monospace"}),
    ], style={"marginBottom": "16px"})

    modal_body = html.Div([
        table_info,
        dbc.Progress(
            value = pct,
            label = f"{pct}%",
            color = "success" if ok else "warning",
            style = {"height": "8px", "marginBottom": "20px"},
        ),
        banner,
        stats,
        html.Div(step_rows, style={
            "border"         : f"1px solid {BORDER_COLOR}",
            "borderRadius"   : "8px",
            "overflow"       : "hidden",
            "marginBottom"   : "16px",
            "backgroundColor": CARD_BG,
        }),
        action_buttons,
    ])

    # Clear pending flag in status
    results["pending"] = False
    return modal_body, results
# ── Catalog options on page load ───────────────────────────────────────────

@callback(
    Output("ob-catalog", "options"),
    Output("ob-catalog", "value"),
    Input("ob-wizard-page", "id"),
)
def load_catalogs(_):
    try:
        df = execute_query("SHOW CATALOGS")
        logger.info(f"load_catalogs: {df.columns.tolist()} "
                    f"{len(df)} rows")
        if df.empty:
            return [], None
        col     = _find_col(
            df, ["catalog", "catalogName", "catalog_name"],
            fallback_idx=0
        )
        options = [{"label": r, "value": r}
                   for r in df[col].tolist()]
        default = TARGET_CATALOG if any(
            o["value"] == TARGET_CATALOG for o in options
        ) else None
        return options, default
    except Exception as e:
        logger.error(f"load_catalogs failed: {e}")
        return [], None


# ── Schema options ─────────────────────────────────────────────────────────

@callback(
    Output("ob-schema",  "options"),
    Output("ob-schema",  "placeholder"),
    Input("ob-catalog",  "value"),
)
def load_schemas(catalog):
    if not catalog:
        return [], "Select catalog first…"
    try:
        validate_identifier(catalog)
        df = execute_query(f"SHOW SCHEMAS IN {catalog}")
        if df.empty:
            return [], "No schemas found"
        col = _find_col(
            df,
            ["databaseName", "namespace", "schema", "schemaName"],
            fallback_idx=0
        )
        return (
            [{"label": r, "value": r} for r in df[col].tolist()],
            "Select schema…"
        )
    except Exception as e:
        logger.error(f"load_schemas failed: {e}")
        return [], f"Error: {e}"


# ── Table options ──────────────────────────────────────────────────────────

@callback(
    Output("ob-table",  "options"),
    Output("ob-table",  "placeholder"),
    Input("ob-schema",  "value"),
    State("ob-catalog", "value"),
)
def load_tables(schema, catalog):
    if not schema or not catalog:
        return [], "Select schema first…"
    try:
        df = execute_query(
            f"SHOW TABLES IN {catalog}.{schema}"
        )
        if df.empty:
            return [], "No tables found"
        col = _find_col(
            df,
            ["tableName", "table_name", "table"],
            fallback_idx=1
        )
        return (
            [{"label": r, "value": r} for r in df[col].tolist()],
            "Select table…"
        )
    except Exception as e:
        logger.error(f"load_tables failed: {e}")
        return [], f"Error: {e}"


# ── Date column options ────────────────────────────────────────────────────

@callback(
    Output("ob-date-col", "options"),
    Output("ob-date-col", "value"),
    Input("ob-table",     "value"),
    State("ob-catalog",   "value"),
    State("ob-schema",    "value"),
)
def load_date_columns(table, catalog, schema):
    if not table or not catalog or not schema:
        return [], None
    try:
        fqn = f"{catalog}.{schema}.{table}"
        validate_identifier(fqn)
        df = execute_query(f"DESCRIBE TABLE {fqn}")
        if df.empty:
            return [_NO_DATE_COL_OPTION], _NO_DATE_COL_VALUE

        DATE_TYPES = {
            "DATE", "TIMESTAMP", "TIMESTAMP_NTZ",
            "DATETIME", "TIMESTAMP_LTZ",
        }
        # Common date-like column names (for STRING columns)
        DATE_NAME_HINTS = {
            "date", "created", "updated", "modified", "timestamp",
            "created_at", "updated_at", "event_time", "event_date",
            "load_date", "inserted_dt", "business_date", "run_date",
            "partition_date", "record_date", "file_date",
            "transaction_date", "start", "end",
            "__start_at", "__end_at", "_commit_timestamp",
        }
        PRIORITY = [
            "business_date", "inserted_dt", "updated_dt",
            "created", "updated", "created_at", "updated_at",
            "transaction_date", "event_date", "load_date",
            "created_date", "modified_date", "run_date",
            "partition_date", "record_date", "file_date",
            "__start_at",
        ]

        date_cols = []
        string_candidates = []

        for _, row in df.iterrows():
            cname      = str(row.iloc[0]).strip()
            dtype      = str(row.iloc[1]).strip() \
                         if len(df.columns) > 1 else ""
            dtype_norm = dtype.upper().split("(")[0].split("<")[0].strip()
            if not cname or cname.startswith("#"):
                continue
            if dtype_norm in DATE_TYPES:
                date_cols.append({
                    "name" : cname,
                    "dtype": dtype_norm,
                    "tag"  : dtype_norm,
                })
            elif dtype_norm == "STRING" and \
                    cname.lower() in DATE_NAME_HINTS:
                string_candidates.append(cname)

        # Probe STRING candidates: sample 5 rows and check
        # if values parse as dates
        if string_candidates:
            try:
                sample_cols = ", ".join(
                    f"`{c}` AS `{c}`" for c in string_candidates
                )
                df_sample = execute_query(
                    f"SELECT {sample_cols} FROM {fqn} "
                    f"WHERE {string_candidates[0]} IS NOT NULL "
                    f"LIMIT 5"
                )
                import re
                date_re = re.compile(
                    r"^\d{4}-\d{2}-\d{2}"
                )
                for sc in string_candidates:
                    if sc in df_sample.columns:
                        vals = df_sample[sc].dropna().astype(str)
                        if len(vals) > 0 and all(
                            date_re.match(v) for v in vals
                        ):
                            date_cols.append({
                                "name" : sc,
                                "dtype": "STRING",
                                "tag"  : "STRING → DATE",
                            })
            except Exception as probe_err:
                logger.warning(
                    f"Date probe failed: {probe_err}"
                )

        # Build options — always include "no date column"
        options = [
            {"label": f"{c['name']}  ({c['tag']})",
             "value": c["name"]}
            for c in date_cols
        ]
        options.append(_NO_DATE_COL_OPTION)

        if not date_cols:
            return options, _NO_DATE_COL_VALUE

        # Auto-select best default
        col_lower = [c["name"].lower() for c in date_cols]
        default   = None
        for p in PRIORITY:
            if p.lower() in col_lower:
                default = date_cols[col_lower.index(p.lower())]["name"]
                break
        if default is None:
            default = date_cols[0]["name"]

        return options, default

    except Exception as e:
        logger.error(f"load_date_columns failed: {e}")
        return [_NO_DATE_COL_OPTION], _NO_DATE_COL_VALUE


# ── Baseline warning (reads from visible pickers) ─────────────────────────

@callback(
    Output("ob-baseline-warning-visible", "children"),
    Input("ob-baseline-start-visible",    "date"),
    Input("ob-baseline-end-visible",      "date"),
)
def baseline_warning_visible(start, end):
    if not start or not end:
        return html.Div()
    try:
        days = (
            date.fromisoformat(end) -
            date.fromisoformat(start)
        ).days + 1
        if days < 14:
            return dbc.Alert(
                f"⚠️ {days} days selected — minimum 14 recommended.",
                color="warning", className="mb-3"
            )
        return dbc.Alert(
            f"✅ {days} days selected — good baseline window.",
            color="success", className="mb-3"
        )
    except Exception:
        return html.Div()


# ══════════════════════════════════════════════════════════════════════════
# BRIDGE CALLBACKS — sync visible → hidden persistent components
# ══════════════════════════════════════════════════════════════════════════

@callback(
    Output("ob-next-1", "n_clicks"),
    Input("ob-next-1-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_next1(n):
    return n or 0

@callback(
    Output("ob-next-2", "n_clicks"),
    Input("ob-next-2-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_next2(n):
    return n or 0

@callback(
    Output("ob-next-3", "n_clicks"),
    Input("ob-next-3-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_next3(n):
    return n or 0

@callback(
    Output("ob-next-4", "n_clicks"),
    Input("ob-next-4-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_next4(n):
    return n or 0

@callback(
    Output("ob-back-2", "n_clicks"),
    Input("ob-back-2-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_back2(n):
    return n or 0

@callback(
    Output("ob-back-3", "n_clicks"),
    Input("ob-back-3-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_back3(n):
    return n or 0

@callback(
    Output("ob-back-4", "n_clicks"),
    Input("ob-back-4-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_back4(n):
    return n or 0

@callback(
    Output("ob-back-5", "n_clicks"),
    Input("ob-back-5-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_back5(n):
    return n or 0

@callback(
    Output("ob-back-existing", "n_clicks"),
    Input("ob-back-existing-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_back_existing(n):
    return n or 0

@callback(
    Output("ob-modify-btn", "n_clicks"),
    Input("ob-modify-btn-visible", "n_clicks"),
    prevent_initial_call=True,
)
def sync_modify(n):
    return n or 0

@callback(
    Output("ob-baseline-options", "value"),
    Input("ob-baseline-options-visible", "value"),
    prevent_initial_call=True,
)
def sync_baseline_options(val):
    return val or []

@callback(
    Output("ob-baseline-start", "date"),
    Input("ob-baseline-start-visible", "date"),
    prevent_initial_call=True,
)
def sync_baseline_start(d):
    return d

@callback(
    Output("ob-baseline-end", "date"),
    Input("ob-baseline-end-visible", "date"),
    prevent_initial_call=True,
)
def sync_baseline_end(d):
    return d


# ══════════════════════════════════════════════════════════════════════════
# STEP NAVIGATION CALLBACKS
# ══════════════════════════════════════════════════════════════════════════

# ── Next 1 → 2 ────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",       "data",     allow_duplicate=True),
    Output("ob-table-meta", "data",     allow_duplicate=True),
    Output("ob-col-config", "data",     allow_duplicate=True),
    Output("ob-existing",   "data",     allow_duplicate=True),
    Output("ob-alert",      "children", allow_duplicate=True),
    Input("ob-next-1",          "n_clicks"),
    State("ob-catalog",         "value"),
    State("ob-schema",          "value"),
    State("ob-table",           "value"),
    State("ob-layer",           "value"),
    State("ob-ingestion-type",  "value"),
    State("ob-frequency",       "value"),
    State("ob-date-col",        "value"),
    State("ob-owner",           "value"),
    State("ob-col-config",      "data"),
    State("ob-table-checks",    "data"),
    State("ob-baseline",        "data"),
    prevent_initial_call=True,
)
def next_step1(
    n_clicks,
    catalog, schema, table, layer, ing_type, freq, date_col, owner,
    col_config, table_checks, baseline,
):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    if not all([catalog, schema, table, layer, ing_type, freq]):
        return (
            dash.no_update, dash.no_update,
            dash.no_update, dash.no_update,
            error_alert("Please fill in all required fields.")
        )

    # Normalize "no date column" sentinel
    if not date_col or date_col == _NO_DATE_COL_VALUE:
        date_col = _NO_DATE_COL_VALUE

    new_meta = {
        "catalog"            : catalog,
        "schema"             : schema,
        "table_name"         : table,
        "layer"              : layer,
        "ingestion_type"     : ing_type,
        "ingestion_frequency": freq,
        "date_column"        : date_col,
        "owner_email"        : owner or "",
        "fqn"                : f"{catalog}.{schema}.{table}",
    }

    try:
        # Check if already registered
        df_ex = execute_query(
            f"""
            SELECT
                t.table_name,
                t.fully_qualified_name,
                t.source_type,
                t.ingestion_pattern,
                t.ingestion_frequency,
                t.business_date_column,
                t.registered_by,
                t.registered_timestamp,
                COUNT(DISTINCT c.column_name)      AS col_count,
                COUNT(DISTINCT cv.column_name)     AS val_count,
                COUNT(DISTINCT tv.validation_name) AS tval_count,
                COUNT(DISTINCT b.metric_name)      AS bl_count
            FROM {PREFIX}uc1_table_registry_b t
            LEFT JOIN {PREFIX}uc1_column_registry_b c
                   ON c.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_column_validation_registry_b cv
                   ON cv.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_table_validation_registry_b tv
                   ON tv.fully_qualified_name = t.fully_qualified_name
            LEFT JOIN {PREFIX}uc1_baseline_metrics_b b
                   ON b.fully_qualified_name = t.fully_qualified_name
            WHERE t.table_name = :table_name
            GROUP BY 1,2,3,4,5,6,7,8
        """,
            {"table_name": table},
        )

        if not df_ex.empty:
            r  = df_ex.iloc[0]
            ex = {
                "table_name"          : str(r["table_name"]),
                "fully_qualified_name": str(r["fully_qualified_name"]),
                "source_type"         : str(r.get("source_type",         "—")),
                "ingestion_pattern"   : str(r.get("ingestion_pattern",   "—")),
                "ingestion_frequency" : str(r.get("ingestion_frequency", "—")),
                "business_date_column": str(r.get("business_date_column","—")),
                "registered_by"       : str(r.get("registered_by",       "—")),
                "registered_timestamp": str(r.get("registered_timestamp","—")),
                "col_count"           : int(r["col_count"]  or 0),
                "val_count"           : int(r["val_count"]  or 0),
                "tval_count"          : int(r["tval_count"] or 0),
                "bl_count"            : int(r["bl_count"]   or 0),
            }
            return "existing", new_meta, col_config, ex, html.Div()

        # DESCRIBE TABLE to get columns
        df_desc = execute_query(
            f"DESCRIBE TABLE {catalog}.{schema}.{table}"
        )

        new_col_config = {}
        for _, row in df_desc.iterrows():
            cname = str(row.iloc[0]).strip()
            dtype = str(row.iloc[1]).strip() \
                    if len(df_desc.columns) > 1 else "STRING"
            if not cname or cname.startswith("#") or cname == "":
                continue
            # Complex (STRUCT/ARRAY) parents start OFF; switching them on
            # in Step 2 expands their nested fields.
            new_col_config[cname] = {
                "dtype"          : dtype,
                "nullable"       : True,
                "enabled"        : _type_base(dtype) not in ("STRUCT", "ARRAY"),
                "is_complex"     : is_complex_dtype(dtype),
                "checks"         : get_default_checks_for_dtype(dtype),
                "warn_threshold" : 5,
                "crit_threshold" : 10,
            }

            # Explode STRUCT / ARRAY columns into leaf columns that get
            # the full primitive treatment (enable, checks, thresholds).
            if _type_base(dtype) in ("STRUCT", "ARRAY"):
                for leaf in flatten_nested_type(cname, dtype):
                    new_col_config[leaf["path"]] = {
                        "dtype"          : leaf["dtype"],
                        "nullable"       : True,
                        "enabled"        : True,
                        "is_complex"     : is_complex_dtype(leaf["dtype"]),
                        "is_nested_child": True,
                        "parent_column"  : cname,
                        "checks"         : get_default_checks_for_dtype(leaf["dtype"]),
                        "warn_threshold" : 5,
                        "crit_threshold" : 10,
                    }

        return 2, new_meta, new_col_config, {}, html.Div()

    except Exception as e:
        logger.error(f"next_step1 failed: {e}")
        return (
            dash.no_update, dash.no_update,
            dash.no_update, dash.no_update,
            error_alert(f"Error loading table: {e}")
        )


# ── Next 2 → 3 ────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",       "data",     allow_duplicate=True),
    Output("ob-col-config", "data",     allow_duplicate=True),
    Output("ob-alert",      "children", allow_duplicate=True),
    Input("ob-next-2",      "n_clicks"),
    State({"type": "ob-col-enabled", "index": ALL}, "value"),
    State({"type": "ob-col-enabled", "index": ALL}, "id"),
    State({"type": "ob-col-checks",  "index": ALL}, "value"),
    State({"type": "ob-col-warn",    "index": ALL}, "value"),
    State({"type": "ob-col-crit",    "index": ALL}, "value"),
    State({"type": "ob-cplx-enabled", "index": ALL}, "value"),
    State({"type": "ob-cplx-enabled", "index": ALL}, "id"),
    State({"type": "ob-cplx-checks",  "index": ALL}, "value"),
    State({"type": "ob-cplx-warn",    "index": ALL}, "value"),
    State({"type": "ob-cplx-crit",    "index": ALL}, "value"),
    State({"type": "ob-nest-enabled", "index": ALL, "parent": ALL}, "value"),
    State({"type": "ob-nest-enabled", "index": ALL, "parent": ALL}, "id"),
    State({"type": "ob-nest-checks",  "index": ALL, "parent": ALL}, "value"),
    State({"type": "ob-nest-warn",    "index": ALL, "parent": ALL}, "value"),
    State({"type": "ob-nest-crit",    "index": ALL, "parent": ALL}, "value"),
    State("ob-col-config",           "data"),
    prevent_initial_call=True,
)
def next_step2(
    n_clicks,
    col_en_vals, col_en_ids, col_ch_vals, col_warn_vals, col_crit_vals,
    cx_en_vals, cx_en_ids, cx_ch_vals, cx_warn_vals, cx_crit_vals,
    nx_en_vals, nx_en_ids, nx_ch_vals, nx_warn_vals, nx_crit_vals,
    col_config,
):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    new_col = {k: dict(v) for k, v in (col_config or {}).items()}

    def _apply(ids, en, ch, wa, cr):
        for i, id_dict in enumerate(ids):
            cname = id_dict["index"]
            if cname not in new_col:
                continue
            new_col[cname]["enabled"] = bool(en[i]) if i < len(en) else True
            new_col[cname]["checks"] = (ch[i] if i < len(ch) else []) or []
            new_col[cname]["warn_threshold"] = wa[i] if i < len(wa) else 5
            new_col[cname]["crit_threshold"] = cr[i] if i < len(cr) else 10

    _apply(col_en_ids, col_en_vals, col_ch_vals, col_warn_vals, col_crit_vals)
    _apply(cx_en_ids,  cx_en_vals,  cx_ch_vals,  cx_warn_vals,  cx_crit_vals)
    _apply(nx_en_ids,  nx_en_vals,  nx_ch_vals,  nx_warn_vals,  nx_crit_vals)

    # A nested field is only active when its parent complex column is ON
    for cname, cfg in new_col.items():
        root = cname.split(".")[0].split("[")[0]
        if cfg.get("is_nested_child") or (
            is_nested_path(cname) and root in new_col
        ):
            parent = cfg.get("parent_column") or root
            cfg["is_nested_child"] = True
            cfg["parent_column"]   = parent
            if not new_col.get(parent, {}).get("enabled", False):
                cfg["enabled"] = False

    return 3, new_col, html.Div()


# ── Step 2 interactivity: enable/disable controls, expand nested panel ───

@callback(
    Output({"type": "ob-col-checks", "index": MATCH}, "disabled"),
    Output({"type": "ob-col-warn",   "index": MATCH}, "disabled"),
    Output({"type": "ob-col-crit",   "index": MATCH}, "disabled"),
    Input({"type": "ob-col-enabled", "index": MATCH}, "value"),
    prevent_initial_call=True,
)
def toggle_col_controls(enabled):
    off = not enabled
    return off, off, off


@callback(
    Output({"type": "ob-cplx-checks",  "index": MATCH}, "disabled"),
    Output({"type": "ob-cplx-warn",    "index": MATCH}, "disabled"),
    Output({"type": "ob-cplx-crit",    "index": MATCH}, "disabled"),
    Output({"type": "ob-nested-panel", "index": MATCH}, "style"),
    Input({"type": "ob-cplx-enabled",  "index": MATCH}, "value"),
    State({"type": "ob-nested-panel",  "index": MATCH}, "style"),
    prevent_initial_call=True,
)
def toggle_complex_parent(enabled, style):
    off = not enabled
    style = dict(style or {})
    style["display"] = "block" if enabled else "none"
    return off, off, off, style


@callback(
    Output({"type": "ob-nest-checks",  "index": MATCH, "parent": MATCH}, "disabled"),
    Output({"type": "ob-nest-warn",    "index": MATCH, "parent": MATCH}, "disabled"),
    Output({"type": "ob-nest-crit",    "index": MATCH, "parent": MATCH}, "disabled"),
    Input({"type": "ob-nest-enabled",  "index": MATCH, "parent": MATCH}, "value"),
    prevent_initial_call=True,
)
def toggle_nested_controls(enabled):
    off = not enabled
    return off, off, off


@callback(
    Output({"type": "ob-nest-enabled", "index": ALL, "parent": MATCH}, "value"),
    Input({"type": "ob-nest-all-on",   "parent": MATCH}, "n_clicks"),
    Input({"type": "ob-nest-all-off",  "parent": MATCH}, "n_clicks"),
    State({"type": "ob-nest-enabled",  "index": ALL, "parent": MATCH}, "value"),
    prevent_initial_call=True,
)
def bulk_toggle_nested(_on, _off, current):
    trig = ctx.triggered_id or {}
    value = trig.get("type") == "ob-nest-all-on"
    return [value] * len(current or [])


# ── Next 3 → 4 ────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",         "data",     allow_duplicate=True),
    Output("ob-table-checks", "data",     allow_duplicate=True),
    Output("ob-alert",        "children", allow_duplicate=True),
    Input("ob-next-3",        "n_clicks"),
    State({"type": "ob-tbl-check-enabled", "index": ALL}, "value"),
    State({"type": "ob-tbl-check-enabled", "index": ALL}, "id"),
    State({"type": "ob-tbl-check-warn",    "index": ALL}, "value"),
    State({"type": "ob-tbl-check-crit",    "index": ALL}, "value"),
    prevent_initial_call=True,
)
def next_step3(
    n_clicks,
    tbl_en_vals, tbl_en_ids, tbl_warn_vals, tbl_crit_vals,
):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    new_tbl = {}
    for i, id_dict in enumerate(tbl_en_ids):
        chk_id  = id_dict["index"]
        chk_def = next(
            (c for c in TABLE_CHECK_TYPES if c["id"] == chk_id), {}
        )
        new_tbl[chk_id] = {
            "enabled": (
                tbl_en_vals[i] if i < len(tbl_en_vals) else False
            ),
            "warn": (
                tbl_warn_vals[i]
                if i < len(tbl_warn_vals) else chk_def.get("warn")
            ),
            "crit": (
                tbl_crit_vals[i]
                if i < len(tbl_crit_vals) else chk_def.get("crit")
            ),
        }

    return 4, new_tbl, html.Div()


# ── Next 4 → 5 ────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",     "data",     allow_duplicate=True),
    Output("ob-baseline", "data",     allow_duplicate=True),
    Output("ob-alert",    "children", allow_duplicate=True),
    Input("ob-next-4",    "n_clicks"),
    State("ob-baseline-start",   "date"),
    State("ob-baseline-end",     "date"),
    State("ob-baseline-options", "value"),
    prevent_initial_call=True,
)
def next_step4(n_clicks, bl_start, bl_end, bl_options):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    if not bl_start or not bl_end:
        return (
            dash.no_update, dash.no_update,
            error_alert("Please select baseline start and end dates.")
        )

    new_bl = {
        "window_start"     : bl_start,
        "window_end"       : bl_end,
        "recompute"        : "recompute" in (bl_options or []),
        "recompute_checked": bl_options or [],
    }
    return 5, new_bl, html.Div()


# ── Back buttons ───────────────────────────────────────────────────────────

@callback(
    Output("ob-step",  "data",     allow_duplicate=True),
    Output("ob-alert", "children", allow_duplicate=True),
    Input("ob-back-2",        "n_clicks"),
    Input("ob-back-3",        "n_clicks"),
    Input("ob-back-4",        "n_clicks"),
    Input("ob-back-5",        "n_clicks"),
    Input("ob-back-existing", "n_clicks"),
    prevent_initial_call=True,
)
def handle_back(b2, b3, b4, b5, b_ex):
    triggered = ctx.triggered_id
    mapping   = {
        "ob-back-2"       : 1,
        "ob-back-3"       : 2,
        "ob-back-4"       : 3,
        "ob-back-5"       : 4,
        "ob-back-existing": 1,
    }
    step = mapping.get(str(triggered), 1)
    return step, html.Div()


# ── Modify existing ────────────────────────────────────────────────────────

@callback(
    Output("ob-step",     "data",     allow_duplicate=True),
    Output("ob-existing", "data",     allow_duplicate=True),
    Output("ob-alert",    "children", allow_duplicate=True),
    Input("ob-modify-btn","n_clicks"),
    prevent_initial_call=True,
)
def handle_modify(n_clicks):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    return 2, {}, html.Div()


# ── Restart ────────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",         "data",     allow_duplicate=True),
    Output("ob-table-meta",   "data",     allow_duplicate=True),
    Output("ob-col-config",   "data",     allow_duplicate=True),
    Output("ob-table-checks", "data",     allow_duplicate=True),
    Output("ob-baseline",     "data",     allow_duplicate=True),
    Output("ob-existing",     "data",     allow_duplicate=True),
    Output("ob-exec-modal",   "is_open",  allow_duplicate=True),
    Output("ob-exec-status",  "data",     allow_duplicate=True),
    Output("ob-alert",        "children", allow_duplicate=True),
    Input("ob-restart-btn",   "n_clicks"),
    prevent_initial_call=True,
)
def handle_restart(n_clicks):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    return 1, {}, {}, {}, {}, {}, False, {}, html.Div()


# ── Step renderer ──────────────────────────────────────────────────────────

@callback(
    Output("ob-step-content", "children"),
    Output("ob-progress-bar", "children"),
    Input("ob-step",          "data"),
    State("ob-table-meta",    "data"),
    State("ob-col-config",    "data"),
    State("ob-table-checks",  "data"),
    State("ob-baseline",      "data"),
    State("ob-existing",      "data"),
)
def render_step(
    step, table_meta, col_config, table_checks, baseline, existing
):
    display_step = (
        1 if step in (1, "existing") else
        5 if step in (5, "executing") else
        int(step) if isinstance(step, int) else 1
    )
    progress = build_progress_bar(display_step)

    if step == 1:
        return build_step1(), progress

    if step == "existing":
        return build_existing_summary(existing or {}), progress

    if step == 2:
        cols = [
            {
                "name"    : cname,
                "dtype"   : cfg.get("dtype", "STRING"),
                "nullable": cfg.get("nullable", True),
            }
            for cname, cfg in (col_config or {}).items()
        ]
        return build_step2(cols, col_config), progress

    if step == 3:
        return build_step3(table_checks), progress

    if step == 4:
        return build_step4(baseline), progress

    if step == 5:
        return build_step5(
            table_meta   or {},
            col_config   or {},
            table_checks or {},
            baseline     or {},
        ), progress

    if step == "executing":
        return html.Div(), progress

    return html.Div("Unknown step."), progress

@callback(
    Output("ob-alert", "children", allow_duplicate=True),
    Input("ob-exec-trigger", "data"),
    prevent_initial_call=True,
)
def debug_trigger(trigger):
    logger.info(f"DEBUG ob-exec-trigger fired: {trigger}")
    if trigger and trigger.get("triggered"):
        return warning_alert("Trigger received — exec-trigger works")
    return dash.no_update