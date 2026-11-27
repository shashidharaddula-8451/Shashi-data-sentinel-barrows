import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone

import requests

from config.settings import DATABRICKS_HOST, DATABRICKS_TOKEN
from db.connection import execute_query

logger = logging.getLogger(__name__)

DATE_TYPES = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "DATETIME", "TIMESTAMP_LTZ"}
COMPLEX_TYPES = {"MAP", "STRUCT", "ARRAY", "VARIANT", "OBJECT"}

DATE_NAME_HINTS = {
    "date", "created", "updated", "modified", "timestamp",
    "created_at", "updated_at", "event_time", "event_date",
    "load_date", "inserted_dt", "business_date", "run_date",
    "partition_date", "record_date", "file_date", "transaction_date",
    "start", "end", "__start_at", "_commit_timestamp",
}

DATE_PRIORITY = [
    "business_date", "inserted_dt", "updated_dt", "created", "updated",
    "created_at", "updated_at", "transaction_date", "event_date",
    "load_date", "created_date", "modified_date", "run_date",
    "partition_date", "record_date", "file_date", "__start_at",
]

PII_DENYLIST = [
    "email", "e_mail", "phone", "mobile", "ssn", "social", "tax_id", "passport", "license",
    "first_name", "last_name", "full_name", "contact", "address", "street", "zip", "postal", "city",
    "ip_address", "device_id", "user_name", "username", "password", "secret", "token", "card", "iban",
    "account_number", "dob", "birth", "date_of_birth", "gender", "ethnicity", "health", "salary",
]

TAG_DENY_PATTERN = r"(pii|sensitive|confidential|phi)"

DATE_PARSE_MIN_RATIO = 0.80
ANALYSIS_CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_CANDIDATES = 12

DATE_LLM_ENDPOINT = os.environ.get("DS_DATE_SUGGESTION_ENDPOINT", "databricks-gpt-oss-20b").strip()
DATE_LLM_TIMEOUT_SECONDS = int(os.environ.get("DS_DATE_SUGGESTION_TIMEOUT", "45"))
DATE_SAMPLE_LIMIT = int(os.environ.get("DS_DATE_SUGGESTION_SAMPLES", "12"))

_ANALYSIS_CACHE = {}


def _now_epoch() -> int:
    return int(time.time())


def _quote_ident(name: str) -> str:
    return "`" + str(name).replace("`", "``") + "`"


def _normalize_type(dtype: str) -> str:
    return (dtype or "").upper().split("<")[0].split("(")[0].strip()


def parse_date_expr(column_expr: str) -> str:
    return f"COALESCE(TRY_CAST({column_expr} AS DATE), TO_DATE(TRY_TO_TIMESTAMP({column_expr})))"


def verify_parse_expression_unit_test() -> dict:
    try:
        q = f"""
        SELECT
            CAST({parse_date_expr("'2026-09-22'")} AS STRING) AS d1,
            CAST({parse_date_expr("'2026-09-24T12:30:49.883000'")} AS STRING) AS d2
        """
        df = execute_query(q)
        if df.empty:
            return {"ok": False, "reason": "empty_result"}
        d1 = str(df.iloc[0].get("d1") or "")[:10]
        d2 = str(df.iloc[0].get("d2") or "")[:10]
        return {"ok": (d1 == "2026-09-22" and d2 == "2026-09-24"), "d1": d1, "d2": d2}
    except Exception as e:
        logger.warning("date parse expression unit test failed: %s", e)
        return {"ok": False, "reason": "exception"}


def _split_fqn(fqn: str):
    parts = str(fqn).split(".")
    if len(parts) < 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]


def _safe_float(v, d=0.0):
    try:
        if v is None:
            return d
        return float(v)
    except Exception:
        return d


def _safe_int(v, d=0):
    try:
        if v is None:
            return d
        return int(v)
    except Exception:
        return d


def _name_tokens(name: str) -> str:
    x = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or ""))
    x = re.sub(r"[^a-zA-Z0-9]+", "_", x).strip("_").lower()
    return x


def _looks_like_pii_name(name: str) -> bool:
    t = _name_tokens(name)
    if not t:
        return False
    return any(token in t for token in PII_DENYLIST)


def _priority_index(name: str) -> int:
    lname = str(name or "").lower()
    try:
        return DATE_PRIORITY.index(lname)
    except ValueError:
        return 999


def _load_tagged_pii_columns(catalog: str, schema: str, table: str):
    tagged_cols = set()
    table_tagged = False

    try:
        df_col = execute_query(
            f"""
            SELECT LOWER(column_name) AS column_name
            FROM {catalog}.information_schema.column_tags
            WHERE table_schema = :table_schema
              AND table_name = :table_name
              AND (
                REGEXP_LIKE(LOWER(tag_name), :deny)
                OR REGEXP_LIKE(LOWER(tag_value), :deny)
              )
            """,
            {
                "table_schema": schema,
                "table_name": table,
                "deny": TAG_DENY_PATTERN,
            },
        )
        if not df_col.empty and "column_name" in df_col.columns:
            tagged_cols = {str(v).lower() for v in df_col["column_name"].dropna().tolist()}
    except Exception as e:
        logger.info("column_tags query unavailable for %s.%s: %s", schema, table, e)

    try:
        df_tbl = execute_query(
            f"""
            SELECT 1 AS hit
            FROM {catalog}.information_schema.table_tags
            WHERE table_schema = :table_schema
              AND table_name = :table_name
              AND (
                REGEXP_LIKE(LOWER(tag_name), :deny)
                OR REGEXP_LIKE(LOWER(tag_value), :deny)
              )
            LIMIT 1
            """,
            {
                "table_schema": schema,
                "table_name": table,
                "deny": TAG_DENY_PATTERN,
            },
        )
        table_tagged = not df_tbl.empty
    except Exception as e:
        logger.info("table_tags query unavailable for %s.%s: %s", schema, table, e)

    return tagged_cols, table_tagged


