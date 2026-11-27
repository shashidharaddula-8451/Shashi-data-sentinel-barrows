# pages/onboarding.py

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH, ctx
import dash_bootstrap_components as dbc
from db.connection import execute_query, execute_write, validate_identifier, get_connection
import json
import os
import time
from databricks.sdk import WorkspaceClient
from config.settings import (
    TARGET_CATALOG, TARGET_SCHEMA,
    DATABRICKS_HOST, DATABRICKS_TOKEN,
    COLUMN_LEVEL_VALIDATIONS,
    COLUMN_CHECKS_BY_TYPE,
    TYPE_FAMILY,
    ID_COLUMN_CHECKS,
    ID_NAME_REGEX,
)
from components.alerts import error_alert, warning_alert
from components.date_column_advisor import (
    analyze_date_columns,
    profile_date_candidate as advisor_profile_date_candidate,
    llm_date_recommendation as advisor_llm_date_recommendation,
    dev_helper_barrows as advisor_dev_helper_barrows,
)
from components.baseline_window_policy import (
    WINDOW_POLICY_MONTH,
    compute_default_window,
    days_in_window,
    first_validation_business_date,
    next_refresh_date,
)
from datetime import date, timedelta
import logging
import uuid

logger = logging.getLogger(__name__)

# Prevent duplicate onboarding execution from repeated clicks/retries of the same submission.
_PROCESSED_SUBMISSION_IDS = set()

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
    {"num": 4, "label": "Baseline Options"},
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

DATE_TYPES = {
    "DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "DATETIME", "TIMESTAMP_LTZ"
}

DATE_NAME_HINTS = {
    "date", "created", "updated", "modified", "timestamp",
    "created_at", "updated_at", "event_time", "event_date",
    "load_date", "inserted_dt", "business_date", "run_date",
    "partition_date", "record_date", "file_date", "transaction_date",
    "start", "end", "__start_at", "__end_at", "_commit_timestamp",
}

DATE_PRIORITY = [
    "business_date", "inserted_dt", "updated_dt", "created", "updated",
    "created_at", "updated_at", "transaction_date", "event_date",
    "load_date", "created_date", "modified_date", "run_date",
    "partition_date", "record_date", "file_date", "__start_at",
]

DATE_PARSE_MIN_RATIO = 0.80
DATE_NULL_MAX_RATIO = 0.50

DATE_LLM_ENDPOINT = os.environ.get("DS_DATE_SUGGESTION_ENDPOINT", "databricks-gpt-oss-20b").strip()
DATE_LLM_TIMEOUT_SECONDS = int(os.environ.get("DS_DATE_SUGGESTION_TIMEOUT", "45"))
DATE_SAMPLE_LIMIT = int(os.environ.get("DS_DATE_SUGGESTION_SAMPLES", "12"))

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

COMING_SOON_CHECKS = {
    "FORMAT_PATTERN",
    "DISTRIBUTION_DRIFT",
    "DATE_VALIDITY",
    "REFERENTIAL_INTEGRITY",
    "DUPLICATE_CHECK",
}

BASELINE_MODE_LAST30 = "LAST_30_COMPLETE_DAYS"
BASELINE_MODE_CUSTOM = "CUSTOM_DATES"
DEFAULT_BASELINE_LAG_DAYS = 1
DEFAULT_VALIDATION_LAG_DAYS = 1
MIN_BASELINE_DAYS_RECOMMENDED = 15
MAX_BASELINE_DAYS_ALLOWED = 90

DS_AGENT1_BASELINE_JOB_ID = os.environ.get("DS_AGENT1_BASELINE_JOB_ID", "").strip()
DS_AGENT1_VALIDATION_JOB_ID = os.environ.get("DS_AGENT1_VALIDATION_JOB_ID", "").strip()
JOB_POLL_INTERVAL_SECONDS = 10
JOB_POLL_TIMEOUT_SECONDS = 300

# ── Helpers ────────────────────────────────────────────────────────────────

def is_complex_dtype(dtype: str) -> bool:
    """Return True if the data type is complex / JSON / nested."""
    norm = (dtype or "").upper().split("<")[0].split("(")[0].strip()
    return norm in COMPLEX_TYPES


def _coerce_min_one_day(raw, default_val: int = 1) -> int:
    try:
        return max(1, int(raw or default_val))
    except Exception:
        return max(1, int(default_val))


def _compute_option_a_window(lag_days: int):
    return compute_default_window(date.today(), lag_days, WINDOW_POLICY_MONTH)


def _window_validation(mode: str, lag_days: int, start_raw: str, end_raw: str):
    mode = mode or BASELINE_MODE_LAST30
    lag = _coerce_min_one_day(lag_days, DEFAULT_BASELINE_LAG_DAYS)

    if mode == BASELINE_MODE_LAST30:
        start_dt, end_dt = _compute_option_a_window(lag)
    else:
        if not start_raw or not end_raw:
            return {
                "valid": False,
                "color": "danger",
                "message": "Select both custom start and end dates.",
                "start": None,
                "end": None,
                "days": 0,
            }
        try:
            start_dt = date.fromisoformat(str(start_raw)[:10])
            end_dt = date.fromisoformat(str(end_raw)[:10])
        except Exception:
            return {
                "valid": False,
                "color": "danger",
                "message": "Baseline dates must be valid ISO dates (YYYY-MM-DD).",
                "start": None,
                "end": None,
                "days": 0,
            }

    max_end = date.today() - timedelta(days=lag)
    if start_dt > end_dt:
        return {
            "valid": False,
            "color": "danger",
            "message": "Baseline start date must be on or before end date.",
            "start": start_dt,
            "end": end_dt,
            "days": 0,
        }
    if end_dt > max_end:
        return {
            "valid": False,
            "color": "danger",
            "message": f"Baseline end date must be on or before {max_end}.",
            "start": start_dt,
            "end": end_dt,
            "days": 0,
        }

    days = days_in_window(start_dt, end_dt)
    if days > MAX_BASELINE_DAYS_ALLOWED:
        return {
            "valid": False,
            "color": "danger",
            "message": f"{days} days selected — maximum allowed is {MAX_BASELINE_DAYS_ALLOWED} days.",
            "start": start_dt,
            "end": end_dt,
            "days": days,
        }

    if days < MIN_BASELINE_DAYS_RECOMMENDED:
        return {
            "valid": True,
            "color": "warning",
            "message": f"{days} days selected — minimum {MIN_BASELINE_DAYS_RECOMMENDED} recommended.",
            "start": start_dt,
            "end": end_dt,
            "days": days,
        }

    return {
        "valid": True,
        "color": "success",
        "message": f"{days} days selected — good baseline window ({start_dt} to {end_dt}).",
        "start": start_dt,
        "end": end_dt,
        "days": days,
    }


def get_default_checks_for_dtype(dtype: str, column_name: str = None) -> list:
    """Return the default-selected checks for a given data type."""
    if is_complex_dtype(dtype):
        defaults = list(COMPLEX_CHECK_DEFAULTS)
    else:
        dtype_upper = (dtype or "").upper().split("(")[0].strip()
        defaults = COLUMN_CHECK_DEFAULTS.get(
        dtype_upper, COLUMN_CHECK_DEFAULTS["DEFAULT"]
        )

    allowed = set(get_available_checks_for_dtype(dtype, column_name))
    return [c for c in defaults if c in allowed]


def get_available_checks_for_dtype(dtype: str, column_name: str = None) -> list:
    """Return the full list of available checks for a column type."""
    if is_complex_dtype(dtype):
        return list(COLUMN_CHECKS_BY_TYPE["COMPLEX"])

    base = normalize_dtype(dtype)
    family = TYPE_FAMILY.get(base, "DEFAULT")
    allowed = list(COLUMN_CHECKS_BY_TYPE.get(
        family,
        COLUMN_CHECKS_BY_TYPE["DEFAULT"],
    ))

    if column_name and _re.search(ID_NAME_REGEX, _rule_name_segment(column_name)):
        allowed = [c for c in ID_COLUMN_CHECKS if c in COLUMN_LEVEL_VALIDATIONS]

    return list(allowed)


def normalize_dtype(dtype: str) -> str:
    norm = (dtype or "STRING").upper().split("(")[0].strip()
    # Preserve STRUCT<...>, MAP<...>, ARRAY<...> as their base type
    base = (dtype or "STRING").upper().split("<")[0].split("(")[0].strip()
    if base in COMPLEX_TYPES:
        return base
    return norm


def _rule_name_segment(path: str) -> str:
    parts = normalize_path(path).split(".")
    if not parts:
        return ""
    last = parts[-1]
    if last == "items" and len(parts) > 1:
        return parts[-2]
    return last


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
    normalize_path,
    schema_tree,
)


def _find_col(df, candidates, fallback_idx=0):
    cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    return df.columns[fallback_idx]


def _profile_date_candidate(fqn: str, column_name: str, dtype_norm: str) -> dict:
    return advisor_profile_date_candidate(
        fqn=fqn,
        column_name=column_name,
        dtype_norm=dtype_norm,
        sampled=False,
        arrival_column=None,
        is_scd2=False,
    )


def _recommend_date_column(fqn: str, date_candidates: list) -> tuple:
    analysis = analyze_date_columns(fqn=fqn, reanalyse=False)
    profiles = list(analysis.get("profiles", []))
    if date_candidates:
        names = {str(c.get("name") or "") for c in date_candidates}
        profiles = [p for p in profiles if str(p.get("name") or "") in names]
    recommended = analysis.get("recommended_column")
    return recommended, profiles


