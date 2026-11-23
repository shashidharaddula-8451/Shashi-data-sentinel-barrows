from datetime import date

from components.baseline_window_policy import (
    WINDOW_POLICY_MONTH,
    compute_default_window,
)


def _assert_window(as_of, lag, expected_start, expected_end):
    start_dt, end_dt = compute_default_window(as_of, lag, WINDOW_POLICY_MONTH)
    assert str(start_dt) == expected_start
    assert str(end_dt) == expected_end


def test_month_window_as_of_2026_11_01_lag_1():
    _assert_window(date(2026, 11, 1), 1, "2026-10-01", "2026-10-31")


def test_month_window_as_of_2026_11_15_lag_1():
    _assert_window(date(2026, 11, 15), 1, "2026-10-15", "2026-11-14")


def test_month_window_as_of_2026_03_01_lag_1():
    _assert_window(date(2026, 3, 1), 1, "2026-02-01", "2026-02-28")


def test_month_window_as_of_2026_03_31_lag_1():
    _assert_window(date(2026, 3, 31), 1, "2026-02-28", "2026-03-30")


def test_month_window_as_of_2026_11_15_lag_14():
    _assert_window(date(2026, 11, 15), 14, "2026-10-02", "2026-11-01")