def _load_column_masks(catalog: str, schema: str, table: str):
    masked_cols = set()
    try:
        df = execute_query(
            f"""
            SELECT LOWER(column_name) AS column_name
            FROM {catalog}.information_schema.column_masks
            WHERE table_schema = :table_schema
              AND table_name = :table_name
            """,
            {"table_schema": schema, "table_name": table},
        )
        if not df.empty and "column_name" in df.columns:
            masked_cols = {str(v).lower() for v in df["column_name"].dropna().tolist()}
    except Exception as e:
        logger.info("column_masks query unavailable for %s.%s: %s", schema, table, e)
    return masked_cols


def _describe_extended_text(fqn: str) -> str:
    try:
        df = execute_query(f"DESCRIBE TABLE EXTENDED {fqn}")
        if df.empty:
            return ""
        return " ".join(str(v).lower() for v in df.fillna("").values.flatten().tolist())
    except Exception:
        return ""


def _table_has_row_filter(fqn: str) -> bool:
    txt = _describe_extended_text(fqn)
    return ("row filter" in txt and "none" not in txt)


def _describe_table_type(fqn: str) -> str:
    try:
        df = execute_query(f"DESCRIBE TABLE EXTENDED {fqn}")
        if df.empty:
            return "UNKNOWN"
        for _, row in df.iterrows():
            k = str(row.iloc[0]).strip().lower()
            if k == "type":
                return str(row.iloc[1]).strip().upper()
    except Exception as e:
        logger.info("table type detection failed for %s: %s", fqn, e)
    return "UNKNOWN"


def _describe_columns(fqn: str):
    out = []
    df = execute_query(f"DESCRIBE TABLE {fqn}")
    if df.empty:
        return out
    for _, row in df.iterrows():
        cname = str(row.iloc[0]).strip()
        dtype = str(row.iloc[1]).strip() if len(df.columns) > 1 else ""
        if not cname or cname.startswith("#"):
            continue
        out.append({
            "name": cname,
            "dtype": dtype,
            "dtype_norm": _normalize_type(dtype),
            "is_nested": ("." in cname or "[" in cname or "]" in cname),
        })
    return out


def _string_parse_ratios_sample_200(fqn: str, string_cols: list):
    if not string_cols:
        return {}

    select_cols = ", ".join(_quote_ident(c) for c in string_cols)
    where_any = " OR ".join(f"{_quote_ident(c)} IS NOT NULL" for c in string_cols)

    ratio_exprs = []
    for c in string_cols:
        qc = _quote_ident(c)
        p = parse_date_expr(qc)
        alias = f"pr__{re.sub(r'[^a-zA-Z0-9_]', '_', c.lower())}"
        ratio_exprs.append(f"AVG(CASE WHEN {p} IS NOT NULL THEN 1.0 ELSE 0.0 END) AS {alias}")

    q = f"""
    WITH s AS (
        SELECT {select_cols}
        FROM {fqn}
        WHERE {where_any}
        LIMIT 200
    )
    SELECT {", ".join(ratio_exprs)}
    FROM s
    """

    out = {}
    try:
        df = execute_query(q)
        if df.empty:
            return out
        row = df.iloc[0]
        for c in string_cols:
            alias = f"pr__{re.sub(r'[^a-zA-Z0-9_]', '_', c.lower())}"
            out[c] = _safe_float(row.get(alias), 0.0)
        return out
    except Exception as e:
        logger.info("string parse ratio query failed for %s: %s", fqn, e)
        return out