def _llm_date_recommendation(fqn: str, profiles: list) -> dict:
    if not profiles:
        return {"used": False, "reason": "no_profiles"}
    payload = {
        "table_name": fqn.split(".")[-1],
        "table_type": "UNKNOWN",
        "is_scd2": False,
        "scd2_stats": {},
        "arrival_column": None,
        "commit_pattern": {},
        "candidates": [
            {
                "name": p.get("name"),
                "dtype": p.get("dtype"),
                "role": p.get("role"),
                "parse_ratio": p.get("parse_ratio"),
                "null_ratio": p.get("null_ratio"),
                "future_ratio": p.get("future_ratio"),
                "distinct_days": p.get("distinct_days"),
                "min_date": p.get("min_date"),
                "max_date": p.get("max_date"),
                "rows_per_day_median": p.get("rows_per_day_median"),
                "rows_per_day_cv": p.get("rows_per_day_cv"),
                "recent_completeness": p.get("recent_completeness"),
                "lag_p50": p.get("lag_p50"),
                "lag_p90": p.get("lag_p90"),
                "lag_p95": p.get("lag_p95"),
                "lag_max": p.get("lag_max"),
                "share_negative_lag": p.get("share_negative_lag"),
                "sample_dates": p.get("sample_dates", []),
            }
            for p in profiles
        ],
    }
    valid = {str(p.get("name") or "") for p in profiles}
    return advisor_llm_date_recommendation(fqn, payload, valid)


def _date_disclaimer_block(selected_col: str, analysis, chosen_validation_lag_days: int = None):
    if isinstance(analysis, list):
        analysis = {
            "profiles": analysis,
            "recommended_column": analysis[0].get("name") if analysis else None,
            "recommended_source": "rule",
            "llm": {"used": False},
        }

    profiles = (analysis or {}).get("profiles", [])
    llm = (analysis or {}).get("llm", {})
    recommended_column = (analysis or {}).get("recommended_column")
    recommended_source = (analysis or {}).get("recommended_source", "rule")

    if not profiles:
        return html.Div()

    profile_map = {str(p.get("name") or ""): p for p in profiles}
    selected = profile_map.get(selected_col) if selected_col else None

    suggested_lag = int((analysis or {}).get("suggested_validation_lag_days") or 1)
    is_scd2 = bool((analysis or {}).get("is_scd2"))
    confidence = str((analysis or {}).get("confidence") or "medium")
    explanation = str((analysis or {}).get("explanation") or "")
    alternatives = list((analysis or {}).get("alternatives") or [])
    use_current_versions_only = bool((analysis or {}).get("use_current_versions_only"))
    source = str((analysis or {}).get("recommended_source") or "rule").upper()

    if chosen_validation_lag_days is None:
        chosen_validation_lag_days = suggested_lag
    try:
        chosen_validation_lag_days = max(1, int(chosen_validation_lag_days))
    except Exception:
        chosen_validation_lag_days = suggested_lag

    if selected_col == _NO_DATE_COL_VALUE:
        top = profiles[0] if profiles else {}
        return dbc.Alert(
            [
                html.Strong("Selection warning: "),
                (
                    f"A likely business date column exists ({top.get('name', 'N/A')}) "
                    "but 'No date column' is selected. This may degrade baseline quality."
                ),
                html.Br(),
                html.Small(
                    "Analysed column names, aggregate statistics and common dates only. "
                    "Columns that may contain personal data were skipped.",
                    style=MUTED_STYLE,
                ),
            ],
            color="warning",
            className="mt-2",
        )

    role_badge = dbc.Badge(f"Role: {str((selected or {}).get('role') or 'N/A')}", color="secondary", className="me-2")
    parse_badge = dbc.Badge(f"parse {(selected or {}).get('parse_ratio', 0.0) * 100:.1f}%", color="info", className="me-2") if selected else html.Span()
    null_badge = dbc.Badge(f"null {(selected or {}).get('null_ratio', 1.0) * 100:.1f}%", color="dark", className="me-2") if selected else html.Span()
    lag_badge = dbc.Badge(
        f"lag p50/p90 {((selected or {}).get('lag_p50') if (selected or {}).get('lag_p50') is not None else 'n/a')}/"
        f"{((selected or {}).get('lag_p90') if (selected or {}).get('lag_p90') is not None else 'n/a')}",
        color="warning",
        className="me-2",
    ) if selected else html.Span()
    scd2_badge = dbc.Badge(f"SCD2 {'yes' if is_scd2 else 'no'}", color="secondary", className="me-2")
    src_badge = dbc.Badge(f"source {source}", color="secondary", className="me-2")
    conf_badge = dbc.Badge(f"confidence {confidence}", color="secondary", className="me-2")

    warning_items = []
    if selected_col and recommended_column and selected_col != recommended_column and selected_col != _NO_DATE_COL_VALUE:
        warning_items.append(f"Selected column differs from suggested column '{recommended_column}'.")
    if selected and str(selected.get("role") or "") == "LIFECYCLE":
        warning_items.append("This looks like a lifecycle date; daily validation slices may be incomplete.")
    if selected and (selected.get("lag_p90") is not None) and float(selected.get("lag_p90") or 0) > chosen_validation_lag_days:
        warning_items.append("Recent days will look incomplete with the current validation lag.")

    alt_block = html.Details([
        html.Summary("Alternatives"),
        html.Ul([
            html.Li(f"{a.get('column')}: {a.get('why_not')}")
            for a in alternatives
            if a.get("column")
        ]) if alternatives else html.Div("No alternatives available."),
    ], className="mt-2")

    excluded = (analysis or {}).get("excluded_columns", [])
    excluded_block = html.Div([
        html.Small(
            "Not analysed (possible PII): " + ", ".join(
                f"{e.get('name')} ({e.get('reason')})" for e in excluded[:8]
            ),
            style=MUTED_STYLE,
        )
    ]) if excluded else html.Div()

    return dbc.Alert(
        [
            html.Div([
                html.Strong(f"Suggested: {recommended_column} - {explanation}"),
                html.Div([
                    role_badge, parse_badge, null_badge, lag_badge,
                    scd2_badge, src_badge, conf_badge,
                ], className="mt-2 mb-2"),
                html.Div([
                    html.Span(f"Suggested validation lag: {suggested_lag} days"),
                ]),
                html.Div(
                    "Validate current versions only (__END_AT IS NULL)",
                    className="mt-1",
                    style={"display": "block" if use_current_versions_only else "none", "fontWeight": "600"},
                ),
                alt_block,
                excluded_block,
                html.Small(
                    "Analysed column names, aggregate statistics and common dates only. "
                    "Columns that may contain personal data were skipped.",
                    style=MUTED_STYLE,
                ),
            ]),
            html.Ul([html.Li(w) for w in warning_items], className="mt-2 mb-0") if warning_items else html.Div(),
        ],
        color="warning" if warning_items else "success",
        className="mt-2",
    )


