# db/queries.py

from config.settings import (
    TARGET_CATALOG,
    TARGET_SCHEMA,
    TABLE_REGISTRY,
    COLUMN_REGISTRY,
    COLUMN_VALIDATION_REGISTRY,
    TABLE_VALIDATION_REGISTRY,
    BASELINE_METRICS
)
from db.connection import validate_identifier

# ── Agent 2 Table References ───────────────────────────────────────────────

LAYER_REGISTRY     = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_layer_registry_b"
RECON_RUN          = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b"
RECON_RESULTS      = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_results_b"


# ═══════════════════════════════════════════════════════════════════════════
# UNITY CATALOG DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: TABLE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def get_all_registered_tables():
    return f"""
        SELECT
            table_id,
            fully_qualified_name,
            table_catalog,
            table_schema,
            table_name,
            source_type,
            ingestion_pattern,
            ingestion_frequency,
            partition_column,
            business_date_column,
            expected_arrival_window_minutes,
            is_active,
            registered_timestamp,
            registered_by,
            change_reason
        FROM {TABLE_REGISTRY}
        ORDER BY registered_timestamp DESC
    """


def get_table_by_fqn(fully_qualified_name: str):
    query = f"""
        SELECT *
        FROM {TABLE_REGISTRY}
        WHERE fully_qualified_name = :fully_qualified_name
    """
    return query, {"fully_qualified_name": fully_qualified_name}


def insert_table_registry(
    table_id                        : str,
    table_catalog                   : str,
    table_schema                    : str,
    table_name                      : str,
    fully_qualified_name            : str,
    source_type                     : str,
    ingestion_pattern               : str,
    ingestion_frequency             : str,
    partition_column                : str,
    business_date_column            : str,
    expected_arrival_window_minutes : int,
    registered_by                   : str,
    change_reason                   : str
):
    query = f"""
        INSERT INTO {TABLE_REGISTRY} (
            table_id,
            table_catalog,
            table_schema,
            table_name,
            fully_qualified_name,
            source_type,
            ingestion_pattern,
            ingestion_frequency,
            partition_column,
            business_date_column,
            expected_arrival_window_minutes,
            is_active,
            registered_timestamp,
            registered_by,
            change_reason
        ) VALUES (
            :table_id,
            :table_catalog,
            :table_schema,
            :table_name,
            :fully_qualified_name,
            :source_type,
            :ingestion_pattern,
            :ingestion_frequency,
            :partition_column,
            :business_date_column,
            :expected_arrival_window_minutes,
            true,
            current_timestamp(),
            :registered_by,
            :change_reason
        )
    """
    params = {
        "table_id": table_id,
        "table_catalog": table_catalog,
        "table_schema": table_schema,
        "table_name": table_name,
        "fully_qualified_name": fully_qualified_name,
        "source_type": source_type,
        "ingestion_pattern": ingestion_pattern,
        "ingestion_frequency": ingestion_frequency,
        "partition_column": partition_column if partition_column else None,
        "business_date_column": business_date_column if business_date_column else None,
        "expected_arrival_window_minutes": expected_arrival_window_minutes,
        "registered_by": registered_by,
        "change_reason": change_reason if change_reason else None,
    }
    return query, params


def toggle_table_active_status(fully_qualified_name: str, is_active: bool):
    query = f"""
        UPDATE {TABLE_REGISTRY}
        SET is_active = :is_active
        WHERE fully_qualified_name = :fully_qualified_name
    """
    return query, {"is_active": is_active, "fully_qualified_name": fully_qualified_name}


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: COLUMN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def get_columns_for_table(fully_qualified_name: str):
    query = f"""
        SELECT
            column_id,
            column_name,
            expected_data_type,
            is_nullable,
            is_active,
            is_business_key,
            created_timestamp,
            created_by
        FROM {COLUMN_REGISTRY}
        WHERE fully_qualified_name = :fully_qualified_name
        ORDER BY column_name
    """
    return query, {"fully_qualified_name": fully_qualified_name}


def insert_column_registry(
    column_id            : str,
    fully_qualified_name : str,
    column_name          : str,
    expected_data_type   : str,
    is_nullable          : bool,
    is_business_key      : bool,
    created_by           : str
):
    query = f"""
        INSERT INTO {COLUMN_REGISTRY} (
            column_id,
            fully_qualified_name,
            column_name,
            expected_data_type,
            is_nullable,
            is_active,
            is_business_key,
            created_timestamp,
            created_by
        ) VALUES (
            :column_id,
            :fully_qualified_name,
            :column_name,
            :expected_data_type,
            :is_nullable,
            true,
            :is_business_key,
            current_timestamp(),
            :created_by
        )
    """
    params = {
        "column_id": column_id,
        "fully_qualified_name": fully_qualified_name,
        "column_name": column_name,
        "expected_data_type": expected_data_type,
        "is_nullable": is_nullable,
        "is_business_key": is_business_key,
        "created_by": created_by,
    }
    return query, params


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: COLUMN VALIDATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def get_column_validations_for_table(fully_qualified_name: str):
    query = f"""
        SELECT
            column_validation_id,
            column_name,
            validation_name,
            is_active,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            custom_parameters,
            created_timestamp,
            created_by
        FROM {COLUMN_VALIDATION_REGISTRY}
        WHERE fully_qualified_name = :fully_qualified_name
        ORDER BY column_name, validation_name
    """
    return query, {"fully_qualified_name": fully_qualified_name}


def insert_column_validation(
    column_validation_id : str,
    fully_qualified_name : str,
    column_name          : str,
    validation_name      : str,
    warning_threshold    : float,
    critical_threshold   : float,
    threshold_unit       : str,
    custom_parameters    : str,
    created_by           : str
):
    query = f"""
        INSERT INTO {COLUMN_VALIDATION_REGISTRY} (
            column_validation_id,
            fully_qualified_name,
            column_name,
            validation_name,
            is_active,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            custom_parameters,
            created_timestamp,
            created_by
        ) VALUES (
            :column_validation_id,
            :fully_qualified_name,
            :column_name,
            :validation_name,
            true,
            :warning_threshold,
            :critical_threshold,
            :threshold_unit,
            :custom_parameters,
            current_timestamp(),
            :created_by
        )
    """
    params = {
        "column_validation_id": column_validation_id,
        "fully_qualified_name": fully_qualified_name,
        "column_name": column_name,
        "validation_name": validation_name,
        "warning_threshold": warning_threshold,
        "critical_threshold": critical_threshold,
        "threshold_unit": threshold_unit,
        "custom_parameters": custom_parameters if custom_parameters else None,
        "created_by": created_by,
    }
    return query, params


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: TABLE VALIDATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def get_table_validations(fully_qualified_name: str):
    query = f"""
        SELECT
            table_validation_id,
            validation_name,
            is_active,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            custom_parameters,
            created_timestamp,
            created_by
        FROM {TABLE_VALIDATION_REGISTRY}
        WHERE fully_qualified_name = :fully_qualified_name
        ORDER BY validation_name
    """
    return query, {"fully_qualified_name": fully_qualified_name}