def _discover_candidates(fqn: str, catalog: str, schema: str, table: str):
    columns = _describe_columns(fqn)
    tagged_cols, table_tagged = _load_tagged_pii_columns(catalog, schema, table)
    masked_cols = _load_column_masks(catalog, schema, table)
    has_row_filter = _table_has_row_filter(fqn)

    string_cols_for_parse = []
    candidates = []
    excluded = []

    for c in columns:
        name = c["name"]
        lname = name.lower()
        dtype_norm = c["dtype_norm"]

        reason = None
        if lname == "__end_at":
            reason = "scd2_end_column"
        elif c.get("is_nested"):
            reason = "nested"
        elif dtype_norm in COMPLEX_TYPES:
            reason = "nested_or_complex"
        elif has_row_filter:
            reason = "table_row_filter"
        elif lname in tagged_cols:
            reason = "tagged_pii_column"
        elif table_tagged:
            reason = "tagged_pii_table"
        elif lname in masked_cols:
            reason = "column_mask"
        elif _looks_like_pii_name(name):
            reason = "pii_name_denylist"

        if reason:
            excluded.append({"name": name, "dtype": c["dtype"], "reason": reason})
            continue

        if dtype_norm in DATE_TYPES:
            candidates.append({
                "name": name,
                "dtype": dtype_norm,
                "candidate_source": "native_date_type",
                "parse_ratio_seed": 1.0,
            })
        elif dtype_norm == "STRING":
            string_cols_for_parse.append(name)

    parse_ratios = _string_parse_ratios_sample_200(fqn, string_cols_for_parse)
    for c in string_cols_for_parse:
        ratio = _safe_float(parse_ratios.get(c), 0.0)
        if ratio >= DATE_PARSE_MIN_RATIO:
            candidates.append({
                "name": c,
                "dtype": "STRING",
                "candidate_source": "string_parseable",
                "parse_ratio_seed": ratio,
            })
        else:
            excluded.append({"name": c, "dtype": "STRING", "reason": f"string_parse_ratio_lt_{DATE_PARSE_MIN_RATIO:.2f}"})

    def _sort_key(x):
        lname = str(x["name"]).lower()
        hint_rank = 0 if lname in DATE_NAME_HINTS else 1
        return (_priority_index(lname), hint_rank, lname)

    candidates = sorted(candidates, key=_sort_key)[:MAX_CANDIDATES]
    return columns, candidates, excluded


def _describe_size_bytes(fqn: str) -> int:
    try:
        df = execute_query(f"DESCRIBE DETAIL {fqn}")
        if df.empty:
            return 0
        return _safe_int(df.iloc[0].get("sizeInBytes"), 0)
    except Exception:
        return 0


def _history_commit_pattern(fqn: str):
    out = {
        "latest_commit_date": None,
        "typical_commit_hour_utc": None,
        "commits_per_day": None,
        "commit_count": 0,
    }
    try:
        df = execute_query(f"DESCRIBE HISTORY {fqn} LIMIT 50")
        if df.empty:
            return out

        op_col = "operation" if "operation" in df.columns else None
        ts_col = "timestamp" if "timestamp" in df.columns else None
        if not ts_col:
            return out

        keep = df.copy()
        if op_col:
            keep[op_col] = keep[op_col].astype(str).str.upper()
            keep = keep[
                ~keep[op_col].str.startswith("VACUUM")
                & ~keep[op_col].str.startswith("OPTIMIZE")
                & ~keep[op_col].str.contains("SET TBLPROPERTIES", regex=False)
            ]

        if keep.empty:
            return out

        keep[ts_col] = keep[ts_col].astype(str)
        parsed = []
        for x in keep[ts_col].str[:19].tolist():
            try:
                parsed.append(datetime.fromisoformat(x.replace("Z", "+00:00")))
            except Exception:
                pass
        if not parsed:
            return out

        parsed_utc = [p.astimezone(timezone.utc) if p.tzinfo else p.replace(tzinfo=timezone.utc) for p in parsed]
        dates = [p.date() for p in parsed_utc]
        hours = [p.hour for p in parsed_utc]

        per_day = {}
        for d in dates:
            per_day[d] = per_day.get(d, 0) + 1

        out["latest_commit_date"] = str(max(dates)) if dates else None
        out["typical_commit_hour_utc"] = max(set(hours), key=hours.count) if hours else None
        out["commits_per_day"] = (sum(per_day.values()) / max(1, len(per_day))) if per_day else None
        out["commit_count"] = len(parsed_utc)
    except Exception as e:
        logger.info("commit history read failed for %s: %s", fqn, e)
    return out


def _scd2_stats_one_query(fqn: str, columns: list):
    names = {c["name"].lower() for c in columns}
    has_start = "__start_at" in names
    has_end = "__end_at" in names
    is_scd2 = has_start and has_end

    out = {
        "is_scd2": is_scd2,
        "current_rows": None,
        "total_rows": None,
        "versions_per_key_avg": None,
        "start_eq_updated_ratio": None,
    }
    if not is_scd2:
        return out

    has_id = "id" in names
    has_updated = "updated" in names

    id_expr = (
        f"(SELECT AVG(cnt) FROM (SELECT COUNT(*) AS cnt FROM {fqn} WHERE id IS NOT NULL GROUP BY id) k)"
        if has_id else "CAST(NULL AS DOUBLE)"
    )
    upd_expr = (
        f"AVG(CASE WHEN __START_AT IS NOT NULL AND {parse_date_expr('updated')} IS NOT NULL AND TO_DATE(__START_AT) = {parse_date_expr('updated')} THEN 1.0 ELSE 0.0 END)"
        if has_updated else "CAST(NULL AS DOUBLE)"
    )

    try:
        df = execute_query(
            f"""
            SELECT
                COUNT(*) AS total_rows,
                SUM(CASE WHEN __END_AT IS NULL THEN 1 ELSE 0 END) AS current_rows,
                {id_expr} AS versions_per_key_avg,
                {upd_expr} AS start_eq_updated_ratio
            FROM {fqn}
            """
        )
        if not df.empty:
            r = df.iloc[0]
            out["total_rows"] = _safe_int(r.get("total_rows"), 0)
            out["current_rows"] = _safe_int(r.get("current_rows"), 0)
            out["versions_per_key_avg"] = _safe_float(r.get("versions_per_key_avg"), None)
            out["start_eq_updated_ratio"] = _safe_float(r.get("start_eq_updated_ratio"), None)
    except Exception as e:
        logger.info("scd2 stats query failed for %s: %s", fqn, e)

    return out


