# config/settings.py

import os
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATABRICKS CONNECTION
# ─────────────────────────────────────────────

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH", "")

# ─────────────────────────────────────────────
# CATALOG AND SCHEMA
# ─────────────────────────────────────────────

TARGET_CATALOG = os.environ.get("TARGET_CATALOG", "learning_dev")
TARGET_SCHEMA = os.environ.get("TARGET_SCHEMA", "s819534")

# ─────────────────────────────────────────────
# TABLE REFERENCES
# ─────────────────────────────────────────────

TABLE_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_table_registry_b"
COLUMN_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_column_registry_b"
COLUMN_VALIDATION_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_column_validation_registry_b"
TABLE_VALIDATION_REGISTRY = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_table_validation_registry_b"
BASELINE_METRICS = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc1_baseline_metrics_b"


LAYER_REGISTRY         = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_layer_registry_b"
RECONCILIATION_RUN     = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_run_b"
RECONCILIATION_RESULTS = f"{TARGET_CATALOG}.{TARGET_SCHEMA}.uc2_reconciliation_results_b"

# ─────────────────────────────────────────────
# ENUMERATIONS
# ─────────────────────────────────────────────

SOURCE_TYPES = [
    "FILE",
    "CDC",
    "API",
    "DATABASE"
]

INGESTION_PATTERNS = [
    "AUTOLOADER",
    "BATCH",
    "COPY_INTO",
    "STREAMING"
]

INGESTION_FREQUENCIES = [
    "HOURLY",
    "DAILY",
    "NEAR_REALTIME",
    "WEEKLY"
]

THRESHOLD_UNITS = [
    "PERCENTAGE",
    "COUNT",
    "STDDEV_MULTIPLIER",
    "MINUTES",
    "BOOLEAN"
]

TABLE_LEVEL_VALIDATIONS = [
    "SCHEMA_CONFORMANCE",
    "VOLUME_ANOMALY",
    "DUPLICATE_INGESTION",
    "PARTITION_FRESHNESS",
    "JOB_FAILURE",
    "FILE_COMPLETENESS"
]

COLUMN_LEVEL_VALIDATIONS = [
    "NULL_SPIKE",
    "NUMERIC_RANGE",
    "REFERENTIAL_INTEGRITY",
    "CATEGORICAL_DOMAIN",
    "FORMAT_PATTERN",
    "DATE_VALIDITY",
    "DISTRIBUTION_DRIFT",
    "CROSS_COLUMN_CONSISTENCY",
    "CARDINALITY_DRIFT"
]

COLUMN_CHECKS_BY_TYPE = {
    "STRING":    ["NULL_SPIKE", "FORMAT_PATTERN", "CATEGORICAL_DOMAIN", "CARDINALITY_DRIFT",
                  "DATE_VALIDITY", "REFERENTIAL_INTEGRITY", "CROSS_COLUMN_CONSISTENCY"],
    "INTEGER":   ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT", "CATEGORICAL_DOMAIN",
                  "CARDINALITY_DRIFT", "REFERENTIAL_INTEGRITY", "CROSS_COLUMN_CONSISTENCY"],
    "DECIMAL":   ["NULL_SPIKE", "NUMERIC_RANGE", "DISTRIBUTION_DRIFT", "CROSS_COLUMN_CONSISTENCY"],
    "BOOLEAN":   ["NULL_SPIKE", "DISTRIBUTION_DRIFT"],
    "DATETIME":  ["NULL_SPIKE", "DATE_VALIDITY", "CROSS_COLUMN_CONSISTENCY"],
    "COMPLEX":   ["NULL_SPIKE"],
    "DEFAULT":   ["NULL_SPIKE"],
}

TYPE_FAMILY = {
    "STRING": "STRING", "VARCHAR": "STRING", "CHAR": "STRING",
    "TINYINT": "INTEGER", "SMALLINT": "INTEGER", "INT": "INTEGER", "INTEGER": "INTEGER", "BIGINT": "INTEGER",
    "LONG": "INTEGER", "SHORT": "INTEGER", "BYTE": "INTEGER",
    "FLOAT": "DECIMAL", "DOUBLE": "DECIMAL", "DECIMAL": "DECIMAL", "REAL": "DECIMAL",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATETIME", "TIMESTAMP": "DATETIME", "TIMESTAMP_NTZ": "DATETIME",
}

ID_COLUMN_CHECKS = ["NULL_SPIKE", "FORMAT_PATTERN", "CARDINALITY_DRIFT", "REFERENTIAL_INTEGRITY"]
ID_NAME_REGEX = r"^(id)$|(Id|_id|_ID|_key|_KEY)$"

# Validations for complex / JSON / nested columns (MAP, STRUCT, ARRAY, JSON strings)
COMPLEX_COLUMN_VALIDATIONS = [
    "NULL_SPIKE",
    "JSON_VALID",
    "SCHEMA_DRIFT",
    "NESTED_NULL_RATE",
    "KEY_CARDINALITY",
]

# ─────────────────────────────────────────────
# CONFIG VALIDATION
# ─────────────────────────────────────────────

def validate_config():
    """
    Validates that required environment variables are present.
    Logs a warning but does NOT crash the app if variables are missing.
    Returns True if all required variables are set, False otherwise.
    """
    missing = []

    auth_mode = os.environ.get("DATABRICKS_AUTH_MODE", "pat").strip().lower()

    if not DATABRICKS_HOST:
        missing.append("DATABRICKS_HOST")
    if not HTTP_PATH:
        missing.append("DATABRICKS_HTTP_PATH")

    if auth_mode == "service_principal":
        for var in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
            if not os.environ.get(var):
                missing.append(var)
    elif not DATABRICKS_TOKEN:
        missing.append("DATABRICKS_TOKEN")

    if missing:
        logger.warning(
            f"Missing environment variables: {', '.join(missing)}. "
            f"App will start but database connections will not work. "
            f"Please set these in the Databricks Apps configuration."
        )
        return False

    logger.info(
        f"All environment variables found. Configuration valid. "
        f"Auth mode: {auth_mode}."
    )
    return True