def insert_table_validation(
    table_validation_id  : str,
    fully_qualified_name : str,
    validation_name      : str,
    warning_threshold    : float,
    critical_threshold   : float,
    threshold_unit       : str,
    custom_parameters    : str,
    created_by           : str
):
    query = f"""
        INSERT INTO {TABLE_VALIDATION_REGISTRY} (
            table_validation_id,
            fully_qualified_name,
            validation_name,
            is_active,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            custom_parameters,
            created_timestamp,
            created_by
        ) VALUES (
            :table_validation_id,
            :fully_qualified_name,
            :validation_name,
            true,
            :warning_threshold,
            :critical_threshold,
            :threshold_unit,
            :custom_parameters,
            current_timestamp(),
            :created_by
        )
    """
    params = {
        "table_validation_id": table_validation_id,
        "fully_qualified_name": fully_qualified_name,
        "validation_name": validation_name,
        "warning_threshold": warning_threshold,
        "critical_threshold": critical_threshold,
        "threshold_unit": threshold_unit,
        "custom_parameters": custom_parameters if custom_parameters else None,
        "created_by": created_by,
    }
    return query, params


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: BASELINE METRICS
# ═══════════════════════════════════════════════════════════════════════════

def get_baselines_for_table(fully_qualified_name: str):
    query = f"""
        SELECT
            baseline_id,
            column_name,
            check_type,
            metric_name,
            baseline_date,
            baseline_window_days,
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
        FROM {BASELINE_METRICS}
        WHERE fully_qualified_name = :fully_qualified_name
        ORDER BY baseline_date DESC, column_name, check_type
    """
    return query, {"fully_qualified_name": fully_qualified_name}


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 1: DASHBOARD SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def get_validation_coverage():
    return f"""
        SELECT
            t.fully_qualified_name,
            t.source_type,
            t.ingestion_frequency,
            t.is_active,
            COUNT(DISTINCT cr.column_name)              AS columns_enrolled,
            COUNT(DISTINCT cv.validation_name)          AS column_validations_configured,
            COUNT(DISTINCT tv.validation_name)          AS table_validations_configured
        FROM {TABLE_REGISTRY} t
        LEFT JOIN {COLUMN_REGISTRY} cr
            ON  t.fully_qualified_name = cr.fully_qualified_name
            AND cr.is_active           = true
        LEFT JOIN {COLUMN_VALIDATION_REGISTRY} cv
            ON  t.fully_qualified_name = cv.fully_qualified_name
            AND cv.is_active           = true
        LEFT JOIN {TABLE_VALIDATION_REGISTRY} tv
            ON  t.fully_qualified_name = tv.fully_qualified_name
            AND tv.is_active           = true
        GROUP BY
            t.fully_qualified_name,
            t.source_type,
            t.ingestion_frequency,
            t.is_active
        ORDER BY t.fully_qualified_name
    """


# ─────────────────────────────────────────────
# AGENT 1: VALIDATION RESULTS QUERIES
# ─────────────────────────────────────────────

VALIDATION_RUN     = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b"
VALIDATION_RESULTS = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_results_b"


def get_validation_run_summary():
    return f"""
        SELECT
            validation_run_id,
            business_date,
            SUBSTRING_INDEX(fully_qualified_name, '.', -1) AS table_name,
            fully_qualified_name,
            overall_status,
            total_checks_run,
            total_checks_passed,
            total_checks_warned,
            total_checks_critical,
            total_checks_errored,
            ai_enrichment_status,
            CASE WHEN alert_sent = true THEN 'YES' ELSE 'NO' END AS alert_fired,
            ROUND(validation_duration_seconds, 2)               AS duration_sec,
            created_timestamp
        FROM {VALIDATION_RUN}
        ORDER BY business_date DESC, fully_qualified_name
    """


def get_validation_results_for_run(validation_run_id: str):
    query = f"""
        SELECT
            result_id,
            check_type,
            check_level,
            column_name,
            check_status,
            ROUND(observed_value, 6)        AS observed_value,
            ROUND(baseline_value, 6)        AS baseline_value,
            ROUND(deviation_percentage, 4)  AS deviation_pct,
            threshold_warning,
            threshold_critical,
            ai_summary,
            ai_recommended_action,
            ai_failure_category,
            ROUND(ai_confidence_score, 2)   AS ai_confidence_score,
            check_detail,
            ROUND(check_duration_seconds, 3) AS duration_sec
        FROM {VALIDATION_RESULTS}
        WHERE validation_run_id = :validation_run_id
        ORDER BY
            CASE check_status
                WHEN 'CRITICAL' THEN 1
                WHEN 'WARNING'  THEN 2
                WHEN 'ERROR'    THEN 3
                WHEN 'PASS'     THEN 4
                ELSE 5
            END,
            check_type,
            column_name
    """
    return query, {"validation_run_id": validation_run_id}


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 2: LAYER REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def get_all_layers():
    return f"""
        SELECT
            layer_id,
            source_fully_qualified_name,
            layer_name,
            layer_fully_qualified_name,
            business_date_column,
            ROUND(expected_survival_rate * 100, 1) AS expected_survival_pct,
            expected_latency_minutes,
            reconciliation_metrics,
            is_active,
            registered_timestamp,
            registered_by
        FROM {LAYER_REGISTRY}
        ORDER BY
            source_fully_qualified_name,
            CASE layer_name
                WHEN 'BRONZE' THEN 1
                WHEN 'SILVER' THEN 2
                WHEN 'GOLD'   THEN 3
                ELSE 4
            END
    """


def insert_layer(
    layer_id                   : str,
    source_fully_qualified_name: str,
    layer_name                 : str,
    layer_fully_qualified_name : str,
    layer_catalog              : str,
    layer_schema               : str,
    layer_table                : str,
    business_date_column       : str,
    expected_survival_rate     : float,
    expected_latency_minutes   : int,
    reconciliation_metrics     : str,
    registered_by              : str
):
    survival = (
        expected_survival_rate / 100
        if expected_survival_rate > 1
        else expected_survival_rate
    )

    query = f"""
        INSERT INTO {LAYER_REGISTRY} (
            layer_id,
            source_fully_qualified_name,
            layer_name,
            layer_fully_qualified_name,
            layer_catalog,
            layer_schema,
            layer_table,
            business_date_column,
            expected_survival_rate,
            expected_latency_minutes,
            reconciliation_metrics,
            is_active,
            registered_timestamp,
            registered_by
        ) VALUES (
            :layer_id,
            :source_fully_qualified_name,
            :layer_name,
            :layer_fully_qualified_name,
            :layer_catalog,
            :layer_schema,
            :layer_table,
            :business_date_column,
            :expected_survival_rate,
            :expected_latency_minutes,
            :reconciliation_metrics,
            true,
            current_timestamp(),
            :registered_by
        )
    """
    params = {
        "layer_id": layer_id,
        "source_fully_qualified_name": source_fully_qualified_name,
        "layer_name": layer_name,
        "layer_fully_qualified_name": layer_fully_qualified_name,
        "layer_catalog": layer_catalog,
        "layer_schema": layer_schema,
        "layer_table": layer_table,
        "business_date_column": business_date_column,
        "expected_survival_rate": survival,
        "expected_latency_minutes": expected_latency_minutes,
        "reconciliation_metrics": reconciliation_metrics,
        "registered_by": registered_by,
    }
    return query, params