def _arrival_column(candidates: list, scd2_info: dict, commit_pattern: dict):
    if scd2_info.get("is_scd2"):
        return "__START_AT"

    arrival_re = re.compile(r"(__start_at|_commit_timestamp|updated|ingest|load)", re.IGNORECASE)
    ranked = [c["name"] for c in candidates if arrival_re.search(c["name"])]
    return ranked[0] if ranked else None


def _source_clause(fqn: str, sampled: bool) -> str:
    return f"{fqn} TABLESAMPLE (2 PERCENT)" if sampled else fqn


def _profile_candidates_one_query(fqn: str, candidates: list, arrival_column: str, is_scd2: bool, sampled: bool):
    if not candidates:
        return []

    src = _source_clause(fqn, sampled)
    pieces = []

    for cand in candidates:
        name = cand["name"]
        dtype = cand["dtype"]
        qcol = _quote_ident(name)
        d_expr = parse_date_expr(qcol)
        d_valid = f"CASE WHEN {d_expr} BETWEEN DATE '1900-01-01' AND DATE '2100-12-31' THEN {d_expr} END"

        arr_expr = "CAST(NULL AS DATE)"
        if arrival_column:
            arr_expr = parse_date_expr(_quote_ident(arrival_column))

        lag_select = "CAST(NULL AS DOUBLE)"
        lag_select_90 = "CAST(NULL AS DOUBLE)"
        lag_select_95 = "CAST(NULL AS DOUBLE)"
        lag_max = "CAST(NULL AS DOUBLE)"
        lag_neg = "CAST(NULL AS DOUBLE)"

        if arrival_column and name != arrival_column:
            lag_base = "SELECT DATEDIFF(arrival_date, d_valid) AS lag_days FROM base WHERE arrival_date IS NOT NULL AND d_valid IS NOT NULL"
            lag_select = f"(SELECT percentile_approx(lag_days, 0.5) FROM ({lag_base}) l)"
            lag_select_90 = f"(SELECT percentile_approx(lag_days, 0.9) FROM ({lag_base}) l)"
            lag_select_95 = f"(SELECT percentile_approx(lag_days, 0.95) FROM ({lag_base}) l)"
            lag_max = f"(SELECT MAX(lag_days) FROM ({lag_base}) l)"
            lag_neg = f"(SELECT AVG(CASE WHEN lag_days < 0 THEN 1.0 ELSE 0.0 END) FROM ({lag_base}) l)"

        current_median = "CAST(NULL AS DOUBLE)"
        if is_scd2:
            current_median = (
                "(SELECT percentile_approx(cnt, 0.5) "
                " FROM (SELECT d_valid AS d, COUNT(*) AS cnt"
                "       FROM base"
                "       WHERE d_valid IS NOT NULL AND end_at IS NULL AND d_valid >= DATE_SUB(current_date(), 30)"
                "       GROUP BY d_valid) cd)"
            )

        piece = f"""
        SELECT
            '{name}' AS column_name,
            '{dtype}' AS dtype,
            AVG(CASE WHEN raw_v IS NULL THEN 1.0 ELSE 0.0 END) AS null_ratio,
            AVG(CASE WHEN d_raw IS NOT NULL THEN 1.0 ELSE 0.0 END) AS parse_ratio,
            COUNT(DISTINCT d_valid) AS distinct_days,
            CAST(MIN(d_valid) AS STRING) AS min_date,
            CAST(MAX(d_valid) AS STRING) AS max_date,
            AVG(CASE WHEN d_valid > DATE_ADD(current_date(), 1) THEN 1.0 ELSE 0.0 END) AS future_ratio,
            (
                SELECT percentile_approx(cnt, 0.5)
                FROM (
                    SELECT d_valid AS d, COUNT(*) AS cnt
                    FROM base
                    WHERE d_valid IS NOT NULL AND d_valid >= DATE_SUB(current_date(), 30)
                    GROUP BY d_valid
                ) d0
            ) AS rows_per_day_median,
            (
                SELECT CASE WHEN AVG(cnt) = 0 THEN NULL ELSE STDDEV_SAMP(cnt) / AVG(cnt) END
                FROM (
                    SELECT d_valid AS d, COUNT(*) AS cnt
                    FROM base
                    WHERE d_valid IS NOT NULL AND d_valid >= DATE_SUB(current_date(), 30)
                    GROUP BY d_valid
                ) d1
            ) AS rows_per_day_cv,
            (
                SELECT
                    CASE
                        WHEN prior_med IS NULL OR prior_med = 0 THEN NULL
                        ELSE recent_rows / prior_med
                    END
                FROM (
                    SELECT
                        SUM(CASE WHEN d >= DATE_SUB(max_d, 2) THEN cnt ELSE 0 END) AS recent_rows,
                        percentile_approx(CASE WHEN d < DATE_SUB(max_d, 2) THEN cnt END, 0.5) AS prior_med
                    FROM (
                        SELECT d, cnt, MAX(d) OVER () AS max_d
                        FROM (
                            SELECT d_valid AS d, COUNT(*) AS cnt
                            FROM base
                            WHERE d_valid IS NOT NULL AND d_valid >= DATE_SUB(current_date(), 30)
                            GROUP BY d_valid
                        ) dd
                    ) x
                ) y
            ) AS recent_completeness,
            {lag_select} AS lag_p50,
            {lag_select_90} AS lag_p90,
            {lag_select_95} AS lag_p95,
            {lag_max} AS lag_max,
            {lag_neg} AS share_negative_lag,
            {current_median} AS current_rows_per_day_median,
            (
                SELECT CONCAT_WS(',', COLLECT_LIST(CAST(d AS STRING)))
                FROM (
                    SELECT d_valid AS d
                    FROM base
                    WHERE d_valid IS NOT NULL
                    GROUP BY d_valid
                    HAVING COUNT(*) >= 10
                    ORDER BY d DESC
                    LIMIT {int(max(1, DATE_SAMPLE_LIMIT))}
                ) ds
            ) AS sample_dates_csv,
            {1 if sampled else 0} AS sampled
        FROM (
            SELECT
                {qcol} AS raw_v,
                {d_expr} AS d_raw,
                {d_valid} AS d_valid,
                {arr_expr} AS arrival_date,
                {"__END_AT" if is_scd2 else "CAST(NULL AS TIMESTAMP)"} AS end_at
            FROM {src}
        ) base
        """
        pieces.append(piece.strip())

    union_sql = "\nUNION ALL\n".join(pieces)
    df = execute_query(union_sql)
    if df.empty:
        return []

    out = []
    for _, row in df.iterrows():
        sample_dates = []
        raw_csv = str(row.get("sample_dates_csv") or "").strip()
        if raw_csv:
            sample_dates = [s[:10] for s in raw_csv.split(",") if s]

        out.append({
            "name": str(row.get("column_name") or ""),
            "dtype": str(row.get("dtype") or ""),
            "parse_ratio": _safe_float(row.get("parse_ratio"), 0.0),
            "null_ratio": _safe_float(row.get("null_ratio"), 1.0),
            "distinct_days": _safe_int(row.get("distinct_days"), 0),
            "min_date": str(row.get("min_date") or "")[:10],
            "max_date": str(row.get("max_date") or "")[:10],
            "future_ratio": _safe_float(row.get("future_ratio"), 0.0),
            "rows_per_day_median": _safe_float(row.get("rows_per_day_median"), 0.0),
            "rows_per_day_cv": _safe_float(row.get("rows_per_day_cv"), 0.0),
            "recent_completeness": _safe_float(row.get("recent_completeness"), 0.0),
            "lag_p50": row.get("lag_p50"),
            "lag_p90": row.get("lag_p90"),
            "lag_p95": row.get("lag_p95"),
            "lag_max": row.get("lag_max"),
            "share_negative_lag": row.get("share_negative_lag"),
            "current_rows_per_day_median": row.get("current_rows_per_day_median"),
            "sampled": bool(_safe_int(row.get("sampled"), 0)),
            "sample_dates": sample_dates,
        })
    return out