def _run_date_advisor_dev_helper(catalog: str = "comms_media_prd", schema: str = "exposure_data_asset"):
    return advisor_dev_helper_barrows(catalog=catalog, schema=schema)


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
        dcc.Store(id="ob-date-col-analysis", data={}),
        dcc.Store(id="ob-baseline",     data={}),
        dcc.Store(id="ob-baseline-mode", data=BASELINE_MODE_LAST30),
        dcc.Store(id="ob-baseline-lag-days", data=DEFAULT_BASELINE_LAG_DAYS),
        dcc.Store(id="ob-validation-lag-days", data=DEFAULT_VALIDATION_LAG_DAYS),
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

        dcc.Interval(
            id="ob-baseline-poll-interval",
            interval=5000,
            n_intervals=0,
            disabled=True,
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
                    html.Div([
                        html.Label("Date Column", style={**LABEL_STYLE, "marginBottom": "0"}),
                        html.Div([
                            dbc.Button(
                                "Re-analyse",
                                id="ob-date-reanalyse-btn",
                                color="secondary",
                                outline=True,
                                size="sm",
                                n_clicks=0,
                                style={"display": "none"},
                            ),
                            html.Button(
                                "Apply",
                                id="ob-date-apply-lag-btn",
                                n_clicks=0,
                                style={
                                    "display": "none",
                                    "background": "none",
                                    "border": "none",
                                    "padding": "0",
                                    "margin": "0",
                                    "color": "#4a9edd",
                                    "textDecoration": "underline",
                                    "cursor": "pointer",
                                    "fontWeight": "600",
                                },
                            ),
                            html.Span(id="ob-date-apply-lag-label", style={**MUTED_STYLE, "marginLeft": "4px"}),
                        ], style={"display": "flex", "gap": "10px", "alignItems": "center"}),
                    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"}),
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
                        "Also detects date-like STRING columns with full-table aggregate profiling. "
                        "Choose 'No date column' to baseline "
                        "over the full table.",
                        style=MUTED_STYLE
                    ),
                    html.Div(id="ob-date-analysis-status", style={**MUTED_STYLE, "marginTop": "4px"}),
                    dcc.Loading(
                        id="ob-date-analysis-loading",
                        type="circle",
                        custom_spinner=html.Div([
                            dbc.Spinner(size="sm", color="primary", spinner_style={"marginRight": "8px"}),
                            html.Span("Analysing date columns...", style={"color": TEXT_PRIMARY, "fontWeight": "600"}),
                        ], style={"display": "flex", "alignItems": "center", "gap": "6px", "padding": "8px 0"}),
                        children=html.Div(id="ob-date-col-disclaimer"),
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
    base = _CHECK_SHORT_LABELS.get(code, code.replace("_", " ").title())
    return f"{base} (Coming soon)" if code in COMING_SOON_CHECKS else base


def _is_check_enabled_for_selection(code: str) -> bool:
    return code not in COMING_SOON_CHECKS


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
    available = get_available_checks_for_dtype(dtype, cname)
    # Complex parents with nested fields start OFF (collapsed)
    enabled   = existing.get("enabled", not bool(n_children))
    checks    = [
        c for c in existing.get("checks", get_default_checks_for_dtype(dtype, cname))
        if _is_check_enabled_for_selection(c)
    ]
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
                    options     = [
                        {
                            "label": _check_label(c),
                            "value": c,
                            "title": c,
                            "disabled": not _is_check_enabled_for_selection(c),
                        }
                        for c in available
                    ],
                    value       = [
                        c for c in checks
                        if c in available and _is_check_enabled_for_selection(c)
                    ],
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
        selectable = _is_check_enabled_for_selection(chk_id)
        enabled  = existing.get("enabled", chk["default_on"]) and selectable
        warn_val = existing.get("warn",    chk["warn"])
        crit_val = existing.get("crit",    chk["crit"])
        has_thr  = chk["warn"] is not None
        label = chk["label"] if selectable else f"{chk['label']} (Coming soon)"

        check_rows.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        dbc.Switch(
                            id    = {"type": "ob-tbl-check-enabled",
                                     "index": chk_id},
                            value = enabled,
                            disabled = not selectable,
                        ),
                    ], md=1),
                    dbc.Col([
                        html.Div(
                            label,
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
    baseline_mode = p.get("baseline_mode", BASELINE_MODE_LAST30)
    baseline_lag_days = _coerce_min_one_day(
        p.get("baseline_lag_days", DEFAULT_BASELINE_LAG_DAYS),
        DEFAULT_BASELINE_LAG_DAYS,
    )
    validation_lag_days = _coerce_min_one_day(
        p.get("validation_lag_days", DEFAULT_VALIDATION_LAG_DAYS),
        DEFAULT_VALIDATION_LAG_DAYS,
    )

    auto_start_dt, auto_end_dt = _compute_option_a_window(baseline_lag_days)
    start_val = p.get("window_start", str(auto_start_dt))
    end_val   = p.get("window_end",   str(auto_end_dt))
    is_modify_flow = bool(p.get("is_modify_flow", False))
    recompute = p.get("recompute_checked", ["recompute"] if is_modify_flow else [])
    max_allowed = date.today() - timedelta(days=baseline_lag_days)

    next_refresh = next_refresh_date(date.today(), (1, 15))
    next_refresh_start, next_refresh_end = compute_default_window(
        next_refresh,
        baseline_lag_days,
        WINDOW_POLICY_MONTH,
    )
    first_val_business_date = auto_end_dt + timedelta(days=1)

    return html.Div([
        html.Div([
            html.H4(
                "Step 4 — Baseline Options",
                style={"color": TEXT_HEADING, "fontWeight": "700",
                       "marginBottom": "4px"}
            ),
            html.P(
                "Choose the initial baseline window. Later baselines refresh automatically on the 1st and 15th.",
                style=MUTED_STYLE
            ),
        ], style={"marginBottom": "24px"}),

        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Label("Window Option", style=LABEL_STYLE),
                    dbc.RadioItems(
                        id="ob-baseline-mode-visible",
                        options=[
                            {
                                "label": "Recommended — previous month of complete data",
                                "value": BASELINE_MODE_LAST30,
                            },
                            {
                                "label": "Custom date range",
                                "value": BASELINE_MODE_CUSTOM,
                            },
                        ],
                        value=baseline_mode,
                        className="mb-2",
                        style={"color": TEXT_PRIMARY},
                    ),
                    html.Small(
                        f"Recommended window computes {auto_start_dt} to {auto_end_dt} from lag.",
                        style=MUTED_STYLE,
                    ) if baseline_mode == BASELINE_MODE_LAST30 else html.Div(),
                ], md=12),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    html.Label("Baseline Start Date", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id             = "ob-baseline-start-visible",
                        date           = start_val,
                        disabled       = baseline_mode != BASELINE_MODE_CUSTOM,
                        max_date_allowed = str(max_allowed),
                        display_format = "YYYY-MM-DD",
                        style          = {"width": "100%"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Baseline End Date", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id             = "ob-baseline-end-visible",
                        date           = end_val,
                        disabled       = baseline_mode != BASELINE_MODE_CUSTOM,
                        max_date_allowed = str(max_allowed),
                        display_format = "YYYY-MM-DD",
                        style          = {"width": "100%"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Minimum Recommended", style=LABEL_STYLE),
                    html.Div(
                        f"{MIN_BASELINE_DAYS_RECOMMENDED} days",
                        style={**MUTED_STYLE, "paddingTop": "10px"}
                    ),
                ], md=4),
            ], className="mb-4"),

            dbc.Row([
                dbc.Col([
                    html.Label("Presets", style=LABEL_STYLE),
                    html.Div([
                        dbc.Button("Previous month", id="ob-preset-prev-month", color="secondary", outline=True, size="sm", className="me-2"),
                        dbc.Button("Last 30 days", id="ob-preset-last-30", color="secondary", outline=True, size="sm", className="me-2"),
                        dbc.Button("Last 60 days", id="ob-preset-last-60", color="secondary", outline=True, size="sm"),
                    ]),
                ])
            ], className="mb-3"),

            # Warning rendered here from persistent hidden component
            html.Div(id="ob-baseline-warning-visible"),

            dbc.Alert([
                html.Div("After onboarding", style={"fontWeight": "700", "marginBottom": "4px"}),
                html.Ul([
                    html.Li(
                        f"Baseline refreshes automatically on the 1st and 15th using the previous month of data. "
                        f"Next refresh: {next_refresh} -> window {next_refresh_start} to {next_refresh_end}."
                    ),
                    html.Li(
                        f"Daily validation starts {first_val_business_date} (checks data for {auto_end_dt})."
                    ),
                ], style={"marginBottom": "0px"}),
            ], color="info", className="mb-3"),

            dbc.Accordion([
                dbc.AccordionItem([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Data completeness lag (days)", style=LABEL_STYLE),
                            dbc.Input(
                                id="ob-baseline-lag-visible",
                                value=baseline_lag_days,
                                type="number",
                                min=1,
                                step=1,
                                style={
                                    "backgroundColor": "#2C2E33",
                                    "color": TEXT_PRIMARY,
                                    "border": f"1px solid {BORDER_COLOR}",
                                },
                            ),
                            html.Small("min 1; suggested 14 for late-arriving tables", style=MUTED_STYLE),
                        ], md=6),
                        dbc.Col([
                            html.Label("Validation delay (days)", style=LABEL_STYLE),
                            dbc.Input(
                                id="ob-validation-lag-visible",
                                value=validation_lag_days,
                                type="number",
                                min=1,
                                step=1,
                                style={
                                    "backgroundColor": "#2C2E33",
                                    "color": TEXT_PRIMARY,
                                    "border": f"1px solid {BORDER_COLOR}",
                                },
                            ),
                            html.Small("min 1; suggested 3 for late-arriving tables", style=MUTED_STYLE),
                        ], md=6),
                    ]),
                ], title="Advanced")
            ], start_collapsed=True, className="mb-2"),

            html.Div([
                html.Label("Options", style=LABEL_STYLE),
                dbc.Checklist(
                    id="ob-baseline-options-visible",
                    options=[{"label": "Recompute baseline with the new configuration", "value": "recompute"}],
                    value=recompute,
                    style={
                        "color": TEXT_PRIMARY,
                        "display": "block" if is_modify_flow else "none",
                    },
                ),
                html.Small(
                    "Baseline recompute is always triggered for new onboarding.",
                    style=MUTED_STYLE,
                ) if not is_modify_flow else html.Div(),
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
    bl_mode  = baseline.get("baseline_mode", BASELINE_MODE_LAST30)
    bl_lag   = baseline.get("baseline_lag_days", DEFAULT_BASELINE_LAG_DAYS)
    val_lag  = baseline.get("validation_lag_days", DEFAULT_VALIDATION_LAG_DAYS)
    recompute= baseline.get("recompute",    True)

    try:
        days = (
            date.fromisoformat(bl_end) -
            date.fromisoformat(bl_start)
        ).days + 1
    except Exception:
        days = 0

    try:
        first_validation_dt = date.fromisoformat(str(bl_end)[:10]) + timedelta(days=1)
    except Exception:
        first_validation_dt = date.today()

    lag_for_refresh = _coerce_min_one_day(bl_lag, DEFAULT_BASELINE_LAG_DAYS)
    next_refresh = next_refresh_date(date.today(), (1, 15))
    next_start, next_end = compute_default_window(next_refresh, lag_for_refresh, WINDOW_POLICY_MONTH)

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
              srow("Chosen Date Column",
                 table_meta.get("date_column", "—")
                 if table_meta.get("date_column") != _NO_DATE_COL_VALUE
                 else "None (full table)"),
              srow("Suggested Date Column",
                  table_meta.get("suggested_date_column", "—")
                  if table_meta.get("suggested_date_column")
                  else "—"),
              srow(
                 "Date Column Overridden",
                 "Yes" if bool(table_meta.get("date_column_overridden")) else "No",
              ),
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
            html.H6("📊 Baseline Settings",
                    style={"color": TEXT_HEADING, "fontWeight": "700",
                           "marginBottom": "16px"}),
            srow("Mode", "Recommended month-back window" if bl_mode == BASELINE_MODE_LAST30 else "Custom dates"),
            srow("Data completeness lag", f"{bl_lag} day(s)"),
            srow("Validation delay", f"{val_lag} day(s)"),
            srow("Initial window start",   bl_start),
            srow("Initial window end",     bl_end),
            srow("Window",       f"{days} days",
                 STEP_COMPLETE if days >= MIN_BASELINE_DAYS_RECOMMENDED else "#dc3545"),
            srow("Next refresh", f"{next_refresh} ({next_start} to {next_end})"),
            srow("First validation date", f"{first_validation_dt} (checks {bl_end})"),
            srow("Total Checks", f"{total_checks}"),
            srow("Recompute",    "Yes" if recompute else "No"),
            dbc.Alert(
                f"⚠️ Only {days} days selected. "
                f"Minimum {MIN_BASELINE_DAYS_RECOMMENDED} days recommended.",
                color="warning", className="mb-0 mt-2",
            ) if days < MIN_BASELINE_DAYS_RECOMMENDED else html.Div(),
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


def _table_columns(table_fqn: str, conn=None) -> set:
    df = execute_query(f"DESCRIBE TABLE {table_fqn}", conn=conn)
    cols = set()
    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        if name and not name.startswith("#"):
            cols.add(name)
    return cols


def _persist_table_lags(conn, fqn: str, baseline_lag_days: int, validation_lag_days: int):
    try:
        table_cols = _table_columns(f"{PREFIX}uc1_table_registry_b", conn=conn)
    except Exception as e:
        logger.warning(f"Unable to inspect table registry columns for lag persistence: {e}")
        return

    set_parts = []
    params = {"fully_qualified_name": fqn}
    if "baseline_lag_days" in table_cols:
        set_parts.append("baseline_lag_days = :baseline_lag_days")
        params["baseline_lag_days"] = int(baseline_lag_days)
    if "validation_lag_days" in table_cols:
        set_parts.append("validation_lag_days = :validation_lag_days")
        params["validation_lag_days"] = int(validation_lag_days)

    if not set_parts:
        return

    execute_write(
        f"""
        UPDATE {PREFIX}uc1_table_registry_b
        SET {', '.join(set_parts)}
        WHERE fully_qualified_name = :fully_qualified_name
        """,
        params,
        conn=conn,
    )


def _active_config_counts(conn, fqn: str) -> dict:
    counts = {}
    for key, table_name in [
        ("columns", "uc1_column_registry_b"),
        ("column_validations", "uc1_column_validation_registry_b"),
        ("table_validations", "uc1_table_validation_registry_b"),
    ]:
        df = execute_query(
            f"""
            SELECT COUNT(*) AS c
            FROM {PREFIX}{table_name}
            WHERE fully_qualified_name = :fqn
              AND is_active = true
            """,
            {"fqn": fqn},
            conn=conn,
        )
        counts[key] = int(df.iloc[0]["c"]) if not df.empty else 0
    return counts


def _verify_active_config_uniqueness(conn, fqn: str, col_config: dict, table_checks: dict) -> list:
    errors = []

    expected_cols = {
        cname for cname, cfg in (col_config or {}).items()
        if bool(cfg.get("enabled", True))
    }
    expected_col_checks = {
        (cname, chk)
        for cname, cfg in (col_config or {}).items()
        if bool(cfg.get("enabled", True))
        for chk in (cfg.get("checks", []) or [])
    }
    expected_table_checks = {
        chk for chk, cfg in (table_checks or {}).items()
        if bool(cfg.get("enabled", False))
    }

    # Active columns: exactly one row per expected enabled column.
    df_cols = execute_query(
        f"""
        SELECT column_name
        FROM {PREFIX}uc1_column_registry_b
        WHERE fully_qualified_name = :fqn
          AND is_active = true
        """,
        {"fqn": fqn},
        conn=conn,
    )
    active_cols = [str(r["column_name"]) for _, r in df_cols.iterrows()]
    dup_cols = {c for c in active_cols if active_cols.count(c) > 1}
    if dup_cols:
        errors.append(f"Duplicate active column rows: {sorted(dup_cols)}")
    if set(active_cols) != expected_cols:
        errors.append(
            f"Active columns mismatch. expected={len(expected_cols)} actual={len(set(active_cols))}"
        )

    # Active column checks: exactly one row per expected (column, validation_name).
    df_col_checks = execute_query(
        f"""
        SELECT column_name, validation_name
        FROM {PREFIX}uc1_column_validation_registry_b
        WHERE fully_qualified_name = :fqn
          AND is_active = true
        """,
        {"fqn": fqn},
        conn=conn,
    )
    active_col_checks = [
        (str(r["column_name"]), str(r["validation_name"]))
        for _, r in df_col_checks.iterrows()
    ]
    dup_col_checks = {k for k in active_col_checks if active_col_checks.count(k) > 1}
    if dup_col_checks:
        errors.append(f"Duplicate active column checks: {sorted(dup_col_checks)}")
    if set(active_col_checks) != expected_col_checks:
        errors.append(
            f"Active column checks mismatch. expected={len(expected_col_checks)} actual={len(set(active_col_checks))}"
        )

    # Active table checks: exactly one row per expected validation_name.
    df_tbl_checks = execute_query(
        f"""
        SELECT validation_name
        FROM {PREFIX}uc1_table_validation_registry_b
        WHERE fully_qualified_name = :fqn
          AND is_active = true
        """,
        {"fqn": fqn},
        conn=conn,
    )
    active_tbl_checks = [str(r["validation_name"]) for _, r in df_tbl_checks.iterrows()]
    dup_tbl_checks = {k for k in active_tbl_checks if active_tbl_checks.count(k) > 1}
    if dup_tbl_checks:
        errors.append(f"Duplicate active table checks: {sorted(dup_tbl_checks)}")
    if set(active_tbl_checks) != expected_table_checks:
        errors.append(
            f"Active table checks mismatch. expected={len(expected_table_checks)} actual={len(set(active_tbl_checks))}"
        )

    return errors


def _workspace_client_pat() -> WorkspaceClient:
    return WorkspaceClient(
        host=DATABRICKS_HOST,
        token=DATABRICKS_TOKEN,
        auth_type="pat",
    )


def _persist_last_baseline_run_id(fqn: str, run_id: str, conn=None):
    execute_write(
        f"""
        UPDATE {PREFIX}uc1_table_registry_b
        SET last_baseline_run_id = :run_id
        WHERE fully_qualified_name = :fqn
        """,
        {"run_id": str(run_id), "fqn": fqn},
        conn=conn,
    )


def _first_error_line(text: str) -> str:
    txt = (text or "").strip()
    if not txt:
        return ""
    return txt.splitlines()[0][:300]


def _render_baseline_modal_status(status: dict) -> html.Div:
    st = status or {}
    fqn = st.get("fqn", "")
    registry_ok = bool(st.get("registry_ok", False))
    run_id = st.get("baseline_run_id")
    run_url = st.get("baseline_run_url")
    life_cycle = st.get("baseline_life_cycle", "")
    result_state = st.get("baseline_result_state", "")
    err = st.get("baseline_error", "")

    rows = [
        dbc.Alert("Registry saved ✓" if registry_ok else "Registry save failed.", color="success" if registry_ok else "danger", className="mb-2")
    ]

    if run_id:
        status_text = f"Baseline job run {run_id}"
        if life_cycle:
            status_text += f" · {life_cycle}"
        if result_state:
            status_text += f" / {result_state}"
        rows.append(dbc.Alert([
            html.Div("Baseline job queued/running", style={"fontWeight": "700"}),
            html.Div(status_text),
            html.A("Open run", href=run_url, target="_blank") if run_url else html.Div(),
        ], color="info" if life_cycle not in {"TERMINATED", "INTERNAL_ERROR", "SKIPPED"} else ("success" if result_state == "SUCCESS" else "danger"), className="mb-2"))

    if err:
        rows.append(dbc.Alert(f"Baseline error: {err}", color="danger", className="mb-2"))

    rows.append(
        dbc.Button(
            "Retry baseline",
            id="ob-retry-baseline-btn",
            color="warning",
            size="sm",
            style={"display": "inline-block" if st.get("can_retry", False) else "none"},
        )
    )

    return html.Div(rows)


def _trigger_agent1_baseline_job(table_meta: dict, baseline: dict) -> dict:
    if not DS_AGENT1_BASELINE_JOB_ID:
        return {
            "ok": False,
            "message": "DS_AGENT1_BASELINE_JOB_ID is not configured.",
        }

    fqn = (
        f"{table_meta.get('catalog')}."
        f"{table_meta.get('schema')}."
        f"{table_meta.get('table_name')}"
    )
    mode = baseline.get("baseline_mode", BASELINE_MODE_LAST30)
    run_mode = "CUSTOM" if mode == BASELINE_MODE_CUSTOM else "INITIAL"
    baseline_start = str(baseline.get("window_start") or "")
    baseline_end = str(baseline.get("window_end") or "")
    try:
        as_of_date = str(date.fromisoformat(baseline_end[:10]) + timedelta(days=1))
    except Exception:
        as_of_date = str(date.today())

    params = {
        "run_mode": run_mode,
        "table_filter": fqn,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
        "as_of_date": as_of_date,
    }

    w = _workspace_client_pat()
    run_now = w.jobs.run_now(job_id=int(DS_AGENT1_BASELINE_JOB_ID), job_parameters=params)
    run_id_raw = (
        getattr(run_now, "run_id", None)
        or getattr(getattr(run_now, "response", None), "run_id", None)
    )
    if run_id_raw is None:
        return {
            "ok": False,
            "message": "Agent1 run_now did not return a run_id.",
        }
    run_id = int(run_id_raw)

    run_url = f"https://{DATABRICKS_HOST}/jobs/{DS_AGENT1_BASELINE_JOB_ID}/runs/{run_id}" if DATABRICKS_HOST else None

    return {
        "ok": True,
        "run_id": run_id,
        "run_url": run_url,
        "job_parameters": params,
        "message": "Baseline recompute job queued.",
    }

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
    is_modify_flow = bool((baseline or {}).get("is_modify_flow", False))
    recompute = True if not is_modify_flow else bool(baseline.get("recompute", False))

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

    existing_active_registration = False
    old_counts = {"columns": 0, "column_validations": 0, "table_validations": 0}
    new_counts = dict(old_counts)
    insert_failed_tables = []

    # Batch timestamp is captured once before any insert in this run.
    ts_df = execute_query("SELECT current_timestamp() AS ts", conn=conn)
    batch_ts = ts_df.iloc[0]["ts"]

    existing_df = execute_query(
        f"""
        SELECT 1
        FROM {PREFIX}uc1_table_registry_b
        WHERE fully_qualified_name = :fqn
          AND is_active = true
        LIMIT 1
        """,
        {"fqn": fqn},
        conn=conn,
    )
    existing_active_registration = not existing_df.empty
    if existing_active_registration:
        old_counts = _active_config_counts(conn, fqn)

    # ── Step A: Register or modify table registry row ──────────────────────
    try:
        table_params = {
            "fqn": fqn,
            "table_catalog": table_meta.get("catalog", TARGET_CATALOG),
            "table_schema": table_meta.get("schema", TARGET_SCHEMA),
            "table_name": tname,
            "source_type": table_meta.get("ingestion_type", "FILE"),
            "ingestion_pattern": table_meta.get("layer", "BRONZE"),
            "ingestion_frequency": table_meta.get("ingestion_frequency", "DAILY"),
            "business_date_column": (
                table_meta.get("date_column", "")
                if table_meta.get("date_column") != _NO_DATE_COL_VALUE
                else ""
            ),
            "baseline_lag_days": _coerce_min_one_day(
                baseline.get("baseline_lag_days", DEFAULT_BASELINE_LAG_DAYS),
                DEFAULT_BASELINE_LAG_DAYS,
            ),
            "validation_lag_days": _coerce_min_one_day(
                baseline.get("validation_lag_days", DEFAULT_VALIDATION_LAG_DAYS),
                DEFAULT_VALIDATION_LAG_DAYS,
            ),
        }
        table_params["bl_lag"] = table_params["baseline_lag_days"]
        table_params["val_lag"] = table_params["validation_lag_days"]

        table_cols = _table_columns(f"{PREFIX}uc1_table_registry_b", conn=conn)
        if existing_active_registration:
            set_parts = [
                "table_catalog = :table_catalog",
                "table_schema = :table_schema",
                "table_name = :table_name",
                "source_type = :source_type",
                "ingestion_pattern = :ingestion_pattern",
                "ingestion_frequency = :ingestion_frequency",
                "business_date_column = :business_date_column",
                "registered_timestamp = current_timestamp()",
            ]
            if "baseline_lag_days" in table_cols:
                set_parts.append("baseline_lag_days = :bl_lag")
            if "validation_lag_days" in table_cols:
                set_parts.append("validation_lag_days = :val_lag")
            if "change_reason" in table_cols:
                set_parts.append("change_reason = 'modify'")

            execute_write(
                f"""
                UPDATE {PREFIX}uc1_table_registry_b
                SET {', '.join(set_parts)}
                WHERE fully_qualified_name = :fqn
                  AND is_active = true
                """,
                table_params,
                conn=conn,
            )
        else:
            insert_cols = [
                "table_id",
                "table_catalog",
                "table_schema",
                "table_name",
                "fully_qualified_name",
                "source_type",
                "ingestion_pattern",
                "ingestion_frequency",
                "business_date_column",
                "is_active",
                "registered_timestamp",
                "registered_by",
            ]
            insert_vals = [
                ":table_id",
                ":table_catalog",
                ":table_schema",
                ":table_name",
                ":fqn",
                ":source_type",
                ":ingestion_pattern",
                ":ingestion_frequency",
                ":business_date_column",
                "true",
                "current_timestamp()",
                "'onboarding_wizard'",
            ]
            if "baseline_lag_days" in table_cols:
                insert_cols.append("baseline_lag_days")
                insert_vals.append(":baseline_lag_days")
            if "validation_lag_days" in table_cols:
                insert_cols.append("validation_lag_days")
                insert_vals.append(":validation_lag_days")

            execute_write(
                f"""
                INSERT INTO {PREFIX}uc1_table_registry_b (
                    {', '.join(insert_cols)}
                ) VALUES (
                    {', '.join(insert_vals)}
                )
                """,
                {**table_params, "table_id": str(uuid.uuid4())},
                conn=conn,
            )
        steps.append({
            "label" : "Table registry updated",
            "state" : "done",
            "detail": f"{fqn} ({'modify' if existing_active_registration else 'new'})",
        })
    except Exception as e:
        steps.append({
            "label" : "Table registry update",
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
            insert_failed_tables.append("uc1_column_registry_b")

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
            insert_failed_tables.append("uc1_column_validation_registry_b")

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
            insert_failed_tables.append("uc1_table_validation_registry_b")

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

    # ── Step E: Replace previous active config only after successful inserts ──
    if existing_active_registration:
        if insert_failed_tables:
            all_ok = False
            steps.append({
                "label": "Replaced previous configuration",
                "state": "error",
                "detail": "Skipped deactivation due to insert failures: "
                          + ", ".join(insert_failed_tables),
            })
        else:
            for table_name in [
                "uc1_column_registry_b",
                "uc1_column_validation_registry_b",
                "uc1_table_validation_registry_b",
            ]:
                execute_write(
                    f"""
                    UPDATE {PREFIX}{table_name}
                    SET is_active = false
                    WHERE fully_qualified_name = :fqn
                      AND is_active = true
                      AND created_timestamp < :batch_ts
                    """,
                    {"fqn": fqn, "batch_ts": batch_ts},
                    conn=conn,
                )

            new_counts = _active_config_counts(conn, fqn)
            verification_errors = _verify_active_config_uniqueness(
                conn, fqn, col_config or {}, table_checks or {}
            )
            if verification_errors:
                all_ok = False
                steps.append({
                    "label": "Replaced previous configuration",
                    "state": "error",
                    "detail": (
                        f"columns {old_counts['columns']}→{new_counts['columns']}, "
                        f"column checks {old_counts['column_validations']}→{new_counts['column_validations']}, "
                        f"table checks {old_counts['table_validations']}→{new_counts['table_validations']} | "
                        + " ; ".join(verification_errors)
                    ),
                })
            else:
                steps.append({
                    "label": "Replaced previous configuration",
                    "state": "done",
                    "detail": (
                        f"columns {old_counts['columns']}→{new_counts['columns']}, "
                        f"column checks {old_counts['column_validations']}→{new_counts['column_validations']}, "
                        f"table checks {old_counts['table_validations']}→{new_counts['table_validations']}"
                    ),
                })
    else:
        steps.append({
            "label": "Replaced previous configuration",
            "state": "done",
            "detail": "Not needed for new table registration.",
        })

    # ── Step F: Baseline handling moved to Agent1 job ─────────────────────
    try:
        _persist_table_lags(
            conn,
            fqn,
            _coerce_min_one_day(
                baseline.get("baseline_lag_days", DEFAULT_BASELINE_LAG_DAYS),
                DEFAULT_BASELINE_LAG_DAYS,
            ),
            _coerce_min_one_day(
                baseline.get("validation_lag_days", DEFAULT_VALIDATION_LAG_DAYS),
                DEFAULT_VALIDATION_LAG_DAYS,
            ),
        )
    except Exception as e:
        logger.warning(f"Lag persistence skipped: {e}")

    if recompute:
        steps.append({
            "label" : "Baseline recompute",
            "state" : "done",
            "detail": "Deferred to Agent1 workflow trigger.",
        })
    else:
        steps.append({
            "label" : "Baseline recompute",
            "state" : "done",
            "detail": "Skipped — recompute not selected.",
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
    Output("ob-execute-btn-visible", "disabled", allow_duplicate=True),
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
                "Triggering Agent1 baseline recompute (optional)",
            ]
        ], style={"border"      : f"1px solid {BORDER_COLOR}",
                  "borderRadius": "8px",
                  "overflow"    : "hidden"}),
    ])

    submission_id = str(uuid.uuid4())
    return True, pending_body, {"pending": True, "submission_id": submission_id}, True

@callback(
    Output("ob-exec-modal-body", "children", allow_duplicate=True),
    Output("ob-exec-status",     "data",     allow_duplicate=True),
    Output("ob-baseline-poll-interval", "disabled", allow_duplicate=True),
    Output("ob-execute-btn-visible", "disabled", allow_duplicate=True),
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

    submission_id = str(status.get("submission_id") or "").strip()
    if not submission_id:
        raise dash.exceptions.PreventUpdate
    if submission_id in _PROCESSED_SUBMISSION_IDS:
        raise dash.exceptions.PreventUpdate
    _PROCESSED_SUBMISSION_IDS.add(submission_id)

    if not table_meta or not table_meta.get("table_name"):
        raise dash.exceptions.PreventUpdate

    tname = table_meta.get("table_name", "")
    fqn   = table_meta.get("fqn", "")

    # Run onboarding registry/config writes
    results = _run_onboarding(
        table_meta, col_config, table_checks, baseline
    )

    ok = bool(results.get("all_ok", False))
    out_status = {
        "pending": False,
        "fqn": fqn,
        "submission_id": submission_id,
        "registry_ok": ok,
        "can_retry": False,
        "baseline_run_active": False,
    }

    should_queue_baseline = ok and baseline and (
        True if not bool((baseline or {}).get("is_modify_flow", False))
        else bool((baseline or {}).get("recompute", False))
    )

    if should_queue_baseline:
        try:
            job_result = _trigger_agent1_baseline_job(table_meta, baseline)
            if job_result.get("ok"):
                _persist_last_baseline_run_id(fqn, str(job_result.get("run_id")))
                out_status.update({
                    "baseline_run_id": job_result.get("run_id"),
                    "baseline_run_url": job_result.get("run_url"),
                    "baseline_job_parameters": job_result.get("job_parameters", {}),
                    "baseline_run_active": True,
                })
            else:
                out_status.update({
                    "baseline_error": job_result.get("message", "Job trigger failed."),
                    "can_retry": True,
                })
        except Exception as e:
            out_status.update({
                "baseline_error": str(e),
                "can_retry": True,
            })
    modal_body = _render_baseline_modal_status(out_status)
    return modal_body, out_status, (not out_status.get("baseline_run_active", False)), False


@callback(
    Output("ob-exec-modal-body", "children", allow_duplicate=True),
    Output("ob-exec-status", "data", allow_duplicate=True),
    Output("ob-baseline-poll-interval", "disabled", allow_duplicate=True),
    Input("ob-baseline-poll-interval", "n_intervals"),
    State("ob-exec-status", "data"),
    prevent_initial_call=True,
)
def poll_baseline_job(_n, status):
    st = dict(status or {})
    if not st.get("baseline_run_active"):
        raise dash.exceptions.PreventUpdate

    run_id = st.get("baseline_run_id")
    if not run_id:
        st["baseline_run_active"] = False
        st["can_retry"] = True
        st["baseline_error"] = "Missing run id for baseline poll."
        return _render_baseline_modal_status(st), st, True

    try:
        w = _workspace_client_pat()
        run_info = w.jobs.get_run(run_id=int(run_id))
        state = getattr(run_info, "state", None)
        life_cycle_raw = getattr(state, "life_cycle_state", None) if state is not None else None
        result_state_raw = getattr(state, "result_state", None) if state is not None else None
        life_cycle = getattr(life_cycle_raw, "value", str(life_cycle_raw or ""))
        result_state = getattr(result_state_raw, "value", str(result_state_raw or ""))

        st["baseline_life_cycle"] = life_cycle
        st["baseline_result_state"] = result_state
        st["baseline_run_url"] = getattr(run_info, "run_page_url", st.get("baseline_run_url"))

        if life_cycle in {"TERMINATED", "INTERNAL_ERROR", "SKIPPED"}:
            st["baseline_run_active"] = False
            if result_state != "SUCCESS":
                failed_task = None
                for t in (getattr(run_info, "tasks", None) or []):
                    t_state = getattr(t, "state", None)
                    t_result_raw = getattr(t_state, "result_state", None) if t_state is not None else None
                    t_result = getattr(t_result_raw, "value", str(t_result_raw or ""))
                    if t_result and t_result != "SUCCESS":
                        failed_task = t
                        break
                failed_task_key = getattr(failed_task, "task_key", "") if failed_task else ""
                task_state = getattr(failed_task, "state", None) if failed_task else None
                task_msg = getattr(task_state, "state_message", "") if task_state is not None else ""
                run_msg = getattr(state, "state_message", "") if state is not None else ""
                first_line = _first_error_line(task_msg or run_msg)
                st["baseline_error"] = (
                    f"Failed task: {failed_task_key}. {first_line}".strip()
                )
                st["can_retry"] = True

        return _render_baseline_modal_status(st), st, (not st.get("baseline_run_active", False))

    except Exception as e:
        st["baseline_run_active"] = False
        st["can_retry"] = True
        st["baseline_error"] = str(e)
        return _render_baseline_modal_status(st), st, True


@callback(
    Output("ob-exec-modal-body", "children", allow_duplicate=True),
    Output("ob-exec-status", "data", allow_duplicate=True),
    Output("ob-baseline-poll-interval", "disabled", allow_duplicate=True),
    Input("ob-retry-baseline-btn", "n_clicks"),
    State("ob-exec-status", "data"),
    prevent_initial_call=True,
)
def retry_baseline_only(n_clicks, status):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    st = dict(status or {})
    params = dict(st.get("baseline_job_parameters") or {})
    fqn = st.get("fqn", "")
    if not params or not fqn:
        st["baseline_error"] = "Missing previous baseline parameters for retry."
        st["can_retry"] = True
        return _render_baseline_modal_status(st), st, True

    if not DS_AGENT1_BASELINE_JOB_ID:
        st["baseline_error"] = "DS_AGENT1_BASELINE_JOB_ID is not configured."
        st["can_retry"] = True
        return _render_baseline_modal_status(st), st, True

    try:
        w = _workspace_client_pat()
        run_now = w.jobs.run_now(job_id=int(DS_AGENT1_BASELINE_JOB_ID), job_parameters=params)
        run_id = (
            getattr(run_now, "run_id", None)
            or getattr(getattr(run_now, "response", None), "run_id", None)
        )
        if run_id is None:
            raise RuntimeError("Agent1 retry run_now did not return a run_id.")

        _persist_last_baseline_run_id(fqn, str(run_id))
        st.update({
            "baseline_run_id": int(run_id),
            "baseline_run_active": True,
            "baseline_life_cycle": "PENDING",
            "baseline_result_state": "",
            "baseline_error": "",
            "can_retry": False,
        })
        return _render_baseline_modal_status(st), st, False
    except Exception as e:
        st["baseline_error"] = str(e)
        st["can_retry"] = True
        st["baseline_run_active"] = False
        return _render_baseline_modal_status(st), st, True
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

def _fallback_date_options_from_describe(fqn: str):
    options = []
    try:
        df = execute_query(f"DESCRIBE TABLE {fqn}")
        if df.empty:
            return options
        for _, row in df.iterrows():
            cname = str(row.iloc[0]).strip()
            dtype = str(row.iloc[1]).strip() if len(df.columns) > 1 else ""
            dtype_norm = dtype.upper().split("(")[0].split("<")[0].strip()
            if not cname or cname.startswith("#"):
                continue
            if dtype_norm in DATE_TYPES:
                options.append({"label": f"{cname}  ({dtype_norm})", "value": cname})
            elif dtype_norm == "STRING" and cname.lower() in DATE_NAME_HINTS:
                options.append({"label": f"{cname}  (STRING -> DATE)", "value": cname})
    except Exception:
        return []
    return options

@callback(
    Output("ob-date-col", "options"),
    Output("ob-date-col", "value"),
    Output("ob-date-col-disclaimer", "children"),
    Output("ob-date-col-analysis", "data"),
    Output("ob-date-reanalyse-btn", "style"),
    Output("ob-date-apply-lag-btn", "style"),
    Output("ob-date-apply-lag-label", "children"),
    Input("ob-table",     "value"),
    Input("ob-date-reanalyse-btn", "n_clicks"),
    State("ob-catalog",   "value"),
    State("ob-schema",    "value"),
    State("ob-date-col-analysis", "data"),
    running=[
        (Output("ob-date-col", "disabled"), True, False),
        (Output("ob-date-analysis-status", "children"), "Analysing date columns...", ""),
    ],
    background=True,
)
def load_date_columns(table, _reanalyse_clicks, catalog, schema, existing_analysis):
    if not table or not catalog or not schema:
        return [], None, html.Div(), {}, {"display": "none"}, {"display": "none"}, ""
    try:
        fqn = f"{catalog}.{schema}.{table}"
        validate_identifier(fqn)

        analysis_fqn = str((existing_analysis or {}).get("fqn") or "")
        triggered = str(ctx.triggered_id or "")
        try:
            curr_reanalyse_clicks = int(_reanalyse_clicks or 0)
        except Exception:
            curr_reanalyse_clicks = 0
        try:
            prev_reanalyse_clicks = int((existing_analysis or {}).get("_reanalyse_clicks") or 0)
        except Exception:
            prev_reanalyse_clicks = 0
        force_reanalyse = bool(
            triggered == "ob-date-reanalyse-btn"
            or curr_reanalyse_clicks > prev_reanalyse_clicks
        )

        if analysis_fqn == fqn and not force_reanalyse:
            analysis = existing_analysis or {}
        else:
            analysis = analyze_date_columns(fqn=fqn, reanalyse=force_reanalyse)
        analysis = dict(analysis or {})
        analysis["_reanalyse_clicks"] = curr_reanalyse_clicks

        candidates = list(analysis.get("candidates", []))
        profiles = {str(p.get("name") or ""): p for p in (analysis.get("profiles") or [])}
        recommended_column = str(analysis.get("recommended_column") or "")

        options = []
        has_non_excluded = False
        for c in candidates:
            cname = str(c.get("name") or "")
            if not cname:
                continue

            if bool(c.get("excluded")):
                options.append({
                    "label": f"{cname} (Not analysed (possible PII) - {c.get('exclude_reason')})",
                    "value": cname,
                    "disabled": True,
                })
                continue

            has_non_excluded = True
            role = str((profiles.get(cname) or {}).get("role") or c.get("role") or "AUDIT")
            is_rec = cname == recommended_column
            rec_suffix = " (Recommended)" if is_rec else ""
            options.append({
                "label": f"{cname}{rec_suffix} [{role}]",
                "value": cname,
            })

        options.append(_NO_DATE_COL_OPTION)

        reanalyse_style = {"display": "inline-block"}
        suggested_lag = int((analysis or {}).get("suggested_validation_lag_days") or 1)
        apply_style = {"display": "inline-block"} if has_non_excluded else {"display": "none"}
        apply_label = f"Suggested validation lag: {suggested_lag} days"

        if not has_non_excluded:
            no_date_msg = dbc.Alert(
                [
                    html.Strong("No reliable business date column detected."),
                    html.Br(),
                    html.Small(
                        "You can proceed with full-table baselines or add a date column.",
                        style=MUTED_STYLE,
                    ),
                ],
                color="warning",
                className="mt-2",
            )
            fallback_analysis = dict(analysis or {})
            fallback_analysis["recommended_column"] = _NO_DATE_COL_VALUE
            return (
                options,
                _NO_DATE_COL_VALUE,
                no_date_msg,
                fallback_analysis,
                reanalyse_style,
                {"display": "none"},
                "",
            )

        selected = recommended_column if recommended_column else options[0]["value"]
        disclaimer = _date_disclaimer_block(selected, analysis)

        return (
            options,
            selected,
            disclaimer,
            analysis,
            reanalyse_style,
            apply_style,
            apply_label,
        )

    except Exception as e:
        logger.error(f"load_date_columns failed: {e}")
        try:
            fqn = f"{catalog}.{schema}.{table}"
            fallback_opts = _fallback_date_options_from_describe(fqn)
        except Exception:
            fallback_opts = []
        fallback_opts.append(_NO_DATE_COL_OPTION)
        return (
            fallback_opts,
            (fallback_opts[0]["value"] if fallback_opts and fallback_opts[0].get("value") != _NO_DATE_COL_VALUE else _NO_DATE_COL_VALUE),
            warning_alert("Date analysis failed; showing describe-based date options."),
            {},
            {"display": "inline-block" if table else "none"},
            {"display": "none"},
            "",
        )


# ── Baseline warning (reads from visible pickers) ─────────────────────────

@callback(
    Output("ob-baseline-warning-visible", "children"),
    Input("ob-baseline-mode-visible",     "value"),
    Input("ob-baseline-lag-visible",      "value"),
    Input("ob-baseline-start-visible",    "date"),
    Input("ob-baseline-end-visible",      "date"),
)
def baseline_warning_visible(mode, lag_days, start, end):
    try:
        status = _window_validation(mode, lag_days, start, end)
        icon = "✅" if status["color"] == "success" else "⚠️"
        return dbc.Alert(
            f"{icon} {status['message']}",
            color=status["color"],
            className="mb-3",
        )
    except Exception:
        return html.Div()


@callback(
    Output("ob-baseline-start-visible", "disabled"),
    Output("ob-baseline-end-visible", "disabled"),
    Input("ob-baseline-mode-visible", "value"),
)
def toggle_custom_date_inputs(mode):
    custom_on = (mode or BASELINE_MODE_LAST30) == BASELINE_MODE_CUSTOM
    return (not custom_on), (not custom_on)


@callback(
    Output("ob-baseline-start-visible", "date", allow_duplicate=True),
    Output("ob-baseline-end-visible", "date", allow_duplicate=True),
    Input("ob-baseline-mode-visible", "value"),
    Input("ob-baseline-lag-visible", "value"),
    prevent_initial_call=True,
)
def sync_option_a_dates(mode, lag_days):
    if (mode or BASELINE_MODE_LAST30) != BASELINE_MODE_LAST30:
        return dash.no_update, dash.no_update
    start_dt, end_dt = _compute_option_a_window(lag_days)
    return str(start_dt), str(end_dt)


@callback(
    Output("ob-baseline-start-visible", "max_date_allowed"),
    Output("ob-baseline-end-visible", "max_date_allowed"),
    Input("ob-baseline-lag-visible", "value"),
)
def sync_custom_date_max_allowed(lag_days):
    lag = _coerce_min_one_day(lag_days, DEFAULT_BASELINE_LAG_DAYS)
    max_allowed = str(date.today() - timedelta(days=lag))
    return max_allowed, max_allowed


@callback(
    Output("ob-baseline-start-visible", "date", allow_duplicate=True),
    Output("ob-baseline-end-visible", "date", allow_duplicate=True),
    Input("ob-preset-prev-month", "n_clicks"),
    Input("ob-preset-last-30", "n_clicks"),
    Input("ob-preset-last-60", "n_clicks"),
    State("ob-baseline-lag-visible", "value"),
    prevent_initial_call=True,
)
def apply_date_presets(n_prev, n_30, n_60, lag_days):
    trig = ctx.triggered_id
    lag = _coerce_min_one_day(lag_days, DEFAULT_BASELINE_LAG_DAYS)
    _, end_dt = _compute_option_a_window(lag)
    if trig == "ob-preset-last-60":
        start_dt = end_dt - timedelta(days=59)
    elif trig == "ob-preset-prev-month":
        start_dt, end_dt = _compute_option_a_window(lag)
    else:
        start_dt = end_dt - timedelta(days=29)
    return str(start_dt), str(end_dt)


@callback(
    Output("ob-next-4-visible", "disabled"),
    Input("ob-baseline-mode-visible", "value"),
    Input("ob-baseline-lag-visible", "value"),
    Input("ob-baseline-start-visible", "date"),
    Input("ob-baseline-end-visible", "date"),
)
def disable_review_for_invalid_baseline(mode, lag_days, start, end):
    status = _window_validation(mode, lag_days, start, end)
    return not status["valid"]


@callback(
    Output("ob-date-col-disclaimer", "children", allow_duplicate=True),
    Input("ob-date-col", "value"),
    State("ob-date-col-analysis", "data"),
    State("ob-validation-lag-days", "data"),
    prevent_initial_call=True,
)
def update_date_col_disclaimer(selected_col, analysis, validation_lag_days):
    if not analysis:
        return html.Div()
    try:
        return _date_disclaimer_block(selected_col, analysis, validation_lag_days)
    except Exception as e:
        logger.warning(f"update_date_col_disclaimer failed: {e}")
        return html.Div()


@callback(
    Output("ob-validation-lag-days", "data", allow_duplicate=True),
    Output("ob-baseline", "data", allow_duplicate=True),
    Output("ob-date-col-disclaimer", "children", allow_duplicate=True),
    Input("ob-date-apply-lag-btn", "n_clicks"),
    State("ob-date-col-analysis", "data"),
    State("ob-baseline", "data"),
    State("ob-date-col", "value"),
    prevent_initial_call=True,
)
def apply_suggested_validation_lag(n_clicks, analysis, baseline, selected_col):
    if not n_clicks or not analysis:
        raise dash.exceptions.PreventUpdate

    try:
        suggested = max(1, int((analysis or {}).get("suggested_validation_lag_days") or 1))
    except Exception:
        suggested = 1

    new_baseline = dict(baseline or {})
    new_baseline["validation_lag_days"] = suggested
    new_disclaimer = _date_disclaimer_block(selected_col, analysis, suggested)
    return suggested, new_baseline, new_disclaimer


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


@callback(
    Output("ob-baseline-mode", "data"),
    Input("ob-baseline-mode-visible", "value"),
    prevent_initial_call=True,
)
def sync_baseline_mode(mode):
    return mode or BASELINE_MODE_LAST30


@callback(
    Output("ob-baseline-lag-days", "data"),
    Input("ob-baseline-lag-visible", "value"),
    prevent_initial_call=True,
)
def sync_baseline_lag_days(val):
    try:
        return max(1, int(val))
    except Exception:
        return DEFAULT_BASELINE_LAG_DAYS


@callback(
    Output("ob-validation-lag-days", "data"),
    Input("ob-validation-lag-visible", "value"),
    prevent_initial_call=True,
)
def sync_validation_lag_days(val):
    try:
        return max(1, int(val))
    except Exception:
        return DEFAULT_VALIDATION_LAG_DAYS


# ══════════════════════════════════════════════════════════════════════════
# STEP NAVIGATION CALLBACKS
# ══════════════════════════════════════════════════════════════════════════

# ── Next 1 → 2 ────────────────────────────────────────────────────────────

def _build_col_config_from_describe_df(df_desc):
    col_config = {}
    for _, row in df_desc.iterrows():
        cname = str(row.iloc[0]).strip()
        dtype = str(row.iloc[1]).strip() if len(df_desc.columns) > 1 else "STRING"
        if not cname or cname.startswith("#"):
            continue

        col_config[cname] = {
            "dtype": dtype,
            "nullable": True,
            "enabled": _type_base(dtype) not in ("STRUCT", "ARRAY"),
            "is_complex": is_complex_dtype(dtype),
            "checks": get_default_checks_for_dtype(dtype, cname),
            "warn_threshold": 5,
            "crit_threshold": 10,
        }

        if _type_base(dtype) in ("STRUCT", "ARRAY"):
            for leaf in flatten_nested_type(cname, dtype):
                col_config[leaf["path"]] = {
                    "dtype": leaf["dtype"],
                    "nullable": True,
                    "enabled": True,
                    "is_complex": is_complex_dtype(leaf["dtype"]),
                    "is_nested_child": True,
                    "parent_column": cname,
                    "checks": get_default_checks_for_dtype(leaf["dtype"], leaf["path"]),
                    "warn_threshold": 5,
                    "crit_threshold": 10,
                }

    return col_config

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
    State("ob-date-col-analysis", "data"),
    State("ob-col-config",      "data"),
    State("ob-table-checks",    "data"),
    State("ob-baseline",        "data"),
    prevent_initial_call=True,
)
def next_step1(
    n_clicks,
    catalog, schema, table, layer, ing_type, freq, date_col, owner,
    date_col_analysis, col_config, table_checks, baseline,
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

    suggested_col = str((date_col_analysis or {}).get("recommended_column") or "")
    date_override = bool(
        suggested_col
        and date_col != _NO_DATE_COL_VALUE
        and date_col != suggested_col
    )

    new_meta = {
        "catalog"            : catalog,
        "schema"             : schema,
        "table_name"         : table,
        "layer"              : layer,
        "ingestion_type"     : ing_type,
        "ingestion_frequency": freq,
        "date_column"        : date_col,
        "suggested_date_column": suggested_col,
        "date_column_overridden": date_override,
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

        new_col_config = _build_col_config_from_describe_df(df_desc)

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
            selected = (ch[i] if i < len(ch) else []) or []
            dtype = new_col[cname].get("dtype", "STRING")
            allowed = set(get_available_checks_for_dtype(dtype, cname))
            new_col[cname]["checks"] = [
                c for c in selected
                if c in allowed and _is_check_enabled_for_selection(c)
            ]
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
    Output("ob-baseline",     "data",     allow_duplicate=True),
    Output("ob-alert",        "children", allow_duplicate=True),
    Input("ob-next-3",        "n_clicks"),
    State({"type": "ob-tbl-check-enabled", "index": ALL}, "value"),
    State({"type": "ob-tbl-check-enabled", "index": ALL}, "id"),
    State({"type": "ob-tbl-check-warn",    "index": ALL}, "value"),
    State({"type": "ob-tbl-check-crit",    "index": ALL}, "value"),
    State("ob-col-config",    "data"),
    State("ob-baseline",      "data"),
    prevent_initial_call=True,
)
def next_step3(
    n_clicks,
    tbl_en_vals, tbl_en_ids, tbl_warn_vals, tbl_crit_vals,
    col_config, baseline,
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
                (tbl_en_vals[i] if i < len(tbl_en_vals) else False)
                and _is_check_enabled_for_selection(chk_id)
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

    baseline_data = dict(baseline or {})
    if baseline_data.get("is_modify_flow"):
        old_cols = baseline_data.get("_original_col_config") or {}
        old_tbl = baseline_data.get("_original_table_checks") or {}
        changed = (
            json.dumps(old_cols, sort_keys=True, default=str) != json.dumps(col_config or {}, sort_keys=True, default=str)
            or json.dumps(old_tbl, sort_keys=True, default=str) != json.dumps(new_tbl, sort_keys=True, default=str)
        )
        baseline_data["recompute"] = bool(changed)
        baseline_data["recompute_checked"] = ["recompute"] if changed else []

    return 4, new_tbl, baseline_data, html.Div()


# ── Next 4 → 5 ────────────────────────────────────────────────────────────

@callback(
    Output("ob-step",     "data",     allow_duplicate=True),
    Output("ob-baseline", "data",     allow_duplicate=True),
    Output("ob-alert",    "children", allow_duplicate=True),
    Input("ob-next-4",    "n_clicks"),
    State("ob-baseline-mode",    "data"),
    State("ob-baseline-lag-days", "data"),
    State("ob-validation-lag-days", "data"),
    State("ob-baseline-start",   "date"),
    State("ob-baseline-end",     "date"),
    State("ob-baseline-options", "value"),
    State("ob-baseline",         "data"),
    prevent_initial_call=True,
)
def next_step4(n_clicks, mode, bl_lag_days, val_lag_days, bl_start, bl_end, bl_options, baseline_state):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    mode = mode or BASELINE_MODE_LAST30

    baseline_lag_days = _coerce_min_one_day(bl_lag_days, DEFAULT_BASELINE_LAG_DAYS)
    validation_lag_days = _coerce_min_one_day(val_lag_days, DEFAULT_VALIDATION_LAG_DAYS)

    status = _window_validation(mode, baseline_lag_days, bl_start, bl_end)
    if not status["valid"]:
        return (
            dash.no_update,
            dash.no_update,
            error_alert(status["message"]),
        )

    start_dt = status["start"]
    end_dt = status["end"]
    bl_start = str(start_dt)
    bl_end = str(end_dt)

    new_bl = {
        "baseline_mode"    : mode,
        "baseline_lag_days" : baseline_lag_days,
        "validation_lag_days": validation_lag_days,
        "window_start"     : bl_start,
        "window_end"       : bl_end,
        "recompute"        : "recompute" in (bl_options or []),
        "recompute_checked": bl_options or [],
        "is_modify_flow"   : bool((baseline_state or {}).get("is_modify_flow", False)),
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
    Output("ob-table-meta", "data",   allow_duplicate=True),
    Output("ob-col-config", "data",   allow_duplicate=True),
    Output("ob-table-checks", "data", allow_duplicate=True),
    Output("ob-baseline", "data",     allow_duplicate=True),
    Output("ob-existing", "data",     allow_duplicate=True),
    Output("ob-alert",    "children", allow_duplicate=True),
    Input("ob-modify-btn","n_clicks"),
    State("ob-table-meta", "data"),
    State("ob-existing", "data"),
    prevent_initial_call=True,
)
def handle_modify(n_clicks, table_meta, existing):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    fqn = (existing or {}).get("fully_qualified_name") or (table_meta or {}).get("fqn")
    if not fqn:
        return (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            error_alert("Could not determine selected table for modify flow."),
        )

    try:
        safe_fqn = validate_identifier(fqn)

        df_desc = execute_query(f"DESCRIBE TABLE {safe_fqn}")
        col_config = _build_col_config_from_describe_df(df_desc)

        df_table = execute_query(
            f"""
            SELECT *
            FROM {PREFIX}uc1_table_registry_b
            WHERE fully_qualified_name = :fqn
            ORDER BY registered_timestamp DESC
            LIMIT 1
            """,
            {"fqn": fqn},
        )

        df_cols = execute_query(
            f"""
            SELECT column_name, expected_data_type, is_nullable, is_active
            FROM {PREFIX}uc1_column_registry_b
            WHERE fully_qualified_name = :fqn
            """,
            {"fqn": fqn},
        )
        for _, row in df_cols.iterrows():
            cname = str(row.get("column_name") or "").strip()
            if not cname:
                continue
            dtype = str(row.get("expected_data_type") or "STRING")
            cfg = col_config.get(cname, {
                "dtype": dtype,
                "nullable": bool(row.get("is_nullable", True)),
                "enabled": bool(row.get("is_active", True)),
                "is_complex": is_complex_dtype(dtype),
                "checks": get_default_checks_for_dtype(dtype, cname),
                "warn_threshold": 5,
                "crit_threshold": 10,
            })
            cfg["dtype"] = dtype
            cfg["nullable"] = bool(row.get("is_nullable", True))
            cfg["enabled"] = bool(row.get("is_active", True))
            col_config[cname] = cfg

        df_col_rules = execute_query(
            f"""
            SELECT
                column_name,
                validation_name,
                warning_threshold,
                critical_threshold,
                is_active
            FROM {PREFIX}uc1_column_validation_registry_b
            WHERE fully_qualified_name = :fqn
            """,
            {"fqn": fqn},
        )
        rules_by_col = {}
        thr_by_col = {}
        for _, row in df_col_rules.iterrows():
            if not bool(row.get("is_active", True)):
                continue
            cname = str(row.get("column_name") or "").strip()
            check = str(row.get("validation_name") or "").strip()
            if not cname or not check:
                continue
            if not _is_check_enabled_for_selection(check):
                continue
            rules_by_col.setdefault(cname, []).append(check)
            if cname not in thr_by_col:
                thr_by_col[cname] = (
                    row.get("warning_threshold"),
                    row.get("critical_threshold"),
                )

        for cname, cfg in col_config.items():
            checks = [
                c for c in rules_by_col.get(cname, cfg.get("checks", []))
                if _is_check_enabled_for_selection(c)
            ]
            cfg["checks"] = checks
            warn, crit = thr_by_col.get(cname, (cfg.get("warn_threshold", 5), cfg.get("crit_threshold", 10)))
            cfg["warn_threshold"] = 5 if warn is None else float(warn)
            cfg["crit_threshold"] = 10 if crit is None else float(crit)

        table_checks = {
            chk["id"]: {
                "enabled": chk["default_on"] and _is_check_enabled_for_selection(chk["id"]),
                "warn": chk["warn"],
                "crit": chk["crit"],
            }
            for chk in TABLE_CHECK_TYPES
        }
        df_tbl_rules = execute_query(
            f"""
            SELECT validation_name, warning_threshold, critical_threshold, is_active
            FROM {PREFIX}uc1_table_validation_registry_b
            WHERE fully_qualified_name = :fqn
            """,
            {"fqn": fqn},
        )
        for _, row in df_tbl_rules.iterrows():
            chk_id = str(row.get("validation_name") or "").strip()
            if chk_id not in table_checks or not _is_check_enabled_for_selection(chk_id):
                continue
            table_checks[chk_id] = {
                "enabled": bool(row.get("is_active", True)),
                "warn": row.get("warning_threshold"),
                "crit": row.get("critical_threshold"),
            }

        m_start, m_end = _compute_option_a_window(DEFAULT_BASELINE_LAG_DAYS)
        baseline = {
            "baseline_mode": BASELINE_MODE_LAST30,
            "baseline_lag_days": DEFAULT_BASELINE_LAG_DAYS,
            "validation_lag_days": DEFAULT_VALIDATION_LAG_DAYS,
            "window_start": str(m_start),
            "window_end": str(m_end),
            "recompute": False,
            "recompute_checked": [],
            "is_modify_flow": True,
            "_original_col_config": col_config,
            "_original_table_checks": table_checks,
        }

        if not df_table.empty:
            row = df_table.iloc[0]
            if "baseline_lag_days" in df_table.columns and row.get("baseline_lag_days") is not None:
                baseline["baseline_lag_days"] = _coerce_min_one_day(row.get("baseline_lag_days"), DEFAULT_BASELINE_LAG_DAYS)
            if "validation_lag_days" in df_table.columns and row.get("validation_lag_days") is not None:
                baseline["validation_lag_days"] = _coerce_min_one_day(row.get("validation_lag_days"), DEFAULT_VALIDATION_LAG_DAYS)

        try:
            df_latest_baseline = execute_query(
                f"""
                SELECT
                    baseline_version_id,
                    window_start,
                    window_end,
                    run_mode
                FROM {PREFIX}uc1_baseline_metrics_b
                WHERE fully_qualified_name = :fqn
                  AND baseline_version_id IS NOT NULL
                ORDER BY effective_date DESC, computed_timestamp DESC
                LIMIT 1
                """,
                {"fqn": fqn},
            )
            if not df_latest_baseline.empty:
                b = df_latest_baseline.iloc[0]
                ws = b.get("window_start")
                we = b.get("window_end")
                if ws and we:
                    baseline["baseline_mode"] = BASELINE_MODE_CUSTOM
                    baseline["window_start"] = str(ws)[:10]
                    baseline["window_end"] = str(we)[:10]
        except Exception as e:
            logger.warning(f"Baseline metadata prefill skipped for {fqn}: {e}")

        out_table_meta = dict(table_meta or {})
        parts = fqn.split(".")
        if len(parts) == 3:
            out_table_meta.update({
                "catalog": parts[0],
                "schema": parts[1],
                "table_name": parts[2],
                "fqn": fqn,
            })
        if not df_table.empty:
            r0 = df_table.iloc[0]
            out_table_meta["ingestion_type"] = str(r0.get("source_type") or out_table_meta.get("ingestion_type", "FILE"))
            out_table_meta["layer"] = str(r0.get("ingestion_pattern") or out_table_meta.get("layer", "BRONZE"))
            out_table_meta["ingestion_frequency"] = str(r0.get("ingestion_frequency") or out_table_meta.get("ingestion_frequency", "DAILY"))
            biz_col = str(r0.get("business_date_column") or "").strip()
            out_table_meta["date_column"] = biz_col if biz_col else _NO_DATE_COL_VALUE

        return 2, out_table_meta, col_config, table_checks, baseline, {}, html.Div()
    except Exception as e:
        logger.error(f"handle_modify failed: {e}")
        return (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            error_alert(f"Failed to load existing configuration: {e}"),
        )


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