def update_layer(
    layer_id                   : str,
    layer_fully_qualified_name : str,
    business_date_column       : str,
    expected_survival_rate     : float,
    expected_latency_minutes   : int,
    reconciliation_metrics     : str
):
    survival = (
        expected_survival_rate / 100
        if expected_survival_rate > 1
        else expected_survival_rate
    )

    query = f"""
        UPDATE {LAYER_REGISTRY}
        SET
            layer_fully_qualified_name = :layer_fully_qualified_name,
            business_date_column       = :business_date_column,
            expected_survival_rate     = :expected_survival_rate,
            expected_latency_minutes   = :expected_latency_minutes,
            reconciliation_metrics     = :reconciliation_metrics
        WHERE layer_id = :layer_id
    """
    params = {
        "layer_fully_qualified_name": layer_fully_qualified_name,
        "business_date_column": business_date_column,
        "expected_survival_rate": survival,
        "expected_latency_minutes": expected_latency_minutes,
        "reconciliation_metrics": reconciliation_metrics,
        "layer_id": layer_id,
    }
    return query, params


def toggle_layer_active(layer_id: str, is_active: bool):
    query = f"""
        UPDATE {LAYER_REGISTRY}
        SET is_active = :is_active
        WHERE layer_id = :layer_id
    """
    return query, {"is_active": is_active, "layer_id": layer_id}


# ═══════════════════════════════════════════════════════════════════════════
# AGENT 2: RECONCILIATION QUERIES
# ═══════════════════════════════════════════════════════════════════════════

def get_reconciliation_run_summary():
    return f"""
        SELECT
            business_date,
            SUBSTRING_INDEX(
                source_fully_qualified_name, '.', -1
            )                                               AS table_name,
            source_fully_qualified_name,
            overall_status,
            total_checks_run,
            total_checks_passed,
            total_checks_warned,
            total_checks_critical,
            ai_enrichment_status,
            CASE
                WHEN alert_sent = true THEN 'YES'
                ELSE 'NO'
            END                                             AS alert_fired,
            reconciliation_run_id,
            created_timestamp
        FROM {RECON_RUN}
        ORDER BY business_date DESC, source_fully_qualified_name
    """


def get_reconciliation_results_for_run(reconciliation_run_id: str):
    query = f"""
        SELECT
            result_id,
            from_layer,
            to_layer,
            check_type,
            metric_name,
            check_status,
            ROUND(source_value, 4)         AS source_value,
            ROUND(target_value, 4)         AS target_value,
            ROUND(expected_value, 4)       AS expected_value,
            ROUND(deviation_percentage, 4) AS deviation_pct,
            threshold_warning,
            threshold_critical,
            agent1_overall_status,
            ai_summary,
            ai_recommended_action,
            ai_failure_category,
            ROUND(ai_confidence_score, 2)  AS ai_confidence_score,
            check_detail
        FROM {RECON_RESULTS}
        WHERE reconciliation_run_id = :reconciliation_run_id
        ORDER BY
            CASE check_status
                WHEN 'CRITICAL' THEN 1
                WHEN 'WARNING'  THEN 2
                WHEN 'PASS'     THEN 3
                ELSE 4
            END,
            from_layer,
            check_type
    """
    return query, {"reconciliation_run_id": reconciliation_run_id}


def get_combined_dashboard_summary():
    return f"""
        SELECT
            'Agent 1'                               AS agent,
            COUNT(DISTINCT fully_qualified_name)    AS tables_monitored,
            COUNT(DISTINCT business_date)           AS dates_validated,
            COALESCE(SUM(total_checks_run), 0)      AS total_checks_run,
            COALESCE(SUM(
                CASE WHEN overall_status = 'CRITICAL'
                THEN 1 ELSE 0 END
            ), 0)                                   AS critical_runs,
            COALESCE(SUM(
                CASE WHEN overall_status = 'PASS'
                THEN 1 ELSE 0 END
            ), 0)                                   AS pass_runs,
            MAX(business_date)                      AS latest_date
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b

        UNION ALL

        SELECT
            'Agent 2'                               AS agent,
            COUNT(DISTINCT source_fully_qualified_name),
            COUNT(DISTINCT business_date),
            COALESCE(SUM(total_checks_run), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'CRITICAL'
                THEN 1 ELSE 0 END
            ), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'PASS'
                THEN 1 ELSE 0 END
            ), 0),
            MAX(business_date)
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b

        UNION ALL

        SELECT
            'Agent 3'                               AS agent,
            COUNT(DISTINCT transformation_id),
            COUNT(DISTINCT DATE(review_timestamp)),
            COALESCE(SUM(total_checks_run), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'CRITICAL'
                THEN 1 ELSE 0 END
            ), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'PASS'
                THEN 1 ELSE 0 END
            ), 0),
            MAX(DATE(review_timestamp))
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b

        UNION ALL

        SELECT
            'Agent 4'                               AS agent,
            COUNT(DISTINCT gold_fully_qualified_name),
            COUNT(DISTINCT business_date),
            COALESCE(SUM(total_kpis_checked), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'CRITICAL'
                THEN 1 ELSE 0 END
            ), 0),
            COALESCE(SUM(
                CASE WHEN overall_status = 'PASS'
                THEN 1 ELSE 0 END
            ), 0),
            MAX(business_date)
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
    """


def get_control_plane_table_status():
    """
    Latest overall_status per monitored table, across all four UC stages,
    for the Released/Pending/Quarantined trust summary. One row per table
    reflecting its most recent check result.
    """
    return f"""
        SELECT table_name, overall_status
        FROM (
            SELECT fully_qualified_name AS table_name, overall_status, created_timestamp,
                   ROW_NUMBER() OVER (
                       PARTITION BY fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        ) WHERE rn = 1

        UNION ALL

        SELECT table_name, overall_status
        FROM (
            SELECT source_fully_qualified_name AS table_name, overall_status, created_timestamp,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        ) WHERE rn = 1

        UNION ALL

        SELECT table_name, overall_status
        FROM (
            SELECT target_fully_qualified_name AS table_name, overall_status, review_timestamp,
                   ROW_NUMBER() OVER (
                       PARTITION BY target_fully_qualified_name
                       ORDER BY review_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b
        ) WHERE rn = 1

        UNION ALL

        SELECT table_name, overall_status
        FROM (
            SELECT gold_fully_qualified_name AS table_name, overall_status, created_timestamp,
                   ROW_NUMBER() OVER (
                       PARTITION BY gold_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        ) WHERE rn = 1
    """