def profile_date_candidate(fqn: str, column_name: str, dtype_norm: str, sampled: bool, arrival_column: str, is_scd2: bool):
    rows = _profile_candidates_one_query(
        fqn=fqn,
        candidates=[{"name": column_name, "dtype": dtype_norm}],
        arrival_column=arrival_column,
        is_scd2=is_scd2,
        sampled=sampled,
    )
    return rows[0] if rows else {
        "name": column_name,
        "dtype": dtype_norm,
        "parse_ratio": 0.0,
        "null_ratio": 1.0,
        "distinct_days": 0,
        "min_date": "",
        "max_date": "",
        "future_ratio": 0.0,
        "rows_per_day_median": 0.0,
        "rows_per_day_cv": 0.0,
        "recent_completeness": 0.0,
        "lag_p50": None,
        "lag_p90": None,
        "lag_p95": None,
        "lag_max": None,
        "share_negative_lag": None,
        "current_rows_per_day_median": None,
        "sampled": bool(sampled),
        "sample_dates": [],
    }


def _classify_role(profile: dict, arrival_column: str):
    name = str(profile.get("name") or "")
    lname = name.lower()

    if arrival_column and name == arrival_column:
        return "ARRIVAL"

    if re.search(r"(created|start|end|effective|expiry)", lname) or _safe_float(profile.get("future_ratio"), 0.0) > 0.05:
        return "LIFECYCLE"

    lag_p90 = profile.get("lag_p90")
    parse_ratio = _safe_float(profile.get("parse_ratio"), 0.0)
    future_ratio = _safe_float(profile.get("future_ratio"), 0.0)
    share_neg = profile.get("share_negative_lag")

    if parse_ratio >= 0.95 and lag_p90 is not None and _safe_float(lag_p90, 0.0) > 0 and future_ratio <= 0.05 and (_safe_float(share_neg, 0.0) <= 0.2):
        return "EVENT"

    if re.search(r"(updated|modified|audit)", lname):
        return "AUDIT"

    return "AUDIT"


