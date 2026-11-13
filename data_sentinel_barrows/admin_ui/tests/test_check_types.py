import importlib
import pathlib
import sys
import types

import pytest

ADMIN_UI_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ADMIN_UI_ROOT) not in sys.path:
    sys.path.insert(0, str(ADMIN_UI_ROOT))

# Lightweight stubs so onboarding can be imported in environments
# that do not have Dash/Databricks dependencies installed.
dash_stub = types.ModuleType("dash")

def _dash_component(*args, **kwargs):
    return {"args": args, "kwargs": kwargs}

class _DashNamespace:
    def __getattr__(self, _name):
        return _dash_component

dash_stub.dcc = _DashNamespace()
dash_stub.html = _DashNamespace()
dash_stub.register_page = lambda *args, **kwargs: None
dash_stub.ALL = "ALL"
dash_stub.MATCH = "MATCH"
dash_stub.ctx = types.SimpleNamespace(triggered_id=None)
dash_stub.exceptions = types.SimpleNamespace(PreventUpdate=Exception)
dash_stub.no_update = object()
dash_stub.Input = lambda *args, **kwargs: ("Input", args, kwargs)
dash_stub.Output = lambda *args, **kwargs: ("Output", args, kwargs)
dash_stub.State = lambda *args, **kwargs: ("State", args, kwargs)

def _callback(*args, **kwargs):
    def _decorator(fn):
        return fn
    return _decorator

dash_stub.callback = _callback
sys.modules.setdefault("dash", dash_stub)

dbc_stub = types.ModuleType("dash_bootstrap_components")

def _dbc_component(*args, **kwargs):
    return {"args": args, "kwargs": kwargs}

def _dbc_getattr(_name):
    return _dbc_component

dbc_stub.__getattr__ = _dbc_getattr
sys.modules.setdefault("dash_bootstrap_components", dbc_stub)

dmc_stub = types.ModuleType("dash_mantine_components")
dmc_stub.__getattr__ = _dbc_getattr
sys.modules.setdefault("dash_mantine_components", dmc_stub)

databricks_stub = types.ModuleType("databricks")
databricks_sql_stub = types.ModuleType("databricks.sql")
databricks_stub.sql = databricks_sql_stub
sys.modules.setdefault("databricks", databricks_stub)
sys.modules.setdefault("databricks.sql", databricks_sql_stub)

pandas_stub = types.ModuleType("pandas")
pandas_stub.DataFrame = object
sys.modules.setdefault("pandas", pandas_stub)

onboarding = importlib.import_module("pages.onboarding")
settings = importlib.import_module("config.settings")


@pytest.mark.parametrize(
    "dtype,column_name,expected",
    [
        ("STRING", "name", settings.COLUMN_CHECKS_BY_TYPE["STRING"]),
        ("STRING", "id", settings.ID_COLUMN_CHECKS),
        ("STRING", "partnerId", settings.ID_COLUMN_CHECKS),
        ("DOUBLE", "budget", settings.COLUMN_CHECKS_BY_TYPE["DECIMAL"]),
        ("BIGINT", "accounts.items.id", settings.ID_COLUMN_CHECKS),
        ("INT", "stores.selected.items.id", settings.ID_COLUMN_CHECKS),
        ("INT", "tickets.items", settings.COLUMN_CHECKS_BY_TYPE["INTEGER"]),
        ("BOOLEAN", "accounts.items.agency.billable", settings.COLUMN_CHECKS_BY_TYPE["BOOLEAN"]),
        ("TIMESTAMP", "x", settings.COLUMN_CHECKS_BY_TYPE["DATETIME"]),
        ("ARRAY<STRUCT<id:BIGINT>>", "accounts", ["NULL_SPIKE"]),
    ],
)
def test_get_available_checks_for_dtype(dtype, column_name, expected):
    actual = onboarding.get_available_checks_for_dtype(dtype, column_name)
    assert actual == expected



def test_decimal_has_numeric_range_not_format_pattern():
    checks = onboarding.get_available_checks_for_dtype("DOUBLE", "budget")
    assert "NUMERIC_RANGE" in checks
    assert "FORMAT_PATTERN" not in checks



def test_bigint_nested_id_has_no_numeric_range():
    checks = onboarding.get_available_checks_for_dtype("BIGINT", "accounts.items.id")
    assert checks == settings.ID_COLUMN_CHECKS
    assert "NUMERIC_RANGE" not in checks



def test_int_id_defaults_exclude_numeric_and_distribution():
    defaults = onboarding.get_default_checks_for_dtype("INT", "id")
    assert "NUMERIC_RANGE" not in defaults
    assert "DISTRIBUTION_DRIFT" not in defaults