def get_control_plane_trust_trend():
    """
    Daily trust % (share of tables with a PASS overall_status) for the last
    7 business dates, across all four UC stages. One row per table per day
    (its latest run that day), aggregated into a single trust % per day.
    """
    return f"""
        WITH daily_status AS (
            SELECT business_date, fully_qualified_name AS table_name, overall_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_date, fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
            WHERE business_date >= DATE_SUB(CURRENT_DATE(), 7)

            UNION ALL

            SELECT business_date, source_fully_qualified_name AS table_name, overall_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_date, source_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
            WHERE business_date >= DATE_SUB(CURRENT_DATE(), 7)

            UNION ALL

            SELECT business_date, target_fully_qualified_name AS table_name, overall_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_date, target_fully_qualified_name
                       ORDER BY review_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b
            WHERE business_date >= DATE_SUB(CURRENT_DATE(), 7)

            UNION ALL

            SELECT business_date, gold_fully_qualified_name AS table_name, overall_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_date, gold_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
            WHERE business_date >= DATE_SUB(CURRENT_DATE(), 7)
        )
        SELECT
            business_date,
            ROUND(100.0 * SUM(CASE WHEN overall_status = 'PASS' THEN 1 ELSE 0 END) / COUNT(*), 1) AS trust_pct
        FROM daily_status
        WHERE rn = 1
        GROUP BY business_date
        ORDER BY business_date
    """


def get_control_plane_stage_status():
    """
    Latest run status + timestamp per UC stage (1-4), for the workflow
    stepper on the control plane dashboard.
    """
    return f"""
        SELECT 'UC1' AS stage, overall_status, created_timestamp, created_by AS agent
        FROM (
            SELECT overall_status, created_timestamp, created_by,
                   ROW_NUMBER() OVER (ORDER BY created_timestamp DESC) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        ) WHERE rn = 1

        UNION ALL

        SELECT 'UC2' AS stage, overall_status, created_timestamp, created_by AS agent
        FROM (
            SELECT overall_status, created_timestamp, created_by,
                   ROW_NUMBER() OVER (ORDER BY created_timestamp DESC) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        ) WHERE rn = 1

        UNION ALL

        SELECT 'UC3' AS stage, overall_status, created_timestamp, created_by AS agent
        FROM (
            SELECT overall_status, created_timestamp, created_by,
                   ROW_NUMBER() OVER (ORDER BY created_timestamp DESC) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b
        ) WHERE rn = 1

        UNION ALL

        SELECT 'UC4' AS stage, overall_status, created_timestamp, created_by AS agent
        FROM (
            SELECT overall_status, created_timestamp, created_by,
                   ROW_NUMBER() OVER (ORDER BY created_timestamp DESC) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        ) WHERE rn = 1
    """


def get_control_plane_active_alerts(limit=20):
    """
    Most recent CRITICAL runs across all four agents, for the
    Active Alerts feed on the control plane dashboard. `source` tags which
    agent/table produced the row so a click can fetch that run's detail via
    get_control_plane_alert_run().
    """
    return f"""
        SELECT 'UC1' AS source, created_by AS agent, fully_qualified_name AS table_name,
               overall_status, validation_run_id AS run_id, created_timestamp
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        WHERE overall_status = 'CRITICAL'

        UNION ALL

        SELECT 'UC2' AS source, created_by AS agent, source_fully_qualified_name AS table_name,
               overall_status, reconciliation_run_id AS run_id, created_timestamp
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        WHERE overall_status = 'CRITICAL'

        UNION ALL

        SELECT 'UC3' AS source, created_by AS agent, target_fully_qualified_name AS table_name,
               overall_status, review_id AS run_id, review_timestamp AS created_timestamp
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b
        WHERE overall_status = 'CRITICAL'

        UNION ALL

        SELECT 'UC4' AS source, created_by AS agent, gold_fully_qualified_name AS table_name,
               overall_status, validation_run_id AS run_id, created_timestamp
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        WHERE overall_status = 'CRITICAL'

        ORDER BY created_timestamp DESC
        LIMIT {int(limit)}
    """