def _suggested_validation_lag_days(role: str, profile: dict) -> int:
    if role == "ARRIVAL":
        return 1
    if role == "EVENT":
        lag = profile.get("lag_p90")
        if lag is None:
            return 1
        return max(1, min(60, int(math.ceil(_safe_float(lag, 1.0)))))
    return 1


def _rule_recommendation(profiles: list, arrival_column: str, scd2_info: dict):
    if not profiles:
        return None, "low", "No valid candidate columns found.", [], 1, False, "AUDIT"

    ranked = []
    for p in profiles:
        role = p.get("role")
        score = 0.0
        if role == "ARRIVAL":
            score += 100.0
        elif role == "EVENT":
            score += 80.0
        elif role == "AUDIT":
            score += 50.0
        else:
            score += 10.0
        score += _safe_float(p.get("parse_ratio"), 0.0) * 25.0
        score += (1.0 - min(1.0, _safe_float(p.get("null_ratio"), 1.0))) * 15.0
        score += min(1.0, _safe_float(p.get("recent_completeness"), 0.0)) * 10.0
        score += min(1.0, _safe_float(p.get("distinct_days"), 0) / 365.0) * 5.0
        if role == "LIFECYCLE":
            score -= 20.0
        ranked.append((score, p))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[0][1]
    top_role = str(top.get("role") or "AUDIT")

    suggested_lag = _suggested_validation_lag_days(top_role, top)
    use_current = bool(top_role == "EVENT" and scd2_info.get("is_scd2") and arrival_column and top.get("name") != arrival_column)

    explanation = (
        f"{top.get('name')} has parse {top.get('parse_ratio', 0.0) * 100:.1f}%, "
        f"null {top.get('null_ratio', 1.0) * 100:.1f}%, "
        f"recent completeness {top.get('recent_completeness', 0.0):.2f}."
    )

    if top_role == "ARRIVAL" and scd2_info.get("is_scd2"):
        alt_event = None
        for _, p in ranked[1:]:
            if str(p.get("role") or "") == "EVENT":
                alt_event = p
                break
        if alt_event is not None:
            explanation = (
                "Table is SCD2; __START_AT marks when each change arrived, so each day's slice is complete after 1 day. "
                f"'{alt_event.get('name')}' is an event date but 90% of rows arrive within { _safe_float(alt_event.get('lag_p90'), 0.0):.0f} days."
            )
        else:
            explanation = (
                "Table is SCD2; __START_AT marks when each change arrived, "
                "so each day's slice is complete after 1 day."
            )

    alternatives = []
    for _, p in ranked[1:4]:
        why_not = f"Role {p.get('role')}"
        if p.get("role") == "LIFECYCLE":
            why_not = "Lifecycle-style date is likely not a stable business-day slice"
        elif p.get("lag_p90") is not None and _safe_float(p.get("lag_p90"), 0.0) > suggested_lag:
            why_not = f"Late-arrival lag p90 {_safe_float(p.get('lag_p90'), 0.0):.1f} may require larger validation lag"
        alternatives.append({"column": p.get("name"), "why_not": why_not})

    return top.get("name"), "medium", explanation[:260], alternatives, suggested_lag, use_current, top_role


def _extract_model_content(response_data: dict) -> str:
    choices = response_data.get("choices", []) if isinstance(response_data, dict) else []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        txt = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if t:
                    txt.append(str(t))
        return " ".join(txt)
    return str(choices[0].get("text", ""))


def _parse_json_from_text(content: str) -> dict:
    txt = (content or "").strip()
    if not txt:
        return {}
    if "```json" in txt:
        txt = txt.split("```json", 1)[1]
        if "```" in txt:
            txt = txt.split("```", 1)[0]
    elif "```" in txt:
        parts = txt.split("```")
        if len(parts) >= 2:
            txt = parts[1]
    txt = txt.strip()
    s = txt.find("{")
    e = txt.rfind("}") + 1
    if s < 0 or e <= s:
        return {}
    try:
        return json.loads(txt[s:e])
    except Exception:
        return {}


def _validate_payload_allow_list(payload: dict):
    top_allowed = {
        "table_name", "table_type", "is_scd2", "scd2_stats", "arrival_column", "commit_pattern", "candidates"
    }
    cand_allowed = {
        "name", "dtype", "role", "parse_ratio", "null_ratio", "future_ratio",
        "distinct_days", "min_date", "max_date", "rows_per_day_median", "rows_per_day_cv",
        "recent_completeness", "lag_p50", "lag_p90", "lag_p95", "lag_max", "share_negative_lag", "sample_dates",
    }

    extra_top = set(payload.keys()) - top_allowed
    if extra_top:
        raise ValueError(f"non-allow-listed top-level keys: {sorted(extra_top)}")

    for c in payload.get("candidates", []):
        extra_c = set(c.keys()) - cand_allowed
        if extra_c:
            raise ValueError(f"non-allow-listed candidate keys: {sorted(extra_c)}")


