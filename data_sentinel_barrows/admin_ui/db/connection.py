# db/connection.py

import os
import re

from databricks import sql
from config.settings import DATABRICKS_HOST, DATABRICKS_TOKEN, HTTP_PATH
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Matches a bare SQL identifier or a dotted fully-qualified name of up to
# three parts (e.g. "table", "schema.table", "catalog.schema.table").
# Used as defense-in-depth for any identifier value that isn't a trusted
# internal constant (e.g. one that originates from a UI dropdown, URL, or
# other external input) before it is embedded directly into SQL text, since
# SQL bind parameters cannot represent identifiers.
_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"
)


def validate_identifier(name: str) -> str:
    """
    Validates that `name` is safe to embed directly into SQL text as an
    identifier (table/column/fully-qualified name). Raises ValueError if it
    doesn't match a safe identifier pattern. Returns the name unchanged so
    it can be used inline, e.g. f"SELECT * FROM {validate_identifier(fqn)}".
    """
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


# "service_principal" uses the OAuth credentials Databricks Apps injects at
# runtime; "pat" uses DATABRICKS_TOKEN. Service-principal auth additionally
# requires USE CATALOG on the target catalog, which is granted outside this
# app, so the mode is switched explicitly rather than auto-detected.
AUTH_MODE = os.environ.get("DATABRICKS_AUTH_MODE", "pat").strip().lower()


def _service_principal_credentials():
    from databricks.sdk.core import Config, oauth_service_principal

    host = DATABRICKS_HOST if DATABRICKS_HOST.startswith("http") \
        else f"https://{DATABRICKS_HOST}"
    return oauth_service_principal(Config(
        host          = host,
        client_id     = os.environ["DATABRICKS_CLIENT_ID"],
        client_secret = os.environ["DATABRICKS_CLIENT_SECRET"],
    ))


def get_connection():
    """
    Returns a fresh Databricks SQL connection, authenticating per AUTH_MODE.
    """
    if AUTH_MODE == "service_principal":
        return sql.connect(
            server_hostname      = DATABRICKS_HOST,
            http_path            = HTTP_PATH,
            credentials_provider = _service_principal_credentials,
        )

    return sql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=HTTP_PATH,
        access_token=DATABRICKS_TOKEN
    )


def execute_query(query: str, params: dict = None, conn=None) -> pd.DataFrame:
    """
    Executes a SELECT query and returns results as a pandas DataFrame.
    Returns an empty DataFrame on error.

    `params`, when given, is a dict of named bind parameters referenced in
    `query` via ":name" placeholders (server-side parameter binding).

    `conn`, when given, reuses that open connection instead of opening a new
    one. Pass it when a caller issues many sequential queries/writes (e.g. a
    multi-step onboarding wizard) — opening a fresh SQL-warehouse session
    per call costs about a second each, which multiplies fast and can trip
    the Databricks Apps 120s reverse-proxy request timeout.
    """
    try:
        if conn is not None:
            with conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                result = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                return pd.DataFrame(result, columns=columns)
        with get_connection() as own_conn:
            with own_conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                result = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                return pd.DataFrame(result, columns=columns)
    except Exception as e:
        logger.error(f"Query execution failed: {str(e)}")
        logger.error(f"Query was: {query}")
        raise


def execute_write(query: str, params: dict = None, conn=None) -> bool:
    """
    Executes an INSERT, UPDATE, or MERGE query.
    Returns True on success, raises exception on failure.

    `params`, when given, is a dict of named bind parameters referenced in
    `query` via ":name" placeholders (server-side parameter binding).

    `conn`, when given, reuses that open connection instead of opening a new
    one — see `execute_query` for why this matters for multi-step callers.
    """
    try:
        if conn is not None:
            with conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
            conn.commit()
            return True
        with get_connection() as own_conn:
            with own_conn.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
            own_conn.commit()
            return True
    except Exception as e:
        logger.error(f"Write execution failed: {str(e)}")
        logger.error(f"Query was: {query}")
        raise


def execute_many(queries: list) -> bool:
    """
    Executes multiple write queries in a single connection.
    Each item in `queries` is either a plain SQL string, or a
    (query, params) tuple where `params` is a dict of named bind
    parameters referenced in `query` via ":name" placeholders.
    Returns True if all succeed, raises exception on any failure.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                for item in queries:
                    if isinstance(item, tuple):
                        cursor.execute(item[0], item[1])
                    else:
                        cursor.execute(item)
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Batch write execution failed: {str(e)}")
        raise