def get_control_plane_alert_run(source: str, run_id: str):
    """
    Fetches the parent run/review row for one alert, keyed by which agent
    (`source`: UC1/UC2/UC3/UC4) produced it. Used to render the expanded
    alert card on the control plane's Active Alerts feed.
    """
    table_and_id = {
        "UC1": (f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b", "validation_run_id"),
        "UC2": (f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b", "reconciliation_run_id"),
        "UC3": (f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b", "review_id"),
        "UC4": (f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b", "validation_run_id"),
    }
    table, id_column = table_and_id[source]
    query = f"SELECT * FROM {table} WHERE {id_column} = :run_id"
    return query, {"run_id": run_id}


def get_control_plane_lineage():
    """
    RAW/SILVER/GOLD lineage board: every active layer-registry row
    joined to that layer's latest status, grouped by source table family.
    """
    return f"""
        WITH layers AS (
            SELECT layer_id, source_fully_qualified_name, layer_name,
                   layer_fully_qualified_name, layer_table, source_role
            FROM {LAYER_REGISTRY}
            WHERE is_active = true
        ),
        latest_uc1 AS (
            SELECT fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        ),
        latest_uc2 AS (
            SELECT source_fully_qualified_name, overall_status, created_timestamp, reconciliation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        ),
        latest_uc4 AS (
            SELECT gold_fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY gold_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        )
        SELECT
            l.source_fully_qualified_name AS family,
            l.layer_name,
            l.layer_table            AS table_name,
            l.layer_fully_qualified_name AS fully_qualified_name,
            l.source_role,
            CASE l.layer_name
                WHEN 'BRONZE' THEN u1.overall_status
                WHEN 'SILVER' THEN u2.overall_status
                WHEN 'GOLD'   THEN u4.overall_status
            END AS overall_status,
            CASE l.layer_name
                WHEN 'BRONZE' THEN u1.created_timestamp
                WHEN 'SILVER' THEN u2.created_timestamp
                WHEN 'GOLD'   THEN u4.created_timestamp
            END AS created_timestamp,
            CASE l.layer_name
                WHEN 'BRONZE' THEN u1.validation_run_id
                WHEN 'SILVER' THEN u2.reconciliation_run_id
                WHEN 'GOLD'   THEN u4.validation_run_id
            END AS run_id,
            CASE l.layer_name
                WHEN 'BRONZE' THEN 'UC1'
                WHEN 'SILVER' THEN 'UC2'
                WHEN 'GOLD'   THEN 'UC4'
            END AS source
        FROM layers l
        LEFT JOIN latest_uc1 u1
          ON l.layer_name = 'BRONZE' AND u1.fully_qualified_name = l.layer_fully_qualified_name AND u1.rn = 1
        LEFT JOIN latest_uc2 u2
          ON l.layer_name = 'SILVER' AND u2.source_fully_qualified_name = l.source_fully_qualified_name AND u2.rn = 1
        LEFT JOIN latest_uc4 u4
          ON l.layer_name = 'GOLD' AND u4.gold_fully_qualified_name = l.layer_fully_qualified_name AND u4.rn = 1
        ORDER BY
            l.source_fully_qualified_name,
            CASE l.layer_name WHEN 'BRONZE' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'GOLD' THEN 3 END
    """


def get_control_plane_join_checks():
    """
    Latest JOIN_MATCH_RATE / JOIN_ORPHAN_RATE reconciliation results, for
    SILVER tables built from more than one BRONZE source (fan-in lineage).
    """
    return f"""
        SELECT
            source_fully_qualified_name AS family,
            check_type,
            metric_name,
            check_status,
            source_value,
            target_value,
            expected_value,
            deviation_percentage,
            check_detail,
            created_timestamp
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_fully_qualified_name, check_type
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {RECON_RESULTS}
            WHERE check_type IN ('JOIN_MATCH_RATE', 'JOIN_ORPHAN_RATE')
        ) WHERE rn = 1
        ORDER BY source_fully_qualified_name, check_type
    """


def get_control_plane_lineage_uc():
    """
    RAW/SILVER/GOLD lineage board sourced from Unity Catalog's native
    `system.access.table_lineage`, instead of the hand-maintained layer
    registry. Edges reflect tables actually read/written by executed
    queries, scoped to DataSentinel's pipeline tables (uc1_raw_*,
    uc2_silver_*, uc2_gold_*) and excluding backups/derived check tables.
    Layer is inferred from naming convention since table_lineage has no
    layer concept of its own.
    """
    return f"""
        WITH raw_edges AS (
            SELECT DISTINCT source_table_full_name AS source_table, target_table_full_name AS target_table
            FROM system.access.table_lineage
            WHERE source_table_full_name RLIKE '^{TARGET_CATALOG}\\\\.{TARGET_SCHEMA}\\\\.(uc1_raw_|uc2_silver_|uc2_gold_)[a-z_]+$'
              AND target_table_full_name RLIKE '^{TARGET_CATALOG}\\\\.{TARGET_SCHEMA}\\\\.(uc1_raw_|uc2_silver_|uc2_gold_)[a-z_]+$'
              AND source_table_full_name NOT RLIKE '(_backup|_check)'
              AND target_table_full_name NOT RLIKE '(_backup|_check)'
              AND source_table_full_name <> target_table_full_name
        ),
        classified AS (
            SELECT source_table, target_table,
                CASE WHEN source_table LIKE '%.uc1_raw_%' THEN 'BRONZE'
                     WHEN source_table LIKE '%.uc2_silver_%' THEN 'SILVER'
                     ELSE 'GOLD' END AS source_layer,
                CASE WHEN target_table LIKE '%.uc1_raw_%' THEN 'BRONZE'
                     WHEN target_table LIKE '%.uc2_silver_%' THEN 'SILVER'
                     ELSE 'GOLD' END AS target_layer
            FROM raw_edges
        ),
        b2s AS (SELECT source_table AS bronze_table, target_table AS silver_table FROM classified WHERE source_layer = 'BRONZE' AND target_layer = 'SILVER'),
        s2g AS (SELECT source_table AS silver_table, target_table AS gold_table FROM classified WHERE source_layer = 'SILVER' AND target_layer = 'GOLD'),
        b2g AS (SELECT source_table AS bronze_table, target_table AS gold_table FROM classified WHERE source_layer = 'BRONZE' AND target_layer = 'GOLD'),
        families AS (
            SELECT DISTINCT bronze_table AS family FROM b2s
            UNION SELECT DISTINCT bronze_table AS family FROM b2g
        ),
        rows_bronze AS (
            SELECT family, 'BRONZE' AS layer_name, family AS fully_qualified_name FROM families
        ),
        rows_silver AS (
            SELECT bronze_table AS family, 'SILVER' AS layer_name, silver_table AS fully_qualified_name FROM b2s
        ),
        rows_gold AS (
            SELECT bronze_table AS family, 'GOLD' AS layer_name, gold_table AS fully_qualified_name
            FROM b2g
            UNION
            SELECT b2s.bronze_table AS family, 'GOLD' AS layer_name, s2g.gold_table AS fully_qualified_name
            FROM b2s JOIN s2g ON b2s.silver_table = s2g.silver_table
        ),
        all_rows AS (
            SELECT * FROM rows_bronze
            UNION ALL SELECT * FROM rows_silver
            UNION ALL SELECT * FROM rows_gold
        ),
        latest_uc1 AS (
            SELECT fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        ),
        latest_uc2 AS (
            SELECT source_fully_qualified_name, overall_status, created_timestamp, reconciliation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        ),
        latest_uc4 AS (
            SELECT gold_fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY gold_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        )
        SELECT
            r.family,
            r.layer_name,
            regexp_extract(r.fully_qualified_name, '([^.]+)$', 1) AS table_name,
            r.fully_qualified_name,
            CASE r.layer_name
                WHEN 'BRONZE' THEN u1.overall_status
                WHEN 'SILVER' THEN u2.overall_status
                WHEN 'GOLD'   THEN u4.overall_status
            END AS overall_status,
            CASE r.layer_name
                WHEN 'BRONZE' THEN u1.created_timestamp
                WHEN 'SILVER' THEN u2.created_timestamp
                WHEN 'GOLD'   THEN u4.created_timestamp
            END AS created_timestamp,
            CASE r.layer_name
                WHEN 'BRONZE' THEN u1.validation_run_id
                WHEN 'SILVER' THEN u2.reconciliation_run_id
                WHEN 'GOLD'   THEN u4.validation_run_id
            END AS run_id,
            CASE r.layer_name
                WHEN 'BRONZE' THEN 'UC1'
                WHEN 'SILVER' THEN 'UC2'
                WHEN 'GOLD'   THEN 'UC4'
            END AS source
        FROM all_rows r
        LEFT JOIN latest_uc1 u1
          ON r.layer_name = 'BRONZE' AND u1.fully_qualified_name = r.fully_qualified_name AND u1.rn = 1
        LEFT JOIN latest_uc2 u2
          ON r.layer_name = 'SILVER' AND u2.source_fully_qualified_name = r.family AND u2.rn = 1
        LEFT JOIN latest_uc4 u4
          ON r.layer_name = 'GOLD' AND u4.gold_fully_qualified_name = r.fully_qualified_name AND u4.rn = 1
        ORDER BY
            r.family,
            CASE r.layer_name WHEN 'BRONZE' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'GOLD' THEN 3 END
    """


def get_control_plane_lineage_native():
    """
    Lineage board built the way Databricks' native Catalog Explorer lineage
    tab works: a recursive upstream/downstream traversal of
    `system.access.table_lineage` starting from every actively-onboarded
    raw table (uc1_table_registry_b), with NO naming-pattern restriction on
    what counts as a valid edge (unlike get_control_plane_lineage_uc, which
    only accepts uc1_raw_*/uc2_silver_*/uc2_gold_* names). Backups/checks
    are still excluded so the board stays readable.

    Layer (BRONZE/SILVER/GOLD) here is only an approximation for reusing the
    3-column board renderer -- it's assigned by traversal depth from the
    root (depth 0 = BRONZE, 1 = SILVER, 2+ = GOLD), not by name or registry.
    Because the same physical table can sit at different depths depending
    on which root family reaches it, it may show a different layer per
    family -- that's expected: this tab reflects actual query-level lineage
    depth, not a curated schema.
    """
    return f"""
        WITH RECURSIVE edges AS (
            SELECT DISTINCT source_table_full_name AS source_table, target_table_full_name AS target_table
            FROM system.access.table_lineage
            WHERE source_table_full_name LIKE '{TARGET_CATALOG}.{TARGET_SCHEMA}.%'
              AND target_table_full_name LIKE '{TARGET_CATALOG}.{TARGET_SCHEMA}.%'
              AND source_table_full_name NOT RLIKE '(_backup|_check)'
              AND target_table_full_name NOT RLIKE '(_backup|_check)'
              AND source_table_full_name <> target_table_full_name
        ),
        roots AS (
            SELECT fully_qualified_name AS root
            FROM {TABLE_REGISTRY}
            WHERE is_active = true
        ),
        reachable AS (
            SELECT root AS family, root AS fully_qualified_name, 0 AS depth
            FROM roots
            UNION ALL
            SELECT r.family, e.target_table AS fully_qualified_name, r.depth + 1
            FROM reachable r
            JOIN edges e ON e.source_table = r.fully_qualified_name
            WHERE r.depth < 6
        ),
        min_depth AS (
            SELECT family, fully_qualified_name, MIN(depth) AS depth
            FROM reachable
            GROUP BY family, fully_qualified_name
        ),
        classified AS (
            SELECT family, fully_qualified_name,
                CASE WHEN depth = 0 THEN 'BRONZE'
                     WHEN depth = 1 THEN 'SILVER'
                     ELSE 'GOLD' END AS layer_name
            FROM min_depth
        ),
        latest_uc1 AS (
            SELECT fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_validation_run_b
        ),
        latest_uc2 AS (
            SELECT source_fully_qualified_name, overall_status, created_timestamp, reconciliation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b
        ),
        latest_uc4 AS (
            SELECT gold_fully_qualified_name, overall_status, created_timestamp, validation_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY gold_fully_qualified_name
                       ORDER BY created_timestamp DESC
                   ) AS rn
            FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b
        )
        SELECT
            c.family,
            c.layer_name,
            regexp_extract(c.fully_qualified_name, '([^.]+)$', 1) AS table_name,
            c.fully_qualified_name,
            CASE c.layer_name
                WHEN 'BRONZE' THEN u1.overall_status
                WHEN 'SILVER' THEN u2.overall_status
                WHEN 'GOLD'   THEN u4.overall_status
            END AS overall_status,
            CASE c.layer_name
                WHEN 'BRONZE' THEN u1.created_timestamp
                WHEN 'SILVER' THEN u2.created_timestamp
                WHEN 'GOLD'   THEN u4.created_timestamp
            END AS created_timestamp,
            CASE c.layer_name
                WHEN 'BRONZE' THEN u1.validation_run_id
                WHEN 'SILVER' THEN u2.reconciliation_run_id
                WHEN 'GOLD'   THEN u4.validation_run_id
            END AS run_id,
            CASE c.layer_name
                WHEN 'BRONZE' THEN 'UC1'
                WHEN 'SILVER' THEN 'UC2'
                WHEN 'GOLD'   THEN 'UC4'
            END AS source
        FROM classified c
        LEFT JOIN latest_uc1 u1
          ON c.layer_name = 'BRONZE' AND u1.fully_qualified_name = c.fully_qualified_name AND u1.rn = 1
        LEFT JOIN latest_uc2 u2
          ON c.layer_name = 'SILVER' AND u2.source_fully_qualified_name = c.family AND u2.rn = 1
        LEFT JOIN latest_uc4 u4
          ON c.layer_name = 'GOLD' AND u4.gold_fully_qualified_name = c.fully_qualified_name AND u4.rn = 1
        ORDER BY
            c.family,
            CASE c.layer_name WHEN 'BRONZE' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'GOLD' THEN 3 END
    """


# ─────────────────────────────────────────────
# AGENT 3: TRANSFORMATION REGISTRY QUERIES
# ─────────────────────────────────────────────

TRANSFORMATION_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_transformation_registry_b"
REVIEW_RESULTS_A3       = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc3_review_results_b"


def get_all_transformations():
    return f"""
        SELECT
            transformation_id,
            SUBSTRING_INDEX(
                target_fully_qualified_name, '.', -1
            )                                   AS target_table,
            target_fully_qualified_name,
            target_layer,
            notebook_path,
            function_name,
            SUBSTRING_INDEX(
                source_fully_qualified_name, '.', -1
            )                                   AS source_table,
            source_fully_qualified_name,
            transformation_description,
            expected_survival_rate,
            last_review_status,
            last_reviewed_timestamp,
            is_active,
            registered_timestamp,
            registered_by
        FROM {TRANSFORMATION_REGISTRY}
        ORDER BY registered_timestamp DESC
    """


def insert_transformation(
    transformation_id           : str,
    target_fully_qualified_name : str,
    target_layer                : str,
    notebook_path               : str,
    notebook_language           : str,
    function_name               : str,
    source_fully_qualified_name : str,
    transformation_description  : str,
    checks_enabled              : str,
    expected_survival_rate      : float,
    registered_by               : str
):
    query = f"""
        INSERT INTO {TRANSFORMATION_REGISTRY} (
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
            last_reviewed_timestamp,
            last_review_status,
            last_reviewer,
            is_active,
            registered_timestamp,
            registered_by
        ) VALUES (
            :transformation_id,
            :target_fully_qualified_name,
            :target_layer,
            :notebook_path,
            :notebook_language,
            :function_name,
            :source_fully_qualified_name,
            :transformation_description,
            :checks_enabled,
            :expected_survival_rate,
            NULL,
            'NOT_REVIEWED',
            NULL,
            true,
            current_timestamp(),
            :registered_by
        )
    """
    params = {
        "transformation_id": transformation_id,
        "target_fully_qualified_name": target_fully_qualified_name,
        "target_layer": target_layer,
        "notebook_path": notebook_path,
        "notebook_language": notebook_language,
        "function_name": function_name,
        "source_fully_qualified_name": source_fully_qualified_name,
        "transformation_description": transformation_description,
        "checks_enabled": checks_enabled,
        "expected_survival_rate": expected_survival_rate,
        "registered_by": registered_by,
    }
    return query, params


def toggle_transformation_active(
    transformation_id : str,
    is_active         : bool
):
    query = f"""
        UPDATE {TRANSFORMATION_REGISTRY}
        SET is_active = :is_active
        WHERE transformation_id = :transformation_id
    """
    return query, {"is_active": is_active, "transformation_id": transformation_id}


def get_review_history(transformation_id: str = None):
    where = "WHERE transformation_id = :transformation_id" if transformation_id else ""
    params = {"transformation_id": transformation_id} if transformation_id else {}
    query = f"""
        SELECT
            review_id,
            transformation_id,
            SUBSTRING_INDEX(
                target_fully_qualified_name, '.', -1
            )                                   AS target_table,
            target_fully_qualified_name,
            review_timestamp,
            business_date,
            triggered_by,
            overall_status,
            total_checks_run,
            total_checks_passed,
            total_checks_warned,
            total_checks_critical,
            ai_failure_category,
            ROUND(ai_confidence_score, 2)        AS ai_confidence,
            ai_summary,
            ai_recommended_action,
            alert_sent,
            check_results
        FROM {REVIEW_RESULTS_A3}
        {where}
        ORDER BY review_timestamp DESC
        LIMIT 50
    """
    return query, params


def get_agent3_dashboard_summary():
    return f"""
        SELECT
            COUNT(DISTINCT transformation_id)       AS transformations_registered,
            SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS active_transformations,
            SUM(CASE WHEN last_review_status = 'CRITICAL'
                THEN 1 ELSE 0 END)                  AS critical_last_review,
            SUM(CASE WHEN last_review_status = 'WARNING'
                THEN 1 ELSE 0 END)                  AS warning_last_review,
            SUM(CASE WHEN last_review_status = 'PASS'
                THEN 1 ELSE 0 END)                  AS pass_last_review,
            SUM(CASE WHEN last_review_status = 'NOT_REVIEWED'
                THEN 1 ELSE 0 END)                  AS not_reviewed
        FROM {TRANSFORMATION_REGISTRY}
    """

# ─────────────────────────────────────────────
# AGENT 4: KPI VALIDATION QUERIES
# ─────────────────────────────────────────────

KPI_REGISTRY_A4         = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_registry_b"
KPI_BASELINE_METRICS_A4 = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_baseline_metrics_b"
KPI_VALIDATION_RUN_A4   = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_run_b"
KPI_VALIDATION_RESULTS_A4 = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_validation_results_b"


def get_all_kpis():
    return f"""
        SELECT
            k.kpi_id,
            SUBSTRING_INDEX(
                k.gold_fully_qualified_name, '.', -1
            )                               AS gold_table,
            k.gold_fully_qualified_name,
            k.kpi_name,
            k.kpi_column,
            k.kpi_description,
            k.formula_expression,
            k.min_value,
            k.max_value,
            k.baseline_window_days,
            k.warning_deviation_pct,
            k.critical_deviation_pct,
            k.checks_enabled,
            k.is_active,
            k.registered_timestamp,
            k.registered_by,
            CASE
                WHEN b.baseline_id IS NOT NULL THEN 'YES'
                ELSE 'NO'
            END                             AS has_baseline,
            ROUND(b.mean_value, 4)          AS baseline_mean,
            ROUND(b.stddev_value, 4)        AS baseline_stddev,
            b.baseline_status,
            b.sample_count                  AS baseline_samples,
            b.baseline_date
        FROM {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_registry_b k
        LEFT JOIN {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_baseline_metrics_b b
            ON  k.gold_fully_qualified_name = b.gold_fully_qualified_name
            AND k.kpi_name                  = b.kpi_name
            AND k.kpi_column                = b.kpi_column
        ORDER BY
            k.gold_fully_qualified_name,
            k.kpi_id
    """


def get_kpi_validation_run_summary():
    return f"""
        SELECT
            business_date,
            SUBSTRING_INDEX(
                gold_fully_qualified_name, '.', -1
            )                               AS gold_table,
            gold_fully_qualified_name,
            overall_status,
            total_kpis_checked,
            total_kpis_passed,
            total_kpis_warned,
            total_kpis_critical,
            ai_enrichment_status,
            CASE WHEN alert_sent = true
                 THEN 'YES' ELSE 'NO'
            END                             AS alert_fired,
            validation_run_id,
            created_timestamp
        FROM {KPI_VALIDATION_RUN_A4}
        ORDER BY business_date DESC, gold_fully_qualified_name
    """


def get_kpi_validation_results_for_run(validation_run_id: str):
    query = f"""
        SELECT
            result_id,
            kpi_name,
            kpi_column,
            check_type,
            check_status,
            ROUND(observed_value, 6)        AS observed_value,
            ROUND(expected_value, 6)        AS expected_value,
            ROUND(deviation_percentage, 4)  AS deviation_pct,
            threshold_warning,
            threshold_critical,
            ai_summary,
            ai_recommended_action,
            ai_failure_category,
            ROUND(ai_confidence_score, 2)   AS ai_confidence_score,
            check_detail
        FROM {KPI_VALIDATION_RESULTS_A4}
        WHERE validation_run_id = :validation_run_id
        ORDER BY
            CASE check_status
                WHEN 'CRITICAL' THEN 1
                WHEN 'WARNING'  THEN 2
                WHEN 'PASS'     THEN 3
                ELSE 4
            END,
            kpi_name,
            check_type
    """
    return query, {"validation_run_id": validation_run_id}


def get_agent4_dashboard_summary():
    return f"""
        SELECT
            COUNT(DISTINCT gold_fully_qualified_name) AS kpis_tables_monitored,
            COUNT(DISTINCT business_date)             AS dates_validated,
            COALESCE(SUM(total_kpis_checked), 0)      AS total_kpi_checks,
            COALESCE(SUM(
                CASE WHEN overall_status = 'CRITICAL'
                THEN 1 ELSE 0 END
            ), 0)                                     AS critical_runs,
            COALESCE(SUM(
                CASE WHEN overall_status = 'PASS'
                THEN 1 ELSE 0 END
            ), 0)                                     AS pass_runs,
            MAX(business_date)                        AS latest_date
        FROM {KPI_VALIDATION_RUN_A4}
    """

# ─────────────────────────────────────────────
# AGENT 4: KPI REGISTRY MANAGEMENT QUERIES
# ─────────────────────────────────────────────

def insert_kpi(
    kpi_id                  : str,
    gold_fully_qualified_name: str,
    business_date_column    : str,
    kpi_name                : str,
    kpi_column              : str,
    kpi_description         : str,
    formula_expression      : str,
    formula_columns         : str,
    min_value               : float,
    max_value               : float,
    baseline_window_days    : int,
    warning_deviation_pct   : float,
    critical_deviation_pct  : float,
    checks_enabled          : str,
    registered_by           : str
):
    query = f"""
        INSERT INTO {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_registry_b (
            kpi_id,
            gold_fully_qualified_name,
            business_date_column,
            kpi_name,
            kpi_column,
            kpi_description,
            formula_expression,
            formula_columns,
            min_value,
            max_value,
            baseline_window_days,
            warning_deviation_pct,
            critical_deviation_pct,
            checks_enabled,
            is_active,
            registered_timestamp,
            registered_by,
            change_reason
        ) VALUES (
            :kpi_id,
            :gold_fully_qualified_name,
            :business_date_column,
            :kpi_name,
            :kpi_column,
            :kpi_description,
            :formula_expression,
            :formula_columns,
            :min_value,
            :max_value,
            :baseline_window_days,
            :warning_deviation_pct,
            :critical_deviation_pct,
            :checks_enabled,
            true,
            current_timestamp(),
            :registered_by,
            'Registered via Admin UI'
        )
    """
    params = {
        "kpi_id": kpi_id,
        "gold_fully_qualified_name": gold_fully_qualified_name,
        "business_date_column": business_date_column,
        "kpi_name": kpi_name,
        "kpi_column": kpi_column,
        "kpi_description": kpi_description if kpi_description else "",
        "formula_expression": formula_expression if formula_expression else "",
        "formula_columns": formula_columns,
        "min_value": min_value,
        "max_value": max_value,
        "baseline_window_days": baseline_window_days,
        "warning_deviation_pct": warning_deviation_pct,
        "critical_deviation_pct": critical_deviation_pct,
        "checks_enabled": checks_enabled,
        "registered_by": registered_by,
    }
    return query, params


def toggle_kpi_active(kpi_id: str, is_active: bool):
    query = f"""
        UPDATE {TARGET_CATALOG}.{TARGET_SCHEMA}.uc4_kpi_registry_b
        SET is_active = :is_active
        WHERE kpi_id = :kpi_id
    """
    return query, {"is_active": is_active, "kpi_id": kpi_id}


# ─────────────────────────────────────────────
# AGENT 2: METRIC CONFIGURATION QUERIES
# ─────────────────────────────────────────────

METRIC_CONFIG = (
    f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
    f".uc2_reconciliation_metric_config_b"
)


def get_all_metric_configs():
    return f"""
        SELECT
            metric_config_id,
            SUBSTRING_INDEX(
                source_fully_qualified_name, '.', -1
            )                               AS source_table,
            source_fully_qualified_name,
            from_layer,
            to_layer,
            check_type,
            metric_name,
            source_column,
            target_column,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            is_active,
            display_order,
            created_by,
            updated_by
        FROM {METRIC_CONFIG}
        ORDER BY
            source_fully_qualified_name,
            from_layer,
            to_layer,
            check_type,
            display_order
    """


def insert_metric_config(
    metric_config_id            : str,
    source_fully_qualified_name : str,
    from_layer                  : str,
    to_layer                    : str,
    check_type                  : str,
    metric_name                 : str,
    source_column               : str,
    target_column               : str,
    warning_threshold           : float,
    critical_threshold          : float,
    threshold_unit              : str,
    display_order               : int,
    created_by                  : str
):
    query = f"""
        INSERT INTO {METRIC_CONFIG} (
            metric_config_id,
            source_fully_qualified_name,
            from_layer,
            to_layer,
            check_type,
            metric_name,
            source_column,
            target_column,
            warning_threshold,
            critical_threshold,
            threshold_unit,
            is_active,
            display_order,
            created_timestamp,
            created_by,
            updated_timestamp,
            updated_by
        ) VALUES (
            :metric_config_id,
            :source_fully_qualified_name,
            :from_layer,
            :to_layer,
            :check_type,
            :metric_name,
            :source_column,
            :target_column,
            :warning_threshold,
            :critical_threshold,
            :threshold_unit,
            true,
            :display_order,
            current_timestamp(),
            :created_by,
            current_timestamp(),
            :created_by
        )
    """
    params = {
        "metric_config_id": metric_config_id,
        "source_fully_qualified_name": source_fully_qualified_name,
        "from_layer": from_layer,
        "to_layer": to_layer,
        "check_type": check_type,
        "metric_name": metric_name,
        "source_column": source_column if source_column else None,
        "target_column": target_column if target_column else None,
        "warning_threshold": warning_threshold,
        "critical_threshold": critical_threshold,
        "threshold_unit": threshold_unit,
        "display_order": display_order,
        "created_by": created_by,
    }
    return query, params


def update_metric_config(
    metric_config_id  : str,
    warning_threshold : float,
    critical_threshold: float,
    threshold_unit    : str,
    source_column     : str,
    target_column     : str,
    updated_by        : str
):
    query = f"""
        UPDATE {METRIC_CONFIG}
        SET
            warning_threshold  = :warning_threshold,
            critical_threshold = :critical_threshold,
            threshold_unit     = :threshold_unit,
            source_column      = :source_column,
            target_column      = :target_column,
            updated_timestamp  = current_timestamp(),
            updated_by         = :updated_by
        WHERE metric_config_id = :metric_config_id
    """
    params = {
        "warning_threshold": warning_threshold,
        "critical_threshold": critical_threshold,
        "threshold_unit": threshold_unit,
        "source_column": source_column if source_column else None,
        "target_column": target_column if target_column else None,
        "updated_by": updated_by,
        "metric_config_id": metric_config_id,
    }
    return query, params


def toggle_metric_config_active(metric_config_id: str, is_active: bool):
    query = f"""
        UPDATE {METRIC_CONFIG}
        SET is_active = :is_active
        WHERE metric_config_id = :metric_config_id
    """
    return query, {"is_active": is_active, "metric_config_id": metric_config_id}

# ─────────────────────────────────────────────
# AGENT 2: LAYER CHECK CONFIG QUERIES
# ─────────────────────────────────────────────

LAYER_CHECK_CONFIG = (
    f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
    f".uc2_layer_check_config_b"
)


def get_silver_layer_tables():
    """
    Returns all active Silver layer tables from uc2_layer_registry_b.
    Used by Agent 3 registration form Target dropdown.
    """
    return f"""
        SELECT
            layer_id,
            layer_fully_qualified_name,
            source_fully_qualified_name,
            business_date_column,
            expected_survival_rate
        FROM {LAYER_REGISTRY}
        WHERE layer_name = 'SILVER'
          AND is_active  = true
        ORDER BY layer_fully_qualified_name
    """

def update_layer_check_config(
    layer_check_config_id      : str,
    default_warning_threshold  : float,
    default_critical_threshold : float,
    threshold_unit             : str,
    description                : str,
    updated_by                 : str
):
    query = f"""
        UPDATE {LAYER_CHECK_CONFIG}
        SET
            default_warning_threshold  = :default_warning_threshold,
            default_critical_threshold = :default_critical_threshold,
            threshold_unit             = :threshold_unit,
            description                = :description,
            updated_timestamp          = current_timestamp(),
            updated_by                 = :updated_by
        WHERE layer_check_config_id    = :layer_check_config_id
    """
    params = {
        "default_warning_threshold": default_warning_threshold,
        "default_critical_threshold": default_critical_threshold,
        "threshold_unit": threshold_unit,
        "description": description if description else "",
        "updated_by": updated_by,
        "layer_check_config_id": layer_check_config_id,
    }
    return query, params


def get_hierarchy_view():
    """
    Returns a joined view showing check configs with
    their associated metrics for the hierarchy display.
    """
    return f"""
        SELECT
            lcc.layer_check_config_id,
            SUBSTRING_INDEX(
                lcc.source_fully_qualified_name, '.', -1
            )                                       AS source_table,
            lcc.source_fully_qualified_name,
            lcc.from_layer,
            lcc.to_layer,
            lcc.check_type,
            lcc.default_warning_threshold,
            lcc.default_critical_threshold,
            lcc.threshold_unit,
            lcc.description                         AS check_description,
            lcc.is_active                           AS check_active,
            mc.metric_config_id,
            mc.metric_name,
            mc.source_column,
            mc.target_column,
            mc.warning_threshold                    AS metric_warning,
            mc.critical_threshold                   AS metric_critical,
            mc.is_active                            AS metric_active,
            mc.display_order,
            CASE
                WHEN mc.warning_threshold  != lcc.default_warning_threshold
                  OR mc.critical_threshold != lcc.default_critical_threshold
                THEN true
                ELSE false
            END                                     AS has_override
        FROM {LAYER_CHECK_CONFIG} lcc
        LEFT JOIN {TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_metric_config_b mc
            ON  lcc.source_fully_qualified_name = mc.source_fully_qualified_name
            AND lcc.from_layer                  = mc.from_layer
            AND lcc.to_layer                    = mc.to_layer
            AND lcc.check_type                  = mc.check_type
        ORDER BY
            lcc.source_fully_qualified_name,
            lcc.from_layer,
            lcc.to_layer,
            lcc.check_type,
            mc.display_order
    """