def llm_date_recommendation(fqn: str, payload: dict, valid_candidates: set):
    if not payload.get("candidates"):
        return {"used": False, "reason": "no_candidates"}

    try:
        _validate_payload_allow_list(payload)
    except Exception as e:
        logger.warning("LLM payload validation failed for %s: %s", fqn, e)
        return {"used": False, "reason": "invalid_payload"}

    host = (DATABRICKS_HOST or "").strip().rstrip("/")
    token = (DATABRICKS_TOKEN or "").strip()
    if not host or not token or not DATE_LLM_ENDPOINT:
        return {"used": False, "reason": "missing_llm_env"}
    if not host.startswith("http"):
        host = f"https://{host}"

    system_prompt = (
        "You are a data architect choosing the column that defines which rows belong to a business day "
        "for daily data-quality validation. Prefer a column whose daily slice is complete and stable after "
        "a short lag. For SCD2/CDC tables, the arrival column (__START_AT) defines 'new data that day'; "
        "an event date is appropriate only if its late-arrival lag is acceptable, and then validation must "
        "use current versions only. Never choose lifecycle columns (created/start/end) unless nothing else exists."
    )

    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ],
        "temperature": 0,
        "max_tokens": 500,
    }

    try:
        resp = requests.post(
            f"{host}/serving-endpoints/{DATE_LLM_ENDPOINT}/invocations",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=DATE_LLM_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return {"used": False, "reason": f"http_{resp.status_code}"}

        parsed = _parse_json_from_text(_extract_model_content(resp.json()))
        rec = str(parsed.get("recommended_column") or "").strip()
        role = str(parsed.get("role") or "").strip().upper()
        lag_days = _safe_int(parsed.get("validation_lag_days"), 1)
        use_current = bool(parsed.get("use_current_versions_only", False))
        conf = str(parsed.get("confidence") or "medium").strip().lower()
        explanation = str(parsed.get("explanation") or "").strip()
        alts = parsed.get("alternatives") if isinstance(parsed.get("alternatives"), list) else []

        if rec not in valid_candidates:
            return {"used": False, "reason": "invalid_recommended_column"}
        if lag_days < 1 or lag_days > 60:
            return {"used": False, "reason": "invalid_lag"}
        if conf not in {"high", "medium", "low"}:
            conf = "medium"

        return {
            "used": True,
            "recommended_column": rec,
            "role": role if role else "EVENT",
            "validation_lag_days": lag_days,
            "use_current_versions_only": use_current,
            "confidence": conf,
            "explanation": explanation[:240],
            "alternatives": [
                {"column": str(a.get("column") or "").strip(), "why_not": str(a.get("why_not") or "").strip()}
                for a in alts[:5]
                if str(a.get("column") or "").strip()
            ],
        }
    except Exception as e:
        logger.warning("LLM recommendation failed for %s: %s", fqn, e)
        return {"used": False, "reason": "exception"}


def recommend_date_column(fqn: str, profiles: list, arrival_column: str, llm_payload: dict, scd2_info: dict):
    rule_rec, confidence, explanation, alternatives, suggested_lag, use_current, role = _rule_recommendation(
        profiles,
        arrival_column,
        scd2_info,
    )

    valid_candidates = {p.get("name") for p in profiles}
    llm = llm_date_recommendation(fqn, llm_payload, valid_candidates)
    if llm.get("used"):
        return {
            "recommended_column": llm.get("recommended_column"),
            "recommended_source": "llm",
            "role": llm.get("role") or role,
            "validation_lag_days": _safe_int(llm.get("validation_lag_days"), suggested_lag),
            "use_current_versions_only": bool(llm.get("use_current_versions_only", use_current)),
            "confidence": llm.get("confidence", confidence),
            "explanation": llm.get("explanation") or explanation,
            "alternatives": llm.get("alternatives") or alternatives,
            "llm": llm,
        }

    return {
        "recommended_column": rule_rec,
        "recommended_source": "rule",
        "role": role,
        "validation_lag_days": suggested_lag,
        "use_current_versions_only": use_current,
        "confidence": confidence,
        "explanation": explanation,
        "alternatives": alternatives,
        "llm": llm,
    }


def analyze_date_columns(fqn: str, reanalyse: bool = False):
    started = time.time()
    cache_hit = _ANALYSIS_CACHE.get(fqn)
    now = _now_epoch()
    if not reanalyse and cache_hit and (now - cache_hit.get("ts", 0) <= ANALYSIS_CACHE_TTL_SECONDS):
        return cache_hit["analysis"]

    parse_check = verify_parse_expression_unit_test()
    if not parse_check.get("ok"):
        logger.warning("parse expression unit test did not pass for %s", fqn)

    catalog, schema, table = _split_fqn(fqn)
    columns, candidates, excluded = _discover_candidates(fqn, catalog, schema, table)

    table_type = _describe_table_type(fqn)
    size_bytes = _describe_size_bytes(fqn)
    sampled = size_bytes > (5 * 1024 * 1024 * 1024)

    commit_pattern = _history_commit_pattern(fqn)
    scd2 = _scd2_stats_one_query(fqn, columns)
    arrival_column = _arrival_column(candidates, scd2, commit_pattern)

    profiles = _profile_candidates_one_query(
        fqn=fqn,
        candidates=candidates,
        arrival_column=arrival_column,
        is_scd2=bool(scd2.get("is_scd2")),
        sampled=sampled,
    )

    for p in profiles:
        p["role"] = _classify_role(p, arrival_column)
        p["suggested_validation_lag_days"] = _suggested_validation_lag_days(p["role"], p)
        p["use_current_versions_only"] = bool(
            p["role"] == "EVENT" and scd2.get("is_scd2") and arrival_column and p.get("name") != arrival_column
        )

    payload_candidates = []
    for p in profiles:
        payload_candidates.append({
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
            "sample_dates": p.get("sample_dates", [])[:DATE_SAMPLE_LIMIT],
        })

    llm_payload = {
        "table_name": table,
        "table_type": table_type,
        "is_scd2": bool(scd2.get("is_scd2")),
        "scd2_stats": {
            "current_rows": scd2.get("current_rows"),
            "total_rows": scd2.get("total_rows"),
            "versions_per_key_avg": scd2.get("versions_per_key_avg"),
            "start_eq_updated_ratio": scd2.get("start_eq_updated_ratio"),
        },
        "arrival_column": arrival_column,
        "commit_pattern": commit_pattern,
        "candidates": payload_candidates,
    }

    rec = recommend_date_column(fqn, profiles, arrival_column, llm_payload, scd2)

    profile_map = {p["name"]: p for p in profiles}
    candidates_ui = []
    for c in candidates:
        p = profile_map.get(c["name"], {})
        candidates_ui.append({
            "name": c["name"],
            "dtype": c["dtype"],
            "excluded": False,
            "exclude_reason": "",
            "role": p.get("role"),
        })
    for e in excluded:
        candidates_ui.append({
            "name": e["name"],
            "dtype": e["dtype"],
            "excluded": True,
            "exclude_reason": e["reason"],
            "role": "EXCLUDED",
        })

    analysis = {
        "fqn": fqn,
        "table_name": table,
        "table_type": table_type,
        "size_bytes": size_bytes,
        "sampled": sampled,
        "parse_unit_test": parse_check,
        "is_scd2": bool(scd2.get("is_scd2")),
        "scd2_stats": scd2,
        "arrival_column": arrival_column,
        "commit_pattern": commit_pattern,
        "candidates": candidates_ui,
        "profiles": profiles,
        "recommended_column": rec.get("recommended_column"),
        "recommended_source": rec.get("recommended_source"),
        "recommended_role": rec.get("role"),
        "suggested_validation_lag_days": rec.get("validation_lag_days", 1),
        "use_current_versions_only": bool(rec.get("use_current_versions_only", False)),
        "confidence": rec.get("confidence", "medium"),
        "explanation": rec.get("explanation", ""),
        "alternatives": rec.get("alternatives", []),
        "llm": rec.get("llm", {"used": False}),
        "allow_list_payload": llm_payload,
        "allow_list_payload_keys": sorted(list(llm_payload.keys())),
        "excluded_columns": excluded,
        "cache_expires_at_epoch": now + ANALYSIS_CACHE_TTL_SECONDS,
    }

    _ANALYSIS_CACHE[fqn] = {"ts": now, "analysis": analysis}
    elapsed = time.time() - started
    logger.info("date advisor analysis complete for %s in %.2fs with %d candidates", fqn, elapsed, len(candidates))
    return analysis


def dev_helper_barrows(catalog: str = "comms_media_prd", schema: str = "exposure_data_asset"):
    tables = [
        "bronze_barrows_campaign",
        "bronze_barrows_placement",
        "bronze_barrows_measurement",
    ]
    outputs = {}

    for t in tables:
        fqn = f"{catalog}.{schema}.{t}"
        analysis = analyze_date_columns(fqn=fqn, reanalyse=True)

        payload = analysis.get("allow_list_payload", {})
        payload_text = json.dumps(payload, ensure_ascii=True)

        # Safety sanity check: payload contains only allow-listed keys and date strings, never free-form non-date values.
        for marker in ["@", "password", "secret", "token", "ssn", "passport", "address", "phone"]:
            assert marker not in payload_text.lower(), f"possible payload leakage marker detected: {marker}"

        print("=" * 70)
        print(f"DATE ADVISOR DEV HELPER - {fqn}")
        print("Excluded columns:", analysis.get("excluded_columns", []))
        print("LLM payload keys:", analysis.get("allow_list_payload_keys", []))
        print("Analysis JSON:")
        print(json.dumps({
            "recommended_column": analysis.get("recommended_column"),
            "recommended_source": analysis.get("recommended_source"),
            "recommended_role": analysis.get("recommended_role"),
            "suggested_validation_lag_days": analysis.get("suggested_validation_lag_days"),
            "use_current_versions_only": analysis.get("use_current_versions_only"),
            "confidence": analysis.get("confidence"),
            "explanation": analysis.get("explanation"),
            "alternatives": analysis.get("alternatives", []),
            "profiles": analysis.get("profiles", []),
        }, ensure_ascii=True, indent=2))

        outputs[fqn] = analysis

    return outputs
